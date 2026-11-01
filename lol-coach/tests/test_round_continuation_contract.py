"""Synthetic continuation contracts; passing does not validate tactical quality."""
from copy import deepcopy

import pytest

from lol_coach.decision_contract import output_schema, render_decision, validate_decision


def frame(previous=True):
    result = dict(schema='decision-frame/v1', frame_id='frame-20',
        decision=dict(at_seconds=20, player_entity_id='self', observer_team_id=100),
        lineup=[dict(entity_id='self', relation='ally')], references={}, calculations={},
        facts={'f_tower_hp': dict(value=0, observed_at_seconds=19),
               'f_lane': dict(value={'front_ranged': 3, 'rear_siege': 1}, observed_at_seconds=20)})
    if previous:
        result['task'] = dict(previous_plan=dict(previous_frame_id='frame-10',
            historical_facts={'h_tower_hp': dict(value=100, observed_at_seconds=10)}),
            round_transition=dict(changes={'c_tower_hp': dict(current_fact_id='f_tower_hp'),
                                           'c_lane': dict(current_fact_id='f_lane')}))
    return result


def answer(disposition='retain', continuation=True):
    def option(oid):
        return dict(id=oid, action='synthetic action '+oid, status='conditional',
            fact_refs=['f_lane'], reference_refs=[], preconditions=['Confirm hero safety'],
            ally_requirements=[], enemy_responses=['Opponent may contest'],
            time_budget=dict(travel_seconds=None, execution_seconds=None,
                             exit_seconds=None, window_seconds=None, calculation_refs=[]),
            gains=['Retain position'], costs=['Opportunity cost'], end_state='Reassess',
            abort_signals=['Opponent arrives'], assumptions=[])
    result = dict(schema='round-decision/v1', frame_id='frame-20', objective='Synthetic handoff',
        facts_used=[dict(fact_id='f_tower_hp', value=0),
                    dict(fact_id='f_lane', value={'front_ranged': 3, 'rear_siege': 1})],
        role_assignments=[dict(actor_id='self', role='Reassess frontline', fact_refs=['f_lane'], assumptions=[])],
        options=[option('a'), option('b')],
        recommendation=dict(preferred_option_id='a', fallback_option_id='b',
                            confidence='conditional', why='Current facts support a conditional choice',
                            switch_conditions=['Reassess on enemy arrival']), open_questions=['Hero safety'])
    if continuation:
        result['continuation'] = dict(previous_frame_id='frame-10', disposition=disposition,
            previous_action_execution='unknown', reason='Use current tower and lane evidence',
            current_fact_refs=['f_tower_hp', 'f_lane'],
            change_refs=[] if disposition == 'retain' else ['c_tower_hp'])
    return result


def assert_failure(a, f, path):
    checked = validate_decision(a, f)
    assert checked['status'] == 'FAIL'
    assert any(error['path'].startswith(path) for error in checked['errors'])


def test_schema_optional_root_but_strict_continuation_fields_and_fresh_copies():
    schema = output_schema()
    assert 'continuation' not in schema['required']
    continuation = schema['properties']['continuation']
    assert continuation['additionalProperties'] is False
    assert set(continuation['required']) == set(continuation['properties'])
    assert continuation['properties']['previous_action_execution']['enum'] == ['unknown']
    assert continuation['properties']['current_fact_refs']['minItems'] == 1
    continuation['properties']['disposition']['enum'].append('invented')
    assert 'invented' not in output_schema()['properties']['continuation']['properties']['disposition']['enum']


@pytest.mark.parametrize('disposition', ['retain', 'revise', 'cancel'])
def test_valid_continuation_references_current_values_and_does_not_claim_execution(disposition):
    a, f = answer(disposition), frame()
    original = deepcopy((a, f))
    checked = validate_decision(a, f)
    assert checked['status'] == 'PASS'
    assert checked['tactical_quality'] == 'not_evaluated'
    assert (a, f) == original
    rendered = render_decision(a, checked)
    assert {'retain': '保留', 'revise': '改选', 'cancel': '取消'}[disposition] in rendered
    assert a['continuation']['reason'] in rendered
    assert '上一行动执行：未知' in rendered
    assert '先前建议不等于已经执行' in rendered
    assert 'frame-10' in rendered


@pytest.mark.parametrize('task', [None, {}, {'previous_plan': None}])
def test_old_standalone_answer_remains_valid(task):
    f = frame(False)
    if task is not None:
        f['task'] = task
    a = answer(continuation=False)
    checked = validate_decision(a, f)
    assert checked['status'] == 'PASS'
    assert '上一计划承接' not in render_decision(a, checked)


@pytest.mark.parametrize('task', [None, {}, {'previous_plan': None}])
def test_standalone_answer_cannot_invent_previous_plan(task):
    f = frame(False)
    if task is not None:
        f['task'] = task
    assert_failure(answer(), f, '$.continuation')


