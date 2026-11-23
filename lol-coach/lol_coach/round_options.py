"""Compare three conditional departures using only a frozen team decision frame."""
from bisect import bisect_right
from functools import lru_cache
import json
from math import dist, isclose
from pathlib import Path

from .reasoning_frame import FRAME_SCHEMA, digest, number
from .round_wave_clock import birth_forecast


LANES = ('top', 'mid', 'bot', 'single_lane')
RESOURCE_ORIGINS = (*LANES, 'jungle')
TIMING_CLOCKS = ('immediate_route_duration', 'route_duration', 'wave_clear_duration',
                 'target_deadline', 'target_work_duration', 'return_duration', 'next_wave_deadline',
                 'target_finish_with_help', 'target_finish_without_help')
JUNGLE_CLOCKS = tuple(k for k in TIMING_CLOCKS if k not in
                      ('wave_clear_duration', 'next_wave_deadline', 'return_duration')) + (
                          'camp_clear_duration', 'return_to_camp_duration')


@lru_cache(maxsize=1)
def _camp_profile():
    path = Path(__file__).with_name('profiles') / 'camps_map11_16_22.json'
    return json.loads(path.read_bytes())


def _jungle_observation(frame, actor):
    """Locate the selected player's sampled position with respect to static camps."""
    profile = _camp_profile()
    result = dict(camps_by_distance_from_sample=[], path_fact_id=None, sampled_at=None,
                  age_seconds=None, camp_presence='unknown', current_camp=None,
                  remaining_clear_seconds=None, gold_or_xp_forgone=None, last_personal_observations=[],
                  constant_damage_rate_scenario=None,
                  conditions=['confirm_camp_present_and_contestable', 'check_health_resources_and_smite',
                              'compare_allies_and_opponents_at_destination'])
    if frame['decision']['build'] != profile['build']:
        return result
    for fid, fact in _checked_facts(frame, 'personal_camp_fact_ids'):
        if fact['entity_id'] != actor:
            continue
        v = fact['value']
        if (fact['field'] != 'personal_jungle_camp_observation' or fact['temporal_scope'] != 'historical_personal_camp_hud'
                or v['observer_team_id'] != frame['decision']['observer_team_id']):
            raise ValueError('invalid_personal_camp_fact')
        result['last_personal_observations'].append(dict(fact_id=fid, sampled_at=fact['observed_at_seconds'],
                                                          age_seconds=fact['age_seconds'], **v))
        if fact['age_seconds'] == 0:
            result['camp_presence'] = 'engaged_at_sample' if v['state'] == 'engaged' else 'cleared_at_sample'
            result['current_camp'] = v['camp'] if v['state'] == 'engaged' else None
            if v['state'] == 'engaged' and 'monster_hp' in v:
                elapsed = fact['observed_at_seconds'] - v['last_full_at']
                damage = v['full_hp'] - v['monster_hp']
                if elapsed >= 2 and damage > 0:
                    result['constant_damage_rate_scenario'] = dict(
                        elapsed_seconds=elapsed, damage_since_full=damage,
                        hp_per_second=round(damage/elapsed, 2),
                        seconds_if_rate_held=round(v['monster_hp']*elapsed/damage, 2), evidence_id=fid,
                        assumptions=['uninterrupted_clear', 'same_average_damage_including_pet_and_abilities'],
                        excludes=['unseen_future_smite', 'future_bursts', 'reset_or_disengage'])
    for fid, fact in _checked_facts(frame, 'allied_path_fact_ids'):
        if fact['entity_id'] != actor:
            continue
        v = fact['value']
        if (fact['field'] != 'allied_path_start_sample' or fact.get('unit') != 'map11_world_xz'
                or fact['temporal_scope'] != 'historical_path_start_sample'
                or v.get('observer_team_id') != frame['decision']['observer_team_id']
                or not isinstance(v.get('xz'), list) or len(v['xz']) != 2 or not all(number(x) for x in v['xz'])
                or result['path_fact_id'] is not None):
            raise ValueError('invalid_jungle_position_sample')
        places = [dict(**camp, distance_world=round(dist(v['xz'], camp['xz']), 1)) for camp in profile['camps']]
        result.update(path_fact_id=fid, sampled_at=fact['observed_at_seconds'], age_seconds=fact['age_seconds'],
                      map_config_sha256=profile['config_sha256'],
                      camps_by_distance_from_sample=sorted(places, key=lambda r: r['distance_world'])[:3])
    return result


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


