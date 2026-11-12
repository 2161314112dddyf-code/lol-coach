"""Compare three conditional departures using only a frozen team decision frame."""
from math import isclose

from .reasoning_frame import FRAME_SCHEMA, digest, number
from .round_wave_clock import birth_forecast


LANES = ('top', 'mid', 'bot', 'single_lane')
TIMING_CLOCKS = ('immediate_route_duration', 'route_duration', 'wave_clear_duration',
                 'target_deadline', 'target_work_duration', 'return_duration', 'next_wave_deadline',
                 'target_finish_with_help', 'target_finish_without_help')


def _checked_facts(frame, index):
    at = frame['decision']['at_seconds']
    ids = frame.get(index, [])
    if not isinstance(ids, list) or len(set(ids)) != len(ids):
        raise ValueError('ambiguous_round_fact_index')
    for fid in ids:
        fact = frame['facts'].get(fid)
        if not isinstance(fact, dict) or fid != 'f_' + digest(fact)[:20]:
            raise ValueError('invalid_round_evidence')
        when = fact['observed_at_seconds']
        available = fact.get('available_at_seconds', when)
        if (not number(when) or not number(available) or not 0 <= when <= available <= at
                or not number(fact['age_seconds']) or not isclose(fact['age_seconds'], at - when)):
            raise ValueError('round_evidence_outside_prefix')
        yield fid, fact


def _allied_position_samples(units, total, at):
    """Count each tracked unit's last path start once, by its own packet time."""
    if not isinstance(units, list) or len(units) != total:
        raise ValueError('invalid_lane_unit_samples')
    window_start = max(0, at - 1)
    seen = set()
    times = []
    for unit in units:
        if not isinstance(unit, dict):
            raise ValueError('invalid_lane_unit_samples')
        entity = unit.get('entity_id')
        if not isinstance(entity, str) or not entity or entity in seen:
            raise ValueError('invalid_lane_unit_samples')
        seen.add(entity)
        when, xz = unit.get('sampled_at'), unit.get('last_xz')
        if when is None and xz is None:
            continue
        if (not number(when) or not 0 <= when <= at or not isinstance(xz, list)
                or len(xz) != 2 or not all(number(v) for v in xz)):
            raise ValueError('invalid_lane_position_sample')
        times.append(when)
    recent = sum(when >= window_start for when in times)
    return dict(basis='last_observed_path_start_per_allied_minion', max_age_seconds=1,
                window_start_seconds=window_start, recent_count=recent,
                older_count=len(times)-recent, unsampled_count=total-len(times))


def _lane_observation(frame, lane):
    at, team = (frame['decision'][k] for k in ('at_seconds', 'observer_team_id'))
    result = None
    for fid, fact in _checked_facts(frame, 'lane_fact_ids'):
        if fact['field'] != 'lane_current_units_and_groups' or fact['entity_id'] != 'lane:' + lane:
            continue
        v = fact['value']
        if (v.get('lane') != lane or v.get('observer_team_id', team) != team
                or fact['observed_at_seconds'] != at or result is not None):
            raise ValueError('invalid_lane_observation')
        scope = v.get('count_scope', 'observer_filtered_visible_units')
        counts = []
        for row in v['counts']:
            observed_team = row['team_id']
            if (type(observed_team) is not int or observed_team not in (100, 200)
                    or type(row['count']) is not int or row['count'] < 0
                    or not isinstance(row['kind'], str)
                    or (scope == 'own_team_observed_live_only' and observed_team != team)):
                raise ValueError('invalid_lane_count')
            counts.append(dict(team_id=observed_team, kind=row['kind'], count=row['count']))
        result = dict(fact_id=fid, lane=lane, count_scope=scope, counts=counts)
        enemy_count = None
        enemy_status = 'coverage_unknown'
        result['position_samples'] = None
        if scope == 'own_team_observed_live_only':
            enemy_status = 'outside_source_coverage'
            if 'units' in v:
                result['position_samples'] = _allied_position_samples(
                    v['units'], sum(row['count'] for row in counts), at)
        elif scope == 'observer_filtered_visible_units':
            enemy_count = sum(row['count'] for row in counts if row['team_id'] != team)
            enemy_status = 'observed' if enemy_count else 'none_in_observer_sample'
        result['enemy_minions'] = dict(status=enemy_status, observed_count=enemy_count,
                                      total_alive_count=None)
        if 'wave_spawn_clock' in v:
            clock = v['wave_spawn_clock']
            projection = birth_forecast(clock['observed_starts'], at)
            if any(clock.get(k) != value for k, value in projection.items()):
                raise ValueError('invalid_wave_spawn_forecast')
            result['wave_spawn_clock'] = projection
    return result


