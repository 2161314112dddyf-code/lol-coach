"""Synthetic contract tests. Passing does not validate LoL tactics."""
from copy import deepcopy
import math

import pytest

from lol_coach.decision_contract import output_schema, render_decision, validate_decision


def frame_fixture():
    return {
        'schema': 'decision-frame/v1', 'frame_id': 'synthetic-frame',
        'decision': {'at_seconds': 10, 'player_entity_id': 'self',
                     'observer_team_id': 100, 'build': 'synthetic'},
        'lineup': [{'entity_id': 'self', 'champion': 'A', 'relation': 'ally'},
                   {'entity_id': 'ally', 'champion': 'B', 'relation': 'ally'},
                   {'entity_id': 'enemy', 'champion': 'C', 'relation': 'enemy'}],
        'facts': {'gold': {'entity_id': 'self', 'field': 'current_gold', 'value': 100,
                           'observed_at_seconds': 9, 'temporal_scope': 'observed_sample'},
                  'ally_hp': {'entity_id': 'ally', 'field': 'health', 'value': 0,
                              'observed_at_seconds': 8, 'temporal_scope': 'observed_sample'},
                  'enemy_hp': {'entity_id': 'enemy', 'field': 'health', 'value': 50,
                               'observed_at_seconds': 8, 'temporal_scope': 'last_seen'}},
        'references': {'rule1': {'kind': 'conditional_experience'}}, 'calculations': {},
    }


def answer_fixture():
    def option(oid):
        return {'id': oid, 'action': '合成动作 ' + oid, 'status': 'conditional',
                'fact_refs': ['gold'], 'reference_refs': ['rule1'],
                'preconditions': ['需确认安全路线'],
                'ally_requirements': [{'actor_id': 'ally', 'required_action': '跟进',
                                       'status': 'unknown', 'fact_refs': ['ally_hp']}],
                'enemy_responses': ['对手可能移动'],
                'time_budget': {'travel_seconds': None, 'execution_seconds': None,
                                'exit_seconds': None, 'window_seconds': None,
                                'calculation_refs': []},
                'gains': ['争取位置'], 'costs': ['放弃当前资源'],
                'end_state': '需要重新判断', 'abort_signals': ['队友未到'],
                'assumptions': []}
    return {'schema': 'round-decision/v1', 'frame_id': 'synthetic-frame',
            'objective': '检验条件决策结构',
            'facts_used': [{'fact_id': 'gold', 'value': 100}],
            'role_assignments': [
                {'actor_id': actor, 'role': 'unknown', 'fact_refs': [], 'assumptions': []}
                for actor in ['self', 'ally', 'enemy']],
            'options': [option('a'), option('b')],
            'recommendation': {'preferred_option_id': 'a', 'fallback_option_id': 'b',
                               'confidence': 'conditional', 'why': '条件成立才行动',
                               'switch_conditions': ['看到敌人就重评']},
            'open_questions': ['路线是否安全']}


def check(change=None, frame_change=None):
    answer = answer_fixture(); frame = frame_fixture()
    if change:
        change(answer)
    if frame_change:
        frame_change(frame)
    return validate_decision(answer, frame)


def test_conditional_contract_passes_without_mutation_or_tactical_claim():
    a, f = answer_fixture(), frame_fixture(); before = deepcopy((a, f))
    result = validate_decision(a, f)
    assert result['status'] == 'PASS' and result['errors'] == []
    assert result['tactical_quality'] == 'not_evaluated'
    assert (a, f) == before
    assert '条件推荐' in render_decision(a, result)


@pytest.mark.parametrize('change', [
    lambda a: a['facts_used'][0].update(fact_id='invented'),
    lambda a: a['facts_used'][0].update(value=999),
    lambda a: a['facts_used'][0].update(value='100'),
    lambda a: a.update(frame_id='future-frame'),
    lambda a: a['role_assignments'].pop(),
    lambda a: a['recommendation'].update(fallback_option_id=None),
    lambda a: a['recommendation'].update(fallback_option_id='a'),
    lambda a: a['options'][0].update(status='ruled_out'),
    lambda a: a['options'][0].update(reference_refs=['fake']),
    lambda a: a['options'][0].update(fact_refs=['fake']),
    lambda a: a['options'][1].update(id='a'),
    lambda a: a['options'][0].update(preconditions=[]),
    lambda a: a['options'][0]['time_budget'].update(travel_seconds=[2, 3]),
    lambda a: a['options'][0]['time_budget'].update(calculation_refs=['fake']),
    lambda a: a['recommendation'].update(confidence='supported'),
    lambda a: a['options'][0].update(status='supported'),
    lambda a: a.update(unexpected='future win'),
])
def test_rejects_bounded_contract_violations(change):
    assert check(change)['status'] == 'FAIL'


