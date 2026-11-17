"""Replay continuously from game start and compare the retrospective event ledger to the ROFL footer."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import socket
import ssl
import time
import urllib.request

from lol_coach.file_model_bridge import atomic_json
from lol_coach.replay_container import container_info
from scripts.capture_replay_fog import capture_workspace, owned_replay, request_api, stage, wait_until


def public_event(event, players):
    aliases = {}
    for player in players:
        display = player['championName']
        raw = player.get('rawChampionName', '')
        champion_id = raw.removeprefix('game_character_displayname_') if raw.startswith('game_character_displayname_') else display
        for field in ('summonerName', 'riotIdGameName', 'riotId', 'championName'):
            if name := player.get(field):
                aliases.setdefault(name, set()).add(champion_id)

    def champion(name):
        options = aliases.get(name, set())
        return next(iter(options)) if len(options) == 1 else None

    clean = {k:event[k] for k in ('EventName','EventID','EventTime','DragonType','TurretKilled',
                                  'InhibKilled','Stolen') if k in event}
    for k in ('KillerName','VictimName','Recipient'):
        if k in event:
            clean[k] = champion(event[k])
    if 'Assisters' in event:
        clean['Assisters'] = [champion(a) for a in event['Assisters']]
    return clean


def audit(replay, game_dir, output):
    raw = replay.read_bytes()
    info = container_info(raw)
    footer = json.loads(info['metadata']['statsJson'])
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1',2999)) == 0:
            raise RuntimeError('an existing replay owns the local API')
    output.parent.mkdir(exist_ok=True, parents=True)
    if output.exists():
        raise FileExistsError(output)
    api = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(
        context=ssl._create_unverified_context()))
    events, first_observed, clocks = {}, {}, []
    with capture_workspace(output.parent) as work, owned_replay(stage(game_dir, work), replay) as (pid, alive):
        def ready():
            try:
                return alive() and request_api(api, 'game')['processID'] == pid
            except OSError:
                return False
        wait_until(ready, 'private replay', seconds=75)
        actual = 'Version ' + info['version'] + ' ('
        if not any(actual in f.read_text(errors='replace') for f in (work/'Game/Logs').rglob('*r3dlog.txt')):
            raise ValueError('client version differs from replay')
        request_api(api, 'playback', dict(time=0, paused=True))
        wait_until(lambda: (p:=request_api(api,'playback'))['paused'] and not p['seeking']
                   and abs(p['time']) < .005, 'continuous replay start')
        end = request_api(api,'playback')['length']
        request_api(api, 'playback', dict(paused=False, speed=8))
        deadline = time.monotonic() + end / 2 + 75
        while time.monotonic() < deadline and ready():
            try:
                with api.open('https://127.0.0.1:2999/liveclientdata/allgamedata', timeout=3) as response:
                    doc = json.load(response)
                playback = request_api(api, 'playback')
            except OSError:
                break
            clock = doc['gameData']['gameTime']
            if clocks and clock < clocks[-1][0] - .05:
                raise ValueError('continuous game clock went backwards')
            clocks.append([clock, playback['time']])
            for e in doc.get('events',{}).get('Events',[]):
                row = public_event(e, doc['allPlayers'])
                if events.setdefault(row['EventID'], row) != row:
                    raise ValueError('event identity changed')
                first_observed.setdefault(row['EventID'], clock)
            if clock >= end - .3 or playback['time'] >= end - .1:
                break
            time.sleep(.05 if 430 <= clock <= 470 else .3)
    kills = [e for e in events.values() if e['EventName'] == 'ChampionKill']
    checks = {}
    for player in footer:
        name = player['SKIN']
        seen = [sum(e['KillerName'] == name for e in kills),sum(e['VictimName'] == name for e in kills),
                sum(name in e.get('Assisters',[]) for e in kills)]
        expected = [int(player[k]) for k in ('CHAMPIONS_KILLED','NUM_DEATHS','ASSISTS')]
        checks[name] = dict(event_kda=seen, footer_kda=expected, matches=seen==expected,
                            footer_personal_dragons=int(player['DRAGON_KILLS']))
    atomic_json(output, dict(source_sha256=hashlib.sha256(raw).hexdigest(), client_build=info['version'],
                end_seconds=end, sample_count=len(clocks), clocks=clocks, event_counts=dict(Counter(
                    e['EventName'] for e in events.values())), events=[dict(e, first_observed_seconds=first_observed[i])
                    for i,e in events.items()], checks=checks,
                retrospective_only=True))
    print('samples',len(clocks),'events',len(events),'KDA matched',sum(r['matches'] for r in checks.values()))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('replay', type=Path)
    p.add_argument('--game-dir', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    audit(a.replay.resolve(), a.game_dir.resolve(), a.output.resolve())
