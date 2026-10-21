"""Reproducible cross-field research; counterexamples are output, not hidden."""
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from export_skill_ranks import STEMS
from export_replay_ten import reference


def read(relative, refs):
    path = ROOT/relative
    refs[str(relative)] = reference(path)
    return json.loads(path.read_text(encoding='utf8'))


def skill_checks(stem, refs):
    bundle = read(f'data/private/skill_ranks/{stem}.json', refs)
    state = read(f'data/private/replay_state/{stem}.json', refs)
    if bundle['source_sha256'] != state['source_sha256'] or bundle['version'] != state['version']:
        raise ValueError('Mismatched skill/state sources')
    initial = {(e['entity_id'], e['slot']): e['rank'] for e in bundle['keyframes'] if e['time_seconds'] == 0}
    current = dict(initial)
    increments, budgets, snapshots = [], [], []
    for event in bundle['events']:
        key = event['entity_id'], event['slot']
        before = current.get(key)
        current[key] = event['rank']
        increments.append(dict(event=event, prior_rank=before,
            status='PASS' if before is not None and event['rank'] == before+1 else 'INSUFFICIENT_EVIDENCE'))
        if not event['known_hero']:
            continue
        levels = [e for e in state['updates'] if e['entity_id'] == event['entity_id']
                  and e['time_seconds'] <= event['time_seconds'] and 'level' in e['values']]
        if not levels:
            budgets.append(dict(event=event, status='INSUFFICIENT_EVIDENCE'))
            continue
        # Compare changes from the serialized initial ranks, so auto-granted
        # slots (notably Aphelios R) do not count as spent allocation points.
        spent = sum(v-initial[k] for k, v in current.items() if k[0] == key[0] and k in initial)
        level = levels[-1]['values']['level']
        points = event['unspent_points_observation']
        budgets.append(dict(event=event, spent=spent, level=level,
            status='PASS' if spent+points == level else 'FAIL', level_source=levels[-1]))
    for event in bundle['keyframes']:
        if event['time_seconds'] == 0:
            continue
        key = event['entity_id'], event['slot']
        prior = [e for e in bundle['events'] if (e['entity_id'], e['slot']) == key
                 and e['time_seconds'] <= event['time_seconds']]
        expected = prior[-1]['rank'] if prior else initial.get(key)
        snapshots.append(dict(event=event, expected_rank=expected,
            status='PASS' if event['rank'] == expected else 'FAIL',
            live_source=prior[-1] if prior else None))
    return dict(replay=stem, increment_counts=dict(Counter(e['status'] for e in increments)),
        budget_counts=dict(Counter(e['status'] for e in budgets)),
        keyframe_counts=dict(Counter(e['status'] for e in snapshots)),
        keyframe_counts_by_actor={actor: dict(Counter(e['status'] for e in snapshots
            if e['event']['entity_id'] == actor)) for actor in sorted({e['event']['entity_id'] for e in snapshots})},
        increments=increments, budgets=budgets, keyframes=snapshots)


def inventory_probe(refs):
    stem = STEMS[0]
    inventory = read(f'data/private/replay_inventory/{stem}.json', refs)
    checkpoints = read(f'data/private/remaining_decode/{stem}.json', refs)['inventory_checkpoints']
    updates = read(f'data/private/replay_state/{stem}.json', refs)['updates']
    results = []
    for checkpoint in checkpoints:
        if checkpoint['source']['stream'] != 1:
            continue
        actor, time = checkpoint['entity_id'], checkpoint['time_seconds']
        related = [e for e in inventory['events'] if e['entity_id'] == actor and time-25 <= e['time_seconds'] <= time+6]
        gold = [e for e in updates if e['entity_id'] == actor and time-1 <= e['time_seconds'] <= time+1 and 'current_gold' in e['values']]
        results.append(dict(checkpoint=checkpoint, nearby_operations=related, nearby_gold=gold))
    return results


def main():
    refs = {}
    skills = [skill_checks(stem, refs) for stem in STEMS]
    inventory = inventory_probe(refs)
    for ref in refs.values():
        if reference(Path(ref['path']))['sha256'] != ref['sha256']:
            raise ValueError('Input changed')
    result = dict(skills=skills, inventory=inventory, sources=refs,
                  evidence_level='cross_field_binary_inference; not independent gameplay verification')
    output = ROOT/'data/private/replay_semantics/cross_checks.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding='utf8')
    print(json.dumps([{k: v for k, v in s.items() if k.endswith('counts') or k == 'replay'} for s in skills]))
    for row in inventory:
        cp = row['checkpoint']
        print('SYNC', cp['entity_id'], round(cp['time_seconds'], 3),
              [(e['slot'], e['item_id']) for e in cp['items'] if not e['empty']])
        print('OPS', [(round(e['time_seconds'], 3), e['kind'], e.get('slot'), e.get('item_id')) for e in row['nearby_operations']])
        print('GOLD', [(round(e['time_seconds'], 3), round(e['values']['current_gold'], 2)) for e in row['nearby_gold']])


if __name__ == '__main__':
    main()
