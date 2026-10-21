"""Explicitly fit footer labels; never call this held-out validation."""
import json
from research_inventory_events import ROOT, replay


def main():
    r=json.loads((ROOT/'data/research/inventory_events.json').read_text(encoding='utf8'))
    initial=json.loads((ROOT/'data/research/inventory_constraints.json').read_text(encoding='utf8'))
    known={x['signature'][-4:]:x['item_id'] for x in initial['signatures'] if x['item_id'] is not None}
    for entity,state in r['final_wire_slots'].items():
        if entity=='0x4000003c':continue
        for i,code in enumerate(state[:7]):
            label=r['footer_calibration_labels'][entity][i]
            if code not in (None,'empty') and label:
                if code in known and known[code]!=label:raise ValueError('Conflicting non-Ryze label')
                known[code]=label
    inverse={value:key for key,value in known.items()}
    models=[]
    for a in range(10):
        for b in range(10):
            state=replay(r['events'],swap_b={'08':a,'0e':b})['0x4000003c']
            labels=r['footer_calibration_labels']['0x4000003c']
            if all((code not in known or known[code]==labels[i]) and
                   (labels[i] not in inverse or inverse[labels[i]]==code)
                   for i,code in enumerate(state[:7])):
                models.append({'08':a,'0e':b})
    if len(models)!=1:raise ValueError(f'Nonunique swap calibration: {models}')
    states=replay(r['events'],swap_b=models[0]);items={};witnesses=[];gaps=[]
    for entity,state in states.items():
        for index,code in enumerate(state[:7]):
            label=r['footer_calibration_labels'][entity][index]
            if code in (None,'empty') or label==0:
                if code not in (None,'empty') and label==0:
                    gaps.append(dict(entity_id=entity,slot=index,wire=code,footer=label,reason='Unexplained consumption/removal; do not label wire as empty'))
                continue
            if code in items and items[code]!=label:raise ValueError('Conflicting footer labels')
            items[code]=label
            witnesses.append(dict(entity_id=entity,slot=index,wire=code,item_id=label))
    result=dict(status='CALIBRATION_NOT_VALIDATION',swap_b=models[0],item_labels=items,
       witnesses=witnesses,unexplained_footer_differences=gaps,
       warning='Footer used to identify item bytes and two slot bytes. Never reverse-fill item ownership from these labels.')
    (ROOT/'data/research/inventory_calibration.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
