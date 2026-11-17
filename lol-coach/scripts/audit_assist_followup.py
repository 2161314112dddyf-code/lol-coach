"""Retrospective comparison of allied path starts before and after a measured assist ping."""
import argparse
from collections import defaultdict
from math import dist
from pathlib import Path

from lol_coach.file_model_bridge import atomic_json
from lol_coach.hero_sight import reviewed_heroes
from lol_coach.movement_1622 import iter_path_samples
from lol_coach.replay_pings import build_ping_index
from lol_coach.review_subject import load_review_subject


def describe(sample, centre):
    if sample is None:
        return None
    xz = sample['world_waypoints_xz'][0]
    return dict(t=sample['time_seconds'], xz=xz, distance=round(dist(xz, centre)),
                speed=sample['speed'], source=sample['source'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', required=True, type=Path)
    parser.add_argument('--game-log', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    subject = load_review_subject(args.replay, args.game_log)
    raw = args.replay.read_bytes()
    index = build_ping_index(raw)
    if index['source_sha256'] != subject['replay_sha256']:
        raise ValueError('wrong match')
    allies = {eid: h['name'] for eid, h in reviewed_heroes(index['source_sha256']).items()
              if h['team_id'] == subject['local_team_id']}
    paths = defaultdict(list)
    for sample in iter_path_samples(raw):
        if sample['entity_id'] in allies and sample['world_waypoints_xz']:
            paths[sample['entity_id']].append(sample)
    output = []
    for event in index['events']:
        if event['sender_champion'] != subject['local_champion'] or event['kind'] != 'assist_me':
            continue
        region = event.get('marker_region')
        if not region:
            continue
        t = event['time_seconds']
        centre = region['xz_rounded_to_100']
        cases = []
        for eid, name in allies.items():
            samples = sorted(paths[eid], key=lambda r:(r['time_seconds'], r['source']['chunk'],
                                                       r['source']['offset'], r['source']['record_index']))
            before = [s for s in samples if s['time_seconds'] <= t]
            after = [describe(s, centre) for s in samples if t < s['time_seconds'] <= t + 30]
            start = describe(before[-1], centre) if before else None
            hits = {str(radius): next((s for s in after if s['distance'] <= radius), None)
                    for radius in (300, 600, 900)}
            end = min(after, key=lambda s:s['distance']) if after else None
            cases.append(dict(champion=name, before=start, subsequent_sample_count=len(after),
                              first_sample_within=hits, closest_observed=end))
        output.append(dict(sent=t, region=region, actors=cases))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output, dict(match=subject['match_id'], source_sha256=index['source_sha256'],
                team=subject['local_team_id'], champion=subject['local_champion'], rows=output,
                scope='Outcome-side only. Sample distances to an estimated ring centre rounded to 100. '
                'First sample inside is neither first arrival nor evidence the player answered the call.'))
    for case in output:
        print(round(case['sent'], 3), [(r['champion'], (r['before'] or {}).get('distance'),
              round(r['first_sample_within']['600']['t']-case['sent'], 2)
              if r['first_sample_within']['600'] else None) for r in case['actors']])


if __name__ == '__main__':
    main()
