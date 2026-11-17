import pytest

from lol_coach.ability_damage_data import damage_profile
from lol_coach.review_abilities import _component_at_health
from test_review_abilities import calculate
from test_rune_damage_scenario import BUILD, PAGE, real_page_fixture


BASE = dict(ranks={'Q':1}, ap=0, bonus_ad=20, effective_armor=100)


@pytest.mark.parametrize('component,fraction,raw', [
    ('tap', .2, 93), ('tap', .1999999, 201), ('throw_first', .200001, 93),
    ('throw_first', .19, 201), ('throw_secondary', .19, 100.5), ('throw_secondary', .2, 46.5),
])
def test_q_branches_and_resistance(component, fraction, raw):
    label = 'Q.' + component
    out = calculate(real_page_fixture(), [label], {**BASE, 'target_health_fraction': fraction})
    assert out['damage']['raw_total'] == pytest.approx(raw)
    assert out['damage']['after_resistance_total'] == pytest.approx(raw / 2)
    assert out['rune_damage']['after_resistance_total'] == pytest.approx(raw * 1.08 / 2)
    assert out['spell_health_branches'][label]['branch'] == ('below' if fraction < .2 else 'at_or_above')
    assert out['observed_health_loss'] is None


def test_q_unknown_health_only_reports_ranges_and_keeps_coup_and_cut_down_reachable(monkeypatch):
    bundle = real_page_fixture()
    base = calculate(bundle, ['Q.tap'], BASE)
    assert base['damage']['raw_total'] is None
    assert base['estimated_damage']['raw_total_interval'] == pytest.approx([93, 201])
    runes = base['rune_damage']
    assert runes['after_resistance_total'] is None
    assert runes['after_resistance_total_interval'] == pytest.approx([93/2, 201*1.08/2])
    cut = dict(PAGE, perk_ids=[8010,9111,9104,8017,8304,8347])
    monkeypatch.setattr('lol_coach.replay_runes.player_runes', lambda _:cut)
    runes = calculate(bundle, ['Q.tap'], BASE)['rune_damage']
    # The Q execute and Cut Down cannot both apply to the same hit.
    assert runes['raw_total_interval'] == pytest.approx([93, 201])
    branches = runes['parts'][0]['health_branches']
    assert branches['below']['raw_interval'] == pytest.approx([201,201])
    assert branches['at_or_above']['raw_interval'] == pytest.approx([93,93*1.08])


def test_shield_is_not_target_health_and_thrown_low_ap_is_unreviewed():
    bundle = real_page_fixture()
    shield = dict(target_max_health=1000, shield_scenario={'health_before':190,'universal_shield':700})
    out = calculate(bundle, ['Q.tap'], {**BASE, **shield, 'ap':400})
    assert out['damage']['raw_total'] == pytest.approx(201)
    assert out['rune_damage']['conditional_hp_loss_interval'] == [0,0]
    for fraction in (None, .19, .2):
        args = {**BASE, 'ap':400}
        if fraction is not None:
            args['target_health_fraction'] = fraction
        out = calculate(bundle, ['Q.throw_first'], args)
        if fraction == .2:
            assert out['damage']['raw_total'] == pytest.approx(293)
        else:
            assert 'unverified_low_health_throw_ap_ratio' in out['missing_formula_inputs']['Q.throw_first']
            assert out['rune_damage']['raw_total_interval'] is None


def test_q_and_r_spear_select_their_own_formula_and_health():
    out = calculate(real_page_fixture(), ['Q.tap','R.spear'], {**BASE, 'ranks':{'Q':1,'R':1},
        'pre_hit_health_fractions':{'Q.tap':.15, 'R.spear':.15}})
    assert [p['raw_damage'] for p in out['damage']['parts']] == pytest.approx([201,93])
    assert set(out['spell_health_branches']) == {'Q.tap'}
    assert 'HoldDamageCalc' in out['hit_conditions']['R.spear']
    assert '独立证据' in out['hit_conditions']['R.spear']


def test_display_uncertainty_against_all_rank_five_branches_and_old_profile():
    profile = damage_profile(BUILD, 'Pantheon', 'Q')
    evidence = dict(lower=19.5, upper=20.5)
    hit, interval, state = _component_at_health(profile, 'throw_secondary', {'Q':5}, {'ap':0}, evidence, None)
    assert hit['raw_damage'] is None
    assert interval == pytest.approx([(190+1.15*19.5)/2,(455+2.3*20.5)/2])
    assert state['raw_intervals']['below'] == pytest.approx([(455+2.3*x)/2 for x in (19.5,20.5)])
    del profile['low_health_rule']
    hit, interval, _ = _component_at_health(profile,'tap',{'Q':5},{'ap':0,'bonus_ad':100},None,.1)
    assert hit['raw_damage'] is None and interval is None
    assert 'low_health_rule_not_in_frozen_profile' in hit['missing']
