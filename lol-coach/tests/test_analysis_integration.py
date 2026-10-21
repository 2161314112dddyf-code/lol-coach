"""Synthetic integration boundaries; actual source runs are separately recorded."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest
from lol_coach.action_evidence import conditional_travel,movement_timeline
from lol_coach.analysis_context import cached_champion,join_towers,build_context
from lol_coach.mechanism_rules import evaluate_interaction
from lol_coach.replay_vision import VERSION
from scripts.research_inventory_time import investigate
from test_macro_snapshot import bundles  # synthetic fixture only


def tower_inputs():
    def src(offset):return dict(stream=1,chunk=1,offset=offset,payload_hex='SECRET',payload_sha256='synthetic')
    identity=dict(name='synthetic-tower',team=200,lane=1,role='synthetic',opaque_prefix_hex='SECRET',map_reference_position=['SECRET'])
    t=dict(schema='turret-state/v1',version=VERSION,source={'sha256':'synthetic'},identity_events=[
        dict(entity_id='tower',time_seconds=2,source=src(2),identity=identity)],health_samples=[
        dict(entity_id='tower',time_seconds=2,source=src(3),values={'health':100,'current_gold':999}),
        dict(entity_id='tower',time_seconds=4,source=src(5),values={'health':999})])
    v=dict(schema='named-tower-vision/v1',version=VERSION,source=t['source'],events=[
        dict(entity_id='tower',time_seconds=time,observer_team_id=100,visible=visible,
             source=dict(stream=1,chunk=1,decompressed_offset=offset,payload_hex='SECRET'))
        for time,visible,offset in [(1,True,1),(3,False,4),(5,True,6)]])
    s=dict(source_sha256='synthetic',context=dict(at_seconds=4,observer_team_id=100),world={})
    return s,t,v


def test_tower_hidden_history_whitelist_and_no_mutation():
    s,t,v=tower_inputs();before=deepcopy((t,v));out=join_towers(s,t,v);row=out['world']['enemy_towers']['towers'][0]
    assert row['observed_now'] is None
    assert row['last_observed']['health']['value']==100
    assert 'SECRET' not in json.dumps(out) and 'current_gold' not in json.dumps(out)
    assert (t,v)==before


def test_tower_future_identity_excluded_and_reentry_clears_current():
    s,t,v=tower_inputs();s['context']['at_seconds']=1
    assert join_towers(s,t,v)['world']['enemy_towers']['towers']==[]
    s['context']['at_seconds']=5
    assert join_towers(s,t,v)['world']['enemy_towers']['towers'][0]['observed_now']=={}


def test_tower_preidentity_same_timestamp_sample_excluded():
    s,t,v=tower_inputs();t['health_samples'][0]['source']['offset']=1
    assert join_towers(s,t,v)['world']['enemy_towers']['towers'][0]['last_observed']=={}


@pytest.mark.parametrize('key,value',[('version','future'),('schema','other'),('source',{'sha256':'other'})])
def test_tower_wrong_provenance_rejected(key,value):
    s,t,v=tower_inputs();t[key]=value
    with pytest.raises(ValueError):join_towers(s,t,v)


def test_tower_future_changes_do_not_change_prefix():
    s,t,v=tower_inputs();original=deepcopy(join_towers(deepcopy(s),t,v))
    future=deepcopy(t['identity_events'][0]);future.update(time_seconds=10,entity_id='future-secret');t['identity_events'].append(future)
    t['health_samples'].append(dict(entity_id='tower',time_seconds=10,source={'stream':1,'chunk':1,'offset':99},values={'health':9999}))
    assert join_towers(s,t,v)==original


def make_cache(tmp_path):
    root=tmp_path/'cache-root';(root/'cache').mkdir(parents=True);(root/'raw').mkdir()
    for name in ['A','B','C']:
        url=f'https://ddragon.leagueoflegends.com/cdn/16.20.1/data/en_US/champion/{name}.json'
        champion=dict(id=name,stats={'hp':100},passive={'name':'synthetic','description':'synthetic'},spells=[
            dict(id=str(i),name='synthetic',description='synthetic',tooltip='{{ unknown }}',cooldown=[9],cost=[10],range=[500]) for i in range(4)])
        raw=json.dumps(dict(version='16.20.1',data={name:champion})).encode();(root/'raw'/f'{name}.json').write_bytes(raw)
        record=dict(requested_url=url,http_status=200,evidence_path=f'raw/{name}.json',sha256=hashlib.sha256(raw).hexdigest(),retrieved_at_utc='synthetic')
        (root/'cache'/(hashlib.sha256(url.encode()).hexdigest()+'.json')).write_text(json.dumps(record))
    return root


def test_static_source_hash_and_unknown_cooldowns(tmp_path):
    root=make_cache(tmp_path);r=cached_champion(root,'A')
    assert r['current_cooldowns'] is None and len(r['abilities'])==5
    assert r['abilities'][1]['unresolved_parameters']==['unknown']
    (root/'raw/A.json').write_text('{}')
    with pytest.raises(ValueError,match='hash'):cached_champion(root,'A')


def test_context_lineup_matching_is_conditional_and_no_future_leak(bundles,tmp_path):
    cache=make_cache(tmp_path)
    mechanisms=dict(schema='champion-mechanisms/v1',sources={},interactions=[
        dict(id='ally-rule',participants=['A','B'],relationship='ally',requires={'ready':True}),
        dict(id='wrong-team-rule',participants=['A','C'],relationship='ally',requires={'ready':True})])
    kwargs=dict(at=8,team=100,cache_root=cache,human_cards=dict(schema='conditional-human-experience/v1',cards=[]),mechanisms=mechanisms)
    before=deepcopy(bundles);r=build_context(bundles,**kwargs)
    assert bundles==before
    rules=r['foundation']['conditional_mechanisms'];assert len(rules)==1 and rules[0]['status']=='conditions_unknown'
    assert rules[0]['satisfied_conditions'] is None
    assert r['coverage']['static_abilities']==15 and not r['coverage']['complete_macro_analysis_ready']
    bundles[1]['updates'][-1]['values']['health']=123456  # hidden at t=7
    assert build_context(bundles,**kwargs)==r
    assert r['world']['enemy_towers']['status']=='unknown'
    # Partially identified replays still export their known information.
    bundles[3]['actors'][0]['champion']=None
    bundles[0]['identity_directory']['owners'][0]['champion']=None
    partial=build_context(bundles,**kwargs)
    assert partial['coverage']['unknown_champion_entity_ids']==['self']
    assert partial['coverage']['static_champions']==2


@pytest.mark.parametrize('speed',[0,-1,float('nan'),float('inf'),True])
def test_travel_invalid_speed(speed):
    with pytest.raises(ValueError):conditional_travel([[0,0],[3,4]],speed)


@pytest.mark.parametrize('points',[[],[[0,0]],[[0,0],[True,2]],[[0,0],[float('nan'),0]],[[0,0],[1,2,3]]])
def test_travel_invalid_route(points):
    with pytest.raises(ValueError):conditional_travel(points,1)


def test_travel_is_arithmetic_not_arrival():
    r=conditional_travel([[0,0],[3,4],[6,8]],2)
    assert r['duration_seconds']==5 and r['actual_end_position'] is None and not r['decision_input_eligible']


def test_timeline_replanning_and_single_point_do_not_certify_arrival():
    r=dict(version=VERSION,source_integrity='verified',replay={'sha256':'r'},video={'sha256':'v'},
        timing_sample={'replay_sha256':'r','video_sha256':'v'},track=[
            dict(time=1,points=[[0,0],[3,4]],speed=1),dict(time=2,points=[[1,1],[2,2]],speed=1),
            dict(time=3,points=[[2,2]],speed=1)])
    out=movement_timeline(r);assert out['events'][1]['supersedes_plan_id']=='m1'
    assert all(e['actual_arrival'] is None for e in out['events'])
    assert out['events'][2]['kind']=='single_point_candidate'


@pytest.mark.parametrize('rule_id',['ryze_jhin_followup','zyra_masteryi_slow_immunity','veigar_zyra_control_followup'])
def test_new_rules_met_missing_and_false_conditions(rule_id):
    path=Path(__file__).parents[1]/'lol_coach/profiles/lineup_interactions_16_20_1.json'
    spec=json.loads(path.read_text(encoding='utf8'));rule=next(r for r in spec['interactions'] if r['id']==rule_id)
    b=dict(schema='champion-mechanisms/v1',patch=spec['patch'],interactions=[rule],sources={k:{} for k in ['Ryze','Jhin','Zyra','MasterYi','Veigar']})
    facts=rule['requires'].copy()
    def query(f):return evaluate_interaction(b,rule_id,f,patch='16.20.1')
    result=query(facts);assert result['status']==rule['when_met']['status'] and not result['actual_match_observation']
    assert query({})['status']=='insufficient_information'
    facts[next(iter(facts))]=False;assert query(facts)['status']==rule['when_unmet']['status']


def test_inventory_lag_probe_preserves_unknown_and_conflicts():
    e=dict(entity_id='x',time_seconds=5,slot=0,kind='slot_update',item_id=100,source={'chunk':1,'decompressed_offset':1})
    c=dict(entity_id='x',time_seconds=70,source={'stream':2},items=[{'slot':0,'item_id':200,'empty':False}])
    out=investigate([c],[e]);assert out['totals'][0]['conflict_slots']==1
    assert out['totals'][0]['compared_slots']==1
    assert not out['timestamps_modified'] and not out['decision_input_eligible']
