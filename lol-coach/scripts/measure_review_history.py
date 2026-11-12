"""Measure a reversible display-only history catalog for saved round bundles."""
import argparse
import json
from pathlib import Path

from lol_coach.reasoning_frame import canonical


def measure(frame):
    plan = frame['task']['previous_plan']
    history = plan['historical_facts']
    keys = ('entity_id', 'field', 'observed_at_seconds')
    catalog = {hid: {k: fact[k] for k in keys} for hid, fact in history.items()}

    def display(rows):
        return {**frame, 'task': {**frame['task'], 'previous_plan': {**plan, 'historical_facts': rows}}}

    restored = {}
    for hid, descriptor in catalog.items():
        row = history[hid]
        if (row['previous_frame_id'] != plan['previous_frame_id']
                or row['temporal_scope'] != 'historical_previous_frame'
                or descriptor != {k: row[k] for k in keys}):
            raise ValueError('invalid_historical_reference')
        restored[hid] = row
    original = canonical(frame)
    if canonical(display(restored)) != original:
        raise ValueError('round_trip_changed_frame')
    return dict(frame_id=frame['frame_id'], full_chars=len(original),
                catalog_view_chars=len(canonical(display(catalog))), restored_rows=len(restored),
                identical_reconstruction=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundles', type=Path, nargs='+')
    args = parser.parse_args()
    for path in args.bundles:
        frame = json.loads(path.read_bytes())['frame']
        print(json.dumps(measure(frame)))


if __name__ == '__main__':
    main()
