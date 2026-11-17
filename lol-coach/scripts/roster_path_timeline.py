"""Export each player's own latest observed path start on a fixed grid across one replay."""
import argparse
from bisect import bisect_right
from collections import defaultdict
from hashlib import sha256
from math import floor
from pathlib import Path

from lol_coach.file_model_bridge import atomic_json
from lol_coach.hero_sight import reviewed_heroes
from lol_coach.movement_1622 import iter_path_samples
from lol_coach.replay_container import container_info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.replay.read_bytes()
    fingerprint = sha256(raw).hexdigest()
    roster = reviewed_heroes(fingerprint)
    if len(roster) != 10:
        raise ValueError('this audit requires a verified ten-player mapping')
    end = container_info(raw)['metadata']['gameLength'] / 1000
    samples = defaultdict(list)
    for row in iter_path_samples(raw):
        if row['entity_id'] in roster and row['time_seconds'] <= end:
            src = row['source']
            samples[row['entity_id']].append((row['time_seconds'], src['chunk'], src['offset'],
                                              src['record_index'], row['world_waypoints_xz'][0]))
    marks = list(range(0, floor(end) + 1, 30)) + ([end] if end % 30 else [])
    for entity, player in roster.items():
        events = sorted(samples[entity])
        times = [e[0] for e in events]
        rows = []
        for t in marks:
            i = bisect_right(times, t) - 1
            sample = None
            if i >= 0:
                observed, chunk, offset, record, xz = events[i]
                sample = dict(at_seconds=observed, age_seconds=t-observed, xz=xz,
                              stream=1, chunk=chunk, offset=offset, record_index=record)
            rows.append(dict(at_seconds=t, last_path_start=sample))
        path = args.output / (player['name'] + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(path, dict(source_sha256=fingerprint, champion=player['name'], entity=hex(entity),
                               team=player['team_id'], end_seconds=end, rows=rows,
                               scope='own_observed_path_start_not_action_camera_or_destination'))
    print(len(roster), 'individual tracks;', len(marks), 'cutoffs each;', end, 'seconds')


if __name__ == '__main__':
    main()
