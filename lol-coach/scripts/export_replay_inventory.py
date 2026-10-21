"""Export bounded inventory operations; do not assert a complete slot state."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lol_coach.replay_inventory import VERSION,PROFILE,load_profile,decode_payload
from lol_coach.replay_fields import read_metadata
from export_replay_state import ACTORS
from export_replay_ten import load_reviewed


def build(source,at=None):
    raw=source.read_bytes();sha=hashlib.sha256(raw).hexdigest()
    version,metadata,_=read_metadata(raw)
    if version!=VERSION or sha not in ACTORS:raise ValueError('Unsupported replay build/hash')
    if at is not None and (not math.isfinite(at) or at<0 or at>metadata['gameLength']/1000):
        raise ValueError('Invalid cutoff')
    framer,_,_,refs=load_reviewed(ROOT.parent);profile=load_profile()
    events=[];unresolved=[];barriers=[];counts=Counter()
    for p in framer.packets(source):
        if p['stream']!=1 or p['param'] not in ACTORS[sha] or (at is not None and p['time']>at):continue
        reference=dict(stream=1,chunk=p['chunk'],decompressed_offset=p['offset'],opcode=hex(p['opcode']),
                       payload_hex=p['payload'].hex(),payload_sha256=hashlib.sha256(p['payload']).hexdigest())
        base=dict(time_seconds=p['time'],entity_id=hex(p['param']),source=reference)
        if p['opcode']==0x2ef:
            barriers.append({**base,'reason':'Inventory resynchronization/undo candidate; complete state reconstruction unsafe'})
        if p['opcode'] not in (0x25f,0x132,0x66):continue
        counts['packets']+=1
        try:e=decode_payload(p['opcode'],p['payload'],version=version,profile=profile)
        except ValueError as exc:
            unresolved.append({**base,'error':str(exc)});continue
        events.append({**base,**e});counts[e['kind']]+=1
        if e['kind']=='slot_update' and e['item_id'] is None:counts['unknown_item']+=1
    if hashlib.sha256(source.read_bytes()).hexdigest()!=sha:raise ValueError('Source changed')
    return dict(schema='replay-inventory-operations/v1',version=version,source=str(source),source_sha256=sha,
       profile_sha256=hashlib.sha256(PROFILE.read_bytes()).hexdigest(),dependencies=refs,cutoff_seconds=at,
       decision_input_eligible=False,complete_inventory_state=False,counts=dict(counts),events=events,
       unresolved=unresolved,state_barriers=barriers,
       limitations=profile['limitations'],calibration=profile['calibration'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--at',type=float)
    args=parser.parse_args()
    if args.output.suffix.lower()!='.json':raise ValueError('Output must be JSON')
    if args.output.resolve() in (PROFILE.resolve(),args.replay.resolve()):raise ValueError('Cannot overwrite source/profile')
    if ROOT/'lol_coach' in args.output.resolve().parents:raise ValueError('Cannot overwrite package files')
    result=build(args.replay,args.at)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(output=str(args.output),counts=result['counts'],unresolved=len(result['unresolved']),state_barriers=len(result['state_barriers'])),ensure_ascii=False))


if __name__=='__main__':main()
