"""Recover observed item signatures by joint ID-byte and total-price constraints.

Seeds use stable late inventories, so inventory-footer agreement is calibration,
not an independent test. No inferred item is accepted solely from its price.
"""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from export_replay_ten import load_reviewed
from research_item_byte_model import ITEMS

CATALOG=ROOT/'data/research/inventory_sources/raw/bcd7100b7f6c336f585fccaa28324b9d676bf1b2932ae3bb79ee56b5775c47d6.bin'
SOURCE=Path('C:/Users/21613/Documents/League of Legends/Replays/HN1-11360086609.rofl')


def leb(n):
    b=[]
    while n>=128:b.append((n&127)|128);n>>=7
    return bytes(b+[n])


def compatible(mapping,plain,wire):
    if len(plain)!=len(wire):return False
    trial=dict(mapping);inverse={v:k for k,v in trial.items()}
    for x,y in zip(plain,wire):
        if (x in trial and trial[x]!=y) or (y in inverse and inverse[y]!=x):return False
        trial[x]=y;inverse[y]=x
    return True


def extend(mapping,plain,wire):
    if not compatible(mapping,plain,wire):raise ValueError('Conflicting byte evidence')
    mapping.update(zip(plain,wire))


def main():
    framer,_,_,refs=load_reviewed(ROOT.parent)
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()=='c08c6f1a4a87f1670a6156c6badfca15a21aa13c74eaa18dff5efdc26b94e7e0'
    assert hashlib.sha256(CATALOG.read_bytes()).hexdigest()==CATALOG.stem
    catalog=json.loads(CATALOG.read_text(encoding='utf8'))['data']
    signatures=defaultdict(list)
    for p in framer.packets(SOURCE):
        d=p['payload']
        if p['stream']==1 and p['opcode']==0x25f and len(d) in (14,15) and d[7]==0x34 and d[8]==0x16 and d[0]&1:
            signatures[d[8:14].hex()].append(dict(time=p['time'],entity=hex(p['param']),chunk=p['chunk'],offset=p['offset'],payload_hex=d.hex()))
    item_table={};price_table={};assigned={};seeds=[]
    for item,code in ITEMS.items():
        matching=[sig for sig in signatures if sig.endswith(code)]
        if len(matching)!=1:raise ValueError(f'Seed signature ambiguity {item}: {matching}')
        sig=matching[0];raw=bytes.fromhex(sig)
        price=catalog[str(item)]['gold']['total']
        extend(item_table,leb(item),raw[4:]);extend(price_table,struct.pack('<f',price),raw[:4])
        assigned[sig]=item;seeds.append(dict(item=item,signature=sig,price=price,basis='late inventory/transaction hypothesis'))
    calibration_path=ROOT/'data/research/inventory_calibration.json'
    if calibration_path.exists():
        calibration=json.loads(calibration_path.read_text(encoding='utf8'))
        for code,item in calibration['item_labels'].items():
            extend(item_table,leb(item),bytes.fromhex(code))
            for sig in signatures:
                if not sig.endswith(code):continue
                price=catalog[str(item)]['gold']['total']
                extend(price_table,struct.pack('<f',price),bytes.fromhex(sig)[:4])
                assigned[sig]=item
                seeds.append(dict(item=item,signature=sig,price=price,basis='explicit final-slot calibration; not held-out'))
    rounds=[];candidates={}
    for round_id in range(20):
        added={}
        for sig in signatures:
            raw=bytes.fromhex(sig)
            fits=[]
            for item,data in catalog.items():
                item=int(item);price=data['gold']['total']
                if compatible(item_table,leb(item),raw[4:]) and compatible(price_table,struct.pack('<f',price),raw[:4]):fits.append(item)
            candidates[sig]=fits
            if not fits:raise ValueError(f'No item matches signature {sig}')
            if len(fits)==1 and sig not in assigned:added[sig]=fits[0]
        for sig,item in added.items():
            raw=bytes.fromhex(sig);extend(item_table,leb(item),raw[4:]);extend(price_table,struct.pack('<f',catalog[str(item)]['gold']['total']),raw[:4]);assigned[sig]=item
        rounds.append(dict(round=round_id,new_assignments=added))
        if not added:break
    rows=[dict(signature=sig,item_id=assigned.get(sig),name=catalog[str(assigned[sig])]['name'] if sig in assigned else None,
               candidates=candidates[sig],events=events) for sig,events in signatures.items()]
    result=dict(status='RESEARCH_CANDIDATES',source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
       catalog_sha256=CATALOG.stem,seeds=seeds,item_byte_pairs=item_table,price_byte_pairs=price_table,
       rounds=rounds,signatures=rows,limitation='Joint code/price constraints, seeded by final inventory; slot and timestamp semantics need separate validation.')
    (ROOT/'data/research/inventory_constraints.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(signatures=len(rows),assigned=len(assigned),events=sum(len(v) for v in signatures.values()),
       ambiguous=[dict(signature=x['signature'],candidates=x['candidates']) for x in rows if x['item_id'] is None]),ensure_ascii=False))
    for row in rows:print(row['signature'],row['item_id'],row['name'],len(row['events']))


if __name__=='__main__':main()
