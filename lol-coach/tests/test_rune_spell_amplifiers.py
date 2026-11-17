"""Synthetic, legal Pantheon pages; spell tags and parameters come from the frozen native build."""
import pytest

from lol_coach.damage_scenario import rune_damage, validate_scenario
from lol_coach.rune_damage_data import BUILD, rune_damage_profile


def evaluate(perks, label='R.landing_center', champion='Pantheon', **values):
    pack = dict(build=BUILD, rune_rules=rune_damage_profile(BUILD))
    page = dict(perk_ids=perks, shard_ids=[5008,5008,5013], primary_style_id=8000,
                secondary_style_id=8200 if 8224 in perks else 8300)
    validate_scenario(values,{label})
    part = dict(label=label, damage_type='physical' if label in ('R.spear','Q.tap') else 'magic', raw_damage=300)
    return rune_damage(page, pack, [part], {}, {'effective_magic_resist':50,'effective_armor':50},
                       values, 6, {'ap':0,'bonus_ad':10}, champion=champion)


@pytest.mark.parametrize('fraction,expected', [
    (1, [200,200]), (.6,[200,200]), (.599,[210,222]), (.30,[222,222]), (.20,[222,222]),
    (None,[200,222])])
def test_last_stand_does_not_invent_intermediate_health_curve(fraction, expected):
    values = {} if fraction is None else {'pre_hit_caster_health_fractions':{'R.landing_center':fraction}}
    result = evaluate([8010,9111,9104,8299,8304,8347], **values)
    assert result['after_resistance_total_interval'] == pytest.approx(expected)


def test_axiom_distinguishes_landing_spear_and_basic_spell():
    perks = [8010,9111,9104,8014,8224,8210]
    for label,expected in [('R.landing_center',216),('R.landing_edge',216),('Q.tap',200)]:
        result = evaluate(perks,label,target_health_fraction=1)
        assert result['after_resistance_total'] == pytest.approx(expected)
    for label, champion in [('R.spear','Pantheon'),('R.landing_center','Darius')]:
        result = evaluate(perks,label,champion=champion,target_health_fraction=1)
        assert result['after_resistance_total'] is None
        assert result['blockers'] == ['ultimate_component_damage_tag_unreviewed:' + label]
    overlap = evaluate(perks, target_health_fraction=.1)
    assert overlap['blockers'] == ['stacking_ultimate_and_health_amplifiers_unreviewed:R.landing_center']


def test_last_stand_rejects_health_from_different_hit():
    with pytest.raises(ValueError, match='invalid_pre_hit_caster_health_fractions'):
        validate_scenario({'pre_hit_caster_health_fractions':{'Q.tap':.2}}, {'R.landing_center'})
