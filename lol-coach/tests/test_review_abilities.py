from copy import deepcopy

import pytest

from lol_coach.reasoning_frame import digest
from lol_coach.review_abilities import REF_KEY, session_damage_profiles
from lol_coach.round_tools import bind_round, round_call
from test_round_chain import bundle_at, freeze


def pantheon_frame(build='16.22.836.1077'):
    bundle = bundle_at(448)
    frame = bundle['frame']
    frame['decision']['build'] = build
    frame['lineup'][0]['champion'] = 'Pantheon'
    frame['lineup'][2]['champion'] = 'Jhin'
    return bind_round(freeze(bundle),'jungle','dragon',5)


def calculate(bundle, hits, assumptions=None, target='enemy'):
    return round_call(bundle,'calculate_ability_damage',dict(target_id=target,hits=[
        dict(slot=key.split('.')[0],component=key.split('.')[1]) for key in hits],assumptions=assumptions or {}))


def test_resumed_formula_survives_a_worktree_revision(monkeypatch):
    from lol_coach import ability_damage_data

    previous = pantheon_frame()
    raw = deepcopy(previous)
    ref = raw['frame']['task'].pop(REF_KEY)
    del raw['frame']['references'][ref], raw['reference_library'][ref]
    raw['frame']['decision']['at_seconds'] += 1
    freeze(raw)
    read_profile = ability_damage_data.damage_profile

    def revised_profile(build, champion, slot):
        row = read_profile(build, champion, slot)
        if row and champion == 'Pantheon' and slot == 'R':
            row['components']['landing_center']['base_by_rank'][0] += 1
        return row

    monkeypatch.setattr(ability_damage_data, 'damage_profile', revised_profile)
    assumptions = dict(ranks={'R':1}, ap=0, effective_magic_resist=0)
    fresh = bind_round(raw, 'jungle', 'dragon', 5, upgrade_legacy=True)
    assert calculate(fresh, ['R.landing_center'], assumptions)['damage']['raw_total'] == 301
    with pytest.raises(ValueError, match='conflicting_frozen_ability_formulas'):
        session_damage_profiles([raw, fresh], previous)

    def forbid_worktree_read(*args):
        pytest.fail('the continued session already has its formula')

    monkeypatch.setattr(ability_damage_data, 'damage_profile', forbid_worktree_read)
    pinned = session_damage_profiles([raw], previous)
    continued = bind_round(raw, 'jungle', 'dragon', 5, upgrade_legacy=True, damage_profiles=pinned)
    assert continued['frame']['task'][REF_KEY] == ref
    assert calculate(continued, ['R.landing_center'], assumptions)['damage']['raw_total'] == 300
    assert calculate(previous, ['R.landing_center'], assumptions)['damage']['raw_total'] == 300
    assert calculate(raw, ['R.landing_center'], assumptions)['damage'] is None
    assert session_damage_profiles([raw, previous]) == pinned


@pytest.mark.parametrize('changed', ['match', 'lineup'])
def test_formula_pin_is_scoped_to_the_game_and_roster(changed):
    old = pantheon_frame()
    other = deepcopy(old)
    if changed == 'match':
        other['audit']['source_replay_sha256'] = 'f' * 64
    else:
        other['frame']['lineup'][2]['champion'] = 'Leona'
    with pytest.raises(ValueError, match='ability_formula_sequence_scope_mismatch'):
        session_damage_profiles([freeze(other)], old)


def test_new_session_takes_published_spell_slots_and_uses_exact_build_fallback_only_for_other_champions(monkeypatch):
    from lol_coach import ability_damage_data

    original = pantheon_frame()
    raw = deepcopy(original)
    frame = raw['frame']
    old = frame['task'].pop(REF_KEY)
    del frame['references'][old], raw['reference_library'][old]
    build = frame['decision']['build']
    damage_profile = ability_damage_data.damage_profile
    archived = damage_profile(build, 'Pantheon', 'R')
    archived['components']['landing_center']['base_by_rank'][0] = 285
    pack = dict(build=build, ability_profiles={'Pantheon':{'R':archived}})
    fp = digest(pack)
    key = 'combat_' + fp
    frame['task']['combat_reference'] = key
    frame['references'][key] = dict(kind='combat_catalog_for_player', content_sha256=fp)
    raw['reference_library'][key] = pack
    freeze(raw)
    looked_up = set()

    def record_lookup(build, champion, slot):
        looked_up.add(champion)
        return damage_profile(build, champion, slot)

    monkeypatch.setattr(ability_damage_data, 'damage_profile', record_lookup)
    selected = session_damage_profiles([raw])
    assert 'Pantheon' not in looked_up and 'Jhin' in looked_up
    assert selected['champions']['Pantheon'] == {'R':archived}
    assert session_damage_profiles([raw], original)['champions']['Pantheon']['R'] != archived
    current = bind_round(raw, 'jungle', 'dragon', 5, upgrade_legacy=True, damage_profiles=selected)
    assert round_call(current, 'get_ability_parameters', dict(champion='Pantheon', slot='Q'))['reviewed_damage'] is None
    assert round_call(current, 'get_ability_parameters', dict(champion='Pantheon', slot='R'))['reviewed_damage'] == archived


