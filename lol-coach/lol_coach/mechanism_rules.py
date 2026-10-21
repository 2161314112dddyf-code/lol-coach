"""Versioned static references and tri-state scenario checks, never replay facts."""
import copy
import hashlib
import json
from pathlib import Path
import re

PROFILE = Path(__file__).with_name('profiles') / 'pantheon_mechanisms_16_20_1.json'


def load_spec():
    return json.loads(PROFILE.read_text(encoding='utf-8'))


def resolve_pointer(data, pointer):
    if not isinstance(pointer, str) or not pointer.startswith('/'):
        raise ValueError('Expected an absolute JSON pointer')
    try:
        for part in pointer[1:].split('/'):
            part = part.replace('~1', '/').replace('~0', '~')
            data = data[int(part)] if isinstance(data, list) else data[part]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError('Source pointer missing: ' + pointer) from exc
    return data


def build_bundle(cache_root, spec=None):
    """Read and hash-check existing URL/body caches; never fetch or repair them."""
    spec = copy.deepcopy(spec if spec is not None else load_spec())
    if spec.get('schema') != 'champion-mechanism-spec/v1' or spec.get('patch') != '16.20.1':
        raise ValueError('Unsupported mechanism source version')
    root = Path(cache_root).resolve()
    parsed, sources = {}, {}
    for name, expected in spec['sources'].items():
        key = hashlib.sha256(expected['url'].encode()).hexdigest()
        record = json.loads((root / 'cache' / (key + '.json')).read_text(encoding='utf-8'))
        if record.get('requested_url') != expected['url'] or record.get('http_status') != 200:
            raise ValueError('Unexpected source cache identity/status: ' + name)
        body_path = (root / record['evidence_path']).resolve()
        if not body_path.is_relative_to(root):
            raise ValueError('Source cache path escapes root')
        raw = body_path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != expected['sha256'] or digest != record.get('sha256'):
            raise ValueError('Source hash mismatch: ' + name)
        data = json.loads(raw)
        if data.get('version') != spec['patch'] or data.get('data', {}).get(name, {}).get('id') != name:
            raise ValueError('Source version/champion mismatch: ' + name)
        parsed[name] = data
        sources[name] = dict(url=expected['url'], sha256=digest,
                             retrieved_at_utc=record['retrieved_at_utc'],
                             evidence_path=record['evidence_path'], version=spec['patch'])
    if [card['slot'] for card in spec['cards']] != list('PQWER'):
        raise ValueError('Expected exactly P/Q/W/E/R cards')
    if len({row['id'] for row in spec['interactions']}) != len(spec['interactions']):
        raise ValueError('Duplicate interaction IDs')
    references = []
    for entry in spec['cards'] + spec['interactions']:
        if not entry['evidence']:
            raise ValueError('Missing evidence')
        parameters = set()
        for ref in entry['evidence']:
            value = resolve_pointer(parsed[ref['source']], ref['pointer'])
            if not isinstance(value, str) or not value.strip():
                raise ValueError('Expected a nonempty source description')
            parameters.update(re.findall(r'\{\{\s*(.*?)\s*\}\}', value))
            references.append(dict(source=ref['source'], pointer=ref['pointer'],
                                   text_sha256=hashlib.sha256(value.encode()).hexdigest()))
        entry['unresolved_source_parameters'] = sorted(parameters)
        entry['numeric_action_duration_seconds'] = None
        entry['evidence_level'] = 'official_versioned_description'
        entry['analysis_origin'] = 'project_inference_not_source_quote'
    spec.update(schema='champion-mechanisms/v1', sources=sources,
                source_pointer_checks=references, actual_match_observation=False,
                decision_input_eligible=False, network_used=False)
    return spec


def evaluate_interaction(bundle, interaction_id, facts, *, patch):
    """Caller-supplied hypothetical booleans do not acquire observed status."""
    if bundle.get('schema') != 'champion-mechanisms/v1':
        raise ValueError('Expected a built mechanism bundle')
    if patch != '16.20.1' or bundle.get('patch') != patch:
        raise ValueError('Mechanism patch mismatch')
    cases = [c for c in bundle['interactions'] if c['id'] == interaction_id]
    if len(cases) != 1:
        raise ValueError('Unknown or ambiguous interaction')
    case = cases[0]
    if not isinstance(facts, dict) or set(facts) - set(case['requires']):
        raise ValueError('Unknown scenario condition')
    if any(v is not None and type(v) is not bool for v in facts.values()):
        raise ValueError('Conditions must be true, false, or null')
    unmet, unknown = [], []
    for key, expected in case['requires'].items():
        if type(expected) is not bool:
            raise ValueError('Invalid rule predicate')
        actual = facts.get(key)
        if actual is None:
            unknown.append(key)
        elif actual != expected:
            unmet.append(key)
    if unmet:
        conclusion = case['when_unmet']
    elif unknown:
        conclusion = dict(status='insufficient_information', explanation_zh='条件缺失或未知，不能输出该交互已经成立。')
    else:
        conclusion = case['when_met']
    source_names = sorted({r['source'] for r in case['evidence']})
    return dict(schema='mechanism-scenario/v1', patch=patch, interaction_id=interaction_id,
                relationship=case['relationship'], participants=copy.deepcopy(case['participants']),
                **conclusion, unmet_conditions=unmet, unknown_conditions=unknown,
                supplied_conditions=copy.deepcopy(facts), input_kind='hypothetical_scenario',
                actual_match_observation=False, decision_input_eligible=False,
                current_cooldowns=None, damage_prediction=None, action_duration_seconds=None,
                evidence=copy.deepcopy(case['evidence']),
                sources={name: copy.deepcopy(bundle['sources'][name]) for name in source_names},
                assumptions=copy.deepcopy(case['unknowns']),
                evidence_level='source_backed_project_inference_not_runtime_validation')
