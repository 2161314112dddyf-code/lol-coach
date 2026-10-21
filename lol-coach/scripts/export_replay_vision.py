"""Export hero visibility transitions/intervals or an observer-team prefix."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lol_coach.replay_fields import read_metadata
from lol_coach.replay_vision import VERSION,PROFILE,load_profile,decode_payload,intervals,visibility_at,known_enemy_state,validate_cutoff
from export_replay_state import ACTORS
from export_replay_ten import load_reviewed


def build(source):
    raw=source.read_bytes();sha=hashlib.sha256(raw).hexdigest();version,metadata,stats=read_metadata(raw)
    if sha not in ACTORS or version!=VERSION:raise ValueError('Unsupported replay build/hash')
    profile=load_profile();framer,_,_,refs=load_reviewed(ROOT.parent)
    actors=[dict(entity_id=hex(entity),champion=stats[i]['SKIN'] if stats else None,
                 team_id=int(stats[i]['TEAM']) if stats else None) for i,entity in enumerate(ACTORS[sha])]
    events=[];counts=Counter();unresolved=[]
    for p in framer.packets(source):
        if p['stream']!=1 or p['opcode'] not in (0x3cd,0x484):continue
        counts['all_object_messages']+=1
        if p['param'] not in ACTORS[sha]:continue
        source_ref=dict(stream=1,chunk=p['chunk'],decompressed_offset=p['offset'],opcode=hex(p['opcode']),
            payload_hex=p['payload'].hex(),payload_sha256=hashlib.sha256(p['payload']).hexdigest())
        base=dict(time_seconds=p['time'],entity_id=hex(p['param']),source=source_ref)
        try:fields=decode_payload(p['opcode'],p['payload'],version=version,profile=profile)
        except ValueError as exc:
            unresolved.append({**base,'error':str(exc)})
            fields=dict(observer_team_id=None,visible=None,kind='visibility_unknown_barrier')
        events.append({**base,**fields});counts[fields['kind']]+=1
    if hashlib.sha256(source.read_bytes()).hexdigest()!=sha:raise ValueError('Source changed')
    end=metadata['gameLength']/1000
    return dict(schema='replay-hero-visibility/v1',version=version,source=str(source),source_sha256=sha,
        profile_sha256=hashlib.sha256(PROFILE.read_bytes()).hexdigest(),dependencies=refs,
        game_length_seconds=end,actors=actors,events=events,
        intervals=intervals(events,[a['entity_id'] for a in actors],end),counts=dict(counts),unresolved=unresolved,
        evidence_level='cross_checked_binary_inference',scope=profile['scope'],limitations=profile['limitations'],
        decision_input_eligible=False,hero_visibility_filter_supported=True,complete_world_vision=False)


def prefix(bundle,at,observer_team_id,state=None):
    validate_cutoff(at,bundle['game_length_seconds'])
    actors=[a for a in bundle['actors'] if a['team_id']!=observer_team_id]
    ids=[a['entity_id'] for a in actors]
    events=[e for e in bundle['events'] if e['time_seconds']<=at]
    result=dict(schema='replay-hero-visibility-prefix/v1',version=bundle['version'],source_sha256=bundle['source_sha256'],
        profile_sha256=bundle['profile_sha256'],cutoff_seconds=at,observer_team_id=observer_team_id,
        actors=actors,visibility=visibility_at(events,at,observer_team_id,ids),
        hero_visibility_filter_supported=True,complete_world_vision=False,decision_input_eligible=False,
        limitations=bundle['limitations'])
    if state is not None:
        if state.get('schema')!='replay-state/v1' or 'updates' not in state or state['source_sha256']!=bundle['source_sha256'] or state['version']!=bundle['version']:
            raise ValueError('State input is not the matching complete state export')
        result['observed_enemy_state']=known_enemy_state(events,state['updates'],at,observer_team_id,ids)
        result['excluded_enemy_fields']=['current_gold','total_gold','experience','movement_plan','hidden_state']
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--at',type=float)
    parser.add_argument('--team',type=int,choices=(100,200))
    parser.add_argument('--state',type=Path,help='Optional matching export_replay_state JSON; only with --at/--team')
    args=parser.parse_args()
    if (args.at is None)!=(args.team is None) or (args.state and args.at is None):raise ValueError('Use --at and --team together; --state requires both')
    if args.output.suffix.lower()!='.json':raise ValueError('Output must be JSON')
    protected=[args.replay.resolve(),PROFILE.resolve()]+([args.state.resolve()] if args.state else [])
    if args.output.resolve() in protected or ROOT/'lol_coach' in args.output.resolve().parents:raise ValueError('Cannot overwrite input/package')
    result=build(args.replay)
    if args.at is not None:
        state=json.loads(args.state.read_text(encoding='utf8')) if args.state else None
        result=prefix(result,args.at,args.team,state)
        if args.state:result['state_input_sha256']=hashlib.sha256(args.state.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(output=str(args.output),counts=result.get('counts'),cutoff=args.at,team=args.team),ensure_ascii=False))


if __name__=='__main__':main()