def test_tampered_damage_reference_and_wrong_patch():
    active = pantheon_frame()
    params = round_call(active,'get_ability_parameters',dict(champion='Pantheon',slot='R'))
    assert params['reviewed_damage']['range_by_rank'] == [5500]*3
    active['reference_library'][active['frame']['task'][REF_KEY]]['build']='new'
    with pytest.raises(ValueError,match='changed'):
        round_call(active,'get_ability_parameters',dict(champion='Pantheon',slot='R'))
    other = pantheon_frame('16.21.1')
    assert REF_KEY not in other['frame']['task']
    assert calculate(other,['R.landing_center'])['damage'] is None


def test_only_hypothetical_stats_yield_a_number_in_synthetic_frame():
    bundle = pantheon_frame()
    original = deepcopy(bundle)
    assert calculate(bundle,['R.landing_center'])['damage']['raw_total'] is None
    scenario = dict(ranks={'R':1},ap=0,effective_magic_resist=50)
    centre = calculate(bundle,['R.landing_center'],scenario)
    edge = calculate(bundle,['R.landing_edge'],scenario)
    assert (centre['damage']['raw_total'],centre['damage']['after_resistance_total']) == (300,200)
    assert edge['damage']['after_resistance_total'] == 100
    assert centre['assumptions'] == scenario and centre['observed_health_loss'] is None
    assert bundle == original


def test_mixed_spear_and_landing_require_two_ranks_and_two_resistances():
    bundle = pantheon_frame()
    scenario = dict(ranks={'Q':1,'R':1},bonus_ad=0,ap=0,effective_armor=100,effective_magic_resist=50)
    result=calculate(bundle,['R.spear','R.landing_center'],scenario)['damage']
    assert result['after_resistance_total']==235
    del scenario['effective_armor']
    missing=calculate(bundle,['R.spear','R.landing_center'],scenario)['damage']
    assert missing['after_resistance_total'] is None and missing['parts'][1]['after_resistance']==200


def test_display_derived_interval_propagates_without_replacing_exact_or_unknown_fields(monkeypatch):
    from lol_coach.combat_inputs import combat_inputs

    bundle = pantheon_frame()
    observed = combat_inputs(bundle, 'enemy')
    observed['ranks'].update(Q=3, R=1)
    observed['stats']['ability_power'] = 0
    observed['estimates'] = {'bonus_attack_damage': {'lower': 49.5, 'upper': 50.5}}
    monkeypatch.setattr('lol_coach.review_abilities.combat_inputs', lambda *_: observed)
    hits = ['R.spear', 'R.landing_center']
    result = calculate(bundle, hits, {'effective_magic_resist': 50})
    assert result['damage']['raw_total'] is None
    assert result['estimated_damage']['raw_total_interval'] == pytest.approx([486.925, 488.075])
    assert result['estimated_damage']['after_resistance_total_interval'] is None
    assert result['estimated_damage']['parts'][1]['after_resistance_interval'] == [200, 200]
    resist = {'effective_magic_resist': 50, 'effective_armor': 100}
    total = calculate(bundle, hits, resist)['estimated_damage']['after_resistance_total_interval']
    assert total == pytest.approx([293.4625, 294.0375])
    explicit = calculate(bundle, hits, {**resist, 'bonus_ad': 25})
    assert explicit['estimated_damage'] is None and explicit['damage']['after_resistance_total'] is not None
    observed['ranks']['Q'] = 0
    assert calculate(bundle, hits)['missing_formula_inputs']['R.spear'] == ['rank_Q', 'bonus_ad']
    observed['ranks']['R'] = 0
    assert calculate(bundle, hits)['status'] == 'unlearned_spell'


@pytest.mark.parametrize('hits,assumptions,target',[
    (['R.landing_center','R.landing_edge'],{},'enemy'),
    (['R.landing_center','R.landing_center'],{},'enemy'),
    (['R.landing_center'],{},'ally'),
    (['R.landing_center'],{'ranks':{'R':True}},'enemy'),
    (['R.landing_center'],{'at_seconds':999},'enemy'),
    (['R.landing_center'],{'effective_magic_resist':float('nan')},'enemy'),
])
def test_invalid_or_cross_scope_damage_queries_fail(hits,assumptions,target):
    with pytest.raises(ValueError):
        calculate(pantheon_frame(),hits,assumptions,target)
