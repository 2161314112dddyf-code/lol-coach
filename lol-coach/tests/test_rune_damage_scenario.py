"""Synthetic hit conditions on the reviewed 16.22 rule pack."""
from copy import deepcopy

import pytest

from lol_coach.damage_scenario import armor_penetration, rune_damage, validate_scenario
from lol_coach.reasoning_frame import digest
from lol_coach.replay_runes import FIELD
from lol_coach.rune_damage_data import rune_damage_profile
from test_review_abilities import calculate, pantheon_frame
from test_round_chain import freeze


BUILD = '16.22.836.1077'
PERKS = [8010, 9111, 9104, 8014, 8304, 8347]
DEFENSE = {'effective_armor':100, 'effective_magic_resist':50}
PAGE = dict(perk_ids=PERKS, shard_ids=[5008,5008,5013], primary_style_id=8000, secondary_style_id=8300)


def pack():
    return dict(build=BUILD, rune_rules=rune_damage_profile(BUILD), items={})


def proc_result(key, params, ids, **assumptions):
    # These unit fixtures isolate individual rune branches. No synthetic page
    # is presented as a legal in-game loadout or as an observed outcome.
    page = dict(PAGE, perk_ids=ids)
    parts = [dict(label='R.landing_center', damage_type='magic',raw_damage=300)]
    values = {**assumptions, **({key: params} if params is not None else {})}
    validate_scenario(values, {parts[0]['label']})
    return rune_damage(page, pack(), parts, {}, DEFENSE, values, 18, dict(ap=100, bonus_ad=50))


def real_page_fixture():
    bundle = pantheon_frame()
    frame = bundle['frame']
    fact = dict(entity_id=frame['decision']['player_entity_id'],field=FIELD,value=deepcopy(PAGE),
                temporal_scope='fixed_pregame_selection',observed_at_seconds=0,available_at_seconds=0)
    fid = 'f_' + digest(fact)[:20]
    frame['facts'][fid] = fact
    frame['personal_rune_page_fact_id'] = fid
    frame['lineup'][0]['current_fact_ids'].append(fid)
    record = pack()
    ref = 'combat_' + digest(record)
    frame['task']['combat_reference'] = ref
    frame['references'][ref] = dict(kind='combat_reference',content_sha256=digest(record))
    bundle['reference_library'][ref] = record
    return freeze(bundle)


@pytest.mark.parametrize('fraction,raw,expected', [
    (0.39999,[324,324],[324/1.4,324/1.4]), (.4,[300,300],[300/1.4,300/1.4]),
    (None,[300,324],[300/1.4,324/1.4])])
def test_rune_aware_mcp_subtotal_at_health_boundary(fraction, raw, expected):
    inputs = dict(effective_magic_resist=40, ranks={'R':1}, ap=0)
    if fraction is not None:
        inputs.update(target_health_fraction=fraction)
    result = calculate(real_page_fixture(), ['R.landing_center'], inputs)
    runes = result['rune_damage']
    assert result['primary_result'] == 'rune_damage' and result['primary_status'] == runes['status']
    assert result['status_scope'] == 'legacy_spell_subtotal_only'
    assert runes['raw_total_interval'] == pytest.approx(raw)
    assert runes['after_resistance_total_interval'] == pytest.approx(expected)
    assert bool(runes['after_resistance_total']) == (fraction is not None)
    assert not runes['blockers'] and result['damage']['raw_total'] == 300
    assert len(runes['runes']) == 8 and next(r for r in runes['runes'] if r['rune_id']==5008)['copies'] == 2
    assert result['observed_health_loss'] is None


def test_two_hits_cross_threshold_and_per_hit_offense():
    result = calculate(real_page_fixture(), ['R.spear','R.landing_center'], dict(
        ranks={'R':1,'Q':1}, ap=0, bonus_ad=0, effective_armor=0, effective_magic_resist=0,
        pre_hit_offense={'R.landing_center': {'ap':5}},
        pre_hit_health_fractions={'R.spear':.4,'R.landing_center':.39},
        shield_scenario={'health_before':390,'universal_shield':50}))
    runes = result['rune_damage']
    assert runes['conqueror_sequence']['distinct_spell_slots'] == 1 and not runes['conqueror_sequence']['stacks_simulated']
    assert runes['after_resistance_total'] == pytest.approx(70+305*1.08)
    assert runes['conditional_hp_loss_interval'] == pytest.approx([70+305*1.08-50]*2)
    assert runes['observed_hp_loss'] is None
    with pytest.raises(ValueError,match='before_each_hit'):
        calculate(real_page_fixture(), ['R.spear','R.landing_center'], {'target_health_fraction':.39})


