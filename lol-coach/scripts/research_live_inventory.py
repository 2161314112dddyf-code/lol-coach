"""Crosscheck new inventory messages against independent operation history."""
import json
from collections import defaultdict, Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.inventory_use import decode_use
from lol_coach.inventory_undo import refund_evidence


def read(path):
    return json.loads((ROOT/path).read_text(encoding='utf8'))


def source_order(row):
    s = row.get('source', row)
    return s['chunk'], s.get('decompressed_offset', s.get('offset'))


def main():
    stem = 'HN1-11360086609'
    inventory = read(f'data/private/replay_inventory/{stem}.json')
    checkpoints = read(f'data/private/remaining_decode/{stem}.json')['inventory_checkpoints']
    undos = read('data/private/replay_semantics/inventory_undo.json')['results']
    full = read('data/private/replay_completion/4e9_decoded.json')['rows']
    uses = read('data/private/replay_completion/3f1_candidates.json')
    gold = read(f'data/private/replay_state/{stem}.json')['updates']
    states = defaultdict(dict)
    for cp in checkpoints:
        if cp['time_seconds'] == 0:
            states[cp['entity_id']].update({i['slot']: i['item_id'] for i in cp['items']})
    compound = read(f'data/private/replay_completion/{stem}-compound-inventory.json')
    for cp in compound['events']:
        if cp['time_seconds'] == 0:
            states[cp['entity_id']].update({i['slot']:i['item_id'] for i in cp['items']})
    timeline = [(source_order(e), 'operation', e) for e in inventory['events']]
    timeline += [(source_order(e['checkpoint']), 'undo', e) for e in undos if e['status'] == 'PASS']
    timeline += [(source_order(e), 'full', e) for e in full]
    timeline += [(source_order(e), 'use', e) for e in uses]
    comparisons = []; use_rows = []; reversals=[]
    for _, kind, e in sorted(timeline, key=lambda x: x[0]):
        actor = e.get('entity_id', hex(e.get('param', 0)))
        if kind == 'undo':
            actor = e['checkpoint']['entity_id']
            states[actor].update({int(k): v for k,v in e['restored_main_slots'].items()})
            continue
        state = states[actor]
        if kind == 'operation':
            if e['kind'] == 'slot_update': state[e['slot']] = e['item_id']
            elif e['kind'] == 'slot_clear': state[e['slot']] = 0
            else:
                a,b = e['slot'],e['other_slot']
                state[a],state[b] = state.get(b),state.get(a)
        elif kind == 'use':
            try:
                decoded = decode_use(bytes.fromhex(e['payload']))
            except ValueError as exc:
                use_rows.append({**e, 'accepted':False, 'reason':str(exc), 'item_present':False})
                continue
            item_id = state.get(decoded['slot'])
            use_rows.append({**e, **decoded, 'item_id_before':item_id,
                'item_present':item_id not in (0,None)})
            if decoded['clears_slot']: state[decoded['slot']] = 0
        else:
            observed = {i['slot']: i['item_id'] for i in e['decoded']['items']}
            bad = [(s,state.get(s),observed.get(s,0)) for s in range(7)
                   if state.get(s) != observed.get(s,0)]
            comparisons.append(dict(time=e['time'],actor=actor,source_order=source_order(e),
                bad=bad, observed=observed, operation_state=state.copy()))
            if actor=='0x4000003b' and bad==[(0,1037,0)]:
                balances=[g for g in gold if g['entity_id']==actor and 'current_gold'in g['values']]
                pairs=[(a,b)for a,b in zip(balances,balances[1:])if a['time_seconds']<e['time']<=b['time_seconds']<e['time']+.15]
                if len(pairs)==1:
                    def with_income(g):
                        prior=[q for q in gold if q['entity_id']==actor and q['time_seconds']<=g['time_seconds'] and 'total_gold'in q['values']]
                        return {**g,'values':{**g['values'],'total_gold':prior[-1]['values']['total_gold']}}
                    a,b=map(with_income,pairs[0]);check=refund_evidence(a,b,875)
                    reversals.append(dict(snapshot=e,gold_before=a,gold_after=b,check=check,
                        scope='One observed Pickaxe reversal; not a blanket meaning for 0x4e9'))
            # Deliberately do not synchronize state from the observation being tested.
    result = dict(comparisons=comparisons, uses=use_rows,additional_reversals=reversals,
        summary=dict(full_packets=len(comparisons), exact_seven_slots=sum(not r['bad'] for r in comparisons),
            use_packets=len(use_rows), uses_with_item=sum(r['item_present'] for r in use_rows),
            independently_explained_reversals=sum(r['check']['status']=='PASS'for r in reversals),
            used_items=dict(Counter(r.get('item_id_before') for r in use_rows))),
        limitation='Inventory identities crosschecked without resetting history from 0x4e9; charges and item cooldown not covered.')
    (ROOT/'data/private/replay_completion/live_inventory_validation.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps(result['summary']))
    print(json.dumps([r for r in comparisons if r['bad']][:5]))
    print(json.dumps([r for r in use_rows if not r['item_present']][:5]))


if __name__ == '__main__': main()
