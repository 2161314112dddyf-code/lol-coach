"""Synthetic history-boundary and CLI checks, not tactical model evaluation."""
from copy import deepcopy
import json

import pytest

from lol_coach.decision_contract import validate_decision
from lol_coach.reasoning_frame import canonical, digest, model_messages
from lol_coach.round_chain import attach_previous_plan
from test_decision_contract import answer_fixture, frame_fixture


def freeze(bundle):
    frame = bundle['frame']
    frame.pop('frame_id', None)
    frame['frame_id'] = 'frame_' + digest(frame)[:24]
    return bundle


def bundle_at(at, gold=100, tower_health=500):
    frame = frame_fixture()
    frame['decision']['at_seconds'] = at
    frame['facts']['gold']['value'] = gold
    frame['facts']['gold']['observed_at_seconds'] = at - 1
    frame['facts']['tower_hp'] = dict(entity_id='tower', field='tower_health',
        value=tower_health, observed_at_seconds=at - 0.5, temporal_scope='observed_sample')
    frame['task'] = {'previous_plan': None, 'round_boundaries': None}
    frame['input_policy'] = ['Synthetic input only']
    frame['reasoning_order'] = ['Synthetic test step']
    frame['unknowns'] = {'action_durations': 'unknown'}
    for hero in frame['lineup']:
        hero.update(current_fact_ids=[], history_fact_ids=[])
    return freeze(dict(schema='reasoning-bundle/v1', frame=frame,
        audit={'source_replay_sha256': 'a' * 64, 'secret': 'AUDIT_NOT_MODEL_INPUT'},
        reference_library={'rule1': {'secret': 'LIBRARY_NOT_MODEL_INPUT'}}))


def answer_for(bundle):
    answer = answer_fixture()
    frame = bundle['frame']
    answer['frame_id'] = frame['frame_id']
    answer['facts_used'][0]['value'] = frame['facts']['gold']['value']
    previous = frame['task']['previous_plan']
    if previous:
        answer['continuation'] = dict(previous_frame_id=previous['previous_frame_id'],
            disposition='retain', previous_action_execution='unknown',
            reason='Synthetic retained goal; execution is unknown.',
            current_fact_refs=['gold'], change_refs=[])
    assert validate_decision(answer, frame)['status'] == 'PASS'
    return answer


def pair():
    old, current = bundle_at(10), bundle_at(20, gold=150, tower_health=0)
    return old, current, answer_for(old)


def test_link_keeps_current_facts_and_inputs_immutable():
    old, current, answer = pair()
    before = deepcopy((old, current, answer))
    out = attach_previous_plan(current, old, answer)
    assert (old, current, answer) == before
    assert out['frame']['facts'] == current['frame']['facts']
    assert out['frame']['task']['continuity_status']['status'] == 'linked'
    assert out['frame']['task']['round_boundaries'] is None
    assert out['frame']['frame_id'] != current['frame']['frame_id']
    assert freeze(deepcopy(out))['frame']['frame_id'] == out['frame']['frame_id']


def test_previous_references_are_historical_and_not_execution():
    old, current, answer = pair()
    out = attach_previous_plan(current, old, answer)
    plan = out['frame']['task']['previous_plan']
    assert plan['execution_status'] == 'unknown'
    assert plan['previous_frame_id'] == old['frame']['frame_id']
    for historical in plan['historical_facts'].values():
        assert historical['temporal_scope'] == 'historical_previous_frame'
        assert historical['previous_frame_id'] == old['frame']['frame_id']
        assert historical['age_seconds'] == 20 - historical['observed_at_seconds']
    assert plan['decision_card']['options'][0]['fact_refs'] == ['h_gold']
    assert plan['decision_card']['options'][0]['ally_requirements'][0]['fact_refs'] == ['h_ally_hp']
    assert not set(plan['historical_facts']).intersection(out['frame']['facts'])
    assert plan['historical_facts']['h_gold']['value'] == 100
    assert out['frame']['facts']['gold']['value'] == 150


def test_tower_zero_has_traceable_old_and_new_evidence_without_action_claim():
    old, current, answer = pair()
    out = attach_previous_plan(current, old, answer)
    transition = out['frame']['task']['round_transition']
    changes = list(transition['changes'].values())
    tower = next(c for c in changes if c['field'] == 'tower_health')
    assert tower['kind'] == 'observed_value_changed_not_action_proof'
    assert out['frame']['facts'][tower['current_fact_id']]['value'] == 0
    assert out['frame']['task']['previous_plan']['historical_facts'][tower['historical_fact_id']]['value'] == 500
    assert transition['elapsed_seconds'] == 10


