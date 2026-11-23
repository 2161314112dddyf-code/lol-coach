import pytest

from lol_coach.coaching_checkpoints import select_coaching_checkpoints


def row(at, reason, *triggers):
    return dict(at=at, selected_by=[reason], triggers=list(triggers))


def sight(at, subject, distance):
    kind = 'nearby_enemy_became_visible'
    return row(at, kind, dict(kind=kind, at=at, subject=subject,
                              own_sample=dict(time_seconds=at - 0.1, world_waypoints_xz=[[0, 0]]),
                              enemy_sample=dict(subject=subject, time_seconds=at, xz=[distance, 0])))


def test_personal_call_and_new_opponent_can_interrupt_within_the_same_plan():
    events = [row(0, 'regular'), sight(100, 'a', 1300),
              row(105, 'own_action_signal', dict(kind='on_my_way', sent_at_seconds=104)),
              sight(109, 'b', 1500), sight(110, 'c', 1400)]
    result = select_coaching_checkpoints(events)
    assert result['selected_times'] == [0, 100, 105, 109]
    assert result['rows'][3]['selection_reason'] == 'new_local_opponent'
    assert result['rows'][3]['review_mode'] == 'brief_update'
    assert result['rows'][4]['covered_by_at'] == 109
    assert result['rows'][4]['selection_reason'] == 'same_contact_burst'
    for n in range(len(events) + 1):
        assert select_coaching_checkpoints(events[:n])['rows'] == result['rows'][:n]


def test_same_opponent_gradually_appearing_closer_can_change_the_decision():
    result = select_coaching_checkpoints([sight(10, 'a', 1050), sight(17, 'a', 650),
                                          sight(19, 'a', 240), sight(23, 'a', 205)])
    assert result['selected_times'] == [10, 19]
    close, = result['rows'][2]['nearby_observations']
    assert close['change'] == 'closer_local_opponent'
    assert close['previous_far_sample'] == dict(at=10, distance_world_units=1050)
    assert result['rows'][3]['selection_reason'] == 'repeated_contact'


def test_dense_contacts_stay_out_of_earlier_stop_and_quiet_gap_reopens_review():
    events = [row(0, 'regular'), sight(40, 'a', 1000), sight(40.05, 'b', 1200),
              sight(40.1, 'c', 750), sight(40.14, 'd', 1100), sight(40.18, 'e', 950),
              sight(49, 'c', 700), row(60, 'own_command_reversed'), sight(85, 'c', 650),
              row(88, 'last_game_second')]
    result = select_coaching_checkpoints(events)
    assert result['selected_times'] == [0, 40, 85, 88]
    first, = result['rows'][1]['nearby_observations']
    assert first['subject'] == 'a'
    assert all(r['selection_reason'] == 'same_contact_burst' for r in result['rows'][2:6])
    assert result['rows'][8]['selection_reason'] == 'contact_after_gap'


def test_subsecond_contact_after_an_independent_stop_is_only_available_later():
    events = [row(0, 'regular'), row(80, 'own_action_signal', dict(kind='push', sent_at_seconds=79)),
              sight(80.03, 'a', 980), sight(80.2, 'b', 900)]
    result = select_coaching_checkpoints(events)
    assert result['selected_times'] == [0, 80]
    assert result['rows'][1]['nearby_observations'] == []
    assert all(r['covered_by_at'] == 80 for r in result['rows'][2:])


def test_spaced_arrivals_or_a_closer_sighting_can_update_an_active_contact_burst():
    entries = [sight(30, 'a', 1000), sight(30.1, 'b', 1400), sight(31, 'c', 850),
               sight(35.5, 'd', 900), sight(36, 'e', 750)]
    result = select_coaching_checkpoints(entries)
    assert result['selected_times'] == [30, 35.5]
    assert result['rows'][3]['review_mode'] == 'brief_update'
    assert select_coaching_checkpoints(entries[:3])['rows'] == result['rows'][:3]
    close = select_coaching_checkpoints([sight(40, 'a', 1300), sight(44, 'a', 250)])
    assert close['selected_times'] == [40, 44]
    assert close['rows'][1]['selection_reason'] == 'closer_local_opponent'


def test_contact_rejects_future_position_and_out_of_order_candidates():
    future = sight(20, 'a', 500)
    future['triggers'][0]['own_sample']['time_seconds'] = 21
    with pytest.raises(ValueError, match='current visible position'):
        select_coaching_checkpoints([future])
    with pytest.raises(ValueError, match='increasing clocks'):
        select_coaching_checkpoints([row(20, 'regular'), row(19, 'regular')])
