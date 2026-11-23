"""Freeze one choice and vary the receiving ally's information or ability to help."""
from copy import deepcopy

import pytest

from lol_coach.reasoning_frame import compile_frame
from lol_coach.round_tools import round_call
from lol_coach.team_coordination import coordination_trigger
from test_lane_opportunity import ally_path, lane_case, seen
from test_macro_snapshot import bundles, query
from test_review_pings import delivery, index, ping
from test_round_chain import bundle_at, freeze
from test_round_options import add_fact


def review(bundle, lane='mid'):
    task = bundle['frame']['task']
    task.setdefault('round_comparison', dict(lane=lane, target='river_entrance', help_seconds=3))
    task['team_coordination_review'] = 'team-coordination/v1'
    freeze(bundle)
    original = deepcopy(bundle)
    result = round_call(bundle, 'review_round_plan', {})['team_coordination']
    assert bundle == original
    return result


def test_far_ally_can_be_warned_without_treating_the_players_reach_as_a_threat():
    b = lane_case()
    f = b['frame']
    ally_path(f, 'self', 6500, 9.6)
    ally_id = ally_path(f, 'ally', 100, 9.7)
    sight_id = seen(f, 'jungler', 251, 9.95)
    seen(f, 'enemy', 101, 9.97, visible=False)
    old_plan = round_call(freeze(b), 'review_round_plan', {})
    assert 'team_coordination' not in old_plan
    result = review(b)
    ally, = result['allies']
    assert ally['gap_to_player_world_units'] == 6400
    assert ally['visible_contact_near_ally']['fact_refs'] == [ally_id, sight_id]
    assert ally['visible_contact_near_ally']['sampled_gap_world_units'] == 151
    assert ally['visible_contact_near_ally']['sample_age_seconds'] == pytest.approx([0.3, 0.05])
    assert ally['latest_observed_action'] is None and result['response_status'] == 'unknown'
    assert result['recent_team_pings']['coverage'] == 'unavailable'


@pytest.mark.parametrize('change', ['ally_stale', 'enemy_stale', 'ally_killed', 'enemy_killed'])
def test_refresh_positions_before_suggesting_contact(change):
    b = lane_case()
    f = b['frame']
    ally_path(f, 'self', 100, 9.99)
    ally_path(f, 'ally', 110, 8.99 if change == 'ally_stale' else 9.8)
    seen(f, 'enemy', 111, 8.99 if change == 'enemy_stale' else 9.8)
    if change.endswith('killed'):
        victim = change.split('_')[0]
        add_fact(f, 'recent_public_combat_ids', entity=victim, field='public_kill_feed',
                 scope='historical_event_not_current_death_state', unit=None, when=9.9,
                 value=dict(victim_entity_id=victim, killer_entity_id='jungler'))
    ally, = review(b)['allies']
    assert ally['visible_contact_near_ally'] is None
    if change.startswith('ally'):
        assert ally['gap_to_player_world_units'] is None
    if change == 'ally_killed':
        assert ally['latest_public_death']['at_seconds'] == 9.9


def test_position_after_allied_death_is_not_confirmation_of_respawn():
    b = lane_case()
    f = b['frame']
    ally_path(f, 'self', 100, 9.99)
    ally_path(f, 'ally', 110, 9.95)
    kill = add_fact(f, 'recent_public_combat_ids', entity='ally', field='public_kill_feed',
                    scope='historical_event_not_current_death_state', unit=None, when=9.9,
                    value=dict(victim_entity_id='ally', killer_entity_id='jungler'))
    ally, = review(b)['allies']
    assert ally['latest_public_death']['fact_id'] == kill
    assert ally['gap_to_player_world_units'] == 10  # distance between samples only
    assert ally['followup_availability'] == 'recheck_after_reported_death'


def test_solo_roster_has_no_recipient():
    bundle = bundle_at(10)
    bundle['frame']['lineup'] = bundle['frame']['lineup'][:1]
    assert review(bundle)['allies'] == []


