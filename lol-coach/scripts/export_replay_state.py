"""Export source-linked health/resource/gold state from supplied exact-build ROFLs."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lol_coach.replay_fields import read_metadata
from lol_coach.replay_state import VERSION, PROFILE, decode_payload, inverse_table, prefix_state
from export_replay_ten import load_reviewed

ACTORS={
 'c08c6f1a4a87f1670a6156c6badfca15a21aa13c74eaa18dff5efdc26b94e7e0':list(range(0x40000034,0x4000003e)),
 '1c17e0bb43b2629bf73972ddac9c53782abc1c2c32fca2d039c024e6c004aca3':[0x400000ae],
 'f89bb444d046b7e6a9699e6dc83c06861d81e2a6d4c2b7585cc4e35cc9654238':[0x400000ae],
 '63722ae127363373452b24702a855a0f54de1da0be615e661c73c9cb23912f0b':[0x400000ae],
}


def build(source):
    raw=source.read_bytes();sha=hashlib.sha256(raw).hexdigest()
    _,metadata,_=read_metadata(raw)
    if sha not in ACTORS:
        raise ValueError('Actor directory is not verified for this replay hash')
    framer,_,_,refs=load_reviewed(ROOT.parent)
    inverse=inverse_table();updates=[];counts=Counter();unresolved=[]
    for p in framer.packets(source):
        if p['stream']!=1 or p['opcode']!=0x3df:
            continue
        counts['packets']+=1
        reference=dict(stream=p['stream'],chunk=p['chunk'],decompressed_offset=p['offset'],
                       opcode='0x03df',payload_sha256=hashlib.sha256(p['payload']).hexdigest())
        try:decoded=decode_payload(p['payload'],inverse=inverse)
        except ValueError as exc:
            unresolved.append(dict(time_seconds=p['time'],source=reference,error=str(exc)));continue
        counts['bounded_packets']+=1
        counts['opaque_tail_'+str(len(bytes.fromhex(decoded['opaque_tail_hex'])))]+=1
        for record in decoded['records']:
            if record['entity_id'] not in ACTORS[sha]:continue
            values={};field_sources={}
            for group in record['groups']:
                if group['error']:
                    counts['unresolved_named_groups']+=1
                    unresolved.append(dict(time_seconds=p['time'],entity_id=hex(record['entity_id']),
                                           source=reference,group=group['group'],error=group['error']))
                for name,f in group['fields'].items():
                    values[name]=f['value']
                    field_sources[name]=dict(group=group['group'],bit=f['bit'],
                       payload_offset=group['payload_offset']+f['data_offset'],byte_length=f['byte_length'])
                    counts['field_'+name]+=1
            if values:
                updates.append(dict(time_seconds=p['time'],entity_id=hex(record['entity_id']),
                   values=values,field_sources=field_sources,source={**reference,'record_payload_offset':record['payload_offset']},
                   interpretation='replicated_state_update; may repeat a snapshot, not necessarily a new action'))
    if hashlib.sha256(source.read_bytes()).hexdigest()!=sha:
        raise ValueError('Replay changed during extraction')
    return dict(schema='replay-state/v1',version=VERSION,source=str(source),source_sha256=sha,
        game_length_seconds=metadata['gameLength']/1000,
        profile_sha256=hashlib.sha256(PROFILE.read_bytes()).hexdigest(),dependencies=refs,
        scope='Supplied exact-build files only. Resource type is unspecified. No spell, inventory or visibility decoding.',
        units={'health':'health_points','max_health':'health_points','resource':'resource_points',
               'max_resource':'resource_points','current_gold':'gold','total_gold':'gold',
               'experience':'experience_points','level':'level'},
        decision_input_eligible=False,counts=dict(counts),unresolved=unresolved,updates=updates)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--at',type=float)
    args=parser.parse_args()
    if args.output.suffix.lower() != '.json':
        raise ValueError('Output must be a JSON file')
    protected={args.replay.resolve(),PROFILE.resolve(),Path(__file__).resolve(),
               (ROOT/'lol_coach/replay_state.py').resolve()}
    if args.output.resolve() in protected:
        raise ValueError('Cannot overwrite source or decoder')
    result=build(args.replay)
    if args.at is not None:
        if args.at > result['game_length_seconds']:
            raise ValueError('Cutoff exceeds recorded duration')
        state=prefix_state(result['updates'],args.at)
        result={k:v for k,v in result.items() if k not in ('updates','counts','unresolved')}
        result['prefix']=state
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(output=str(args.output),counts=result.get('counts'),cutoff=args.at),ensure_ascii=False))


if __name__=='__main__':main()
