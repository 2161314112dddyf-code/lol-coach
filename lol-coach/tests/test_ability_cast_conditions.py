import pytest

from lol_coach.reasoning_frame import digest
from lol_coach.round_tools import ROUND_TOOLS
from test_review_abilities import calculate, pantheon_frame
from test_round_chain import freeze


def frame_with_visibility(visible):
    bundle = pantheon_frame()
    frame = bundle['frame']
    enemy = next(hero for hero in frame['lineup'] if hero['entity_id'] == 'enemy')
    fact = dict(entity_id='enemy', field='visibility', value=visible,
                observed_at_seconds=448, temporal_scope='known_state')
    fid = 'f_' + digest(fact)[:20]
    frame['facts'][fid] = fact
    enemy['current_fact_ids'].append(fid)
    return freeze(bundle)


@pytest.mark.parametrize('visible, selectable', [(False, False), (None, None), (True, None)])
def test_w_counterfactual_keeps_target_visibility_separate_from_cast_range(visible, selectable):
    assumptions = dict(ranks={'W':1}, ap=0, bonus_health=100, target_max_health=1500, effective_armor=100)
    result = calculate(frame_with_visibility(visible), ['W.vault'], assumptions)
    targeting = result['targeting']
    assert result['target_team_visible'] is visible
    assert targeting['requires_visible_unit'] is True and targeting['can_select_for_w_now'] is selectable
    assert targeting['in_cast_range_now'] is None
    assert targeting['tooltip_key'] == 'Spell_PantheonW_Tooltip'
    assert result['damage']['after_resistance_total'] == pytest.approx(48)
    assert result['observed_health_loss'] is None


def test_nonpositive_maximum_health_rejected_by_calculator_and_mcp_schema():
    tool = next(item['function'] for item in ROUND_TOOLS if item['function']['name'] == 'calculate_ability_damage')
    assert tool['parameters']['properties']['assumptions']['properties']['target_max_health'] == {
        'type':'number', 'exclusiveMinimum':0}
    for invalid in (-1, 0):
        with pytest.raises(ValueError):
            calculate(pantheon_frame(), ['W.vault'], {'target_max_health':invalid})


@pytest.mark.parametrize('hits', [
    ['R.landing_center', 'Q.tap'], ['Q.throw_secondary', 'R.landing_edge'], ['R.spear', 'Q.throw_first'],
])
def test_r_with_an_ordinary_q_explains_passive_and_the_scope_of_the_sum(hits):
    assumptions = dict(ranks={'R':1,'Q':1}, ap=0, bonus_ad=0, effective_armor=0, effective_magic_resist=0)
    assumptions['pre_hit_health_fractions'] = {key:.75 for key in hits}
    result = calculate(frame_with_visibility(False), hits, assumptions)
    assert result['damage']['after_resistance_total'] > 0
    assert result['cast_sequence']['immediate_normal_q_after_r'] == 'unsupported_empowered_q'
    assert result['cast_sequence']['tooltip_key'] == 'Spell_PantheonRJump_Tooltip'
    assert '先耗掉强化' in result['cast_sequence']['condition']
    assert 'targeting' not in result


def test_two_hits_of_r_are_not_a_followup_q_cast():
    result = calculate(pantheon_frame(), ['R.spear', 'R.landing_center'])
    assert 'cast_sequence' not in result and 'targeting' not in result
