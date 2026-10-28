"""Export named objects and creation positions from the original four replays."""
from collections import Counter
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lol_coach.created_object import decode_creation
from lol_coach.replay_fields import read_metadata
from export_replay_ten import load_reviewed,reference
from export_skill_ranks import STEMS


def main():
    f,*_,deps=load_reviewed(ROOT.parent);summaries=[]
    for stem in STEMS:
        source=Path('C:/Users/21613/Documents/League of Legends/Replays')/(stem+'.rofl')
        ref=reference(source);version,*_=read_metadata(source.read_bytes());events=[];rejected=[];by={};checks=[]
        for p in f.packets(source):
            if p['opcode']!=0x1f3:continue
            actor=hex(p['param']);row=dict(entity_id=actor,time_seconds=p['time'],source=dict(stream=p['stream'],
                chunk=p['chunk'],decompressed_offset=p['offset'],opcode='0x1f3',payload_hex=p['payload'].hex()))
            try:value=decode_creation(p['payload'],version=version)
            except ValueError as exc:rejected.append(dict(**row,reason=str(exc)));continue
            if actor in by:checks.append(dict(entity_id=actor,name_stable=by[actor]==value['model_name']))
            by[actor]=value['model_name'];events.append(dict(**row,identity=value))
        if reference(source)!=ref:raise ValueError('Replay changed')
        summary=dict(replay=stem,records=len(events),entities=len(by),rejected=len(rejected),
            positions=sum(e['identity']['position_xz']is not None for e in events),
            affiliated=sum(e['identity'].get('team_label')is not None for e in events),
            referenced_entities=sum(e['identity'].get('reference_entity_id')is not None for e in events),
            repeated_names=len(checks),name_conflicts=sum(not c['name_stable']for c in checks),
            models=dict(Counter(by.values())))
        bundle=dict(schema='created-objects/v1',source=ref,version=version,dependencies=deps,events=events,
            rejected=rejected,checks=checks,summary=summary,region_visibility_complete=False,
            limitations=['Positions are creation/sync observations, not current moving-object tracks',
                'Team labels and bounded references are inferred; references do not imply ownership',
                'Lifetime and vision-source status unknown; no radius inferred from model name'])
        (ROOT/'data/private/replay_completion'/(stem+'-created-objects.json')).write_text(json.dumps(bundle,indent=2))
        summaries.append(summary)
    (ROOT/'data/private/replay_completion/created_objects_run.json').write_text(json.dumps(summaries,indent=2))
    print(json.dumps(summaries))


if __name__=='__main__':main()