def test_missing_or_unknown_rune_never_produces_a_complete_subtotal():
    assert 'rune_rules_not_preloaded' in calculate(pantheon_frame(), ['R.landing_center'])['rune_damage']['blockers']
    result = proc_result('',None,[8010,9111,9104,8014,8304,9999],target_health_fraction=.2)
    assert result['blockers'] == ['unreviewed_rune_9999'] and result['after_resistance_total_interval'] is None


def test_single_hit_accepts_pre_hit_health_and_rejects_contradictory_health_inputs():
    args = dict(ap=0, ranks={'R':1}, effective_magic_resist=0, target_max_health=1000,
                shield_scenario={'health_before':390,'universal_shield':50})
    result = calculate(real_page_fixture(), ['R.landing_center'], args)['rune_damage']
    assert result['after_resistance_total'] == 324 and result['conditional_hp_loss_interval'] == [274,274]
    with pytest.raises(ValueError,match='conflicting_target_health'):
        calculate(real_page_fixture(), ['R.landing_center'], {**args,'target_health_fraction':.9})


@pytest.mark.parametrize('ready,impaired,extra', [(True,True,45),(False,True,0),(True,False,0)])
def test_cheap_shot_once_bypasses_resists(ready,impaired,extra):
    result = proc_result('cheap_shot', dict(trigger_hit='R.landing_center', ready=ready,
        target_already_impaired=impaired, proc_target_health_fraction=.8), [8010,9111,9104,8014,8126,8135],
        target_health_fraction=.8)
    assert result['after_resistance_total'] == pytest.approx(200+extra)


@pytest.mark.parametrize('prior,ready,kind,total', [(2,True,'physical',325), (2,True,'magic',200+250/1.5),
                                                      (1,True,None,200),(2,False,None,200),(2,True,None,None)])
def test_electrocute_three_distinct_sources_and_adaptive_type(prior,ready,kind,total):
    scenario = dict(trigger_hit='R.landing_center',ready=ready,previous_distinct_sources_in_window=prior)
    if kind:
        scenario['adaptive_damage_type'] = kind
    val = proc_result('electrocute',scenario,[8112,8139,8140,8135,8304,8347])['after_resistance_total']
    assert val is None if total is None else val == pytest.approx(total)


@pytest.mark.parametrize('delay,ready,alive,expected', [(0.99,True,True,200),(1,True,True,200+40/1.5),
                                                         (1,False,True,200),(1,True,False,200)])
def test_scorch_settles_only_after_delay(delay,ready,alive,expected):
    scenario = dict(trigger_hit='R.landing_center',ready=ready,seconds_after_trigger=delay,target_still_damageable=alive)
    result = proc_result('scorch',{**scenario,'proc_target_health_fraction':.8},
                         [8010,9111,9104,8014,8237,8210],target_health_fraction=.8)
    assert result['after_resistance_total'] == pytest.approx(expected)


@pytest.mark.parametrize('armor,expected', [(50,35), (5,0), (-20,-20)])
def test_percentage_then_flat_penetration_with_floor(armor,expected):
    values = dict(armor_after_reductions=armor,total_percent_armor_penetration=10,total_flat_armor_penetration=10)
    assert armor_penetration(values,None,None,None,None)['effective_armor'] == pytest.approx(expected)
    with pytest.raises(ValueError):
        validate_scenario({**values, 'effective_armor':0}, {'R.spear'})


