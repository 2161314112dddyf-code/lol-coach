"""Independent synthetic checks for forecast/label separation, not game trials."""
from copy import deepcopy
import math

import pytest

from lol_coach.travel_validation import evaluate_predictions, freeze_predictions


def path(points=None, *, at=0.0, speed=100.0, stream=1, offset=1,
         actor='unit', encoding='movement_array'):
    return dict(kind='path_command', entity_id=actor, time_seconds=at,
        relative_waypoints=[[0.0, 0.0], [100.0, 0.0]] if points is None else points,
        path_speed=speed, encoding=encoding,
        source=dict(stream=stream, chunk=1, decompressed_offset=offset,
                    packet_index=offset))


def freeze(events):
    return freeze_predictions(events, replay_id='synthetic-test',
        version='16.20.824.8524', source_sha256='a'*64, entity_kind='synthetic_minion')


def evaluate(start, later=(), *, end=20.0):
    predictions = freeze([start])
    return evaluate_predictions(predictions, [start, *later], recording_end_seconds=end)


def first(report):
    assert len(report['rows']) == 1
    return report['rows'][0]


def test_forecast_follows_polyline_instead_of_corner_cutting():
    start = path([[0, 0], [100, 0], [100, 100]], at=3, speed=50)
    prediction = freeze([start])['records'][0]
    assert prediction['distance'] == 200
    assert prediction['predicted_duration_seconds'] == 4
    assert prediction['predicted_arrival_time_seconds'] == 7


def test_current_forecast_unchanged_by_future_and_checkpoint_values():
    start = path()
    future = path([[0, 0], [9999, 9999]], at=5, speed=999, offset=2)
    checkpoint = path([[8888, 8888], [-8888, -8888]], at=0, stream=2)
    a = freeze([start])['records'][0]
    b = freeze([checkpoint, future, start])['records'][0]
    assert a == b
    assert len(freeze([checkpoint])['records']) == 0


def test_forecast_is_a_copy_and_never_says_actual_or_model_eligible():
    start = path()
    old = deepcopy(start)
    predictions = freeze([start])
    assert start == old
    assert predictions['decision_input_eligible'] is False
    assert 'actual_arrival_seconds' not in predictions['records'][0]
    predictions['records'][0]['points'][0][0] = 900
    predictions['records'][0]['support_source']['chunk'] = 900
    assert start == old


def test_same_timestamp_latest_stop_replaces_earlier_plan():
    earlier = path(offset=2)
    later = path([[40, 0]], offset=3)
    result = freeze([later, earlier])
    assert result['records'] == []
    assert result['selection_counts']['same_time_replaced'] == 1
    assert result['selection_counts']['single_point_not_a_forecast'] == 1


def test_same_timestamp_latest_route_replaces_earlier_route():
    earlier = path(offset=2)
    later = path([[40, 0], [140, 100]], offset=3)
    record = freeze([later, earlier])['records'][0]
    assert record['points'] == later['relative_waypoints']
    assert record['support_source'] == later['source']


def test_conflicting_same_packet_is_not_arbitrarily_chosen():
    start = path()
    other = path([[20, 20], [100, 100]])
    with pytest.raises(ValueError, match='Conflicting'):
        freeze([start, other])


def test_zero_speed_and_zero_length_never_divide_or_fake_instant_arrival():
    result = freeze([path(speed=0), path([[4, 4], [4, 4]], at=2)])
    assert result['records'] == []
    assert result['selection_counts']['zero_speed_no_finite_eta'] == 1
    assert result['selection_counts']['zero_length_path'] == 1


@pytest.mark.parametrize('speed', [False, True, -1, math.nan, math.inf, '100'])
def test_malformed_speed_fails_closed(speed):
    with pytest.raises((ValueError, TypeError)):
        freeze([path(speed=speed)])


@pytest.mark.parametrize('at', [-1, math.nan, math.inf, True])
def test_invalid_start_time_fails_closed(at):
    with pytest.raises(ValueError):
        freeze([path(at=at)])