def _timing_clocks(frame, actor, lane, target, help_seconds):
    """Durations describe counterfactual plans; deadlines use absolute game seconds."""
    at, team = (frame['decision'][k] for k in ('at_seconds', 'observer_team_id'))
    intervals, ids = {}, {}
    for fid, fact in _checked_facts(frame, 'timing_fact_ids'):
        v = fact['value']
        if (fact['field'] != 'round_timing_window' or fact['unit'] != 'seconds'
                or fact['temporal_scope'] != 'conditional_timing_for_decision'
                or type(v.get('observer_team_id')) is not int or v['observer_team_id'] != team):
            raise ValueError('invalid_round_timing_scope')
        if (fact['entity_id'], v.get('lane'), v.get('target')) != (actor, lane, target):
            continue
        key, pair = v.get('clock'), v.get('interval')
        if (key not in TIMING_CLOCKS or not isinstance(pair, list) or len(pair) != 2
                or not all(number(n) for n in pair) or not 0 <= pair[0] <= pair[1]):
            raise ValueError('invalid_round_timing_interval')
        if key in ('target_finish_with_help', 'target_finish_without_help'):
            if pair[0] < at or not number(v.get('help_seconds')) or v['help_seconds'] < 0:
                raise ValueError('invalid_marginal_help_window')
            if v['help_seconds'] != help_seconds:
                continue
        # Past measurements need a host-supplied applicability horizon. Never use
        # a historic travel sample (or a path for a different target) as live ETA.
        expires = v.get('valid_until_seconds', fact['observed_at_seconds'])
        if not number(expires) or expires < fact['observed_at_seconds']:
            raise ValueError('invalid_round_timing_expiry')
        if expires < at:
            continue
        if key in intervals:
            raise ValueError('ambiguous_round_timing_clock')
        intervals[key], ids[key] = pair, fid
    return intervals, ids


def _sum_windows(a, b):
    if a is None or b is None:
        return None
    pair = [a[0] + b[0], a[1] + b[1]]
    if not all(number(n) for n in pair):
        raise ValueError('round_time_overflow')
    return pair


def _by_deadline(arrival, deadline, earliest_possible):
    if deadline is None:
        return 'unknown'
    # A delay alone can rule a plan out even without a measured route.
    # It cannot establish success without an upper bound on arrival.
    if earliest_possible > deadline[1]:
        return 'too_late'
    if arrival is None:
        return 'unknown'
    if arrival[1] <= deadline[0]:
        return 'before_or_at'
    if arrival[0] > deadline[1]:
        return 'too_late'
    return 'overlap'


