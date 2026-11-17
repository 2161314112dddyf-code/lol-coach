from copy import deepcopy

import pytest

pytest.importorskip('PIL')
from scripts.render_review_minimap import project, snapshot
from test_round_chain import bundle_at, freeze


def test_map_does_not_display_hidden_stale_or_unobserved_units():
    b = bundle_at(10)
    frame = b['frame']
    frame['task']['review_origin'] = dict(match_id='1', perspective='personal',
                                         replay_sha256=b['audit']['source_replay_sha256'])
    frame['facts'] = {}
    d = frame['decision']
    frame['lineup'] = [dict(entity_id=d['player_entity_id'], champion='Pantheon', relation='ally'),
                       dict(entity_id='opponent',champion='MasterYi',relation='enemy')]
    for lane in ('top','mid','bot'):
        frame['facts'][lane] = dict(entity_id='lane:'+lane,field='lane_current_units_and_groups',
            observed_at_seconds=10,temporal_scope='queried_at_decision_time',
            value=dict(lane=lane,observer_team_id=d['observer_team_id'],count_scope='own_team_observed_live_only',
                       units=[dict(kind='melee',last_xz=[23,34],sampled_at=9.5),
                              dict(kind='melee',last_xz=[25,37],sampled_at=5),
                              dict(kind='ranged',last_xz=None,sampled_at=None)]))
    frame['facts']['enemy'] = dict(entity_id='entity:opponent',field='observer_visibility',observed_at_seconds=10,
        temporal_scope='queried_at_decision_time', value=dict(team_id=d['observer_team_id'],visible=False,
        last_observed_position=dict(sampled_at=9.9,xz=[25,37])))
    assets = dict(build=d['build'])
    data=snapshot(freeze(b),assets)
    assert data['lanes']['bot']=={'registered':3,'recent':1}
    assert len(data['minions'])==3 and data['heroes']==[]
    wrong=deepcopy(b)
    wrong['frame']['task']['review_origin']['replay_sha256']='9'*64
    with pytest.raises(ValueError,match='source_bound'):
        snapshot(freeze(wrong),assets)
    assert project([0,100], [0,0,100,100], 512)==(0,0)
    assert project([100,0], [0,0,100,100], 512)==(511,511)
    assert project([-1,0], [0,0,100,100], 512) is None


def test_late_map_requires_a_native_terrain_match_for_the_same_frame():
    b = bundle_at(448)
    f = b['frame']
    f['task']['review_origin']=dict(match_id='1',perspective='personal',replay_sha256=b['audit']['source_replay_sha256'])
    b=freeze(b)
    with pytest.raises(ValueError,match='native evidence'):
        snapshot(b,dict(build=f['decision']['build']))
    with pytest.raises(ValueError,match='terrain_evidence_mismatch'):
        snapshot(b,dict(build=f['decision']['build']),terrain=dict(schema='native-minimap-variant/v1',
                 source_sha256=b['audit']['source_replay_sha256'],frame_id=f['frame_id'],
                 build=f['decision']['build'],at=447))


def test_only_personal_ping_with_region_observed_by_cutoff_is_drawn():
    b=bundle_at(10)
    f=b['frame']
    f['task']['review_origin']=dict(match_id='1',perspective='personal',replay_sha256=b['audit']['source_replay_sha256'])
    actor,team=f['decision']['player_entity_id'],f['decision']['observer_team_id']
    f['facts'] = {lane:dict(entity_id='lane:'+lane,field='lane_current_units_and_groups',observed_at_seconds=10,
        temporal_scope='queried_at_decision_time',value=dict(lane=lane,observer_team_id=team,
        count_scope='own_team_observed_live_only',units=[])) for lane in ('top','mid','bot')}
    f['recent_team_pings']={'fact_ids':['self','future','ally','otherteam']}
    for name,sender,available,side in [('self',actor,9,team),('future',actor,11,team),
                                       ('ally','somebody',9,team),('otherteam',actor,9,300-team)]:
        f['facts'][name]=dict(entity_id=sender,field='map_ping_sent',observed_at_seconds=8,
             temporal_scope='communication_event',value=dict(kind='assist_me',observer_team_id=side,known_as='own_sent',
             marker_region=dict(map_id=11,description='red bot tower',basis='native_hud_ring_estimate',
                                observed_through_seconds=available,xz_rounded_to_100=[12000,3000])))
    r=snapshot(freeze(b),dict(build=f['decision']['build']))
    assert [p['fact_id'] for p in r['personal_pings']]==['self']
    assert r['personal_pings'][0]['exact_packet_xz'] is None
