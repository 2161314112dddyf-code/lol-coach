"""Add a statically named Map12 relic, using the first observation per mode."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from export_replay_ten import load_reviewed,reference
from research_neutral_strings import compatible,reorder


def main():
    path=ROOT/'lol_coach/profiles/neutral_names_16_20.json';profile=json.loads(path.read_text())
    static=ROOT/'data/research/world_sources/raw/796314255a582977e917bb59d8d6dbfdcd9c1f1f839e9efdde14bda7e037526c.bin'
    config=json.loads(static.read_text());name='HA_AP_HealthRelic';key='Characters/'+name
    if config[key]['name']!=name:raise ValueError('Static relic name mismatch')
    f,*_=load_reviewed(ROOT.parent);source=Path('C:/Users/21613/Documents/League of Legends/Replays/HN1-11360086609.rofl')
    anchors=[];covered=set()
    for row in f.packets(source):
        if row['opcode']!=0x2df:continue
        d=row['payload'];mode=str(int.from_bytes(d[:4],'little')>>12&3)
        if mode in covered or mode not in profile['modes']:continue
        spec=profile['modes'][mode];table={int(k):v for k,v in spec['byte_pairs'].items()};candidates=[]
        for start in range(4,min(80,len(d)-len(name))):
            if spec['length_pairs'].get(str(d[start-1]))!=len(name):continue
            updated=compatible(name,reorder(d[start:start+len(name)],spec['order']),table)
            if updated is not None:candidates.append((start,updated))
        if len(candidates)!=1:raise ValueError('Ambiguous relic anchor')
        start,updated=candidates[0];spec['byte_pairs']=updated;covered.add(mode)
        anchors.append(dict(entity_id=hex(row['param']),time_seconds=row['time'],mode=mode,
            chunk=row['chunk'],offset=row['offset'],payload_hex=d.hex(),name_start=start))
    profile['model_names']=sorted(set(profile['model_names']+[name]))
    profile['character_records']={n:('Characters/'+n if n==name else f'Characters/{n}/CharacterRecords/Root')for n in profile['model_names']}
    profile['relic_calibration_scope']=f'First {len(anchors)} Map12 observations, one per supported mode; remaining relic observations withheld'
    path.write_text(json.dumps(profile,indent=2)+'\n',encoding='utf8')
    (ROOT/'data/private/replay_completion/relic_name_calibration.json').write_text(json.dumps(dict(anchors=anchors,source=reference(source),static=reference(static)),indent=2))
    print(json.dumps(dict(anchors=len(anchors),modes=sorted(covered))))


if __name__=='__main__':main()