def test_zero_is_not_false():
    result = check(lambda a: a['facts_used'].append({'fact_id': 'ally_hp', 'value': False}))
    assert result['status'] == 'FAIL'


@pytest.mark.parametrize('bad', [None, 'text', [], {'x': 1}, 7, True])
def test_malformed_answers_do_not_crash(bad):
    assert validate_decision(bad, frame_fixture())['status'] == 'FAIL'


@pytest.mark.parametrize('change', [
    lambda a: a.update(options='not a list'),
    lambda a: a['options'][0].update(time_budget=[]),
    lambda a: a['options'][0].update(ally_requirements=[None]),
    lambda a: a['role_assignments'][0].update(actor_id=[]),
    lambda a: a['facts_used'][0].update(value=math.nan),
    lambda a: a['facts_used'][0].update(value=10 ** 500),
    lambda a: a['options'][0]['time_budget'].update(travel_seconds=[True, 1]),
    lambda a: a['options'][0]['time_budget'].update(travel_seconds=[math.inf, 1]),
    lambda a: a['recommendation'].update(why='   '),
    lambda a: a['recommendation'].update(extra='unexpected'),
])
def test_malformed_nested_answers_do_not_crash(change):
    assert check(change)['status'] == 'FAIL'


def test_future_fact_is_rejected_even_if_value_matches():
    assert check(frame_change=lambda f: f['facts']['gold'].update(observed_at_seconds=11))['status'] == 'FAIL'
    assert check(frame_change=lambda f: f['facts']['gold'].update(available_at_seconds=11))['status'] == 'FAIL'


def test_observed_followup_requires_matching_ally_and_nonhistorical_fact():
    change = lambda a: a['options'][0]['ally_requirements'][0].update(status='observed')
    assert check(change)['status'] == 'FAIL'
    assert check(change, lambda f: f['facts']['ally_hp'].update(temporal_scope='last_seen'))['status'] == 'FAIL'
    assert check(lambda a: a['options'][0]['ally_requirements'][0].update(
        status='observed', fact_refs=['gold']))['status'] == 'FAIL'


@pytest.mark.parametrize('scope', ['last_seen_sample', 'last_seen_position_candidate',
                                  'historical_event', 'historical_event_not_current_death_state',
                                  'historical_operation', 'roster', 'visibility_policy'])
def test_compiler_temporal_scopes_cannot_prove_observed_followup(scope):
    change = lambda a: a['options'][0]['ally_requirements'][0].update(status='observed')
    assert check(change, lambda f: f['facts']['ally_hp'].update(temporal_scope=scope))['status'] == 'FAIL'


def test_observed_followup_rejects_mixed_current_and_historical_evidence():
    def frame_change(f):
        f['facts']['ally_past'] = {**f['facts']['ally_hp'], 'temporal_scope': 'historical_event'}
    result = check(lambda a: a['options'][0]['ally_requirements'][0].update(
        status='observed', fact_refs=['ally_hp', 'ally_past']), frame_change)
    assert result['status'] == 'FAIL'


def test_observed_position_candidate_cannot_prove_an_action():
    change = lambda a: a['options'][0]['ally_requirements'][0].update(status='observed')
    result = check(change, lambda f: f['facts']['ally_hp'].update(temporal_scope='observed_position_candidate'))
    assert result['status'] == 'FAIL'
    assert result['tactical_quality'] == 'not_evaluated'


def observed_action_fixture(status='in_progress'):
    answer, frame = answer_fixture(), frame_fixture()
    frame['facts']['ally_action'] = {
        'entity_id': 'ally', 'field': 'action_observation',
        'value': {'action_key': 'moving_to_entry', 'status': status},
        'observed_at_seconds': 10, 'temporal_scope': 'observed_action'}
    answer['options'][0]['ally_requirements'][0].update(
        status='observed', action_key='moving_to_entry', fact_refs=['ally_action'])
    return answer, frame


@pytest.mark.parametrize('status', ['in_progress', 'completed'])
def test_observed_followup_matches_the_same_actor_and_explicit_action(status):
    answer, frame = observed_action_fixture(status)
    result = validate_decision(answer, frame)
    assert result['status'] == 'PASS'
    assert any('不证明会继续' in text for text in result['limitations'])


