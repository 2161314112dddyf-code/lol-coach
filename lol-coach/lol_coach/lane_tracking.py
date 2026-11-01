"""Causal position estimates along the latest received lane-minion path.

This estimates motion; it does not prove arrival, visibility, or survival.
Callers must first filter paths to the observer's current visible interval and
exclude inactive entities. Checkpoint/future paths cannot enter the estimator.
"""
from copy import deepcopy
import math


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _point(value):
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and all(_finite(axis) for axis in value))


def latest_paths_at(events, at):
    """Select live prefix paths only; callers still own observer/lifecycle gates.

    A later path replaces all of the earlier path, including a single-point
    stop. No checkpoint, future row, or interpolation from a future row is used.
    """
    if not _finite(at) or at < 0:
        raise ValueError('Invalid tracking cutoff')
    result, keys = {}, {}
    for event in events:
        if event.get('kind') != 'path_command' or event.get('source', {}).get('stream') != 1:
            continue
        time = event.get('time_seconds')
        if not _finite(time) or time < 0:
            raise ValueError('Invalid live path timestamp')
        if time > at:
            continue
        actor = event.get('entity_id')
        if not isinstance(actor, str):
            raise ValueError('Missing path entity')
        source = event['source']
        location = tuple(source.get(field, -1) for field in
                         ('chunk', 'decompressed_offset', 'packet_index'))
        if any(type(value) is not int or value < -1 for value in location):
            raise ValueError('Invalid path source ordering')
        key = (time, *location)
        if actor not in keys or key > keys[actor]:
            result[actor], keys[actor] = deepcopy(event), key
        elif key == keys[actor] and event != result[actor]:
            raise ValueError('Conflicting paths at identical packet location')
    return result


def estimate_path(event, at, *, map_binding=None):
    """Advance a received path at constant serialized speed, clamped to its end.

    ``relative_position_estimate`` is in the common ``lane_relative`` space.
    Optional world coordinates require an explicit caller-supplied map binding;
    that binding remains an inference if its evidence says so. An empirical
    aggregate error distribution must never be presented as a point guarantee.
    """
    if event.get('kind') != 'path_command' or event.get('source', {}).get('stream') != 1:
        raise ValueError('Expected a live path command')
    time = event.get('time_seconds')
    if not _finite(time) or time < 0 or not _finite(at) or at < time:
        raise ValueError('Invalid path estimate time or future support')
    points = event.get('relative_waypoints')
    if not isinstance(points, (list, tuple)) or not points or not all(_point(p) for p in points):
        raise ValueError('Expected finite relative path points')
    speed = event.get('path_speed')
    if not _finite(speed) or not 0 <= speed <= 5000:
        raise ValueError('Invalid serialized path speed')
    lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
    total = sum(lengths)
    elapsed = at-time
    budget = speed*elapsed
    if not math.isfinite(total) or not math.isfinite(budget):
        raise ValueError('Path distance overflow')
    position = list(points[0])
    clamped = False
    if total == 0:
        state = 'single_point_hold'
    elif speed == 0:
        state = 'zero_speed_hold'
    elif budget >= total:
        position = list(points[-1])
        clamped = True
        state = 'planned_endpoint_estimate'
    else:
        remaining = budget
        for a, b, length in zip(points, points[1:], lengths):
            if length == 0:
                continue
            if remaining <= length:
                position = [a[i]+(b[i]-a[i])*remaining/length for i in range(2)]
                break
            remaining -= length
        state = 'moving_estimate'
    world = None
    if map_binding is not None:
        if (not isinstance(map_binding, dict) or type(map_binding.get('map_id')) is not int
                or map_binding['map_id'] not in (11, 12)
                or not _point(map_binding.get('origin_xz'))
                or not isinstance(map_binding.get('binding_status'), str)
                or not map_binding['binding_status']):
            raise ValueError('Explicit supported map-origin binding required')
        world = [position[i]+map_binding['origin_xz'][i] for i in range(2)]
    return dict(entity_id=event.get('entity_id'), at_seconds=at,
        relative_position_estimate=position, coordinate_space='lane_relative',
        world_position_estimate=world, map_binding=deepcopy(map_binding),
        motion_state=state, method='constant_speed_along_latest_received_path',
        support_time_seconds=time, path_age_seconds=elapsed,
        source=deepcopy(event['source']), endpoint_clamped=clamped,
        actual_arrival=None, alive=None, estimated=True,
        error_semantics='Aggregate held-out errors are not a per-point guarantee',
        path_distance=total, travelled_path_distance=min(budget, total),
        remaining_path_distance=max(0., total-budget),
        assumptions=['Serialized speed holds until a replacing command',
            'No unseen cancellation, displacement, or speed change after support',
            'Caller filtered observer visibility interval and lifecycle'])