def test_reviewed_dirk_and_rank_one_r_require_the_frozen_inventory():
    values = dict(armor_after_reductions=50,use_reviewed_armor_penetration=True)
    profile = {'passive_percent_armor_penetration_by_rank':[.1,.2,.3]}
    items = {'3134':dict(raw_description='<attention>10</attention>穿甲'), '3000':{}}
    inventory = [dict(item_id=3134,count=1)]
    calc = armor_penetration(values, {'items':items},inventory,profile,1)
    assert calc['effective_armor'] == 35 and calc['total_flat_armor_penetration'] == 10
    inventory.append(dict(item_id=3000,count=1))
    assert armor_penetration(values, {'items':items},inventory,profile,1)['effective_armor'] is None
    with pytest.raises(ValueError,match='one_complete'):
        validate_scenario({'armor_after_reductions':50}, {'R.spear'})


@pytest.mark.parametrize('fraction,expected',[(.60,200),(.601,216)])
def test_cut_down_strictly_above_threshold(fraction,expected):
    result = proc_result('',None,[8010,9111,9104,8017,8304,8347],target_health_fraction=fraction)
    assert result['after_resistance_total'] == pytest.approx(expected)


@pytest.mark.parametrize('hp,ready,souls,expected',[(.49,True,3,200+(30+33+5+5)/2),(.5,True,3,200),(.49,False,99,200)])
def test_dark_harvest_uses_prior_souls_and_separate_eligibility_sample(hp,ready,souls,expected):
    scenario = dict(trigger_hit='R.landing_center',ready=ready,health_fraction_at_soul_check=hp,
                    souls_before_proc=souls,adaptive_damage_type='physical',proc_target_health_fraction=.6)
    result = proc_result('dark_harvest',scenario,[8128,8139,8140,8135,8014,8009],target_health_fraction=.8)
    assert result['after_resistance_total'] == pytest.approx(expected)


def test_true_damage_proc_with_unknown_impact_health_and_mutually_exclusive_rows():
    result = proc_result('cheap_shot',dict(trigger_hit='R.landing_center',ready=True,target_already_impaired=True),
                         [8010,9111,9104,8014,8126,8347],target_health_fraction=.2)
    assert result['after_resistance_total'] is None
    assert result['after_resistance_total_interval'] == pytest.approx([216 + 45, 216 + 45 * 1.08])
    assert not result['blockers']
    with pytest.raises(ValueError,match='mutually_exclusive'):
        proc_result('',None,[8010,9111,9104,8014,8017,8347])


@pytest.mark.parametrize('perk,proc_key,proc_params,base_hp,proc_hp,proc_raw', [
    (8014, 'cheap_shot', dict(target_already_impaired=True), .40, .39, 45),
    (8017, 'sudden_impact', dict(seconds_since_qualifying_mobility=1), .60, .61, 80)])
def test_health_amp_on_separate_true_proc_samples_its_own_impact(perk, proc_key, proc_params, base_hp, proc_hp, proc_raw):
    proc_id = 8126 if proc_key == 'cheap_shot' else 8143
    result = proc_result(proc_key, dict(trigger_hit='R.landing_center', ready=True,
        proc_target_health_fraction=proc_hp, **proc_params),
        [8010, 9111, 9104, perk, proc_id, 8347], target_health_fraction=base_hp)
    assert result['after_resistance_total'] == pytest.approx(200 + proc_raw * 1.08)


@pytest.mark.parametrize('label,frozen_policy,expected', [
    ('Q.reviewed', True, 108), ('Q.reviewed', False, None),
    ('summoner.smite', True, None), ('jungle.pet', True, None), ('summoner.ignite', True, None)])
def test_true_damage_primary_part_obeys_same_source_and_frozen_rule_guard(label, frozen_policy, expected):
    catalog = pack()
    if not frozen_policy:
        catalog['rune_rules'].pop('true_damage_amplification')
        catalog['rune_rules']['rules']['8014']['validated_damage_types'] = ['physical', 'magic']
    result = rune_damage(PAGE, catalog, [dict(label=label, damage_type='true', raw_damage=100)],
                         {}, DEFENSE, dict(target_health_fraction=.39), 18, {})
    if expected is None:
        assert result['blockers'] == ['health_amplifier_on_true_damage_unverified']
        assert result['after_resistance_total_interval'] is None
    else:
        assert result['after_resistance_total'] == pytest.approx(expected)