def test_timestamp_refresh_alone_is_not_value_change():
    old = bundle_at(10)
    current = bundle_at(20)
    out = attach_previous_plan(current, old, answer_for(old))
    assert out['frame']['task']['round_transition']['changes'] == {}


def test_new_observation_has_no_invented_previous_value_and_absence_is_not_death():
    old, current, answer = pair()
    del current['frame']['facts']['enemy_hp']
    current['frame']['facts']['new_hero_health'] = dict(entity_id='new_enemy', field='health',
        value=300, observed_at_seconds=19, temporal_scope='observed_sample')
    freeze(current)
    out = attach_previous_plan(current, old, answer)
    changes = list(out['frame']['task']['round_transition']['changes'].values())
    new = next(c for c in changes if c['entity_id'] == 'new_enemy')
    assert new['kind'] == 'newly_available_observation_not_action_proof'
    assert new['historical_fact_id'] is None
    assert all(c['entity_id'] != 'enemy' for c in changes)


def test_latest_value_is_compared_without_promoting_older_sample():
    old, current, answer = pair()
    current['frame']['facts']['older_tower_sample'] = dict(entity_id='tower', field='tower_health',
        value=450, observed_at_seconds=11, temporal_scope='historical_sample')
    freeze(current)
    out = attach_previous_plan(current, old, answer)
    changes = out['frame']['task']['round_transition']['changes'].values()
    assert next(c for c in changes if c['field'] == 'tower_health')['current_fact_id'] == 'tower_hp'


@pytest.mark.parametrize('key,value,reason', [
    ('build', 'different', 'build_mismatch'),
    ('observer_team_id', 200, 'observer_team_id_mismatch'),
    ('player_entity_id', 'someone_else', 'player_entity_id_mismatch'),
    ('at_seconds', 20, 'previous_time_not_earlier'),
    ('at_seconds', 21, 'previous_time_not_earlier'),
])
def test_incompatible_previous_decision_falls_back(key, value, reason):
    old, current, answer = pair()
    old['frame']['decision'][key] = value
    freeze(old)
    answer['frame_id'] = old['frame']['frame_id']
    out = attach_previous_plan(current, old, answer)
    assert out['frame']['task']['continuity_status'] == {'status': 'standalone', 'reason': reason}
    assert out['frame']['task']['previous_plan'] is None
    assert out['frame']['facts'] == current['frame']['facts']


@pytest.mark.parametrize('source,reason', [('b' * 64, 'source_replay_mismatch'),
    (None, 'missing_source_binding'), ('short', 'missing_source_binding')])
def test_source_identity_is_required_for_history(source, reason):
    old, current, answer = pair()
    old['audit']['source_replay_sha256'] = source
    out = attach_previous_plan(current, old, answer)
    assert out['frame']['task']['continuity_status']['reason'] == reason


@pytest.mark.parametrize('kind', ['missing_bundle', 'missing_answer', 'invalid_answer',
    'answer_other_frame', 'changed_old_frame'])
def test_missing_or_unvalidated_history_cannot_enter_current_input(kind):
    old, current, answer = pair()
    if kind == 'missing_bundle': old = None
    elif kind == 'missing_answer': answer = None
    elif kind == 'invalid_answer': answer['facts_used'][0]['value'] = 999
    elif kind == 'answer_other_frame': answer['frame_id'] = 'another-frame'
    else: old['frame']['facts']['gold']['value'] = 999
    out = attach_previous_plan(current, old, answer)
    assert out['frame']['task']['continuity_status']['status'] == 'standalone'
    assert out['frame']['task']['previous_plan'] is None
    assert 'round_transition' not in out['frame']['task']
    assert validate_decision(answer_for(out), out['frame'])['status'] == 'PASS'


@pytest.mark.parametrize('mutation', [
    lambda old: old.update(frame=[]),
    lambda old: old['frame'].update(task=None),
    lambda old: old['frame']['decision'].pop('build'),
    lambda old: old['frame']['facts'].update(gold='invalid'),
    lambda old: old['frame']['facts']['gold'].pop('temporal_scope'),
    lambda old: old['frame']['facts']['gold'].update(observed_at_seconds=11),
    lambda old: old['frame']['facts']['gold'].update(available_at_seconds=11),
])
def test_malformed_or_future_previous_input_falls_back_without_crash(mutation):
    old, current, answer = pair()
    mutation(old)
    if isinstance(old['frame'], dict): freeze(old)
    out = attach_previous_plan(current, old, answer)
    assert out['frame']['task']['continuity_status']['status'] == 'standalone'
    assert out['frame']['task']['previous_plan'] is None


