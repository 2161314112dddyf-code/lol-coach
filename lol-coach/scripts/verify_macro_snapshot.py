"""Real cached replay integration checks; not independent game UI validation."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.macro_snapshot import build_snapshot, order, SCHEMA
from export_macro_snapshot import load_inputs


def prefix_inputs(bundles, at):
    ten, state, inv, vision = bundles
    categories = dict(ten['categories'])
    categories['movement'] = {'events': [e for e in categories['movement']['events'] if e['time_seconds'] <= at]}
    categories['lifecycle'] = {'events': [e for e in categories['lifecycle']['events'] if e['time_seconds'] <= at]}
    categories['kills'] = [e for e in categories['kills'] if e['time_seconds'] <= at]
    # Poison final performance/configuration; only roster metadata is permitted.
    for key in ('inventory', 'economy', 'combat_totals', 'loadouts', 'creep_score'):
        categories[key] = [{'future_secret': 'MUST_NOT_APPEAR'}]
    return [{**ten, 'categories': categories},
        {**state, 'updates': [e for e in state['updates'] if e['time_seconds'] <= at]},
        {**inv, **{k: [e for e in inv[k] if e['time_seconds'] <= at] for k in ('events', 'unresolved', 'state_barriers')}},
        {**vision, 'events': [e for e in vision['events'] if e['time_seconds'] <= at], 'intervals': []}]


def main():
    checks, manifests = [], []
    samples_checked = 0
    for replay_id in ('HN1-11360086609', 'HN1-11363048522', 'HN1-11363093470', 'HN1-11372643015'):
        bundles, inputs = load_inputs(replay_id)
        vision = bundles[3]
        source = Path(vision['source'])
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        assert before == vision['source_sha256']
        queries = [(50, 100, None)]
        if replay_id == 'HN1-11360086609':
            queries += [(41.1, 200, None), (400, 100, '0x40000034'), (400, 200, '0x4000003b')]
        for at, team, player in queries:
            result = build_snapshot(*bundles, at=at, team=team, player=player)
            truncated = build_snapshot(*prefix_inputs(bundles, at), at=at, team=team, player=player)
            assert result == truncated, 'Future/footer leakage'
            for ev in result['evidence'].values():
                assert ev['time_seconds'] <= at
            for hero in result['heroes']:
                if hero['relation'] == 'enemy' and hero['visibility']['value'] is not True:
                    assert hero['observed_now'] is None and hero['position_candidate'] is None
                if hero['entity_id'] != player:
                    assert hero['private_economy']['value'] is None
                    assert hero['inventory']['recent_self_operations'] == []
                assert hero['inventory']['current_slots'] is None
                observations = list(hero['last_observed'].values())
                if hero['last_observed_position']:
                    observations.append(hero['last_observed_position'])
                for sample in observations:
                    ev = result['evidence'][sample['evidence_id']]
                    assert sample['observed_at_seconds'] <= at
                    assert sample['age_seconds'] == at-sample['observed_at_seconds']
                    if hero['relation'] == 'enemy':
                        # Independently select last relevant visibility packet before sample.
                        eligible = [v for v in vision['events'] if v['entity_id'] == hero['entity_id']
                            and v['observer_team_id'] in (None, team) and order(v) <= order(ev)]
                        assert eligible and max(eligible, key=order)['visible'] is True
                    samples_checked += 1
            if replay_id == 'HN1-11360086609' and at == 41.1:
                aphelios = next(h for h in result['heroes'] if h['champion'] == 'Aphelios')
                assert aphelios['visibility']['value'] is False and aphelios['observed_now'] is None
                assert abs(aphelios['last_observed']['health']['value']-662.1997680664062) < 0.001
            checks.append(dict(replay_id=replay_id, at_seconds=at, observer_team_id=team,
                actors=len(result['heroes']), evidence_count=len(result['evidence']), status='PASS',
                checks=['prefix_invariance', 'final_metadata_exclusion', 'sample_visibility_and_age',
                        'private_field_exclusion', 'unknown_inventory_preserved']))
        after = hashlib.sha256(source.read_bytes()).hexdigest()
        assert after == before
        manifests.append(dict(replay_id=replay_id, source_sha256=before, source_unchanged=True, inputs=inputs))
    report = dict(target_version=SCHEMA, executed_by='Codex', source='target_claim',
        evidence_level='REPRODUCED', scope='Existing real replay exports, prefix and knowledge integration',
        checks=checks, observed_samples_checked=samples_checked, sources=manifests,
        limitations=['No independent UI verification', 'Incomplete world and mechanics remain unknown'],
        signer=None)
    path = ROOT/'reports/macro_snapshot_real_validation.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(dict(queries=len(checks), observed_samples_checked=samples_checked,
                         status='PASS', report=str(path))))


if __name__ == '__main__':
    main()
