"""Synthetic fixtures test information boundaries, not game semantics."""
from copy import deepcopy

import pytest

from lol_coach.macro_snapshot import build_snapshot, VERSION


def row(t, entity='enemy', offset=1, **extra):
    return dict(time_seconds=t, entity_id=entity,
                source=dict(stream=1, chunk=1, decompressed_offset=offset), **extra)


@pytest.fixture
def bundles():
    actors = [dict(entity_id='self', champion='A', team_id=100),
              dict(entity_id='ally', champion='B', team_id=100),
              dict(entity_id='enemy', champion='C', team_id=200)]
    base = dict(version=VERSION, source_sha256='synthetic', game_length_seconds=20)
    ten = dict(schema='replay-ten/v1', version=VERSION, replay_sha256='synthetic', game_length_metadata_ms=20000,
        identity_directory={'owners': actors}, entity_to_participant={a['entity_id']: i for i, a in enumerate(actors)},
        categories=dict(participants=actors, movement={'events': []}, lifecycle={'events': []}, kills=[],
                        inventory=[{'final_secret': 999}], economy=[{'gold': 999}]))
    state = dict(**base, schema='replay-state/v1', units={'health': 'health_points'}, updates=[
        row(1, 'self', values={'health': 0, 'current_gold': 100}),
        row(1, 'ally', values={'health': 500, 'current_gold': 222}),
        row(3, values={'health': 300, 'current_gold': 333}),
        row(7, values={'health': 7777, 'current_gold': 7777})])
    inv = dict(**base, schema='replay-inventory-operations/v1', events=[], state_barriers=[], unresolved=[], cutoff_seconds=None)
    vision = dict(**base, schema='replay-hero-visibility/v1', actors=actors, events=[
        row(2, visible=True, observer_team_id=100), row(5, visible=False, observer_team_id=100),
        row(9, visible=True, observer_team_id=100)])
    return [ten, state, inv, vision]


def query(bundles, at=8, **kwargs):
    return build_snapshot(*bundles, at=at, team=100, **kwargs)


def hero(result, entity='enemy'):
    return next(h for h in result['heroes'] if h['entity_id'] == entity)


def test_hidden_and_reentry_never_carry_hidden_or_stale_samples(bundles):
    h = hero(query(bundles))
    assert h['observed_now'] is None
    assert h['last_observed']['health']['value'] == 300
    assert h['last_observed']['health']['age_seconds'] == 5
    assert hero(query(bundles, at=9))['observed_now'] == {}


def test_future_and_final_metadata_cannot_change_snapshot(bundles):
    before = query(bundles)
    changed = deepcopy(bundles)
    changed[0]['categories']['inventory'] = [{'item_id': 'future-secret'}]
    changed[0]['categories']['economy'] = [{'gold': 123456}]
    changed[1]['updates'].append(row(11, values={'health': 12345}))
    changed[2]['events'].append(row(12, 'self', kind='slot_clear', slot=0))
    changed[3]['events'].append(row(15, visible=False, observer_team_id=100))
    assert query(changed) == before


def test_same_time_packet_order_is_respected(bundles):
    bundles[3]['events'] = [row(2, offset=10, visible=True, observer_team_id=100)]
    bundles[1]['updates'] = [row(2, offset=9, values={'health': 12345}),
                             row(2, offset=11, values={'resource': 50})]
    assert set(hero(query(bundles))['observed_now']) == {'resource'}


def test_private_values_require_self_and_unknown_does_not_become_zero(bundles):
    result = query(bundles, player='self')
    assert hero(result, 'self')['observed_now']['health']['value'] == 0
    assert hero(result, 'self')['private_economy']['current_gold']['value'] == 100
    for entity in ('ally', 'enemy'):
        h = hero(result, entity)
        assert h['private_economy']['value'] is None
        assert 'current_gold' not in (h['observed_now'] or {})
    assert hero(query(bundles), 'self')['private_economy']['status'] == 'unknown'