def test_invalid_current_frame_is_an_error_not_successful_fallback():
    current = bundle_at(20)
    current['frame']['facts']['gold']['available_at_seconds'] = 21
    freeze(current)
    with pytest.raises(ValueError, match='future_or_invalid_fact_time'):
        attach_previous_plan(current)
    current = bundle_at(20)
    current['frame']['facts']['gold']['value'] = 999
    with pytest.raises(ValueError, match='frame_identity_mismatch'):
        attach_previous_plan(current)


def test_only_one_step_of_history_and_no_audit_or_library_leaks():
    first, second, first_answer = pair()
    first_answer['objective'] = 'FIRST_PLAN_SENTINEL'
    linked_second = attach_previous_plan(second, first, first_answer)
    second_answer = answer_for(linked_second)
    second_answer['objective'] = 'SECOND_PLAN_SENTINEL'
    third = attach_previous_plan(bundle_at(30, gold=200), linked_second, second_answer)
    plan = third['frame']['task']['previous_plan']
    assert plan['decision_card']['objective'] == 'SECOND_PLAN_SENTINEL'
    assert 'FIRST_PLAN_SENTINEL' not in canonical(third['frame'])
    assert {f['previous_frame_id'] for f in plan['historical_facts'].values()} == {linked_second['frame']['frame_id']}
    assert 'continuation' not in plan['decision_card']
    sent = canonical(model_messages(third, {}))
    assert 'AUDIT_NOT_MODEL_INPUT' not in sent
    assert 'LIBRARY_NOT_MODEL_INPUT' not in sent
    assert third['audit']['round_chain']['history_steps'] == 1


def test_relinking_without_previous_input_clears_stale_plan_and_transition():
    old, current, answer = pair()
    linked = attach_previous_plan(current, old, answer)
    standalone = attach_previous_plan(linked)
    assert standalone['frame']['task']['previous_plan'] is None
    assert 'round_transition' not in standalone['frame']['task']
    assert standalone['audit']['round_chain']['status'] == 'rejected_or_missing'


def test_context_budget_refuses_truncation_and_keeps_inputs():
    old, current, answer = pair()
    before = deepcopy((old, current, answer))
    with pytest.raises(ValueError, match='never truncate'):
        attach_previous_plan(current, old, answer, max_chars=100)
    assert (old, current, answer) == before


@pytest.mark.parametrize('budget', [0, -1, True, 2.5])
def test_invalid_context_budget_rejected(budget):
    with pytest.raises(ValueError, match='max_chars'):
        attach_previous_plan(bundle_at(20), max_chars=budget)


def cli_inputs(tmp_path, monkeypatch):
    from scripts import reasoning
    old, current, answer = pair()
    for name, value in [('old.json', old), ('current.json', current), ('answer.json', answer)]:
        (tmp_path/name).write_text(json.dumps(value), encoding='utf8')
    monkeypatch.setattr(reasoning, 'ROOT', tmp_path)
    manifests = []
    monkeypatch.setattr(reasoning, 'manifest', lambda *args, **kwargs: manifests.append((args, kwargs)))
    target = tmp_path/'data/private/reasoning/new-chain'
    args = ['reasoning.py', 'chain', '--bundle', str(tmp_path/'current.json'),
            '--previous-bundle', str(tmp_path/'old.json'), '--previous-answer', str(tmp_path/'answer.json'),
            '--output', str(target)]
    monkeypatch.setattr('sys.argv', args)
    return reasoning, target, args, manifests


def test_chain_cli_outputs_frozen_bundle_messages_and_history(tmp_path, monkeypatch):
    reasoning, target, args, manifests = cli_inputs(tmp_path, monkeypatch)
    assert reasoning.main() == 0
    bundle = reasoning.read_bundle(target/'bundle.json')
    assert bundle['frame']['task']['continuity_status']['status'] == 'linked'
    messages = json.loads((target/'messages.json').read_text(encoding='utf8'))
    assert json.loads(messages[1]['content'])['decision_frame'] == bundle['frame']
    assert (target/'frame.md').is_file() and (target/'response.schema.json').is_file()
    assert manifests[0][1]['authorship'] == 'deterministic_one_step_plan_binding_not_model_output'