def test_previous_plan_requires_continuation():
    assert_failure(answer(continuation=False), frame(), '$.continuation')


def test_previous_frame_id_must_match_bound_plan():
    a = answer()
    a['continuation']['previous_frame_id'] = 'another-frame'
    assert_failure(a, frame(), '$.continuation.previous_frame_id')


@pytest.mark.parametrize('execution', ['completed', 'in_progress', 'not_started', True, None])
def test_suggestions_cannot_be_upgraded_to_observed_execution(execution):
    a = answer()
    a['continuation']['previous_action_execution'] = execution
    assert_failure(a, frame(), '$.continuation.previous_action_execution')


@pytest.mark.parametrize('field', ['previous_frame_id', 'disposition', 'previous_action_execution',
                                  'reason', 'current_fact_refs', 'change_refs'])
def test_all_continuation_fields_required_when_present(field):
    a = answer()
    del a['continuation'][field]
    assert_failure(a, frame(), '$.continuation.'+field)


@pytest.mark.parametrize('refs', [[], ['missing'], ['h_tower_hp']])
def test_current_fact_refs_must_be_nonempty_and_current(refs):
    a = answer()
    a['continuation']['current_fact_refs'] = refs
    assert_failure(a, frame(), '$.continuation.current_fact_refs')


def test_current_continuation_refs_must_also_be_value_checked_in_facts_used():
    a = answer()
    a['facts_used'] = [a['facts_used'][1]]
    assert_failure(a, frame(), '$.continuation.current_fact_refs')


@pytest.mark.parametrize('disposition', ['revise', 'cancel'])
def test_revision_and_cancellation_require_change_witness(disposition):
    a = answer(disposition)
    a['continuation']['change_refs'] = []
    assert_failure(a, frame(), '$.continuation.change_refs')


def test_even_retention_cannot_cite_unknown_changes():
    a = answer()
    a['continuation']['change_refs'] = ['invented-change']
    assert_failure(a, frame(), '$.continuation.change_refs')


def test_change_current_fact_must_be_in_current_refs_not_only_facts_used():
    a = answer('revise')
    a['continuation']['current_fact_refs'] = ['f_lane']
    assert_failure(a, frame(), '$.continuation.change_refs')


def test_multiple_changes_each_require_their_current_fact():
    a = answer('revise')
    a['continuation']['change_refs'] = ['c_tower_hp', 'c_lane']
    assert validate_decision(a, frame())['status'] == 'PASS'
    a['continuation']['current_fact_refs'] = ['f_tower_hp']
    assert_failure(a, frame(), '$.continuation.change_refs[1]')


def test_historical_id_stays_forbidden_even_if_incorrectly_injected_into_current_facts():
    a, f = answer(), frame()
    f['facts']['h_tower_hp'] = dict(value=100, observed_at_seconds=10)
    a['facts_used'].append(dict(fact_id='h_tower_hp', value=100))
    a['continuation']['current_fact_refs'] = ['h_tower_hp']
    assert_failure(a, f, '$.facts_used')
    assert_failure(a, f, '$.continuation.current_fact_refs')


def test_history_cannot_be_used_in_other_current_reference_fields():
    a = answer()
    a['options'][0]['fact_refs'] = ['h_tower_hp']
    assert_failure(a, frame(), '$.options[0].fact_refs')


def test_future_current_fact_and_tampered_values_remain_rejected():
    a, f = answer('cancel'), frame()
    f['facts']['f_tower_hp']['available_at_seconds'] = 21
    assert_failure(a, f, '$.continuation.current_fact_refs')
    f = frame()
    a['facts_used'][0]['value'] = 100
    assert_failure(a, f, '$.facts_used[0].value')


@pytest.mark.parametrize('change', [None, {}, {'current_fact_id': 'missing'}, {'current_fact_id': 'h_tower_hp'}])
def test_malformed_change_cannot_supply_evidence(change):
    f = frame()
    f['task']['round_transition']['changes']['c_tower_hp'] = change
    assert_failure(answer('cancel'), f, '$.continuation.change_refs')


@pytest.mark.parametrize('previous', ['not-object', {}, {'previous_frame_id': None}])
def test_malformed_previous_plan_fails_without_crashing(previous):
    f = frame()
    f['task']['previous_plan'] = previous
    assert_failure(answer(), f, 'frame.task.previous_plan')


def test_strict_object_rejects_extra_field_empty_reason_and_unknown_disposition():
    for change in ({'executed': True}, {'reason': ' '}, {'disposition': 'continue_anyway'}):
        a = answer()
        a['continuation'].update(change)
        assert_failure(a, frame(), '$.continuation')


def test_rendered_continuation_must_match_validated_answer_hash():
    a = answer('revise')
    checked = validate_decision(a, frame())
    a['continuation']['reason'] = 'Changed after validation'
    assert '分析输出未通过检查' in render_decision(a, checked)
