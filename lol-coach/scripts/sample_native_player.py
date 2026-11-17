"""Read one player's own status at chosen clocks of a local offline ROFL (Windows)."""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import ssl
import urllib.request

from lol_coach.hero_sight import reviewed_heroes
from lol_coach.movement_1622 import VERSION
from lol_coach.player_state import SAMPLE_ROOT, own_live_sample
from lol_coach.replay_container import container_info
from scripts.capture_replay_fog import capture_workspace, owned_replay, request_api, stage, wait_until


def sample(replay, game_dir, team, champion, clocks, root):
    raw = replay.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if container_info(raw)['version'] != VERSION:
        raise ValueError('unsupported_player_status_build')
    players = [hex(e) for e,h in reviewed_heroes(sha).items() if h['name'] == champion and h['team_id'] == team]
    if len(players) != 1:
        raise ValueError('expected_one_reviewed_player')
    if any(not 0 <= clock < float('inf') for clock in clocks):
        raise ValueError('invalid_clock')
    player, = players
    folder = root / sha / player
    folder.mkdir(exist_ok=True, parents=True)
    source = 'native_replay_liveclient_allplayers_self'
    path = folder / (source + '.json')
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1',2999)) == 0:
            raise RuntimeError('A replay API is already in use')
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(
        context=ssl._create_unverified_context()))
    samples = []
    with capture_workspace(folder) as scratch, owned_replay(stage(game_dir,scratch),replay) as (pid,alive):
        def ready():
            if not alive():
                raise RuntimeError('Private replay exited')
            try:
                return request_api(client,'game')['processID'] == pid
            except OSError:
                return False
        wait_until(ready,'native replay API',seconds=75)
        if not any('Version '+VERSION+' (' in f.read_text(errors='replace') for f in
                   (scratch/'Game/Logs').rglob('*r3dlog.txt')):
            raise ValueError('unverified_client_build')
        for clock in sorted(set(clocks)):
            if not ready():
                raise RuntimeError('Private replay unavailable')
            request_api(client,'playback',dict(time=clock,paused=True))
            wait_until(lambda: (p:=request_api(client,'playback'))['paused'] and not p['seeking']
                        and abs(p['time']-clock)<.002, 'paused game clock')
            with client.open('https://127.0.0.1:2999/liveclientdata/allgamedata', timeout=3) as response:
                doc = json.load(response)
            if not ready():
                raise RuntimeError('Replay process changed during sampling')
            samples.append(own_live_sample(doc,clock,sha,team,player))
    from uuid import uuid4
    # Exclusive writer so overlapping sessions cannot discard each other's samples.
    lock = folder / '.own-state.lock'
    handle = lock.open('x')
    try:
        with handle:
            receipt = dict(schema='own-replay-state/v1', source_sha256=sha, entity_id=player,
                           team_id=team, build=VERSION)
            rows = {}
            if path.is_file():
                old = json.loads(path.read_bytes())
                if any(old.get(k) != v for k,v in receipt.items()):
                    raise ValueError('existing_player_state_scope_mismatch')
                rows = {r['time']:r for r in old['samples']}
            for row in samples:
                if rows.setdefault(row['time'],row) != row:
                    raise ValueError('conflicting_native_sample')
            receipt['samples'] = [rows[t] for t in sorted(rows)]
            temp = folder / (uuid4().hex + '.tmp')
            temp.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf8')
            temp.replace(path)
    finally:
        lock.unlink()
    return path


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('replay',type=Path)
    p.add_argument('--game-dir',type=Path,required=True)
    p.add_argument('--team',type=int,choices=(100,200),required=True)
    p.add_argument('--champion',required=True)
    p.add_argument('--at',type=float,nargs='+',required=True)
    p.add_argument('--output-root',type=Path,default=SAMPLE_ROOT)
    a=p.parse_args()
    print(sample(a.replay.resolve(),a.game_dir.resolve(),a.team,a.champion,a.at,a.output_root))