def test_preloaded_slot_index_conflict_rejected_and_reference_only_rule_blocks_totals():
    catalog = pack()
    catalog['runes'] = {'9111':{'tree_id':8000, 'slot_index':1}, '9104':{'tree_id':8000,'slot_index':1}}
    with pytest.raises(ValueError, match='mutually_exclusive'):
        rune_damage(PAGE, catalog, [], {}, DEFENSE, {}, 18, {})
    result = proc_result('',None,[8369,8304,8347,9111,9104,8014])
    assert 'unevaluated_rune_rule_8369' in result['blockers']
    assert result['raw_total_interval'] is None and result['after_resistance_total_interval'] is None


@pytest.mark.parametrize('elapsed,lo,hi',[(.5,280,280),(4,200,280),(4.001,200,200)])
def test_sudden_impact_post_dash_window(elapsed,lo,hi):
    scenario = dict(trigger_hit='R.landing_center',ready=True,seconds_since_qualifying_mobility=elapsed)
    result = proc_result('sudden_impact',{**scenario,'proc_target_health_fraction':.8},
                         [8010,9111,9104,8014,8143,8135],target_health_fraction=.8)
    assert result['after_resistance_total_interval'] == pytest.approx([lo,hi])


@pytest.mark.parametrize('key,page_ids,at_w,resolved_raw', [
    ('cheap_shot',[8010,9111,9104,8014,8126,8135],
     {'ready':True, 'target_already_impaired':False}, [0,0]),
    ('dark_harvest',[8128,8139,8140,8135,8014,8009],
     {'ready':True, 'souls_before_proc':3, 'health_fraction_at_soul_check':.5,
      'adaptive_damage_type':'physical'}, [0,0]),
    ('scorch',[8010,9111,9104,8014,8237,8210],
     {'ready':True, 'seconds_after_trigger':.9, 'target_still_damageable':True}, [0,0]),
    ('electrocute',[8112,8139,8140,8135,8304,8347],
     {'ready':True,'previous_distinct_sources_in_window':1}, [0,0]),
    ('sudden_impact',[8010,9111,9104,8014,8143,8135],
     {'ready':True,'seconds_since_qualifying_mobility':4.0}, [0,80]),
    ('sudden_impact',[8010,9111,9104,8014,8143,8135],
     {'ready':False,'seconds_since_qualifying_mobility':2.0}, [0,0]),
])
def test_a_negative_or_unresolved_proc_at_one_hit_does_not_decide_the_window(key,page_ids,at_w,resolved_raw):
    page = dict(PAGE, perk_ids=page_ids)
    parts = [dict(label='W.vault',damage_type='physical',raw_damage=60),
             dict(label='Q.tap',damage_type='physical',raw_damage=70)]
    resistances = dict(effective_armor=0, effective_magic_resist=0)
    stats = dict(ap=0, bonus_ad=0)
    proc = dict(trigger_hit='W.vault', proc_target_health_fraction=.9, **at_w)
    values = dict(pre_hit_health_fractions={'W.vault':.9,'Q.tap':.8}, **{key:proc})
    labels = {p['label'] for p in parts}
    validate_scenario(values,labels)
    result = rune_damage(page,pack(),parts,{},resistances,values,18,stats)
    assert result['raw_total_interval'] is None and result['after_resistance_total'] is None
    assert result['blockers'] == ['unresolved_alternative_trigger_' + key]
    failed = result['parts'][-1]
    assert failed['checked_hit'] == 'W.vault' and failed['checked_hit_raw_interval'] == resolved_raw
    assert failed['raw_interval'] is None and failed['unresolved_hits'] == ['Q.tap']
    proc['other_hits_cannot_trigger'] = True
    validate_scenario(values,labels)
    alternate = rune_damage(page,pack(),parts,{},resistances,values,18,stats)
    assert alternate['after_resistance_total_interval'] == pytest.approx([130+x for x in resolved_raw])


def test_intervening_stun_allows_one_proc_at_later_hit():
    parts = [dict(label='W.vault',damage_type='physical',raw_damage=60),
             dict(label='Q.tap',damage_type='physical',raw_damage=70)]
    page = dict(PAGE,perk_ids=[8010,9111,9104,8014,8126,8135])
    values = dict(pre_hit_health_fractions={'W.vault':.9,'Q.tap':.8})
    base = dict(effective_armor=0,effective_magic_resist=0)
    missing = rune_damage(page,pack(),parts,{},base,values,18,{})
    assert missing['parts'][-1]['unresolved_hits'] == ['W.vault','Q.tap']
    values['cheap_shot'] = dict(trigger_hit='Q.tap', ready=True, target_already_impaired=True,
                                proc_target_health_fraction=.8)
    hit = rune_damage(page,pack(),parts,{},base,values,18,{})
    assert hit['after_resistance_total'] == 175 and len(hit['parts']) == 3


