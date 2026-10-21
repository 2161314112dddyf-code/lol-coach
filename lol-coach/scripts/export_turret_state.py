"""Export named towers and their replicated health, retaining undecodable packets."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lol_coach.replay_fields import read_metadata
from lol_coach.replay_state import decode_payload,inverse_table
from lol_coach.turret_identity import decode_name,health_fields,load_profile,prefix_state
from lol_coach.http import save_json
from scripts.export_replay_ten import load_reviewed,reference


def build(replay):
    source=reference(replay);version,metadata,stats=read_metadata(replay.read_bytes())
    framer,_,_,deps=load_reviewed(ROOT.parent);profile=load_profile();inverse=inverse_table()
    packets=sorted(framer.packets(replay),key=lambda p:(p['time'],0 if p['stream']==2 else 1,p['chunk'],p['offset']))
    identities={};events=[];samples=[];destroyed=[];rejected=[]
    for p in packets:
        source_packet={k:p[k] for k in ('stream','chunk','offset','opcode')}
        source_packet['payload_sha256']=hashlib.sha256(p['payload']).hexdigest()
        base=dict(time_seconds=p['time'],entity_id=hex(p['param']),source=source_packet)
        if p['opcode']==0xd8:
            try:identity=decode_name(p['payload'],version=version,profile=profile)
            except ValueError as exc:
                rejected.append(dict(**base,reason=str(exc),payload_hex=p['payload'].hex()));continue
            previous=identities.get(p['param'])
            if previous and previous['identity']['name']!=identity['name']:raise ValueError('Runtime ID identity conflict')
            event=dict(**base,identity=identity)
            identities.setdefault(p['param'],event);events.append(event)
        elif p['opcode']==0x3df:
            for record in decode_payload(p['payload'],version=version,inverse=inverse)['records']:
                entity=record['entity_id']
                if entity not in identities:continue
                values,fields=health_fields(record)
                if values:samples.append(dict(time_seconds=p['time'],entity_id=hex(entity),values=values,
                    source=dict(source_packet,fields=fields),identity_observed_at=identities[entity]['time_seconds']))
        elif p['stream']==1 and p['opcode']==0x269 and p['param'] in identities:
            destroyed.append(dict(**base,event='turret_destruction',
                interpretation='exact-build event-family inference; health and final totals crosscheck',
                payload_hex=p['payload'].hex(),killer=None))
    if reference(replay)!=source:raise ValueError('Replay changed')
    return dict(schema='turret-state/v1',version=version,source=source,decoder_dependencies=deps,
        profile=reference(ROOT/'lol_coach/profiles/turret_names_16_20.json'),
        identity_events=events,health_samples=samples,destruction_events=destroyed,rejected_name_packets=rejected,
        decision_input_eligible=False,limitations=[
            'No name mode 2 decoder; initial unknown identity is never backfilled from a later keyframe',
            'Map12 geometry association does not establish mode, skin or the replay map-ID field',
            'Static positions are reference positions, not decoded runtime coordinates',
            'Health is replicated sampling, not continuous health; no nonhero visibility filter',
            'Nexus, inhibitors, minion identity and objective respawn timers remain unresolved'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--at',type=float)
    args=parser.parse_args()
    protected=[args.replay,ROOT/'lol_coach/profiles/turret_names_16_20.json']
    if args.output.resolve() in {p.resolve() for p in protected}:raise ValueError('Cannot overwrite input')
    result=build(args.replay)
    if args.at is not None:result=prefix_state(result,args.at)
    save_json(args.output,result)
    print(json.dumps(dict(output=str(args.output),identity_events=len(result.get('identity_events',[])),
        health_samples=len(result.get('health_samples',[])),destructions=len(result.get('destruction_events',[])),
        rejected=len(result.get('rejected_name_packets',[])),prefix_objects=len(result.get('objects',{})))))


if __name__=='__main__':main()