def _allied_birth_cohorts(units, clock, at, *, include_geometry=False):
    """Group still-registered allies by observed spawner starts, independently of their map position."""
    starts = clock['observed_starts']
    intervals = clock['sample_intervals_seconds']
    groups = {}
    samples = {}
    unassigned = 0
    for unit in units:
        born = unit.get('born_at')
        if born is not None and (not number(born) or not 0 <= born <= at):
            raise ValueError('invalid_lane_unit_birth')
        index = -1 if born is None else bisect_right(starts, born) - 1
        # The bounded marker history can begin after an older surviving unit.
        # A missing later marker cannot extend a wave across an entire observed cadence.
        if index < 0 or (born > starts[index] and (not intervals or born - starts[index] >= min(intervals))):
            unassigned += 1
            continue
        start = starts[index]
        group = groups.setdefault(start, dict(first_melee_born_at=start, registered=0,
                                              registered_siege=0, recent_position_count=0))
        group['registered'] += 1
        group['registered_siege'] += int(unit.get('kind') == 'siege')
        sampled = unit.get('sampled_at')
        group['recent_position_count'] += int(sampled is not None and sampled >= at - 1)
        if include_geometry and sampled is not None:
            samples.setdefault(start, []).append((unit['last_xz'], at - sampled))
    cohorts = [groups[t] for t in sorted(groups)]
    if include_geometry:
        for row in cohorts:
            group_samples = samples.get(row['first_melee_born_at'], [])
            row['position_count'] = len(group_samples)
            row['sample_centroid_xz'] = None
            row['sample_age_seconds'] = None
            if group_samples:
                points, ages = zip(*group_samples)
                row['sample_centroid_xz'] = [sum(axis)/len(points) for axis in zip(*points)]
                row['sample_age_seconds'] = [min(ages), max(ages)]
    return dict(basis='registered_allies_by_observed_birth_marker', cohorts=cohorts,
                unassigned_count=unassigned)


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
            if scope == 'own_team_observed_live_only' and 'units' in v:
                result['allied_birth_cohorts'] = _allied_birth_cohorts(v['units'], projection, at)
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
        if (key not in (JUNGLE_CLOCKS if lane == 'jungle' else TIMING_CLOCKS) or not isinstance(pair, list) or len(pair) != 2
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
    if lane not in RESOURCE_ORIGINS or not isinstance(target, str) or not target.strip() or target != target.strip():
        raise ValueError('invalid_lane_or_target')
    if not number(help_seconds) or help_seconds < 0:
        raise ValueError('invalid_proposed_help_seconds')
    matches = [h for h in frame['lineup'] if h['entity_id'] == actor]
    if len(matches) != 1 or matches[0]['relation'] != 'ally':
        raise ValueError('actor_outside_observer_team')

    clocks, ids = _timing_clocks(frame, actor, lane, target, help_seconds)
    jungle = lane == 'jungle'
    lane_obs = None if jungle else _lane_observation(frame, lane)
    clear_clock = 'camp_clear_duration' if jungle else 'wave_clear_duration'
    return_clock = 'return_to_camp_duration' if jungle else 'return_duration'
    base = [at, at]
    durations = [('leave_now', [0, 0]), ('help_then_leave', [help_seconds, help_seconds]),
                 ('clear_then_leave', clocks.get(clear_clock))]
    options = []
    for action, delay in durations:
        depart = _sum_windows(base, delay)
        route = 'route_duration'
        if delay == [0, 0] and 'immediate_route_duration' in clocks:
            route = 'immediate_route_duration'
        arrive = _sum_windows(depart, clocks.get(route))
        finish = _sum_windows(arrive, clocks.get('target_work_duration'))
        returned = _sum_windows(finish, clocks.get(return_clock))
        earliest_departure = depart[0] if depart else at
        earliest_return = (finish or arrive or depart or base)[0]
        evidence_keys = [route, 'target_deadline', 'target_work_duration', return_clock, 'next_wave_deadline']
        conditions = ['actor_can_act_and_take_route', 'same_origin_path_and_speed_as_clock']
        if action == 'help_then_leave':
            conditions += ['help_possible_from_present_position', 'proposed_hold_does_not_prove_contribution']
        if action == 'clear_then_leave':
            conditions.append('camp_available_and_actor_can_finish_from_current_state' if jungle
                              else 'actor_can_reach_and_clear_this_wave_from_present_position')
            evidence_keys.append(clear_clock)
        route_budget = None
        deadline = clocks.get('target_deadline')
        if deadline is not None and depart is not None:
            route_budget = [deadline[0] - depart[1], deadline[1] - depart[0]]
        options.append(dict(action=action, depart_at=depart, arrive_at=arrive, finish_target_at=finish,
            available_travel_seconds=route_budget,
            return_to_lane_at=None if jungle else returned, target_window=_by_deadline(arrive, clocks.get('target_deadline'), earliest_departure),
            next_wave_window=_by_deadline(returned, clocks.get('next_wave_deadline'), earliest_return),
            conditions=conditions, evidence_ids=[ids[k] for k in evidence_keys if k in ids]))
        if jungle:
            options[-1]['return_to_camp_at'] = returned
    unknowns = [k for k in (JUNGLE_CLOCKS if jungle else TIMING_CLOCKS) if k not in clocks]
    if lane_obs is None and not jungle:
        unknowns.append('lane_observation')
    contribution = None
    with_help, without_help = clocks.get('target_finish_with_help'), clocks.get('target_finish_without_help')
    if with_help is not None and without_help is not None:
        contribution = dict(estimated_seconds_saved=[without_help[0] - with_help[1], without_help[1] - with_help[0]],
            evidence_ids=[ids['target_finish_with_help'], ids['target_finish_without_help']],
            assumption='only_this_actors_help_changes_other_participants_and_target_are_fixed')
    result = dict(schema='round-options/v1', frame_id=frame['frame_id'], at_seconds=at, observer_team_id=team,
        actor_id=actor, lane=lane, target=target, proposed_help_seconds=help_seconds,
        lane_observation=lane_obs, clocks=clocks, clock_evidence_ids=ids, options=options, unknowns=unknowns,
        unit='absolute_game_seconds_for_option_windows', actual_arrival=None,
        additional_objective_contribution=contribution, exact_minions_forgone=None)
    if jungle:
        result['jungle_observation'] = _jungle_observation(frame, actor)
    return result


def _coordination_wave(frame, lane):
    obs = _lane_observation(frame, lane)
    if obs is None:
        return None
    clock = obs.get('wave_spawn_clock', {})
    result = dict(lane=lane, fact_id=obs['fact_id'], visible_counts=obs['counts'],
                  enemy_coverage=obs['enemy_minions']['status'],
                  next_allied_birth_at_base=clock.get('next_birth_window'),
                  next_clash_at=None, crash_at=None)
    if 'allied_birth_cohorts' in obs:
        units = frame['facts'][obs['fact_id']]['value']['units']
        cohorts = _allied_birth_cohorts(units, clock, frame['decision']['at_seconds'], include_geometry=True)
        result['registered_cohorts'] = cohorts['cohorts']
        result['unassigned_count'] = cohorts['unassigned_count']
        for older, later in zip(cohorts['cohorts'], cohorts['cohorts'][1:]):
            a, b = older['sample_centroid_xz'], later['sample_centroid_xz']
            later['sampled_gap_from_older_cohort_world_units'] = round(dist(a, b), 1) if a and b else None
    return result


def resource_window(frame, comparison, *, self_state=None):
    """Facts for communicating the cost of leaving lane/camp on this frame's named route."""
    at = frame['decision']['at_seconds']
    if (comparison['frame_id'] != frame['frame_id'] or comparison['at_seconds'] != at
            or comparison['actor_id'] != frame['decision']['player_entity_id']
            or comparison['observer_team_id'] != frame['decision']['observer_team_id']):
        raise ValueError('coordination_resource_scope_mismatch')
    lane, clocks = comparison['lane'], comparison['clocks']
    deadline = clocks.get('target_deadline')
    own = self_state or {}
    result = dict(origin=lane, timing_target=comparison['target'], target_arrival_deadline=deadline,
                  timing_recipient_id=None,
                  timing_scope='时限只适用于所列目的地；队友能等多久、是否愿意配合需另有证据。',
                  timing_fact_ids=comparison['clock_evidence_ids'],
                  arrival_options=[{k:row[k] for k in ('action', 'depart_at', 'arrive_at', 'target_window',
                                                         'return_to_lane_at', 'next_wave_window')}
                                   for row in comparison['options'] if row['action'] != 'help_then_leave'],
                  observed_self_at_sample={k:own[k] for k in ('health', 'max_health', 'resource', 'max_resource',
                                                               'personal_hud_state') if k in own},
                  arrival_health_resource=None)
    result['target_work_comparison'] = dict(
        finish_with_this_help=clocks.get('target_finish_with_help'),
        finish_without_this_help=clocks.get('target_finish_without_help'),
        conditional_effect=comparison['additional_objective_contribution'])
    # An objective deadline only applies to its named destination. Reaching it never proves ally readiness.
    destination_lane = comparison['target'] if comparison['target'] in LANES else None
    lanes = ([lane] if lane in LANES else [])
    if destination_lane and destination_lane not in lanes:
        lanes.append(destination_lane)
    if not lanes:
        lanes = ['top', 'mid', 'bot']
    result['timing_target_lane'] = destination_lane
    result['lane_scope'] = '限时未绑定线上接应，三路线况仅供选人。' if lane == 'jungle' and not destination_lane else '兵线观测不产生到场时限。'
    result['lanes'] = [wave for name in lanes if (wave := _coordination_wave(frame, name)) is not None]
    if result['lanes']:
        result['wave_actions_to_compare'] = {
            'leave_untouched': '先看双方都不碰兵时前后波何时接上。若本人先走，另看对手留下截线或清线。',
            'last_hit': '本人只收残血兵。能否安全补、对手额外打兵量与援兵先后决定会推还是会被推。',
            'slow_push': '只削薄到前波能存活至援兵接上，观察对手能否提前削薄。出生时刻只计在基地。',
            'fast_push': '清完后还须让兵在敌方增援前进塔。单人送不进去才请求帮推；己方塔下能接但有越塔风险时请保护。',
        }
    if lane == 'jungle':
        camp = comparison['jungle_observation']
        result['camp'] = dict(name=camp['current_camp'], status=camp['camp_presence'], smite_ready=None,
                              last_personal_observations=camp['last_personal_observations'],
                              clear_at_constant_rate=None)
        native = own.get('personal_client_state')
        if native:
            result['camp']['equipped_summoners_at_sample'] = dict(
                values=native['value']['summoner_spells'], fact_id=native['fact_id'],
                observed_at_seconds=native['observed_at_seconds'])
        rate = camp['constant_damage_rate_scenario']
        if rate:
            # The published two-decimal estimate is for display. Keep the original
            # precision when comparing the scenario to an absolute deadline.
            hp = frame['facts'][rate['evidence_id']]['value']['monster_hp']
            finish = at + hp * rate['elapsed_seconds'] / rate['damage_since_full']
            departure = [finish, finish]
            arrival = _sum_windows(departure, clocks.get('route_duration'))
            result['camp']['clear_at_constant_rate'] = dict(
                **rate, depart_at_if_rate_holds=round(finish, 2), arrive_at_if_rate_holds=arrival,
                target_window_if_rate_holds=_by_deadline(arrival, deadline, departure[0]),
                seconds_left_for_travel_if_rate_holds=(
                    [t - departure[0] for t in deadline] if deadline is not None else None))
    return result
