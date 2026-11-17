import pytest

from lol_coach.rune_damage_data import BUILD, rune_damage_profile


def test_actual_red_jungle_loadout_each_slot_has_a_reviewed_effect():
    profile = rune_damage_profile(BUILD)
    rules = profile['rules']
    loadout = [8010, 9111, 9104, 8014, 8304, 8347, 5008, 5008, 5013]
    assert all(str(slot) in rules for slot in loadout)
    assert rules['8010']['adaptive_force_per_stack_endpoints'] == [1.8, 4.0]
    assert rules['8010']['max_stacks'] == 12 and rules['8010']['duration_seconds'] == 5
    assert rules['8014']['target_health_fraction_below'] == 0.4
    assert rules['8014']['multiplier'] == 1.08
    assert rules['5008']['kind'] == 'no_separate_spell_hit'
    assert rules['5008']['parameters']['StatGain2'] == 9.0
    assert len({r['record'] for r in rules.values()}) == len(rules)
    assert all(len(r['tooltip_sha256']) == 64 for r in rules.values())
    assert all(len(s['sha256']) == 64 for s in profile['sources'])


@pytest.mark.parametrize('rune,level_1,level_18,cooldown', [
    ('8112', 70, 240, 20), ('8126', 10, 45, 4), ('8237', 20, 40, 10)])
def test_exact_client_proc_endpoint_and_default_linear_curve(rune, level_1, level_18, cooldown):
    row = rune_damage_profile(BUILD)['rules'][rune]
    values = row['damage_by_level']
    assert len(values) == 18 and values[0] == level_1 and values[-1] == level_18
    assert values[5] == pytest.approx(level_1 + 5*(level_18-level_1)/17)
    assert row['cooldown_seconds'] == cooldown


def test_patch_scope_immutable_and_electrocute_trigger_scales():
    assert rune_damage_profile('16.22.1') is None
    rules = rune_damage_profile(BUILD)['rules']
    assert rules['8237']['delay_seconds'] == 1
    proc = rules['8112']
    assert (proc['required_distinct_attacks_or_abilities'], proc['window_seconds']) == (3, 3)
    assert (proc['bonus_ad_ratio'], proc['ap_ratio']) == (.10, .05)
    proc.clear()
    assert rune_damage_profile(BUILD)['rules']['8112']['cooldown_seconds'] == 20


def test_extreme_health_amplifiers_and_souls_have_distinct_triggers():
    rows = rune_damage_profile(BUILD)['rules']
    assert rows['8017']['target_health_fraction_above'] == .6 and rows['8017']['multiplier'] == 1.08
    harvest = rows['8128']
    assert (harvest['target_health_fraction_below'], harvest['base_damage'], harvest['damage_per_soul']) == (.5, 30, 11)
    assert (harvest['takedown_reset_seconds'], harvest['cooldown_seconds']) == (1, 35)
    assert rows['8224']['display_name'] == 'Axiom Arcanist'
    assert rows['8224']['kind'] == 'ultimate_amplifier'
    assert (rows['8224']['single_target_bonus'], rows['8224']['aoe_bonus']) == (.12, .08)
    assert (rows['8229']['max_distance'], rows['8229']['max_bonus']) == (750, 1)
    for rune in ('8229', '8005', '8369', '8473', '8299'):
        assert rows[rune]['unreviewed']
