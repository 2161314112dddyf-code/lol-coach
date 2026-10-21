"""Test live 0x2ef as reversal of an observed purchase, independently of KFs."""
from collections import defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from check_replay_semantics import read
from lol_coach.inventory_undo import refund_evidence
from export_replay_ten import reference


def main():
    refs = {}
    stem = 'HN1-11360086609'
    inv = read(f'data/private/replay_inventory/{stem}.json', refs)
    extended = read(f'data/private/remaining_decode/{stem}.json', refs)
    state = read(f'data/private/replay_state/{stem}.json', refs)
    refs['original_replay'] = reference(Path(inv['source']))
    if not (refs['original_replay']['sha256'] == inv['source_sha256']
            == extended['source']['sha256'] == state['source_sha256']):
        raise ValueError('Mismatched inventory/state sources')
    events, cps, gold = inv['events'], extended['inventory_checkpoints'], state['updates']
    profile = read('lol_coach/profiles/inventory_16_20.json', refs)
    prices = {v['item_id']: v['total_price'] for v in profile['items'].values()}
    prices[0] = 0
    states, transactions = defaultdict(dict), defaultdict(list)
    for cp in cps:
        if cp['time_seconds'] == 0:
            states[cp['entity_id']].update({i['slot']: i['item_id'] for i in cp['items'] if i['slot'] < 6})
    grouped = defaultdict(list)
    for e in events:
        grouped[e['time_seconds'], e['entity_id']].append(e)
    timeline = [(t, a, 'operations', rows) for (t, a), rows in grouped.items()]
    timeline += [(c['time_seconds'], c['entity_id'], 'sync', c) for c in cps if c['source']['stream'] == 1]
    results = []
    for time, actor, kind, rows in sorted(timeline, key=lambda x: x[0]):
        slots = states[actor]
        if kind == 'operations':
            before = dict(slots)
            for e in rows:
                if e['kind'] == 'slot_update':
                    slots[e['slot']] = e['item_id']
                elif e['kind'] == 'slot_clear':
                    slots[e['slot']] = 0
                elif e['kind'] == 'slot_swap':
                    a, b = e['slot'], e['other_slot']
                    slots[a], slots[b] = slots.get(b), slots.get(a)
            purchases = [e for e in rows if e['kind'] == 'slot_update' and e['outer_flag'] == 1]
            if len(purchases) == 1 and all(before.get(i) in prices and slots.get(i) in prices for i in range(6)):
                paid = sum(prices[slots[i]]-prices[before[i]] for i in range(6))
                transactions[actor].append(dict(time_seconds=time, before=before, after=dict(slots),
                    price_from_components=paid, operations=rows, undone=False))
            continue
        # This is a hypothesis under test. Missing records are not globally
        # converted to empty: require a matching historical pre-purchase state.
        observed = {i['slot']: i['item_id'] for i in rows['items'] if i['slot'] < 6}
        candidates = [tr for tr in transactions[actor] if not tr['undone'] and 0 <= time-tr['time_seconds'] < 30
            and all(tr['after'].get(i) == slots.get(i) for i in range(6))
            and all(tr['before'].get(i) == observed.get(i, 0) for i in range(6))]
        trace = dict(checkpoint=rows, candidate_count=len(candidates), status='INSUFFICIENT_EVIDENCE')
        if len(candidates) == 1:
            tr = candidates[0]
            observations = [e for e in gold if e['entity_id'] == actor and 'current_gold' in e['values']]
            pairs = [(a,b) for a,b in zip(observations, observations[1:])
                     if time <= b['time_seconds'] <= time+0.15 and a['time_seconds'] < time]
            trace.update(transaction=tr.copy(), expected_refund=tr['price_from_components'])
            if len(pairs) == 1:
                a, b = pairs[0]
                refund = b['values']['current_gold']-a['values']['current_gold']
                residual = refund-tr['price_from_components']
                # Use independently decoded cumulative income; do not assume
                # the 3-gold residual is passive income just because it fits.
                def with_income(row):
                    prior = [e for e in gold if e['entity_id'] == actor
                             and e['time_seconds'] <= row['time_seconds'] and 'total_gold' in e['values']]
                    if not prior:
                        raise ValueError('No cumulative-income evidence')
                    return {**row, 'values': {**row['values'], 'total_gold': prior[-1]['values']['total_gold']},
                            'total_gold_source': prior[-1]}
                a, b = with_income(a), with_income(b)
                comparison = refund_evidence(a, b, tr['price_from_components'])
                trace.update(gold_before=a, gold_after=b, observed_gold_delta=refund,
                    residual_gold=residual,
                    refund_crosscheck=comparison, status=comparison['status'])
                if comparison['status'] == 'PASS':
                    tr['undone'] = True
                    states[actor] = dict(tr['before'])
                    trace['restored_main_slots'] = {i: states[actor][i] for i in range(6)}
                    trace['evidence_available_at'] = comparison['evidence_available_at']
        results.append(trace)
    for ref in refs.values():
        if reference(Path(ref['path']))['sha256'] != ref['sha256']:
            raise ValueError('Input changed')
    output = ROOT/'data/private/replay_semantics/inventory_undo.json'
    output.write_text(json.dumps(dict(results=results, sources=refs,
        version='16.20.824.8524', decision_input_eligible=False,
        limitation='Six live reversal cases with history and net-refund witnesses. Only main slots 0..5; not general inventory coverage or keyframe semantics.'), indent=2), encoding='utf8')
    print(json.dumps([dict(time=round(e['checkpoint']['time_seconds'],3), candidates=e['candidate_count'],
        expected=e.get('expected_refund'), observed=e.get('observed_gold_delta'), residual=e.get('residual_gold'),
        status=e['status']) for e in results]))


if __name__ == '__main__':
    main()