def test_single_point_far_from_endpoint_is_interruption_not_arrival():
    report = evaluate(path(), [path([[30, 0]], at=.3, offset=2)])
    row = first(report)
    assert row['outcome'] == 'interrupted_before_expected_arrival'
    assert row['endpoint_distance'] == 70
    assert row['arrival_observation_bracket_seconds'] is None
    assert row['report_time_absolute_error_seconds'] is None
    assert report['short_endpoint_report_deviation']['count'] == 0


def test_missing_endpoint_after_deadline_remains_failure_in_denominator():
    report = evaluate(path(), [path([[30, 0]], at=2, offset=2)])
    row = first(report)
    assert row['outcome'] == 'not_at_endpoint_after_expected_arrival'
    assert row['overdue_observation_seconds'] == 1
    assert report['short_outcome_counts']['not_at_endpoint_after_expected_arrival'] == 1
    assert report['short_endpoint_report_deviation']['count'] == 0


def test_next_command_at_endpoint_is_observation_not_exact_physical_arrival():
    start = path()
    report = evaluate(start, [path([[100, 0], [100, 100]], at=1.1, offset=2)])
    row = first(report)
    assert row['outcome'] == 'endpoint_position_report'
    assert row['exact_arrival_seconds'] is None
    assert row['observation_delay_seconds'] is None
    assert row['arrival_observation_bracket_seconds'] == [0, 1.1]
    assert row['report_time_absolute_error_seconds'] == pytest.approx(.1)
    assert row['instant_arrival_baseline_report_error_seconds'] == pytest.approx(1.1)
    assert report['narrow_bracket_count'] == 0
    assert report['decision_input_eligible'] is False


def test_independent_checkpoint_tightens_bracket_without_changing_prediction():
    start = path()
    predictions = freeze([start])
    before = deepcopy(predictions)
    report = evaluate_predictions(predictions, [start,
        path([[80, 0]], at=.8, stream=2),
        path([[100, 0]], at=1.1, offset=2)], recording_end_seconds=10)
    row = first(report)
    assert predictions == before
    assert row['arrival_observation_bracket_seconds'] == [.8, 1.1]
    assert row['arrival_bracket_width_seconds'] == pytest.approx(.3)
    assert row['distance_outside_arrival_bracket_seconds'] == 0
    assert row['worst_case_error_within_bracket_seconds'] == pytest.approx(.2)
    assert report['narrow_bracket_count'] == 1


def test_late_missed_checkpoint_cannot_be_replaced_by_later_success():
    report = evaluate(path(), [path([[50, 0]], at=1.2, stream=2),
        path([[100, 0]], at=2, offset=2)])
    row = first(report)
    assert row['outcome'] == 'not_at_endpoint_after_expected_arrival'
    assert row['observation_time_seconds'] == 1.2
    assert row['arrival_observation_bracket_seconds'] is None


def test_replan_closes_old_window_before_later_return_to_old_endpoint():
    report = evaluate(path(), [path([[40, 0], [40, 100]], at=.4, offset=2),
        path([[100, 0]], at=1.0, offset=3)])
    row = first(report)
    assert row['outcome'] == 'interrupted_before_expected_arrival'
    assert row['observation_time_seconds'] == .4


def test_future_beyond_recording_cannot_confirm_arrival():
    report = evaluate(path(), [path([[100, 0]], at=2)], end=1.5)
    assert first(report)['outcome'] == 'censored_no_position_report'
    assert first(report)['observation_time_seconds'] is None


def test_other_entity_endpoint_cannot_confirm_this_entity():
    report = evaluate(path(), [path([[100, 0]], at=1, actor='other')])
    assert first(report)['outcome'] == 'censored_no_position_report'


def health(at=.4, value=0, stream=1, offset=2):
    return dict(kind='health_sample', entity_id='unit', time_seconds=at,
        values={'health': value}, source=dict(stream=stream, chunk=1,
            decompressed_offset=offset, packet_index=offset))


