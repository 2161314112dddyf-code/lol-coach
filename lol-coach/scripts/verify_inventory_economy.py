"""Cross-check inventory costs against separately decoded replicated gold.

Gold values never participate in fitting item-byte labels in this check.
"""
from bisect import bisect_left,bisect_right
from collections import defaultdict,Counter
import json
from research_inventory_events import ROOT
from research_inventory_constraints import CATALOG


def main():
    r=json.loads((ROOT/'data/research/inventory_events.json').read_text(encoding='utf8'))
    recipes=json.loads((ROOT/'data/research/inventory_recipes.json').read_text(encoding='utf8'))
    cal=json.loads((ROOT/'data/research/inventory_calibration.json').read_text(encoding='utf8'))
    cat=json.loads(CATALOG.read_text(encoding='utf8'))['data']
    ids={code:values[0] for code,values in recipes['candidates'].items() if len(values)==1}
    gold=json.loads((ROOT/'data/private/replay_state/HN1-11360086609.json').read_text(encoding='utf8'))
    if gold['source_sha256']!=r['source_sha256']:raise ValueError('Mismatched replay evidence')
    curves=defaultdict(list);current={}
    for u in gold['updates']:
        values=current.setdefault(u['entity_id'],{})
        if not any('gold' in k for k in u['values']):continue
        values.update({k:v for k,v in u['values'].items() if 'gold' in k})
        if 'current_gold' in values and 'total_gold' in values:
            curves[u['entity_id']].append(dict(time=u['time_seconds'],spent=values['total_gold']-values['current_gold'],source=u['source']))
    groups=[]
    for e in r['events']:
        if not groups or e['entity_id']!=groups[-1][0]['entity_id'] or abs(e['time_seconds']-groups[-1][0]['time_seconds'])>0.002:
            groups.append([])
        groups[-1].append(e)
    states={};checks=[]
    for group in groups:
        entity=group[0]['entity_id'];t=group[0]['time_seconds'];end=group[-1]['time_seconds']
        state=states.setdefault(entity,[None]*10);removed=[];added=[];unknown=False
        for e in group:
            slot=e['slot']
            if e['kind']=='slot_clear':
                if state[slot] is None:unknown=True
                elif state[slot]!=0:removed.append(state[slot])
                state[slot]=0
            elif e['kind']=='slot_update':
                value=ids.get(e['item_wire']) if not e['empty'] else 0
                if value is None:unknown=True
                elif value:added.append(value)
                state[slot]=value
            else:
                other=e['other_slot'] if e['other_slot'] is not None else cal['swap_b'][e['other_slot_wire']]
                state[slot],state[other]=state[other],state[slot]
        if not added and not removed:continue
        expected=(sum(cat[str(i)]['gold']['total'] for i in added)-sum(cat[str(i)]['gold']['total'] for i in removed)
                  if added else -sum(cat[str(i)]['gold']['sell'] for i in removed))
        curve=curves[entity];times=[p['time'] for p in curve]
        before=bisect_left(times,t-1e-7)-1
        first_after=bisect_left(times,end-1e-7)
        after=bisect_right(times,times[first_after]+1e-7)-1 if first_after<len(times) else len(times)-1
        if before<0 or after<=before or times[after]<t-1e-7 or times[after]-end>0.15:
            observed=None;status='INSUFFICIENT_EVIDENCE'
        else:
            observed=curve[after]['spent']-curve[before]['spent']
            status='INSUFFICIENT_EVIDENCE' if unknown else ('PASS' if abs(observed-expected)<0.1 else 'FAIL')
        checks.append(dict(entity_id=entity,time_seconds=t,added_items=added,removed_items=removed,
            expected_net_spend=expected,observed_net_spend=observed,status=status,
            inventory_sources=[e['source'] for e in group],
            gold_before=curve[before] if before>=0 else None,gold_after=curve[after] if after>=0 else None))
    # Two purchases can share one replication update. Compare their sum once,
    # never attribute that whole debit to each individual operation.
    windows=defaultdict(list)
    for check in checks:
        key=(check['entity_id'],check['gold_before']['time'] if check['gold_before'] else None,
             check['gold_after']['time'] if check['gold_after'] else None)
        windows[key].append(check)
    comparisons=[]
    for members in windows.values():
        observed=members[0]['observed_net_spend']
        expected=sum(x['expected_net_spend'] for x in members)
        status=('INSUFFICIENT_EVIDENCE' if any(x['status']=='INSUFFICIENT_EVIDENCE' for x in members)
                else 'PASS' if abs(observed-expected)<0.1 else 'FAIL')
        comparisons.append(dict(status=status,expected_net_spend=expected,observed_net_spend=observed,
           entity_id=members[0]['entity_id'],operation_times=[x['time_seconds'] for x in members]))
    result=dict(acceptance_id='DYN-03',status='INSUFFICIENT_EVIDENCE',source_sha256=r['source_sha256'],
        counts=dict(Counter(x['status'] for x in comparisons)),comparisons=comparisons,checks=checks,
        limitation='Model assumes clears are components when followed by updates, otherwise sales. Failures retained; undo, consumption and sync require separate opcodes.')
    (ROOT/'reports/inventory_economy_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(counts=result['counts'],nonpass=[x for x in comparisons if x['status']!='PASS']),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
