"""Standalone validation of conditional route arithmetic, never model input.

Predictions use a received route and its speed only. The evaluator reads later
position reports separately; a report timestamp is NOT an exact arrival time.
"""
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
import math
import statistics

from .action_evidence import conditional_travel


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode('utf8')).hexdigest()


def order(row):
    src = row['source']
    return (row['time_seconds'], src.get('chunk', -1),
            src.get('decompressed_offset', -1), src.get('packet_index', -1))


def finite(value):
    return type(value) in (float, int) and math.isfinite(value)


def freeze_predictions(events, *, replay_id, version, source_sha256, entity_kind):
    """Freeze all live multi-point path forecasts before any scoring.

    End-of-timestamp selection avoids counting overwritten simultaneous routes
    as independent forecasts. No checkpoint, later position or outcome is used.
    """
    selected = {}
    counts = Counter()
    for event in events:
        if event.get('kind') != 'path_command' or event.get('source', {}).get('stream') != 1:
            continue
        t = event.get('time_seconds')
        if not finite(t) or t < 0 or not isinstance(event.get('entity_id'), str):
            raise ValueError('Invalid live path time/entity')
        key = (event['entity_id'], t)
        counts['live_path_rows'] += 1
        if key in selected:
            counts['same_time_replaced'] += 1
            if order(event) == order(selected[key]) and event != selected[key]:
                raise ValueError('Conflicting path source')
        if key not in selected or order(event) > order(selected[key]):
            selected[key] = event
    records = []
    for event in sorted(selected.values(), key=lambda r: (r['entity_id'], order(r))):
        points = event.get('relative_waypoints')
        if (not isinstance(points, list) or not points
                or any(not isinstance(p, (list, tuple)) or len(p)!=2
                       or not all(finite(x) for x in p) for p in points)):
            raise ValueError('Invalid received path')
        if not finite(event.get('path_speed')) or event['path_speed'] < 0:
            raise ValueError('Invalid received speed')
        if len(points) == 1:
            counts['single_point_not_a_forecast'] += 1
            continue
        if event.get('path_speed') == 0:
            counts['zero_speed_no_finite_eta'] += 1
            continue
        arithmetic = conditional_travel(points, event.get('path_speed'))
        if arithmetic['route_length_game_units'] == 0:
            counts['zero_length_path'] += 1
            continue
        row = dict(entity_id=event['entity_id'], support_time_seconds=event['time_seconds'],
            support_source=deepcopy(event['source']), support_sha256=digest(event),
            points=deepcopy(points), speed=event['path_speed'],
            flags=event.get('flags'), extra_byte=event.get('extra_byte'),
            distance=arithmetic['route_length_game_units'],
            predicted_duration_seconds=arithmetic['duration_seconds'],
            predicted_arrival_time_seconds=event['time_seconds']+arithmetic['duration_seconds'])
        if not finite(row['predicted_arrival_time_seconds']):
            raise ValueError('Forecast overflow')
        row['prediction_id'] = 'eta_' + digest(row)[:24]
        records.append(row)
    return dict(schema='frozen-travel-predictions/v1', replay_id=replay_id, version=version,
        source_sha256=source_sha256, entity_kind=entity_kind,
        formula='sum_received_polyline_segment_lengths / speed_at_support',
        assumptions=['Received route remains followed', 'Speed remains constant',
                     'No interruption, displacement, stopping, death or unmodeled delay'],
        decision_input_eligible=False, records=records, selection_counts=dict(counts))


def _stats(values):
    values = sorted(values)
    if not values:
        return dict(count=0, median=None, p90=None, maximum=None, over_1_5=None)
    return dict(count=len(values), median=statistics.median(values),
        p90=values[math.ceil(.9*len(values))-1], maximum=values[-1],
        over_1_5=sum(v > 1.5 for v in values))