def test_player_dead_at_this_instant_can_warn_an_ally_but_cannot_move_to_help():
    b = lane_case()
    f = b['frame']
    ally_path(f, 'self', 100, 9.99)
    ally_path(f, 'ally', 150, 9.9)
    seen(f, 'jungler', 200, 9.9)
    state = add_fact(f, 'native_ids', entity='self', field='personal_client_state',
                     scope='personal_native_observation', unit=None, when=10,
                     value=dict(is_dead=True, respawn_timer_seconds=17))
    f['lineup'][0]['current_fact_ids'].append(state)
    result = review(b)
    ally, = result['allies']
    assert result['player_physical_action_gate'] == 'cannot_move_or_cast_while_dead'
    assert ally['gap_to_player_world_units'] is None
    assert ally['visible_contact_near_ally']['entity_id'] == 'jungler'


def test_ping_send_channel_delivery_and_actions_remain_separate(bundles):
    snap = query(bundles, at=8, player='self')
    events = [ping('self', 'assist_me', 6), ping('ally', 'on_my_way', 7, channel='team'),
              ping('ally', 'push', 6.5, delivery=delivery('player', 'self', 7.9)),
              ping('enemy', team=200, channel='team'), ping('ally', when=8.1, channel='team')]
    b = compile_frame(snap, ping_index=index(snap, events))
    result = review(b)
    pings = result['recent_team_pings']
    assert [(row['kind'], row['known_as']) for row in pings['personal_events']] == [
        ('assist_me', 'own_sent'), ('push', 'delivered_to_player')]
    assert pings['team_channel_sends'] == [dict(sender_entity_id='ally', kind='on_my_way',
                                                 sent_at_seconds=7, personal_receipt='unknown')]
    assert pings['channel_reference_id'] in b['frame']['references']
    assert result['response_status'] == 'unknown'
    assert result['allies'][0]['latest_observed_action'] is None


def contact_frame(at, *, enemy_visible=True, jungle_visible=False, jungle_x=200, ally_x=100):
    b = lane_case()
    f = b['frame']
    f['decision']['at_seconds'] = at
    f['task']['roam_actors'] = {'enemy_jungle': 'jungler'}
    ally_path(f, 'self', 0, at - 0.2)
    ally_path(f, 'ally', ally_x, at - 0.2)
    for actor, x, visible in [('enemy', 110, enemy_visible), ('tahm', 240, True),
                              ('jungler', jungle_x, jungle_visible)]:
        pos = dict(sampled_at=at - 0.1, age_seconds=0.1, xz=[x, 0])
        add_fact(f, 'vision_fact_ids', entity='entity:' + actor, field='observer_visibility',
                 value=dict(team_id=100, visible=visible, last_observed_position=pos),
                 unit=None, scope='queried_at_decision_time', when=at)
    return freeze(b)


def record_ping(bundle, kind, when, point, actor='self', delivery_at=None):
    f = bundle['frame']
    own = actor == 'self'
    value = dict(kind=kind, observer_team_id=100, marker_xz=point,
                 known_as='own_sent' if own else 'delivered_to_player',
                 available_at_seconds=when if own else delivery_at)
    if not own:
        value['recipient_entity_id'] = 'self'
    fid = add_fact(f, 'test_ping_ids', entity=actor, field='map_ping_sent', scope='communication_event',
                   unit=None, value=value, when=when, available=value['available_at_seconds'])
    f['recent_team_pings'] = dict(fact_ids=f['test_ping_ids'], coverage='verified_events_only',
                                  window_start_seconds=0)
    freeze(bundle)
    return fid


def test_quiet_lane_first_frame_brush_and_continuous_trade():
    first = contact_frame(10, enemy_visible=False)
    second = contact_frame(11)
    third = contact_frame(12)
    for now, before in [(third, None), (second, first), (third, second)]:
        assert coordination_trigger(now, before) == dict(active=False, reasons=[], fact_ids=[])
    # Even an identified enemy jungler present at the first pause does not prove a change.
    assert not coordination_trigger(contact_frame(11, jungle_visible=True))['active']