@pytest.mark.parametrize('change', [
    lambda a, f: a['options'][0]['ally_requirements'][0].pop('action_key'),
    lambda a, f: a['options'][0]['ally_requirements'][0].update(action_key='already_attacking'),
    lambda a, f: f['facts']['ally_action'].update(entity_id='enemy'),
    lambda a, f: f['facts']['ally_action'].update(field='health'),
    lambda a, f: f['facts']['ally_action'].update(temporal_scope='historical_event'),
    lambda a, f: f['facts']['ally_action']['value'].update(status='planned'),
    lambda a, f: f['facts']['ally_action'].update(value=100),
    lambda a, f: f['facts']['ally_action'].update(observed_at_seconds=11),
    lambda a, f: f['facts']['ally_action'].update(available_at_seconds=11),
])
def test_observed_action_rejects_unmatched_or_unavailable_evidence(change):
    answer, frame = observed_action_fixture()
    change(answer, frame)
    assert validate_decision(answer, frame)['status'] == 'FAIL'


def test_valid_action_does_not_allow_mixed_historical_followup_evidence():
    answer, frame = observed_action_fixture()
    frame['facts']['ally_past'] = {**frame['facts']['ally_action'], 'temporal_scope': 'historical_event'}
    answer['options'][0]['ally_requirements'][0]['fact_refs'].append('ally_past')
    assert validate_decision(answer, frame)['status'] == 'FAIL'


def test_action_key_stays_optional_for_conditional_and_unknown_requirements():
    answer, frame = answer_fixture(), frame_fixture()
    for status in ('conditional', 'unknown'):
        answer['options'][0]['ally_requirements'][0]['status'] = status
        assert 'action_key' not in answer['options'][0]['ally_requirements'][0]
        assert validate_decision(answer, frame)['status'] == 'PASS'


def test_registered_time_range_must_match_and_be_ordered():
    def change(a):
        a['options'][0]['time_budget'].update(travel_seconds=[2, 3], calculation_refs=['calc'])
    def frame_change(f):
        f['calculations']['calc'] = {'time_budget': {'travel_seconds': [2, 3]}}
    assert check(change, frame_change)['status'] == 'PASS'
    assert check(change, lambda f: f['calculations'].update(calc={'time_budget': {'travel_seconds': [4, 5]}}))['status'] == 'FAIL'
    assert check(lambda a: a['options'][0]['time_budget'].update(travel_seconds=[3, 2], calculation_refs=['calc']),
                 lambda f: f['calculations'].update(calc={'time_budget': {'travel_seconds': [3, 2]}}))['status'] == 'FAIL'


def test_insufficient_evidence_can_preserve_options_without_forcing_rank():
    a = answer_fixture()
    a['recommendation'].update(preferred_option_id=None, fallback_option_id=None,
                               confidence='insufficient_evidence')
    assert validate_decision(a, frame_fixture())['status'] == 'PASS'
    a['open_questions'] = []
    assert validate_decision(a, frame_fixture())['status'] == 'FAIL'


def test_invalid_answer_does_not_render_as_recommendation():
    a = answer_fixture(); a['frame_id'] = 'wrong'
    result = validate_decision(a, frame_fixture()); md = render_decision(a, result)
    assert '未通过' in md and '首选：' not in md


def test_renderer_distinguishes_excluded_option_from_executable_candidates():
    answer, frame = answer_fixture(), frame_fixture()
    answer['options'][1]['status'] = 'ruled_out'
    answer['recommendation'].update(preferred_option_id=None, fallback_option_id=None,
                                    confidence='insufficient_evidence')
    result = validate_decision(answer, frame)
    assert result['status'] == 'PASS'
    md = render_decision(answer, result)
    assert '候选（已排除，不执行）：合成动作 b' in md
    assert '候选（待条件满足）：合成动作 a' in md


def test_renderer_does_not_reuse_a_pass_for_a_changed_answer():
    a = answer_fixture(); result = validate_decision(a, frame_fixture())
    a['options'][0]['action'] = '未经检查的新动作'
    md = render_decision(a, result)
    assert '未通过' in md and '未经检查的新动作' not in md


def test_schema_is_fresh_and_closed():
    a = output_schema(); a['properties']['objective']['minLength'] = 999
    b = output_schema()
    assert b['properties']['objective']['minLength'] == 1
    assert b['additionalProperties'] is False
    assert b['properties']['options']['minItems'] == 2


@pytest.mark.parametrize('bad', [None, {}, {'schema': 'decision-frame/v1'},
                              {'schema': 'wrong'}])
def test_bad_frame_does_not_crash(bad):
    assert validate_decision(answer_fixture(), bad)['status'] == 'FAIL'