def evaluate_predictions(predictions, events, *, recording_end_seconds):
    """Label all frozen forecasts, using later reports without refitting ETA.

    Terminal observations and the next live path close the old-plan window.
    Checkpoint first points can tighten an arrival bracket before that boundary.
    A closed bracket is conditional on no unseen displacement/backtracking;
    missing intermediate observations do not prove continuous movement.
    """
    if predictions.get('schema') != 'frozen-travel-predictions/v1':
        raise ValueError('Expected frozen predictions')
    if not finite(recording_end_seconds) or recording_end_seconds < 0:
        raise ValueError('Invalid recording end')
    by_actor = defaultdict(list)
    supports = {}
    for event in events:
        if event.get('kind') == 'path_command' or event.get('kind') in ('health_sample', 'terminal_removal_candidate', 'observed_death', 'respawn_candidate'):
            if not finite(event.get('time_seconds')) or event['time_seconds'] < 0:
                raise ValueError('Invalid evaluation timestamp')
            if event.get('source', {}).get('stream') not in (1, 2):
                raise ValueError('Invalid evaluation stream')
            if event['kind'] == 'path_command':
                points = event.get('relative_waypoints')
                if (not isinstance(points, list) or not points
                        or any(not isinstance(p, (list, tuple)) or len(p)!=2
                               or not all(finite(x) for x in p) for p in points)):
                    raise ValueError('Invalid evaluation position')
            by_actor[event['entity_id']].append(event)
            if event.get('kind') == 'path_command' and event['source']['stream'] == 1:
                supports[digest(event)] = event
    for actor in by_actor:
        by_actor[actor].sort(key=order)
    rows = []
    for pred in predictions['records']:
        if pred['support_sha256'] not in supports:
            raise ValueError('Forecast source differs from evaluation evidence')
        body = {k: v for k, v in pred.items() if k != 'prediction_id'}
        if pred['prediction_id'] != 'eta_' + digest(body)[:24]:
            raise ValueError('Frozen prediction was changed')
        t0, eta = pred['support_time_seconds'], pred['predicted_arrival_time_seconds']
        if t0 > recording_end_seconds:
            raise ValueError('Forecast outside recording')
        end = pred['points'][-1]
        last_outside = t0 if math.dist(pred['points'][0], end) > 5 else None
        bracket = None
        outcome = 'censored_no_position_report'
        witness = None
        observed_at = None
        endpoint_distance = None
        prior_death = None
        for event in by_actor[pred['entity_id']]:
            if order(event) > order(supports[pred['support_sha256']]):
                break
            if event['source']['stream'] != 1:
                continue
            if (event['kind'] in ('observed_death', 'terminal_removal_candidate')
                    or event['kind']=='health_sample' and event.get('values',{}).get('health') == 0):
                prior_death = event
            elif event['kind']=='respawn_candidate':
                # Ends the known-death interval only; does not certify current
                # health, visibility or ability to perform the proposed route.
                prior_death = None
        if prior_death is not None:
            outcome = 'ineligible_known_dead_at_support'
            witness = deepcopy(prior_death['source']); observed_at = prior_death['time_seconds']
        for event in by_actor[pred['entity_id']]:
            if prior_death is not None:
                break
            t = event['time_seconds']
            live = event['source']['stream'] == 1
            if (t > recording_end_seconds or t < t0
                    or t == t0 and (not live or order(event) <= order(supports[pred['support_sha256']]))):
                continue
            terminal = live and (event['kind'] in ('terminal_removal_candidate', 'observed_death') or
                event['kind'] == 'health_sample' and event.get('values', {}).get('health') == 0)
            if terminal:
                outcome = 'terminated_before_endpoint_report'
                witness = deepcopy(event['source']); observed_at = t
                break
            if event['kind'] != 'path_command':
                continue
            # Checkpoint labels use their own serialized path start, never the
            # predictor's propagated location. Other checkpoint encodings excluded.
            if not live and (event['source']['stream'] != 2 or event.get('encoding') != 'movement_array'):
                continue
            point = event['relative_waypoints'][0]
            endpoint_distance = math.dist(point, end)
            witness = deepcopy(event['source']); observed_at = t
            if endpoint_distance <= 5:
                outcome = 'endpoint_position_report'
                bracket = [last_outside, t] if last_outside is not None else None
                break
            last_outside = t
            if live:
                outcome = ('interrupted_before_expected_arrival' if t < eta
                           else 'not_at_endpoint_after_expected_arrival')
                break
            if t >= eta:
                # Preserve this missed forecast even if a later sample reaches
                # the endpoint. This is an audit, not best-match label search.
                outcome = 'not_at_endpoint_after_expected_arrival'
                break
        row = dict(prediction_id=pred['prediction_id'], entity_id=pred['entity_id'],
            support_time_seconds=t0, predicted_duration_seconds=pred['predicted_duration_seconds'],
            outcome=outcome, observation_time_seconds=observed_at,
            observation_source=witness, endpoint_distance=endpoint_distance,
            arrival_observation_bracket_seconds=bracket,
            arrival_bracket_width_seconds=None if bracket is None else bracket[1]-bracket[0],
            exact_arrival_seconds=None, observation_delay_seconds=None,
            report_time_signed_error_seconds=None, report_time_absolute_error_seconds=None,
            distance_outside_arrival_bracket_seconds=None,
            worst_case_error_within_bracket_seconds=None,
            instant_arrival_baseline_report_error_seconds=None,
            overdue_observation_seconds=None,
            prior_arrival_or_departure_unknown=True,
            bracket_semantics='observation bounds, conditional on no unobserved displacement/backtracking')
        if outcome == 'endpoint_position_report':
            row['report_time_signed_error_seconds'] = eta-observed_at
            row['report_time_absolute_error_seconds'] = abs(eta-observed_at)
            row['instant_arrival_baseline_report_error_seconds'] = observed_at-t0
            if bracket:
                row['distance_outside_arrival_bracket_seconds'] = max(bracket[0]-eta, eta-bracket[1], 0)
                row['worst_case_error_within_bracket_seconds'] = max(abs(eta-bracket[0]), abs(eta-bracket[1]))
        elif outcome == 'not_at_endpoint_after_expected_arrival':
            row['overdue_observation_seconds'] = observed_at-eta
        rows.append(row)
    short = [r for r in rows if .1 <= r['predicted_duration_seconds'] <= 10]
    reached = [r for r in short if r['outcome'] == 'endpoint_position_report']
    narrow = [r for r in reached if r['arrival_bracket_width_seconds'] is not None
              and r['arrival_bracket_width_seconds'] <= 1]
    live_reached = [r for r in reached if r['observation_source']['stream']==1]
    return dict(schema='travel-validation/v1', replay_id=predictions['replay_id'],
        entity_kind=predictions['entity_kind'], frozen_prediction_sha256=digest(predictions),
        outcome_counts=dict(Counter(r['outcome'] for r in rows)),
        short_outcome_counts=dict(Counter(r['outcome'] for r in short)),
        short_endpoint_report_deviation=_stats([r['report_time_absolute_error_seconds'] for r in reached]),
        short_live_endpoint_report_deviation=_stats([r['report_time_absolute_error_seconds'] for r in live_reached]),
        checkpoint_endpoint_observation_count=sum(r['observation_source']['stream']==2 for r in reached),
        instant_arrival_baseline_report_deviation=_stats([r['instant_arrival_baseline_report_error_seconds'] for r in reached]),
        worst_case_within_observation_bracket=_stats([r['worst_case_error_within_bracket_seconds'] for r in reached
                                                     if r['worst_case_error_within_bracket_seconds'] is not None]),
        narrow_bracket_count=len(narrow), rows=rows,
        decision_input_eligible=False,
        limitations=['Report timestamp is not physical arrival time',
                    'Replans and terminal/censored observations retained, never counted as successful arrivals',
                    'Same replay decoder is not independent video evidence',
                    'Counts of reports are correlated within one actor/game; not independent game trials'])