@pytest.mark.parametrize('previous_jungler', ['hidden', 'visible_far'])
def test_extra_jungler_reaches_player_and_ally_only_on_the_first_changed_frame(previous_jungler):
    before = contact_frame(10, jungle_visible=previous_jungler == 'visible_far', jungle_x=6000)
    during = contact_frame(11, jungle_visible=True)
    result = coordination_trigger(during, before)
    assert result['reasons'] == ['new_local_opponent_affects_ally']
    assert set(result['fact_ids']) <= during['frame']['facts'].keys()
    assert not coordination_trigger(contact_frame(12, jungle_visible=True), during)['active']
    assert not coordination_trigger(contact_frame(11, jungle_visible=True, ally_x=6000), before)['active']


def test_personal_tactical_signal_repeated_in_the_same_region_is_silent():
    first = contact_frame(10)
    before_id = record_ping(first, 'on_my_way', 9.8, [100, 100])
    assert coordination_trigger(first)['fact_ids'] == [before_id]
    second = contact_frame(11)
    record_ping(second, 'on_my_way', 10.9, [115, 100])
    assert not coordination_trigger(second, first)['active']
    later = contact_frame(12)
    next_id = record_ping(later, 'on_my_way', 11.9, [3000, 100])
    assert coordination_trigger(later, second)['fact_ids'] == [next_id]


@pytest.mark.parametrize('kind', ['enemy_vision', 'enemy_missing', 'need_vision', 'command'])
def test_routine_map_marks_alone_do_not_interrupt_lane_review(kind):
    now = contact_frame(10)
    record_ping(now, kind, 9.8, [100, 100])
    assert not coordination_trigger(now)['active']


def test_alternating_tactical_ping_types_dont_reopen_the_card_at_the_same_spot():
    before = contact_frame(10)
    for kind, when in [('on_my_way', 9.7), ('assist_me', 9.9)]:
        record_ping(before, kind, when, [10, 100])
    now = contact_frame(11)
    for kind, when in [('on_my_way', 10.2), ('assist_me', 10.9)]:
        record_ping(now, kind, when, [10, 110])
    assert not coordination_trigger(now, before)['active']


@pytest.mark.parametrize('ally_x, active', [(100, True), (6000, False)])
def test_recent_ally_request_needs_delivery_and_a_local_sender(ally_x, active):
    before = contact_frame(10)
    now = contact_frame(11, ally_x=ally_x)
    request = record_ping(now, 'assist_me', 9.8, [115, 100], actor='ally', delivery_at=10.9)
    result = coordination_trigger(now, before)
    assert result['active'] == active
    if active:
        assert result['reasons'] == ['nearby_ally_request_delivered'] and request in result['fact_ids']


@pytest.mark.parametrize('ally_x, active', [(100, True), (6000, False)])
def test_delayed_public_death_changes_only_the_relevant_players_frame(ally_x, active):
    before = contact_frame(10, ally_x=ally_x)
    now = contact_frame(11, ally_x=ally_x)
    later = contact_frame(12, ally_x=ally_x)
    for b in [now, later]:
        add_fact(b['frame'], 'recent_public_combat_ids', entity='ally', field='public_kill_feed',
                 scope='historical_event_not_current_death_state', unit=None, when=9.9, available=10.5,
                 value=dict(victim_entity_id='ally', killer_entity_id='jungler'))
    assert coordination_trigger(now, before)['active'] == active
    assert not coordination_trigger(later, now)['active']


def test_gate_refuses_history_from_another_match_or_a_later_frame():
    a, b = contact_frame(10), contact_frame(11)
    with pytest.raises(ValueError, match='previous_scope_mismatch'):
        coordination_trigger(a, b)
    a['audit']['source_replay_sha256'] = 'b' * 64
    with pytest.raises(ValueError, match='previous_scope_mismatch'):
        coordination_trigger(b, a)
