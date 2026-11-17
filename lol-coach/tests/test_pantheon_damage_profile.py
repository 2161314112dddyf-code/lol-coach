import pytest

from lol_coach.ability_damage_data import damage_profile, raw_component


BUILD = '16.22.836.1077'


def test_ultimate_distinguishes_physical_spear_and_exclusive_magic_zones():
    profile = damage_profile(BUILD, 'Pantheon', 'R')
    ranks, stats = {'R': 1, 'Q': 3}, {'bonus_ad': 50, 'ap': 40}
    center, edge, spear = [raw_component(profile, c, ranks, stats)
                           for c in ('landing_center', 'landing_edge', 'spear')]
    assert profile['range_by_rank'] == [5500]*3
    assert profile['mutually_exclusive'] == [['landing_center', 'landing_edge']]
    assert (center['raw_damage'], edge['raw_damage']) == (340, 170)
    assert center['damage_type'] == edge['damage_type'] == 'magic'
    assert spear['damage_type'] == 'physical'
    assert spear['raw_damage'] == pytest.approx(130 + 50 * 1.15 + 40 * .5)


def test_wrong_build_unknown_rank_or_stat_never_substitutes_a_guess():
    assert damage_profile('16.22.1', 'Pantheon', 'R') is None
    assert damage_profile(BUILD, 'Pantheon', 'E') is None
    assert damage_profile(BUILD, 'Leona', 'R') is None
    p = damage_profile(BUILD, 'Pantheon', 'R')
    miss = raw_component(p, 'spear', {'R': 1}, {'ap': 0})
    assert set(miss['missing']) == {'bonus_ad', 'rank_Q'} and miss['raw_damage'] is None
    for bad in (0, 4, 1.0, True):
        with pytest.raises(ValueError):
            raw_component(p, 'landing_center', {'R':bad}, {'ap':0})
    for bad in (True, float('nan'), float('inf')):
        with pytest.raises(ValueError):
            raw_component(p, 'landing_edge', {'R':3}, {'ap':bad})


def test_q_and_w_hit_conditions_are_distinct_and_w_scales_with_target_hp():
    q, w = [damage_profile(BUILD,'Pantheon',s) for s in 'QW']
    stats = {'ap':100, 'bonus_ad':40, 'bonus_health':500, 'target_max_health':2000}
    ranks = {'Q':1,'W':1}
    assert raw_component(q,'tap',ranks,stats)['raw_damage'] == pytest.approx(116)
    assert raw_component(q,'throw_first',ranks,stats)['raw_damage'] == pytest.approx(166)
    assert raw_component(q,'throw_secondary',ranks,stats)['raw_damage'] == pytest.approx(83)
    assert raw_component(w,'vault',ranks,stats)['raw_damage'] == pytest.approx(190)
    assert raw_component(w,'vault',ranks,{'ap':100})['raw_damage'] is None


def test_caller_cannot_mutate_the_stored_profile():
    damage_profile(BUILD,'Pantheon','R')['components'].clear()
    assert len(damage_profile(BUILD,'Pantheon','R')['components']) == 3
