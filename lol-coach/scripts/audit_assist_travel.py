"""Re-read the two frozen jungle frames with personal movement evidence over stdio MCP."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from lol_coach.file_model_bridge import atomic_json
from lol_coach.movement_1622 import RED_JUNGLE_REPLAY, VERSION, iter_path_samples
from lol_coach.reasoning_frame import canonical, digest
from lol_coach.round_chain import _check_bundle, _source
from lol_coach.round_lane_evidence import _attach_allied_path_starts
from lol_coach.round_tools import round_call
from scripts.round_review_mcp import query, round_client


async def run(args):
    raw = args.replay.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if sha != RED_JUNGLE_REPLAY:
        raise ValueError('expected_reviewed_red_jungle_replay')
    args.output.mkdir(parents=True, exist_ok=False)
    for slot, at in [('04', 448), ('11', 1335)]:
        original = (args.session / slot / 'bundle.json').read_bytes()
        bundle = json.loads(original)
        f = _check_bundle(bundle)
        d = f['decision']
        if (_source(bundle) != sha or d['build'] != VERSION or d['at_seconds'] != at or
                d['observer_team_id'] != 200 or d['player_entity_id'] != '0x400000b4'):
            raise ValueError('unexpected_subject_or_clock')
        ids = list(f['allied_path_fact_ids'])
        _attach_allied_path_starts(bundle, raw)
        assert f['allied_path_fact_ids'] == ids
        f.pop('frame_id')
        f['frame_id'] = 'frame_' + digest(f)[:24]
        bundle['audit']['frame_chars'] = len(canonical(f))
        path = args.output / f'bundle-{at}.json'
        atomic_json(path, bundle)
        async with round_client(path, hashlib.sha256(path.read_bytes()).hexdigest()) as (client, protocol):
            report = await query(client, 'review_round_plan', {})
            assert report == round_call(bundle, 'review_round_plan', {})
        part = report['team_pings']['assist_distances']
        atomic_json(args.output / f'mcp-{at}.json', dict(frame_id=f['frame_id'], source_replay_sha256=sha,
                    input_bundle_sha256=hashlib.sha256(original).hexdigest(), protocol=protocol,
                    tool='review_round_plan', direct_equal=True, assist_distances=part))
        print(at, part['personal_travel']['walk_scenario'], flush=True)

    # Read outcomes only after both prefix-only tool responses have been saved.
    starts = [r for r in iter_path_samples(raw, at_seconds=1339)
              if r['entity_id'] == 0x400000b4 and (453 <= r['time_seconds'] <= 459 or r['time_seconds'] > 1335)]
    atomic_json(args.output / 'later-samples.json', dict(source_sha256=sha, use='evaluation_only',
                samples=[dict(at=r['time_seconds'], start_xz=r['world_waypoints_xz'][0],
                              speed=r['speed'], source=r['source']) for r in starts]))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', type=Path, required=True)
    parser.add_argument('--session', type=Path, default=Path('data/private/reasoning_sessions/pantheon-red-full-20261116-v2'))
    parser.add_argument('--output', type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