def test_only_observed_start_point_and_never_hidden_endpoint(bundles):
    bundles[0]['categories']['movement']['events'] = [
        row(3, relative_waypoints=[[10, 20], [999, 999]], record_id='p1'),
        row(7, relative_waypoints=[[888, 888], [777, 777]], record_id='p2')]
    at4 = hero(query(bundles, at=4))
    assert at4['position_candidate']['value'] == [10, 20]
    h = hero(query(bundles))
    assert h['position_candidate'] is None
    assert h['last_observed_position']['value'] == [10, 20]
    assert hero(query(bundles, at=9))['position_candidate'] is None


def test_inventory_remains_incomplete_and_barriers_are_exposed_only_for_self(bundles):
    bundles[2]['events'] = [row(1, 'self', kind='slot_update', slot=0, item_id=1001),
                              row(3, kind='slot_update', slot=0, item_id=9999)]
    bundles[2]['state_barriers'] = [row(5, 'self'), row(15, 'self')]
    result = query(bundles, player='self')
    inv = hero(result, 'self')['inventory']
    assert inv['current_slots'] is None and inv['status'] == 'incomplete'
    assert inv['latest_self_barrier']['time_seconds'] == 5
    assert len(inv['recent_self_operations']) == 1
    assert hero(result)['inventory']['recent_self_operations'] == []


def test_both_lineups_and_opportunity_contract_present(bundles):
    r = query(bundles)
    interactions = {i['actor_id']: i for i in r['composition']['interactions']}
    assert interactions['self']['allied_ids'] == ['ally']
    assert interactions['self']['opponent_ids'] == ['enemy']
    assert interactions['enemy']['opponent_ids'] == ['self', 'ally']
    assert r['world']['action_durations']['value'] is None
    assert 'opportunity_cost' in r['analysis_contract']['action_comparison_fields']
    assert not r['analysis_contract']['complete_macro_analysis_ready']


def test_public_kills_do_not_expose_assists_or_future_respawn(bundles):
    bundles[0]['categories']['kills'] = [row(4, victim_entity_id='enemy', killer_entity_id='self', assist_entity_ids=['ally'])]
    bundles[0]['categories']['lifecycle']['events'] = [row(6, kind='respawn_candidate')]
    r = query(bundles)
    assert 'assist_entity_ids' not in r['recent_public_combat'][0]
    assert hero(r)['last_allied_lifecycle_event'] is None


def test_every_sample_has_prefix_evidence_and_input_is_not_mutated(bundles):
    original = deepcopy(bundles)
    result = query(bundles, player='self')
    assert bundles == original
    assert all(e['time_seconds'] <= 8 for e in result['evidence'].values())
    for h in result['heroes']:
        for sample in h['last_observed'].values():
            assert sample['evidence_id'] in result['evidence']


@pytest.mark.parametrize('at', [-1, float('nan'), float('inf'), 21, True])
def test_invalid_cutoff_rejected(bundles, at):
    with pytest.raises(ValueError):
        query(bundles, at=at)


@pytest.mark.parametrize('which,key,value', [(1, 'source_sha256', 'other'), (2, 'version', '16.21'),
    (3, 'schema', 'replay-hero-visibility-prefix/v1'), (2, 'cutoff_seconds', 7), (1, 'game_length_seconds', 19)])
def test_incompatible_inputs_rejected(bundles, which, key, value):
    bundles[which][key] = value
    with pytest.raises(ValueError):
        query(bundles)


def test_wrong_player_rejected(bundles):
    with pytest.raises(ValueError):
        query(bundles, player='enemy')


def test_unknown_roster_identity_never_grants_private_or_team_information(bundles):
    for bundle in (bundles[0], bundles[3]):
        actors = bundle['identity_directory']['owners'] if 'identity_directory' in bundle else bundle['actors']
        for a in actors:
            a['team_id'] = None
    r = query(bundles)
    assert r['summary']['unknown_team_ids'] == ['self', 'ally', 'enemy']
    assert all(h['observed_now'] is None for h in r['heroes'])
