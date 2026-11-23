"""Synthetic query/receipt binding; no model judgement is asserted."""
from copy import deepcopy
import pytest
from lol_coach.calculation_receipts import damage_receipts, render_damage_receipts


def fixture():
    args=dict(target_id='enemy',hits=[dict(slot='R',component='landing_center')],
              assumptions=dict(shield_scenario=dict(health_before=700,universal_shield=100)))
    query=dict(id='q1',name='calculate_ability_damage',arguments=args)
    value=dict(frame_id='f1',target_id='enemy',target='Jhin',hits=args['hits'],assumptions=args['assumptions'],
               rune_damage=dict(after_resistance_total_interval=[200,250],conditional_hp_loss_interval=[100,150]))
    return dict(frame=dict(frame_id='f1')),dict(trace=[dict(event='model_response',response=dict(tool_requests=[query])),
        dict(event='tool_results',results=[dict(id='q1',name=query['name'],content=value)])])


def test_rendered_health_is_calculated_from_the_receipt_not_model_text():
    bundle,result=fixture();before=deepcopy(result)
    receipts=damage_receipts(bundle,result)
    assert receipts[0]['conditional_health_remaining_interval']==[550,600]
    assert '550.00～600.00' in render_damage_receipts(receipts) and result==before


@pytest.mark.parametrize('key,value',[('frame_id','other'),('target_id','other'),('assumptions',{})])
def test_cannot_borrow_another_frames_target_or_hypothesis(key,value):
    bundle,result=fixture()
    result['trace'][1]['results'][0]['content'][key]=value
    with pytest.raises(ValueError,match='match'):
        damage_receipts(bundle,result)


def test_missing_hp_inputs_stay_unknown():
    bundle,result=fixture()
    result['trace'][1]['results'][0]['content']['rune_damage'].pop('conditional_hp_loss_interval')
    assert damage_receipts(bundle,result)[0]['conditional_health_remaining_interval'] is None
