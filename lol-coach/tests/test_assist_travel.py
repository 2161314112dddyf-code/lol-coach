"""Synthetic negative controls for player-scoped conditional assist calculations."""
import pytest

from lol_coach.player_action import allied_paths
from lol_coach.review_pings import _own_travel, assist_distances, attach_own_assist_path
from test_lane_opportunity import ally_path, lane_case
from test_round_options import add_fact


def case(when=9.8, speed=400, points=None, own=True):
    b = lane_case()
    f = b['frame']
    fid = ally_path(f, 'self', 0, when)
    b['audit'].setdefault('fact_sources', {})[fid] = dict(source={'chunk': 1},
        packet_path=dict(speed=speed, xz=points if points is not None else [[0, 0], [0, 400]]))
    sender = 'self' if own else 'ally'
    mark = dict(kind='assist_me', known_as='own_sent' if own else 'delivered_to_team',
                marker_region=dict(map_id=11, xz_rounded_to_100=[4000, 0]))
    pid = add_fact(f, 'test_pings', entity=sender, field='map_ping_sent', value=mark,
                   unit=None, scope='communication_event', when=9)
    f['recent_team_pings'] = {'fact_ids': [pid]}
    attach_own_assist_path(b)
    return f, dict(events=[dict(fact_id=pid, **mark)], through_seconds=10)


EXT = dict(champions={'Pantheon': dict(static_version='16.22.1',
    abilities={'R': dict(id='PantheonR', range_by_rank=[5500] * 3)})})


def calc(frame, gap=4000, hud='lit_no_visible_cooldown_overlay', **state):
    return _own_travel(frame, allied_paths(frame)['self'], [gap, 0], EXT,
                       dict(personal_hud_state=dict(value=dict(R_indicator=hud)), **state))


def test_order_and_hypothetical_walk_have_different_destinations():
    f, _ = case()
    out = calc(f)
    assert out['walk_scenario']['seconds_from_sampled_start'] == 10
    assert out['latest_order']['constant_speed_seconds_from_packet'] == 1
    assert out['latest_order']['endpoint_xz'] == [0, 400]
    assert out['pantheon_R']['centre_geometry_from_sample'] == 'inside'
    assert out['guaranteed_arrival_seconds'] is out['pantheon_R']['landing_at_seconds'] is None


def test_last_single_point_and_stale_start_cannot_assert_current_range():
    f, _ = case(when=5, points=[[0, 0]])
    out = calc(f, gap=6500)
    assert out['latest_order']['constant_speed_seconds_from_packet'] is None
    assert out['start_evidence'] == 'stale_sample'
    assert out['pantheon_R']['decision_check'] == 'refresh_own_position_before_range_check'
    assert out['pantheon_R']['ideal_walk_seconds_to_range_from_sample'] == 2.5
    assert out['actual_route_to_marker'] is None


def test_different_sender_or_missing_order_does_not_supply_own_speed():
    f, pings = case(own=False)
    assert 'own_assist_path_fact_ids' not in f
    assert assist_distances(pings, f['lineup'], allied_paths(f), [], frame=f) is None
    assert calc(f)['walk_scenario'] is None


def test_cooldown_death_and_wrong_build_do_not_imply_immediate_R():
    f, _ = case(speed=0)
    assert calc(f)['walk_scenario'] is None
    assert calc(f, hud='cooldown_sweep_visible')['pantheon_R']['decision_check'] == 'cooldown_overlay_at_hud_sample'
    dead = dict(observed_at_seconds=10, value=dict(is_dead=True))
    assert calc(f, personal_client_state=dead)['pantheon_R']['decision_check'] == 'cannot_cast_while_dead'
    f['decision']['build'] = 'other'
    assert 'pantheon_R' not in calc(f)


@pytest.mark.parametrize('speed', [False, -1, float('inf')])
def test_malformed_speed_is_rejected(speed):
    # Frozen facts disallow infinity during hashing.
    with pytest.raises(ValueError):
        calc(case(speed=speed)[0])


def test_enemy_sample_at_or_before_public_kill_excluded():
    f, pings = case()
    add_fact(f, 'recent_public_combat_ids', entity='enemy', field='public_kill_feed',
             value=dict(victim_entity_id='enemy', killer_entity_id='ally'), unit=None,
             scope='historical_event_not_current_death_state', when=9.99)
    enemy = dict(entity_id='enemy', visible=True, fact_id='sight',
                 last_observed_path_start=dict(xz=[4000, 0], age_seconds=.1, sampled_at=9.9))
    got = assist_distances(pings, f['lineup'], allied_paths(f), [enemy], frame=f)
    assert 'enemy' not in {a['entity_id'] for a in got['actors']}
