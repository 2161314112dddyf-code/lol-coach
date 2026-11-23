"""Optional handbook questions are routed by visible events in this personal frame."""
from copy import deepcopy

import pytest

from lol_coach.coaching_knowledge import attach_handbook
from test_round_chain import bundle_at, freeze


def attached_task(bundle):
    return attach_handbook(freeze(bundle))['frame']['task']['knowledge_handbook']


@pytest.mark.parametrize(('reason', 'reference'), [
    ('new_personal_team_signal', 'knowledge:K15'),
    ('nearby_ally_request_delivered', 'knowledge:K15'),
    ('new_local_opponent_affects_ally', 'knowledge:K23'),
    ('local_ally_death_became_known', 'knowledge:K10'),
])
def test_only_matching_question_is_offered_for_an_active_trigger(reason, reference):
    bundle = bundle_at(10)
    frame = bundle['frame']
    frame['task']['team_coordination_trigger'] = dict(active=True, reasons=[reason], fact_ids=['gold'])
    guidance = attached_task(bundle)['decision_guidance']
    assert [item['reference_id'] for item in guidance] == [reference]
    assert guidance[0]['fact_refs'] == ['gold']
    assert guidance[0]['fact_scope'] == 'combined_team_trigger_evidence'
    frame['task']['team_coordination_trigger']['active'] = False
    assert attached_task(bundle)['decision_guidance'] == []


def test_personal_kill_must_be_known_recent_and_personal():
    bundle = bundle_at(10)
    frame = bundle['frame']
    frame['recent_public_combat_ids'] = ['missing', 'kill']
    row = dict(field='public_kill_feed', entity_id='enemy', temporal_scope='historical_event_not_current_death_state',
               observed_at_seconds=9, available_at_seconds=10,
               value={'killer_entity_id': 'self', 'victim_entity_id': 'enemy'})
    frame['facts']['kill'] = row
    item, = attached_task(bundle)['decision_guidance']
    assert (item['reference_id'], item['fact_refs']) == ('knowledge:K01', ['kill'])
    frame['facts']['kill'] = {**row, 'available_at_seconds': 11}
    with pytest.raises(ValueError, match='future_or_invalid_fact_time'):
        attached_task(bundle)
    for patch in (dict(observed_at_seconds=1),
                  dict(value={'killer_entity_id': 'ally', 'victim_entity_id': 'enemy'}),
                  dict(value=None)):
        frame['facts']['kill'] = {**row, **patch}
        assert attached_task(bundle)['decision_guidance'] == []

    frame['facts']['kill'] = row
    frame['facts']['state'] = dict(field='personal_client_state', entity_id='self',
        observed_at_seconds=10, temporal_scope='personal_native_observation', value={'is_dead': True})
    frame['task']['team_coordination_trigger'] = dict(active=True, reasons=['new_personal_team_signal'],
                                                      fact_ids=['gold'])
    assert attached_task(bundle)['decision_guidance'] == []


def test_all_cards_remain_available_even_when_the_agent_receives_no_question():
    bundle = attach_handbook(bundle_at(10))
    frame = bundle['frame']
    handbook = frame['task']['knowledge_handbook']
    assert not handbook['decision_guidance']
    modes = {rid: frame['references'][rid]['use_mode'] for rid in handbook['reference_ids']}
    assert len(modes) == 24
    assert {rid for rid, mode in modes.items() if mode != 'context'} == {
        'knowledge:K01', 'knowledge:K10', 'knowledge:K15', 'knowledge:K23'}
    # Preserve earlier frozen envelopes, including the absence of a routing policy.
    legacy = deepcopy(bundle)
    del legacy['frame']['task']['knowledge_handbook']['decision_guidance']
    freeze(legacy)
    assert attach_handbook(legacy) == legacy