def test_live_zero_health_censors_later_corpse_endpoint():
    report = evaluate(path(), [health(), path([[100, 0]], at=1, offset=3)])
    row = first(report)
    assert row['outcome'] == 'terminated_before_endpoint_report'
    assert row['observation_time_seconds'] == .4
    assert row['exact_arrival_seconds'] is None
    assert report['short_endpoint_report_deviation']['count'] == 0


def test_post_arrival_death_does_not_erase_prior_endpoint_observation():
    report = evaluate(path(), [path([[100, 0]], at=1, offset=2), health(at=2, offset=3)])
    assert first(report)['outcome'] == 'endpoint_position_report'
    assert first(report)['observation_time_seconds'] == 1


def test_checkpoint_health_does_not_cancel_live_prediction():
    report = evaluate(path(), [health(stream=2), path([[100, 0]], at=1, offset=3)])
    assert first(report)['outcome'] == 'endpoint_position_report'


def test_positive_live_health_does_not_cancel_prediction():
    report = evaluate(path(), [health(value=1), path([[100, 0]], at=1, offset=3)])
    assert first(report)['outcome'] == 'endpoint_position_report'


def test_terminal_removal_censors_future_endpoint_observation():
    removal = health()
    removal['kind'] = 'terminal_removal_candidate'
    report = evaluate(path(), [removal, path([[100, 0]], at=1, offset=3)])
    assert first(report)['outcome'] == 'terminated_before_endpoint_report'


def test_hero_observed_death_is_a_terminal_label_without_inventing_health():
    death = dict(kind='observed_death', entity_id='unit', time_seconds=.4,
        source=dict(stream=1, chunk=1, decompressed_offset=2, packet_index=2))
    report = evaluate(path(), [death, path([[900, 900]], at=15, offset=3)])
    row = first(report)
    assert row['outcome'] == 'terminated_before_endpoint_report'
    assert row['observation_time_seconds'] == .4
    assert row['overdue_observation_seconds'] is None
    assert 'values' not in death
    assert report['short_endpoint_report_deviation']['count'] == 0


def test_checkpoint_death_is_not_a_live_termination_label():
    death = dict(kind='observed_death', entity_id='unit', time_seconds=.4,
        source=dict(stream=2, chunk=1, decompressed_offset=2, packet_index=2))
    report = evaluate(path(), [death, path([[100, 0]], at=1, offset=3)])
    assert first(report)['outcome'] == 'endpoint_position_report'


def test_invalid_single_point_is_rejected_even_without_a_forecast():
    with pytest.raises(ValueError):
        freeze([path([[math.nan, 0]])])


def test_wide_interval_cannot_be_presented_as_narrow_exact_timing():
    report = evaluate(path(), [path([[100, 0]], at=8, offset=2)])
    row = first(report)
    assert row['arrival_observation_bracket_seconds'] == [0, 8]
    assert row['arrival_bracket_width_seconds'] == 8
    assert row['worst_case_error_within_bracket_seconds'] == 7
    assert row['distance_outside_arrival_bracket_seconds'] == 0
    assert row['report_time_absolute_error_seconds'] == 7
    assert report['narrow_bracket_count'] == 0
    assert row['exact_arrival_seconds'] is None


def test_unsupported_checkpoint_encoding_is_not_a_timing_label():
    report = evaluate(path(), [path([[100, 0]], at=1, stream=2, encoding='unknown')])
    assert first(report)['outcome'] == 'censored_no_position_report'


def test_short_forecast_gate_does_not_delete_long_forecasts():
    start = path([[0, 0], [2000, 0]])
    report = evaluate(start, [path([[2000, 0]], at=20)], end=21)
    assert first(report)['outcome'] == 'endpoint_position_report'
    assert report['outcome_counts']['endpoint_position_report'] == 1
    assert report['short_outcome_counts'] == {}
    assert report['short_endpoint_report_deviation']['count'] == 0


