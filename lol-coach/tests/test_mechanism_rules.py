"""Synthetic scenarios test gating, not the truth of in-game interactions."""
import copy
import hashlib
import json
import pytest

from lol_coach.mechanism_rules import build_bundle, evaluate_interaction, load_spec


@pytest.fixture
def source_cache(tmp_path):
    spec = load_spec()
    root = tmp_path / 'synthetic-cache'
    (root / 'cache').mkdir(parents=True)
    (root / 'raw').mkdir()
    for name, source in spec['sources'].items():
        data = dict(version='16.20.1', data={name: dict(id=name,
            passive=dict(description='synthetic passive'),
            spells=[dict(description='synthetic description', tooltip='synthetic {{ unknown_duration }}') for _ in range(4)])})
        raw = json.dumps(data).encode()
        digest = hashlib.sha256(raw).hexdigest()
        source['sha256'] = digest
        path = 'raw/' + name + '.json'
        (root / path).write_bytes(raw)
        key = hashlib.sha256(source['url'].encode()).hexdigest()
        (root / 'cache' / (key + '.json')).write_text(json.dumps(dict(
            requested_url=source['url'], http_status=200, sha256=digest,
            evidence_path=path, retrieved_at_utc='synthetic_fixture')), encoding='utf-8')
    return root, spec


@pytest.fixture
def bundle(source_cache):
    return build_bundle(*source_cache)


def evaluate(bundle, case, facts):
    return evaluate_interaction(bundle, case, facts, patch='16.20.1')


def all_conditions(bundle, case):
    return next(c for c in bundle['interactions'] if c['id'] == case)['requires'].copy()


def test_source_build_retains_unresolved_parameters_and_unknown_duration(bundle):
    assert [c['slot'] for c in bundle['cards']] == list('PQWER')
    assert bundle['cards'][1]['unresolved_source_parameters'] == ['unknown_duration']
    assert all(c['numeric_action_duration_seconds'] is None for c in bundle['cards'])
    assert len(bundle['sources']) == 3 and len(bundle['source_pointer_checks']) == 13
    assert bundle['decision_input_eligible'] is False


@pytest.mark.parametrize('case,expected', [
    ('pantheon_jhin_followup', 'conditional_followup'),
    ('pantheon_morgana_black_shield', 'stun_blocked_by_black_shield')])
def test_positive_scenario_is_not_a_match_observation(bundle, case, expected):
    before = copy.deepcopy(bundle)
    facts = all_conditions(bundle, case)
    result = evaluate(bundle, case, facts)
    assert result['status'] == expected
    assert result['actual_match_observation'] is False
    assert result['decision_input_eligible'] is False
    assert result['current_cooldowns'] is None and result['damage_prediction'] is None
    result['sources'][next(iter(result['sources']))]['sha256'] = 'changed-output'
    assert bundle == before


@pytest.mark.parametrize('key', [
    'jhin_w_available', 'target_is_first_champion_hit',
    'allied_damage_mark_active_at_jhin_w_impact', 'target_can_be_rooted_at_jhin_w_impact'])
def test_missing_followup_requirement_is_not_unconditional_synergy(bundle, key):
    case = 'pantheon_jhin_followup'
    facts = all_conditions(bundle, case)
    facts[key] = False
    result = evaluate(bundle, case, facts)
    assert result['status'] == 'route_conditions_not_met'
    assert result['unmet_conditions'] == [key]


def test_absent_black_shield_is_not_guaranteed_stun(bundle):
    case = 'pantheon_morgana_black_shield'
    facts = all_conditions(bundle, case)
    facts['black_shield_active_on_target_at_w_impact'] = False
    assert evaluate(bundle, case, facts)['status'] == 'this_counter_not_established'


@pytest.mark.parametrize('facts', [{}, {'pantheon_w_connects': True},
    {'pantheon_w_connects': True, 'black_shield_active_on_target_at_w_impact': None}])
def test_absent_and_null_are_unknown(bundle, facts):
    result = evaluate(bundle, 'pantheon_morgana_black_shield', facts)
    assert result['status'] == 'insufficient_information'
    assert result['unknown_conditions']
    assert not result['unmet_conditions']


def test_known_failure_keeps_other_unknowns(bundle):
    result = evaluate(bundle, 'pantheon_jhin_followup', {'jhin_w_available': False})
    assert result['status'] == 'route_conditions_not_met'
    assert result['unknown_conditions']


@pytest.mark.parametrize('value', [0, 1, 'true', 'false', [], {}])
def test_no_truthiness_coercion(bundle, value):
    with pytest.raises(ValueError, match='true, false, or null'):
        evaluate(bundle, 'pantheon_morgana_black_shield', {'pantheon_w_connects': value})


def test_unknown_condition_is_not_silently_ignored(bundle):
    with pytest.raises(ValueError, match='Unknown scenario condition'):
        evaluate(bundle, 'pantheon_jhin_followup', {'jhin_can_win': True})


@pytest.mark.parametrize('patch', ['16.21.1', '16.20.824.8524', None])
def test_runtime_build_is_not_the_static_patch(bundle, patch):
    with pytest.raises(ValueError, match='patch mismatch'):
        evaluate_interaction(bundle, 'pantheon_jhin_followup', {}, patch=patch)


def test_wrong_source_bytes_fail(source_cache):
    root, spec = source_cache
    (root / 'raw/Pantheon.json').write_bytes(b'{}')
    with pytest.raises(ValueError, match='hash mismatch'):
        build_bundle(root, spec)


def test_wrong_source_version_fails_even_if_hash_matches(source_cache):
    root, spec = source_cache
    path = root / 'raw/Pantheon.json'
    body = json.loads(path.read_bytes())
    body['version'] = '16.19.1'
    raw = json.dumps(body).encode()
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    source = spec['sources']['Pantheon']
    source['sha256'] = digest
    key = hashlib.sha256(source['url'].encode()).hexdigest()
    index = root / 'cache' / (key + '.json')
    record = json.loads(index.read_text())
    record['sha256'] = digest
    index.write_text(json.dumps(record))
    with pytest.raises(ValueError, match='version/champion mismatch'):
        build_bundle(root, spec)


def test_missing_pointer_is_not_valid_evidence(source_cache):
    root, spec = source_cache
    spec['cards'][0]['evidence'][0]['pointer'] = '/data/Pantheon/absent'
    with pytest.raises(ValueError, match='pointer missing'):
        build_bundle(root, spec)


def test_missing_cached_body_is_not_success(source_cache):
    root, spec = source_cache
    (root / 'raw/Jhin.json').unlink()
    with pytest.raises(FileNotFoundError):
        build_bundle(root, spec)


def test_cache_path_cannot_escape_root(source_cache):
    root, spec = source_cache
    source = spec['sources']['Pantheon']
    key = hashlib.sha256(source['url'].encode()).hexdigest()
    index = root / 'cache' / (key + '.json')
    record = json.loads(index.read_text())
    record['evidence_path'] = '../outside.json'
    index.write_text(json.dumps(record))
    with pytest.raises(ValueError, match='escapes root'):
        build_bundle(root, spec)
