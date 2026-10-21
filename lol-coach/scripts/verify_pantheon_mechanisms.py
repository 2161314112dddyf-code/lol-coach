"""Real cached-source checks and explicitly synthetic CLI scenario examples."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.mechanism_rules import build_bundle, resolve_pointer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True, help='Must not exist')
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    cache = ROOT / 'data/research/champion_catalog'
    tool = ROOT / 'scripts/pantheon_mechanisms.py'
    commands = []

    def run(*argv, expected_code=0):
        completed = subprocess.run([sys.executable, str(tool), *map(str, argv)],
                                   cwd=ROOT, capture_output=True, encoding='utf-8')
        commands.append(dict(arguments=list(map(str, argv)), returncode=completed.returncode,
                             stdout=completed.stdout.strip(), stderr=completed.stderr.strip()))
        if completed.returncode != expected_code:
            raise ValueError('Unexpected CLI exit: ' + completed.stderr)

    path = out / 'Pantheon.mechanisms.json'
    run('build', '--output', path)
    bundle = json.loads(path.read_text(encoding='utf-8'))
    assert bundle == build_bundle(cache), 'Offline rebuild differs'
    assert len(bundle['cards']) == 5 and len(bundle['interactions']) == 2
    sources = {name: json.loads((cache / ref['evidence_path']).read_bytes())
               for name, ref in bundle['sources'].items()}
    # Primary-source anchors for the cross-champion inferences; not a game test.
    anchors = [
        ('Pantheon', '/data/Pantheon/spells/1/tooltip', 'physical damage'),
        ('Pantheon', '/data/Pantheon/spells/1/tooltip', 'Stunning'),
        ('Pantheon', '/data/Pantheon/spells/2/tooltip', 'non-tower damage'),
        ('Jhin', '/data/Jhin/spells/1/tooltip', 'damaged by an allied champion'),
        ('Jhin', '/data/Jhin/spells/1/description', 'first champion'),
        ('Morgana', '/data/Morgana/spells/2/description', 'absorbs magical damage'),
        ('Morgana', '/data/Morgana/spells/2/tooltip', 'until it breaks'),
    ]
    for name, pointer, text in anchors:
        assert text in resolve_pointer(sources[name], pointer), (name, pointer, text)
    cases = {c['id']: c for c in bundle['interactions']}
    ally = cases['pantheon_jhin_followup']['requires']
    enemy = cases['pantheon_morgana_black_shield']['requires']
    examples = [
        ('ally_met', 'pantheon_jhin_followup', dict(ally), 'conditional_followup'),
        ('ally_unmet', 'pantheon_jhin_followup', dict(ally, jhin_w_available=False), 'route_conditions_not_met'),
        ('ally_unknown', 'pantheon_jhin_followup', {}, 'insufficient_information'),
        ('counter_active', 'pantheon_morgana_black_shield', dict(enemy), 'stun_blocked_by_black_shield'),
        ('counter_absent', 'pantheon_morgana_black_shield', dict(enemy, black_shield_active_on_target_at_w_impact=False), 'this_counter_not_established'),
        ('counter_unknown', 'pantheon_morgana_black_shield', {}, 'insufficient_information'),
    ]
    results = []
    for name, case, facts, expected in examples:
        fact_path, result_path = out / (name + '.facts.json'), out / (name + '.result.json')
        fact_path.write_text(json.dumps(facts, indent=2), encoding='utf-8')
        run('query', '--bundle', path, '--case', case, '--patch', '16.20.1',
            '--facts', fact_path, '--output', result_path)
        result = json.loads(result_path.read_text(encoding='utf-8'))
        assert result['status'] == expected
        assert result['actual_match_observation'] is False and result['decision_input_eligible'] is False
        results.append(dict(name=name, input_kind='synthetic_scenario', status='PASS', result_status=expected))
    invalid_path = out / 'must-not-exist.json'
    run('query', '--bundle', path, '--case', 'pantheon_jhin_followup', '--patch', '16.21.1',
        '--facts', out / 'ally_met.facts.json', '--output', invalid_path, expected_code=1)
    assert not invalid_path.exists()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    run('build', '--output', path, expected_code=2)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    for name, ref in bundle['sources'].items():
        assert hashlib.sha256((cache / ref['evidence_path']).read_bytes()).hexdigest() == ref['sha256']
    report = dict(task='MECH-001', patch=bundle['patch'], source_files_verified=3,
                  source_pointer_checks=len(bundle['source_pointer_checks']), source_anchor_checks=len(anchors),
                  cards=5, interaction_cases=2, offline_rebuild_equal=True,
                  scenarios=results, wrong_version_rejected=True, existing_output_preserved=True,
                  sources_unchanged=True, network_used=False, game_interaction_test=None,
                  independent_review=None, human_signoff=None, commands=commands)
    (out / 'validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key not in ('commands', 'scenarios')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
