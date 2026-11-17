"""A player's decision uses that team's vision without claiming personal awareness."""
from copy import deepcopy

import pytest

from lol_coach.reasoning_frame import compile_frame
from lol_coach.round_tools import bind_round, round_call
from test_macro_snapshot import bundles, query
from lol_coach.round_chain import attach_previous_plan
from test_round_chain import answer_for, bundle_at, freeze


def bind(bundle):
    return bind_round(bundle, 'mid', 'dragon', 5)


def test_identical_replay_samples_in_two_reviews_have_distinct_decision_ids():
    raw = bundle_at(8)
    origin = dict(match_id='123', replay_sha256=raw['audit']['source_replay_sha256'], perspective='personal')
    personal = bind_round(raw, 'mid', 'dragon', 5, review_origin=origin)
    other = dict(origin, replay_sha256='2' * 64)
    copied = deepcopy(raw)
    copied['audit']['source_replay_sha256'] = other['replay_sha256']
    assert personal['frame']['frame_id'] != bind_round(copied, 'mid', 'dragon', 5, review_origin=other)['frame']['frame_id']
    with pytest.raises(ValueError, match='different_review_origin'):
        bind_round(personal, 'mid', 'dragon', 5, review_origin=dict(origin, perspective='comparison'))


def test_new_binding_names_one_player_without_changing_the_input(bundles):
    raw = compile_frame(query(bundles, at=8, player='self'))
    bound = bind(raw)
    frame = bound['frame']
    hero = next(row for row in frame['lineup'] if row['entity_id'] == 'self')
    assert frame['task']['player_perspective'] == dict(player_entity_id='self', champion=hero['champion'], observer_team_id=100)
    assert 'player_perspective' not in raw['frame']['task']
    assert bind(bound) == bound
    sight = round_call(bound, 'enemy_sightings', {})
    assert sight['player_entity_id'] == 'self' and sight['visibility_scope'] == 'shared_team_vision'
    assert sight['player_attention'] == 'unknown'
    assert round_call(bound, 'review_round_plan', {})['player_entity_id'] == 'self'


def test_archive_without_the_new_marker_keeps_its_exact_frame_id():
    archive = bind(bundle_at(8))
    del archive['frame']['task']['player_perspective']
    freeze(archive)
    assert bind(archive) == archive


def test_macro_comparison_shows_another_lane_with_its_real_coverage():
    from test_round_options import add_fact
    raw = bundle_at(8)
    fid = add_fact(raw['frame'], 'lane_fact_ids', entity='lane:top',
                   field='lane_current_units_and_groups', scope='queried_at_decision_time', unit=None,
                   value=dict(lane='top', count_scope='own_team_observed_live_only',
                              counts=[dict(team_id=100, kind='melee', count=2)]))
    archived = bind(raw)
    current = bind_round(archived, 'mid', 'dragon', 5, macro_review=True)
    assert current['frame']['frame_id'] != archived['frame']['frame_id']
    assert 'macro_round_context' not in round_call(archived, 'review_round_plan', {})
    context = round_call(current, 'review_round_plan', {})['macro_round_context']
    lane = next(x for x in context['observed_lanes'] if x['lane']=='top')
    assert context['compared_destination']=='dragon' and lane['fact_id']==fid
    assert lane['enemy_minions']['status']=='outside_source_coverage'
    assert lane['enemy_minions']['observed_count'] is None
    assert bind_round(current, 'mid', 'dragon', 5, macro_review=True) == current


def test_upgrading_a_working_copy_preserves_the_legacy_previous_card_and_calculations():
    old = bundle_at(10)
    archive = bind_round(attach_previous_plan(bundle_at(20),old,answer_for(old)), 'mid','dragon',5,
                         ally_id='ally',enemy_id='enemy')
    frame = archive['frame']
    del frame['task']['player_perspective']
    freeze(archive)
    before = deepcopy(archive)
    current = bind_round(archive, 'mid','dragon',5, upgrade_legacy=True)
    assert archive == before and current['frame']['frame_id'] != frame['frame_id']
    assert current['frame']['task']['previous_plan']['previous_frame_id'] == old['frame']['frame_id']
    assert current['frame']['task']['engagement_question'] == frame['task']['engagement_question']
    assert current['frame']['calculations'] == frame['calculations']
    assert bind_round(current, 'mid','dragon',5, upgrade_legacy=True) == current


@pytest.mark.parametrize('player',['enemy','unknown_actor'])
def test_own_team_binding_fails_for_another_team_or_missing_actor(player):
    bundle = bundle_at(8)
    bundle['frame']['decision']['player_entity_id'] = player
    with pytest.raises(ValueError, match='own_team_player'):
        bind(freeze(bundle))


def test_team_and_champion_must_match_the_roster_and_existing_binding(bundles):
    raw = compile_frame(query(bundles, at=8, player='self'))
    frame = raw['frame']
    identity = next(v for v in frame['facts'].values() if (v['entity_id'], v['field']) == ('self', 'identity'))
    for other_identity in ({'team_id':200}, {'champion':'someone_else'}):
        original = deepcopy(identity['value'])
        identity['value'].update(other_identity)
        with pytest.raises(ValueError, match='roster_identity_mismatch'):
            bind(freeze(raw))
        identity['value'] = original
    bound = bind(freeze(raw))
    bound['frame']['task']['player_perspective']['player_entity_id'] = 'ally'
    with pytest.raises(ValueError, match='player_perspective_mismatch'):
        bind(freeze(bound))
