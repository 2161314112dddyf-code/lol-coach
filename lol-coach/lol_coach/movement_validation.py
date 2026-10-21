"""Keep packet candidates separate from explicitly observed video time intervals."""
import math


def candidate_transitions(records):
    """Classify a single entity's ordered records without joining path segments."""
    active = None
    previous_time = -math.inf
    output = []
    for record in records:
        time = record['time']
        points = record['points']
        speed = record['speed']
        values = [time, speed] + [v for p in points for v in p]
        if (not points or any(len(p) != 2 for p in points) or
                any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values) or
                speed < 0 or time < 0 or time <= previous_time):
            raise ValueError('Invalid or unordered candidate records')
        previous_time = time
        if len(points) > 1:
            if active is not None:
                output.append({'kind': 'path_superseded', 'start_time': active['time'],
                               'next_record_time': time, 'actual_arrival': None})
            active = record
        elif active is not None:
            length = sum(math.dist(a, b) for a, b in zip(active['points'], active['points'][1:]))
            output.append({'kind': 'single_point_at_planned_endpoint' if points[0] == active['points'][-1]
                           else 'single_point_elsewhere',
                           'start_time': active['time'], 'single_point_time': time,
                           'planned_endpoint': active['points'][-1], 'single_point': points[0],
                           'packet_interval_seconds': time - active['time'],
                           'planned_length_game_units': length,
                           'constant_speed_duration_hypothesis_seconds': length / active['speed'] if active['speed'] > 0 else None,
                           'actual_arrival': None, 'actual_duration_seconds': None,
                           'manual_stop_confirmed': None})
            active = None
    if active is not None:
        output.append({'kind': 'open_path', 'start_time': active['time'], 'actual_arrival': None})
    return output


def shared_clock_offset(event_pairs):
    """Diagnose, but do not fit, packet-minus-video offset from matched brackets.

    Only useful conditional on correctness of manual event association/brackets.
    No conversion from packet timestamp to game clock is asserted.
    """
    if not event_pairs:
        raise ValueError('No event pairs')
    ranges = []
    for pair in event_pairs:
        lo, hi = pair['video_interval_seconds']
        time = pair['packet_time_seconds']
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (lo, hi, time)) or lo > hi:
            raise ValueError('Invalid event interval')
        ranges.append([time - hi, time - lo])
    low, high = max(r[0] for r in ranges), min(r[1] for r in ranges)
    return {'offset_ranges_seconds': ranges, 'has_shared_offset': low <= high,
            'shared_offset_interval_seconds': [low, high] if low <= high else None,
            'minimum_interval_gap_seconds': max(0, low - high),
            'status': 'conditional_manual_bracket_diagnostic_not_clock_calibration'}


def observed_duration_interval(start, end):
    """Propagate observed event bounds; do not use packet time or speed.

    Bounds must distinguish two ordered events. Overlap cannot silently become
    a zero-duration measurement. Returned bounds are not statistical confidence.
    """
    for pair in (start, end):
        if len(pair) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or
                                 not math.isfinite(v) or v < 0 for v in pair) or pair[0] > pair[1]:
            raise ValueError('Invalid observation interval')
    if start[1] >= end[0]:
        raise ValueError('Start and end observations are not separated')
    return [end[0] - start[1], end[1] - start[0]]