def test_frozen_prediction_tampering_is_rejected():
    start = path()
    predictions = freeze([start])
    predictions['records'][0]['predicted_duration_seconds'] += 100
    with pytest.raises(ValueError, match='changed'):
        evaluate_predictions(predictions, [start], recording_end_seconds=10)


def test_changed_source_is_not_silently_scored():
    start = path()
    predictions = freeze([start])
    start['path_speed'] = 200
    with pytest.raises(ValueError, match='source differs'):
        evaluate_predictions(predictions, [start], recording_end_seconds=10)


@pytest.mark.parametrize('at', [math.nan, math.inf, -1, True])
def test_invalid_label_time_fails_closed(at):
    with pytest.raises(ValueError):
        evaluate(path(), [path([[100, 0]], at=at, offset=2)])


@pytest.mark.parametrize('at', [math.nan, math.inf, -1, True])
def test_invalid_recording_end_is_rejected(at):
    with pytest.raises(ValueError):
        evaluate(path(), end=at)


def test_start_after_recording_end_is_rejected():
    with pytest.raises(ValueError, match='outside recording'):
        evaluate(path(at=10), end=1)


def test_endpoint_radius_is_inclusive_and_does_not_hide_outside_point():
    close = evaluate(path(), [path([[95, 0]], at=1, offset=2)])
    outside = evaluate(path(), [path([[94.9, 0]], at=1, offset=2)])
    assert first(close)['outcome'] == 'endpoint_position_report'
    assert first(outside)['outcome'] == 'not_at_endpoint_after_expected_arrival'


def lifecycle(kind, *, at, offset):
    return dict(kind=kind, entity_id='unit', time_seconds=at,
        source=dict(stream=1, chunk=1, decompressed_offset=offset, packet_index=offset))


def test_path_34ms_after_death_is_ineligible_not_late_after_respawn():
    start = path(at=10.034, offset=3)
    predictions = freeze([start])
    before = deepcopy(predictions)
    report = evaluate_predictions(predictions, [
        lifecycle('observed_death', at=10, offset=2), start,
        lifecycle('respawn_candidate', at=25, offset=4),
        path([[1000, 1000]], at=25.1, offset=5)], recording_end_seconds=30)
    row = first(report)
    assert predictions == before
    assert row['outcome'] == 'ineligible_known_dead_at_support'
    assert row['observation_time_seconds'] == 10
    assert row['observation_source']['decompressed_offset'] == 2
    assert row['overdue_observation_seconds'] is None
    assert report['short_outcome_counts'] == {'ineligible_known_dead_at_support': 1}
    assert report['short_live_endpoint_report_deviation']['count'] == 0


@pytest.mark.parametrize('terminal_kind', ['observed_death', 'terminal_removal_candidate', 'health_sample'])
def test_each_prior_terminal_kind_prevents_scoring_new_path_as_live(terminal_kind):
    terminal = lifecycle(terminal_kind, at=1, offset=1)
    if terminal_kind == 'health_sample':
        terminal['values'] = {'health': 0}
    start = path(at=2, offset=2)
    report = evaluate_predictions(freeze([start]), [terminal, start,
        path([[100, 0]], at=3, offset=3)], recording_end_seconds=10)
    assert first(report)['outcome'] == 'ineligible_known_dead_at_support'


def test_new_plan_after_respawn_candidate_can_be_scored_without_claiming_alive():
    start = path(at=3, offset=3)
    report = evaluate_predictions(freeze([start]), [
        lifecycle('observed_death', at=1, offset=1),
        lifecycle('respawn_candidate', at=2, offset=2), start,
        path([[100, 0]], at=4, offset=4)], recording_end_seconds=10)
    row = first(report)
    assert row['outcome'] == 'endpoint_position_report'
    assert 'alive' not in row
    assert row['exact_arrival_seconds'] is None
    assert report['decision_input_eligible'] is False


