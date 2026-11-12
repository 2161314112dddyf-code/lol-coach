"""Forecast the next observed allied lane birth from the same spawner's prefix."""
from collections import defaultdict
import hashlib
import math

from .movement_1622 import MAP11_REPLAYS, VERSION, minion_birth, minion_class
from .reasoning_frame import number
from .replay_container import container_info, packets


LANE_NAMES = {'top': 'top', 'middle': 'mid', 'bottom': 'bot'}


def wave_clock_at(births, *, at_seconds):
    """Input is one team's single spawner, with independent live birth records.

    Ranged -> melee marks an observed new cohort. A second melee in the same
    group is not another wave. Siege-type variation does not split cohorts.
    The recent gap envelope is an empirical forecast, not a patch timer.
    """
    if not number(at_seconds) or at_seconds < 0:
        raise ValueError('invalid_wave_clock_cutoff')
    prefix = {}
    for when, entity, kind in births:
        if not number(when) or when < 0:
            raise ValueError('invalid_minion_birth_time')
        if when > at_seconds:
            continue
        if entity in prefix and prefix[entity] != (when, kind):
            raise ValueError('ambiguous_minion_birth_identity')
        prefix[entity] = (when, kind)

    # Batching by timestamp also makes mixed-type, same-tick ordering ambiguous.
    # Only an unambiguous melee batch after ranged can start a new marker.
    batches = defaultdict(list)
    for entity, (when, kind) in prefix.items():
        batches[when].append((kind, entity))
    previous = None
    starts = []
    for when, rows in sorted(batches.items()):
        kinds = {k for k, _ in rows}
        if kinds == {'siege'}:
            continue
        if kinds == {'melee'} and previous == 'ranged':
            starts.append((when, min(e for _, e in rows)))
        previous = next(iter(kinds)) if len(kinds) == 1 else None

    recent = starts[-6:]  # At most five recently observed peer-to-peer intervals.
    times = [t for t, _ in recent]
    return dict(birth_forecast(times, at_seconds), observed_marker_entity_ids=[hex(e) for _, e in recent])


def birth_forecast(times, at_seconds):
    """Reproducible projection of the last six observed same-spawner markers."""
    if (not isinstance(times, list) or len(times) > 6 or not number(at_seconds) or at_seconds < 0
            or not all(number(t) and 0 <= t <= at_seconds for t in times)
            or times != sorted(set(times))):
        raise ValueError('invalid_wave_spawn_history')
    gaps = [b - a for a, b in zip(times, times[1:])]
    window = None
    status = 'insufficient_local_history'
    if len(gaps) >= 2:
        # Round outward to the game-second scale used for decisions.
        low, high = math.floor(times[-1] + min(gaps)), math.ceil(times[-1] + max(gaps))
        if high > at_seconds:
            window = [max(at_seconds, low), high]
            status = 'conditional_on_recent_birth_cadence'
        else:
            status = 'expected_birth_not_observed_in_prefix'
    return dict(status=status, observed_starts=times, sample_intervals_seconds=gaps, next_birth_window=window,
                basis='first_observed_melee_after_ranged_same_team_lane_spawner',
                meaning='conditional_next_allied_birth_at_base_not_lane_arrival_or_clear_time')


def _allied_births(raw, at_seconds, observer_team_id):
    info = container_info(raw)
    if info['version'] != VERSION or hashlib.sha256(raw).hexdigest() not in MAP11_REPLAYS:
        raise ValueError('unreviewed_wave_clock_source')
    if (type(observer_team_id) is not int or observer_team_id not in (100, 200)
            or not number(at_seconds) or not 0 <= at_seconds <= info['metadata']['gameLength'] / 1000):
        raise ValueError('invalid_wave_clock_scope')
    births = {lane: [] for lane in LANE_NAMES.values()}
    for packet in packets(raw):
        if packet['stream'] != 1 or packet['opcode'] != 0x456 or packet['time'] > at_seconds:
            continue
        origin = minion_birth(packet['payload'])
        if origin and origin[0] == observer_team_id:
            lane = LANE_NAMES[origin[1]]
            births[lane].append((packet['time'], packet['param'], minion_class(packet['payload'])))
    return births


def allied_wave_clocks(raw, *, at_seconds, observer_team_id):
    births = _allied_births(raw, at_seconds, observer_team_id)
    return {lane: wave_clock_at(rows, at_seconds=at_seconds) for lane, rows in births.items()}


def audit_birth_forecasts(raw, *, lane='mid', observer_team_id=100):
    """Score rolling prefixes on one spawner; never expose later labels to the tool."""
    end = container_info(raw)['metadata']['gameLength'] / 1000
    rows = _allied_births(raw, end, observer_team_id)[lane]
    # Separate outcome pass reading the actual first observed melee after ranged.
    markers = []
    prior = None
    for t, entity, kind in sorted(set(rows)):
        if kind in ('ranged', 'melee'):
            if kind == 'melee' and prior == 'ranged':
                markers.append(t)
            prior = kind
    hits, cold, misses = 0, 0, []
    for cut, outcome in zip(markers, markers[1:]):
        prefix = [r for r in rows if r[0] <= cut]
        predicted = wave_clock_at(prefix, at_seconds=cut)['next_birth_window']
        if predicted is None:
            cold += 1
        elif predicted[0] <= outcome <= predicted[1]:
            hits += 1
        else:
            misses.append(dict(at=cut, predicted=predicted, observed=outcome))
    return dict(observer_team_id=observer_team_id, lane=lane, replay_sha256=hashlib.sha256(raw).hexdigest(),
                hits=hits, misses=misses, insufficient=cold, compared=hits + len(misses))


if __name__ == '__main__':
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description='Backtest the next allied birth at a single lane spawner.')
    parser.add_argument('replays', nargs='+', type=Path)
    parser.add_argument('--lane', choices=['top', 'mid', 'bot'], default='mid')
    parser.add_argument('--team', choices=[100, 200], type=int, default=100)
    args = parser.parse_args()
    for path in args.replays:
        audit = audit_birth_forecasts(path.read_bytes(), lane=args.lane, observer_team_id=args.team)
        print(json.dumps(dict(replay=path.name, **audit), allow_nan=False))
