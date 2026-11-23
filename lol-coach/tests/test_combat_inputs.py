"""Synthetic panel rows test cutoff, player binding and explicit unknowns."""
import json
import pytest

from lol_coach.combat_inputs import attach_combat_inputs, combat_inputs
from lol_coach.reasoning_frame import compile_frame, digest


def make_bundle(at=448):
    return compile_frame(dict(schema='macro-snapshot/v1',version='16.22.test',source_sha256='a'*64,
        context=dict(at_seconds=at,observer_team_id=200,player_entity_id='0xb4'),
        heroes=[dict(entity_id='0xb4',team_id=200,champion='Pantheon',visibility=dict(value=True),inventory={}),
                dict(entity_id='0xb1',team_id=100,champion='Jhin',visibility=dict(value=None),inventory={})],
        evidence={},recent_public_combat=[]))


def write_panel(root,team=200):
    row=dict(at=448,frame_sha256='b'*64,ranks=dict(R=1),stats=dict(ability_power=0,attack_damage=128),
             environment=dict(map_number=11,game_mode='CLASSIC'),receipt='test-frame')
    rec=dict(schema='own-combat-panel/v1',source_sha256='a'*64,build='16.22.test',
             own_entity_id='0xb4',team=team,samples=[row])
    rec['checksum']=digest(rec)
    directory=root/('a'*64)
    directory.mkdir(exist_ok=True)
    path=directory/'0xb4.json'
    path.write_text(json.dumps(rec))
    return path


def test_exact_clock_reads_personal_panel_once_and_freezes_it(tmp_path):
    path=write_panel(tmp_path)
    base=make_bundle()
    frozen=attach_combat_inputs(base,tmp_path)
    path.unlink()
    result=combat_inputs(frozen,'0xb1')
    assert result['ranks']=={'Q':None,'W':None,'E':None,'R':1}
    assert result['stats']['ability_power']==0 and result['stats']['bonus_attack_damage'] is None
    assert result['environment']=={'map_number':11,'game_mode':'CLASSIC'}
    assert all(v is None for v in result['defenses'].values())
    assert set(result['evidence'].values()) <= frozen['frame']['facts'].keys()
    assert not combat_inputs(base,'0xb1')['evidence']
    assert attach_combat_inputs(frozen,tmp_path) is frozen


@pytest.mark.parametrize('clock',[447.999,448.001])
def test_different_clock_cannot_supply_current_dynamic_stats(tmp_path,clock):
    write_panel(tmp_path)
    base=make_bundle(clock)
    assert attach_combat_inputs(base,tmp_path) is base


def test_bad_team_binding_is_rejected(tmp_path):
    write_panel(tmp_path,team=100)
    with pytest.raises(ValueError,match='scope mismatch'):
        attach_combat_inputs(make_bundle(),tmp_path)


def test_cooldowns_are_observed_values_only_at_exact_sample_clock(tmp_path):
    path = write_panel(tmp_path)
    record = json.loads(path.read_bytes())
    record.pop('checksum')
    record['samples'][0]['remaining_cooldowns'] = dict(Q=6,W=2,E=14,R=64)
    record['checksum'] = digest(record)
    path.write_text(json.dumps(record))
    exact = attach_combat_inputs(make_bundle(),tmp_path)
    fid, = exact['frame']['native_combat_panel_ids']
    assert exact['frame']['facts'][fid]['value']['remaining_cooldowns_at_sample']['E'] == 14
    assert 'native_combat_panel_ids' not in attach_combat_inputs(make_bundle(448.001),tmp_path)['frame']


@pytest.mark.parametrize(('visible','sample_time','expected'),[(True,448,1222),(False,448,None),(True,447,None)])
def test_only_current_visible_enemy_public_health_is_read(visible,sample_time,expected):
    snapshot=dict(schema='macro-snapshot/v1',version='16.22.test',source_sha256='a'*64,
        context=dict(at_seconds=448,observer_team_id=200,player_entity_id='0xb4'),
        heroes=[dict(entity_id='0xb4',team_id=200,champion='Pantheon',visibility=dict(value=True),inventory={}),
                dict(entity_id='0xb1',team_id=100,champion='Jhin',inventory={},
                     visibility=dict(value=visible,transition_seconds=445,evidence_id='seen'),
                     observed_now=dict(max_health=dict(value=1222,observed_at_seconds=sample_time,evidence_id='hp'),
                                       health=dict(value=611,observed_at_seconds=sample_time,evidence_id='hp_now')))],
        evidence={'seen':dict(entity_id='0xb1',time_seconds=445),'hp':dict(entity_id='0xb1',
                  field='max_health',time_seconds=sample_time),'hp_now':dict(entity_id='0xb1',
                  field='health',time_seconds=sample_time)},recent_public_combat=[])
    bundle=compile_frame(snapshot)
    read=combat_inputs(bundle,'0xb1')
    assert read['defenses']['target_max_health']==expected
    assert read['defenses']['effective_magic_resist'] is None
    if expected is None:
        assert 'target_health_at_decision' not in read
    else:
        hp = read['target_health_at_decision']
        assert hp['at_seconds'] == 448 and hp['fraction'] == 0.5
        assert set(hp['evidence_ids']) <= bundle['frame']['facts'].keys()
    if visible and sample_time == 448:
        frame=bundle['frame']
        fact=dict(entity_id='entity:0xb1',field='observer_visibility',
                  value=dict(team_id=200,visible=False),observed_at_seconds=448,
                  temporal_scope='queried_at_decision_time')
        fact_id='f_'+digest(fact)[:20]
        frame['facts'][fact_id]=fact
        frame['vision_fact_ids']=[fact_id]
        frame.pop('frame_id')
        frame['frame_id']='frame_'+digest(frame)[:24]
        assert combat_inputs(bundle,'0xb1')['defenses']['target_max_health'] is None


def test_estimate_is_frozen_separately_from_exact_stat(tmp_path):
    path = write_panel(tmp_path)
    bundle = make_bundle()
    frame = bundle['frame']
    profile = json.loads(path.read_bytes())
    frame['decision']['build'] = profile['build'] = '16.22.836.1077'
    profile.pop('checksum')
    profile['checksum'] = digest(profile)
    path.write_text(json.dumps(profile))
    owner = next(hero for hero in frame['lineup'] if hero['entity_id'] == '0xb4')
    level = dict(entity_id='0xb4', field='personal_client_state', value={'level': 6},
                 observed_at_seconds=448, temporal_scope='personal_native_observation')
    level_id = 'f_' + digest(level)[:20]
    frame['facts'][level_id] = level
    owner['current_fact_ids'].append(level_id)
    frame.pop('frame_id')
    frame['frame_id'] = 'frame_' + digest(frame)[:24]
    frozen = attach_combat_inputs(bundle, tmp_path)
    path.unlink()
    read = combat_inputs(frozen, None)
    interval = read['estimates']['bonus_attack_damage']
    assert interval['lower'] == pytest.approx(50.465)
    assert interval['upper'] == pytest.approx(51.465)
    assert interval['evidence_ids'] == [read['evidence']['attack_damage'], level_id]
    assert interval['source']['damagePerLevelModifiable'] == pytest.approx(3.3)
    assert read['stats']['bonus_attack_damage'] is None
