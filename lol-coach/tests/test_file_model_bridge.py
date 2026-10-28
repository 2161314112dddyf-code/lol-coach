"""Transport fixtures, not model intelligence or gameplay evaluations."""
import json
from pathlib import Path

import pytest

import lol_coach.file_model_bridge as transport
from lol_coach.reasoning_frame import digest
from lol_coach.reasoning_runner import run_reasoning
from test_reasoning_runner import bundle_fixture, answer_fixture


@pytest.fixture
def area(tmp_path, monkeypatch):
    monkeypatch.setattr(transport, 'ROOT', tmp_path)
    return tmp_path / 'data/private/reasoning_sessions'


def request():
    return {'messages':[{'role':'user','content':'synthetic'}], 'tools':[], 'response_schema':{}}


def responder(payload, *, transform=None):
    def answer(event):
        response = {'request_id':event['request_id'], 'response':payload}
        if transform:
            transform(response)
        transport.atomic_json(Path(event['response_path']), response)
    return answer


def test_live_runner_uses_reference_roundtrip_without_audit_leak(area):
    seen = []
    def respond(event):
        envelope = json.loads(Path(event['request_path']).read_text(encoding='utf-8'))
        seen.append(envelope)
        if event['sequence'] == 1:
            payload = {'tool_requests':[{'id':'r1','name':'get_reference','arguments':{'reference_id':'rule1'}}]}
        else:
            payload = {'answer':answer_fixture()}
        transport.atomic_json(Path(event['response_path']), {'request_id':event['request_id'],'response':payload})
    bridge = transport.file_generate(area/'roundtrip', on_request=respond)
    result = run_reasoning(bundle_fixture(), bridge)
    assert result['status'] == 'completed' and result['model_calls'] == 2
    assert result['reference_reads'] == ['rule1']
    assert 'REFERENCE_BODY_SENTINEL' not in json.dumps(seen[0])
    assert 'REFERENCE_BODY_SENTINEL' in json.dumps(seen[1])
    assert 'AUDIT_SENTINEL' not in json.dumps(seen)
    assert 'PACKET_SENTINEL' not in json.dumps(seen)
    assert not list((area/'roundtrip').rglob('*.tmp'))


def test_wrong_request_id_fails_without_accepting_answer(area):
    bridge = transport.file_generate(area/'wrong', on_request=responder({'answer':{}},
        transform=lambda r:r.update(request_id='stale-id')))
    with pytest.raises(ValueError, match='request_id'):
        bridge(request())


def test_timeout_is_bounded_and_runner_retains_failure(area):
    clock = [0.0]
    bridge = transport.file_generate(area/'timeout', timeout_seconds=0.25, poll_interval=0.1,
        clock=lambda:clock[0], sleep=lambda seconds:clock.__setitem__(0,clock[0]+seconds))
    result = run_reasoning(bundle_fixture(), bridge)
    assert result['status'] == 'failed' and 'TimeoutError' in result['error']
    assert result['model_calls'] == 1 and result['answer'] is None
    assert clock[0] == pytest.approx(0.25)
    assert (area/'timeout/requests/01.json').exists()


@pytest.mark.parametrize('raw', ['{broken', '{"request_id":"x","response":{"answer":{"x":NaN}}}',
                                 '{"request_id":"x","response":{"answer":{"x":1e999}}}', '[]'])
def test_malformed_or_nonfinite_response_is_rejected(area, raw):
    def respond(event):
        Path(event['response_path']).write_text(raw, encoding='utf-8')
    bridge = transport.file_generate(area/'bad', on_request=respond)
    with pytest.raises(ValueError):
        bridge(request())


def test_response_size_is_bounded(area):
    bridge = transport.file_generate(area/'large', max_response_bytes=64,
        on_request=lambda e:Path(e['response_path']).write_bytes(b'x'*65))
    with pytest.raises(ValueError, match='maximum byte size'):
        bridge(request())


def test_output_is_confined_and_no_existing_evidence_is_overwritten(area):
    transport.file_generate(area/'session')
    with pytest.raises(FileExistsError):
        transport.file_generate(area/'session')
    with pytest.raises(ValueError, match='new child'):
        transport.file_generate(area.parent/'outside')
    path = area/'session/protected.json'
    transport.atomic_json(path, {'first':1})
    with pytest.raises(FileExistsError):
        transport.atomic_json(path, {'second':2})
    assert json.loads(path.read_text(encoding='utf-8')) == {'first':1}


def test_unexpected_request_fields_cannot_smuggle_audit(area):
    bridge = transport.file_generate(area/'smuggle')
    with pytest.raises(ValueError, match='Only runner'):
        bridge({**request(), 'audit':{'secret':'never-publish'}})
    assert not list((area/'smuggle/requests').iterdir())


def test_preexisting_response_is_not_replayed(area):
    bridge = transport.file_generate(area/'preexisting')
    (area/'preexisting/responses/01.json').write_text('{}', encoding='utf-8')
    with pytest.raises(FileExistsError, match='before request'):
        bridge(request())


def test_cli_timeout_saves_explicit_terminal_artifacts(area, monkeypatch, tmp_path):
    from scripts import run_reasoning_session as cli
    bundle = bundle_fixture()
    bundle['frame']['frame_id'] = 'frame_' + digest({k:v for k,v in bundle['frame'].items() if k!='frame_id'})[:24]
    path=tmp_path/'bundle.json';path.write_text(json.dumps(bundle), encoding='utf-8')
    output=area/'cli-timeout'
    monkeypatch.setattr('sys.argv', ['run_reasoning_session', '--bundle', str(path), '--output',str(output),
                                   '--timeout-seconds','0.01','--max-calls','1'])
    assert cli.main() == 2
    result=json.loads((output/'result.json').read_text(encoding='utf-8'))
    manifest=json.loads((output/'manifest.json').read_text(encoding='utf-8'))
    assert result['status']=='failed' and 'TimeoutError' in result['error']
    assert manifest['execution_method']=='file_model_bridge'
    assert manifest['external_api_used_by_cli'] is False
    assert manifest['model_callback_calls']==1 and (output/'answer.md').exists()
    assert 'answer.json' not in manifest['outputs']
