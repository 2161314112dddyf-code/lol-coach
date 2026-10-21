"""Bound observed inventory shapes. Wire items stay identifiable without names.

This is research output: byte/slot hypotheses are explicit, unsupported branches
are retained, and no inventory state is asserted complete or visible.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.replay_fields import read_metadata
from export_replay_ten import load_reviewed
from research_inventory_constraints import SOURCE

from lol_coach.replay_inventory import SLOTS, SLOT_CONSTANTS, take, slot, item, decode_raw as decode


def replay(events, *, swap_b=None):
    states = {}
    for e in events:
        state = states.setdefault(e['entity_id'],[None]*10)
        index = e['slot']
        if e['kind']=='slot_update':
            state[index] = e['item_wire'] if not e['empty'] else 'empty'
        elif e['kind']=='slot_clear':
            state[index] = 'empty'
        else:
            other = e['other_slot']
            if other is None and swap_b is not None:
                other=swap_b.get(e['other_slot_wire'])
            if other is None:
                # An unknown swap partner can invalidate any slot. Never keep
                # a previous slot assignment as certain after an unresolved op.
                state[:] = [None]*10
            else:
                state[index],state[other] = state[other],state[index]
    return states


def main():
    raw=SOURCE.read_bytes();sha=hashlib.sha256(raw).hexdigest()
    if sha!='c08c6f1a4a87f1670a6156c6badfca15a21aa13c74eaa18dff5efdc26b94e7e0':
        raise ValueError('Unexpected source hash')
    version,_,stats=read_metadata(raw)
    framer,_,_,refs=load_reviewed(ROOT.parent)
    constraints=json.loads((ROOT/'data/research/inventory_constraints.json').read_text(encoding='utf8'))
    signatures={x['signature']:x for x in constraints['signatures']}
    events=[];failures=[];counts=Counter()
    for p in framer.packets(SOURCE):
        if p['stream']!=1 or p['opcode'] not in (0x25f,0x132,0x66) or not 0x40000034<=p['param']<=0x4000003d:
            continue
        counts[hex(p['opcode'])]+=1
        reference=dict(stream=1,chunk=p['chunk'],decompressed_offset=p['offset'],
                       opcode=hex(p['opcode']),payload_hex=p['payload'].hex())
        try:e=decode(p['opcode'],p['payload'])
        except ValueError as exc:
            failures.append(dict(time_seconds=p['time'],entity_id=hex(p['param']),source=reference,error=str(exc)))
            continue
        if e['kind']=='slot_update':
            sig=(e['price_wire'] or '')+(e['item_wire'] or '')
            row=signatures.get(sig,{})
            e['item_id']=row.get('item_id')
            e['item_candidates']=row.get('candidates',[])
            e['name_basis']='catalog/byte constraints with disclosed final-inventory calibration' if row else 'unresolved'
        e.update(time_seconds=p['time'],entity_id=hex(p['param']),source=reference)
        events.append(e)
    states=replay(events)
    footer={hex(0x40000034+i):[int(s[f'ITEM{j}']) for j in range(7)] for i,s in enumerate(stats)}
    result=dict(status='RESEARCH_PARTIAL',version=version,source_sha256=sha,dependencies=refs,
       decision_input_eligible=False,counts=dict(counts),events=events,failures=failures,
       final_wire_slots=states,footer_calibration_labels=footer,
       limitations=['Initial slots unknown. Unresolved swap invalidates slot state.',
          'No purchase/sale inference; slot updates may be free grants or transforms.',
          'Only observed payload shapes. Slot semantics derived from inventory records.',
          'Footer labels are calibration, never an independent final-inventory test.',
          'Keyframe inventory timing/view discrepancy unresolved.'])
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest()!=sha:raise ValueError('Source changed')
    (ROOT/'data/research/inventory_events.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(counts=dict(counts),bounded=len(events),failures=failures,final_wire_slots=states,footer=footer),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