def test_known_black_cleaver_requires_per_hit_armor_or_explicit_constant(monkeypatch):
    monkeypatch.setattr('lol_coach.review_abilities.personal_state', lambda f: {
        'inventory':[{'item_id':3071,'count':1}], 'level':18})
    b = real_page_fixture()
    args = dict(ap=0,bonus_ad=0,ranks={'Q':1,'R':1},effective_armor=100,
                pre_hit_health_fractions={'Q.tap':.9,'R.spear':.8})
    hits = ['Q.tap','R.spear']
    blocked = calculate(b,hits,args)
    assert blocked['damage']['after_resistance_total'] is None
    assert blocked['rune_damage']['after_resistance_total_interval'] is None
    assert set(blocked['changing_armor']['missing_pre_hit_armor']) == set(hits)
    partial = calculate(b,hits,{**args,'pre_hit_resistances':{'Q.tap':{'effective_armor':100}}})
    assert partial['rune_damage']['missing_inputs'] == {'R.spear':['effective_armor']}
    assert partial['damage']['parts'][0]['after_resistance'] == 35
    fixed = calculate(b,hits,{**args,'assume_constant_effective_armor':True})
    assert fixed['rune_damage']['after_resistance_total'] == fixed['damage']['after_resistance_total'] == 70
    per = {'Q.tap':{'effective_armor':100},'R.spear':{'effective_armor':75}}
    changed = calculate(b,hits,{**args,'pre_hit_resistances':per})
    assert not changed['changing_armor']['missing_pre_hit_armor']
    assert changed['rune_damage']['after_resistance_total'] == changed['damage']['after_resistance_total'] == 75
    assert [r['effective_resistance'] for r in changed['rune_damage']['parts']] == [100,75]
    with pytest.raises(ValueError, match='constant_or_per_hit'):
        calculate(b,hits,{**args,'assume_constant_effective_armor':True,'pre_hit_resistances':per})
    with pytest.raises(ValueError, match='unequipped_rune'):
        calculate(b,hits,{**args,'pre_hit_resistances':{'rune.8128':{'effective_armor':50}}})


def test_display_rounded_ad_uses_same_per_hit_armor_in_both_interval_outputs(monkeypatch):
    from lol_coach.combat_inputs import combat_inputs
    b = real_page_fixture()
    read = combat_inputs(b,'enemy')
    read['ranks'].update(Q=1,R=1)
    read['stats']['ability_power'] = 0
    read['estimates']['bonus_attack_damage'] = {'lower':49,'upper':51}
    monkeypatch.setattr('lol_coach.review_abilities.combat_inputs',lambda *_:read)
    q = calculate(b,['Q.tap','R.spear'],{'pre_hit_resistances':{
        'Q.tap':{'effective_armor':100}, 'R.spear':{'effective_armor':0}},
        'pre_hit_health_fractions':{'Q.tap':.9,'R.spear':.8}})
    expected = [1.5*(70+1.15*x) for x in [49,51]]
    assert q['rune_damage']['after_resistance_total_interval'] == pytest.approx(expected)
    assert q['estimated_damage']['after_resistance_total_interval'] == pytest.approx(expected)
    assert q['damage']['after_resistance_total'] is None


def test_separately_applied_dark_harvest_gets_its_own_resistance():
    params = dict(trigger_hit='R.landing_center',ready=True,adaptive_damage_type='physical',
                  souls_before_proc=3,health_fraction_at_soul_check=.49,proc_target_health_fraction=.6)
    out = proc_result('dark_harvest',params,[8128,8139,8140,8135,8014,8009],target_health_fraction=.8,
                      pre_hit_resistances={'R.landing_center':{'effective_magic_resist':0},
                                           'rune.8128':{'effective_armor':0}})
    assert out['after_resistance_total'] == 373