def test_same_time_prior_death_then_respawn_then_path_uses_source_order():
    start = path(at=10, offset=3)
    events = [start, lifecycle('respawn_candidate', at=10, offset=2),
              lifecycle('observed_death', at=10, offset=1),
              path([[100, 0]], at=11, offset=4)]
    report = evaluate_predictions(freeze([start]), events, recording_end_seconds=20)
    assert first(report)['outcome'] == 'endpoint_position_report'


def test_same_time_prior_respawn_then_death_then_path_stays_ineligible():
    start = path(at=10, offset=3)
    events = [start, lifecycle('observed_death', at=10, offset=2),
              lifecycle('respawn_candidate', at=10, offset=1),
              path([[100, 0]], at=11, offset=4)]
    report = evaluate_predictions(freeze([start]), events, recording_end_seconds=20)
    assert first(report)['outcome'] == 'ineligible_known_dead_at_support'


def test_same_time_respawn_after_path_does_not_retroactively_license_dead_plan():
    start = path(at=10, offset=2)
    report = evaluate_predictions(freeze([start]), [
        lifecycle('observed_death', at=10, offset=1), start,
        lifecycle('respawn_candidate', at=10, offset=3),
        path([[100, 0]], at=11, offset=4)], recording_end_seconds=20)
    assert first(report)['outcome'] == 'ineligible_known_dead_at_support'


def test_same_time_death_after_path_terminates_instead_of_being_skipped():
    start = path(at=10, offset=2)
    report = evaluate_predictions(freeze([start]), [start,
        lifecycle('observed_death', at=10, offset=3),
        path([[100, 0]], at=11, offset=4)], recording_end_seconds=20)
    row = first(report)
    assert row['outcome'] == 'terminated_before_endpoint_report'
    assert row['observation_time_seconds'] == 10
    assert report['short_live_endpoint_report_deviation']['count'] == 0


def test_wide_checkpoint_endpoint_is_not_live_endpoint_timing_error():
    report = evaluate(path(), [path([[100, 0]], at=8, stream=2, offset=2)])
    row = first(report)
    assert row['outcome'] == 'endpoint_position_report'
    assert row['report_time_absolute_error_seconds'] == 7
    assert row['arrival_bracket_width_seconds'] == 8
    assert report['short_endpoint_report_deviation']['count'] == 1
    assert report['checkpoint_endpoint_observation_count'] == 1
    assert report['short_live_endpoint_report_deviation']['count'] == 0
    assert report['narrow_bracket_count'] == 0


def test_mixed_checkpoint_and_live_reports_are_stratified():
    a, b = path(actor='a'), path(actor='b')
    predictions = freeze([a, b])
    report = evaluate_predictions(predictions, [a, b,
        path([[100, 0]], at=8, stream=2, actor='a', offset=2),
        path([[100, 0]], at=1.1, actor='b', offset=3)], recording_end_seconds=10)
    assert report['short_endpoint_report_deviation']['count'] == 2
    assert report['checkpoint_endpoint_observation_count'] == 1
    assert report['short_live_endpoint_report_deviation']['count'] == 1
    assert report['short_live_endpoint_report_deviation']['median'] == pytest.approx(.1)


def test_late_elsewhere_position_keeps_prior_arrival_uncertain():
    report = evaluate(path(), [path([[200, 200]], at=8, offset=2)])
    row = first(report)
    assert row['outcome'] == 'not_at_endpoint_after_expected_arrival'
    assert row['prior_arrival_or_departure_unknown'] is True
    assert row['exact_arrival_seconds'] is None
    assert row['overdue_observation_seconds'] == 7


def test_same_time_checkpoint_does_not_override_live_start_without_cross_stream_order():
    start = path(at=10, offset=2)
    report = evaluate_predictions(freeze([start]), [start,
        path([[100, 0]], at=10, stream=2, offset=99),
        path([[20, 0]], at=10.2, offset=3)], recording_end_seconds=20)
    assert first(report)['outcome'] == 'interrupted_before_expected_arrival'
    assert report['checkpoint_endpoint_observation_count'] == 0