@pytest.mark.parametrize('mode', ['missing', 'malformed'])
def test_chain_cli_unreadable_previous_answer_still_outputs_standalone(tmp_path, monkeypatch, mode):
    reasoning, target, args, manifests = cli_inputs(tmp_path, monkeypatch)
    path = tmp_path/'answer.json'
    if mode == 'missing': path.unlink()
    else: path.write_text('{ malformed', encoding='utf8')
    assert reasoning.main() == 0
    bundle = reasoning.read_bundle(target/'bundle.json')
    assert bundle['frame']['task']['previous_plan'] is None
    assert bundle['frame']['task']['continuity_status']['status'] == 'standalone'
    assert any(i.get('status') == 'unreadable_previous_input' for i in manifests[0][0][1])


def test_chain_cli_refuses_overwrite_without_changing_existing_result(tmp_path, monkeypatch):
    reasoning, target, args, manifests = cli_inputs(tmp_path, monkeypatch)
    assert reasoning.main() == 0
    before = (target/'bundle.json').read_bytes()
    with pytest.raises(FileExistsError):
        reasoning.main()
    assert (target/'bundle.json').read_bytes() == before


def test_chain_cli_refuses_output_outside_private_reasoning(tmp_path, monkeypatch):
    reasoning, target, args, manifests = cli_inputs(tmp_path, monkeypatch)
    args[-1] = str(tmp_path/'outside')
    with pytest.raises(ValueError, match='Output must be a new child'):
        reasoning.main()
    assert not (tmp_path/'outside').exists()


def test_model_receives_tool_batch_budget_and_configured_response_limits():
    from lol_coach.reasoning_runner import run_reasoning
    bundle = bundle_at(10)
    requests = []

    def generate(request):
        requests.append(deepcopy(request))
        return {'answer': answer_for(bundle)}

    result = run_reasoning(bundle, generate, max_calls=3, max_repairs=0)
    assert result['status'] == 'completed'
    protocol = requests[0]['messages'][-1]['content']
    assert '每批资料请求1至5项' in protocol
    assert '每会话累计最多10项' in protocol
    assert '最多3次模型响应' in protocol
    assert '答案最多修正0次' in protocol
    assert '请求id在会话中不可重复' in protocol
    assert '同批reference_id不可重复' in protocol
    assert '为最终答案预留响应次数' in protocol
    assert '"name":"get_reference"' in protocol
    assert '"arguments":{"reference_id":' in protocol
    assert '或{"answer":决策对象}' in protocol


def test_session_manifest_keeps_start_hashes_when_files_change_during_callback(tmp_path, monkeypatch):
    """Simulate a disk edit during a call; no project source or real model is used."""
    import hashlib
    import lol_coach.file_model_bridge as transport
    from scripts import run_reasoning_session as session

    bundle = bundle_at(10)
    input_path = tmp_path/'input.json'
    input_path.write_text(json.dumps(bundle), encoding='utf8')
    input_start_hash = hashlib.sha256(input_path.read_bytes()).hexdigest()
    output = tmp_path/'data/private/reasoning_sessions/hash-capture'
    phase = {'during_call': False}
    changed_source = 'lol_coach/reasoning_runner.py'
    monkeypatch.setattr(session, 'ROOT', tmp_path)
    monkeypatch.setattr(transport, 'ROOT', tmp_path)

    def fake_hash(path):
        relative = path.relative_to(tmp_path).as_posix()
        if relative == changed_source:
            return ('2' if phase['during_call'] else '1') * 64
        if relative.startswith(('scripts/', 'lol_coach/')):
            return '3' * 64
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def generate(request):
        phase['during_call'] = True
        # The in-memory frozen input remains the original one. A later disk
        # change must not replace its provenance in the completed manifest.
        input_path.write_text(json.dumps(bundle) + '\n', encoding='utf8')
        return {'answer': answer_for(bundle)}

    monkeypatch.setattr(session, 'file_sha256', fake_hash)
    monkeypatch.setattr(session, 'file_generate', lambda *args, **kwargs: generate)
    monkeypatch.setattr('sys.argv', ['run_reasoning_session.py', '--bundle', str(input_path),
                                   '--output', str(output)])
    assert session.main() == 0
    manifest = json.loads((output/'manifest.json').read_text(encoding='utf8'))
    assert manifest['implementation'][changed_source] == '1' * 64
    assert manifest['implementation_changed_during_run'] == {changed_source: '2' * 64}
    assert manifest['input_bundle']['sha256'] == input_start_hash
    assert manifest['input_bundle']['sha256'] != hashlib.sha256(input_path.read_bytes()).hexdigest()
    assert manifest['status'] == 'completed' and manifest['model_callback_calls'] == 1