def compare_round_options(frame, *, lane, target, help_seconds, actor_id=None):
    """Holding is a proposed delay. Clearing requires that actor's own clear clock.

    A reusable route_duration asserts the same origin, traversable path and speed
    under all three options. immediate_route_duration applies only to departure now.
    An arrival window measures reaching the named target, never a kill or a secured
    objective. next_wave_deadline concerns the following wave, after work and return.
    """
    if (frame.get('schema') != FRAME_SCHEMA
            or frame.get('frame_id') != 'frame_' + digest({k: v for k, v in frame.items() if k != 'frame_id'})[:24]):
        raise ValueError('invalid_frozen_frame')
    d = frame['decision']
    at, team = d['at_seconds'], d['observer_team_id']
    actor = d['player_entity_id'] if actor_id is None else actor_id
    if type(team) is not int or team not in (100, 200) or not number(at) or at < 0:
        raise ValueError('invalid_decision_scope')
    if lane not in LANES or not isinstance(target, str) or not target.strip() or target != target.strip():
        raise ValueError('invalid_lane_or_target')
    if not number(help_seconds) or help_seconds < 0:
        raise ValueError('invalid_proposed_help_seconds')
    matches = [h for h in frame['lineup'] if h['entity_id'] == actor]
    if len(matches) != 1 or matches[0]['relation'] != 'ally':
        raise ValueError('actor_outside_observer_team')

    clocks, ids = _timing_clocks(frame, actor, lane, target, help_seconds)
    lane_obs = _lane_observation(frame, lane)
    base = [at, at]
    durations = [('leave_now', [0, 0]), ('help_then_leave', [help_seconds, help_seconds]),
                 ('clear_then_leave', clocks.get('wave_clear_duration'))]
    options = []
    for action, delay in durations:
        depart = _sum_windows(base, delay)
        route = 'route_duration'
        if delay == [0, 0] and 'immediate_route_duration' in clocks:
            route = 'immediate_route_duration'
        arrive = _sum_windows(depart, clocks.get(route))
        finish = _sum_windows(arrive, clocks.get('target_work_duration'))
        returned = _sum_windows(finish, clocks.get('return_duration'))
        earliest_departure = depart[0] if depart else at
        earliest_return = (finish or arrive or depart or base)[0]
        evidence_keys = [route, 'target_deadline', 'target_work_duration', 'return_duration', 'next_wave_deadline']
        conditions = ['actor_can_act_and_take_route', 'same_origin_path_and_speed_as_clock']
        if action == 'help_then_leave':
            conditions += ['help_possible_from_present_position', 'proposed_hold_does_not_prove_contribution']
        if action == 'clear_then_leave':
            conditions += ['actor_can_reach_and_clear_this_wave_from_present_position']
            evidence_keys.append('wave_clear_duration')
        route_budget = None
        deadline = clocks.get('target_deadline')
        if deadline is not None and depart is not None:
            route_budget = [deadline[0] - depart[1], deadline[1] - depart[0]]
        options.append(dict(action=action, depart_at=depart, arrive_at=arrive, finish_target_at=finish,
            available_travel_seconds=route_budget,
            return_to_lane_at=returned, target_window=_by_deadline(arrive, clocks.get('target_deadline'), earliest_departure),
            next_wave_window=_by_deadline(returned, clocks.get('next_wave_deadline'), earliest_return),
            conditions=conditions, evidence_ids=[ids[k] for k in evidence_keys if k in ids]))
    unknowns = [k for k in TIMING_CLOCKS if k not in clocks]
    if lane_obs is None:
        unknowns.append('lane_observation')
    contribution = None
    with_help, without_help = clocks.get('target_finish_with_help'), clocks.get('target_finish_without_help')
    if with_help is not None and without_help is not None:
        contribution = dict(estimated_seconds_saved=[without_help[0] - with_help[1], without_help[1] - with_help[0]],
            evidence_ids=[ids['target_finish_with_help'], ids['target_finish_without_help']],
            assumption='only_this_actors_help_changes_other_participants_and_target_are_fixed')
    return dict(schema='round-options/v1', frame_id=frame['frame_id'], at_seconds=at, observer_team_id=team,
        actor_id=actor, lane=lane, target=target, proposed_help_seconds=help_seconds,
        lane_observation=lane_obs, clocks=clocks, clock_evidence_ids=ids, options=options, unknowns=unknowns,
        unit='absolute_game_seconds_for_option_windows', actual_arrival=None,
        additional_objective_contribution=contribution, exact_minions_forgone=None)
