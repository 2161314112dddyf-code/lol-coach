"""Constrain model-name bytes using live packets, reserving all keyframes."""
import json
from pathlib import Path
from research_neutral_strings import compatible, reorder
ROOT=Path(__file__).resolve().parents[1]


def main():
    doc=json.loads((ROOT/'data/private/replay_completion/neutral_string_candidates.json').read_text())
    rows=[r for r in doc['rows']if r['stream']==1]
    lengths={i:{}for i in range(3)};sizes={i:{}for i in range(3)}
    tables={i:dict((int(k),v)for k,v in t['table'].items())for i,t in enumerate(doc['tables'])}
    resolved=[];pending=rows[:];extra_keyframes=[]
    while pending:
        progress=False;left=[]
        for row in pending:
            options=[c for c in row['candidates']if lengths[c['mode']].get(c['length_wire'],len(c['name']))==len(c['name'])
                and sizes[c['mode']].get(len(c['name']),c['length_wire'])==c['length_wire']]
            if len(options)!=1:left.append(row);continue
            c=options[0];i=c['mode'];name=c['name'];wire=reorder(bytes.fromhex(row['payload'])[c['start']:c['end']],doc['tables'][i]['order'])
            table=compatible(name,wire,tables[i])
            if table is None:raise ValueError('Conflicting neutral string table')
            tables[i]=table;lengths[i][c['length_wire']]=len(name);sizes[i][len(name)]=c['length_wire']
            resolved.append(dict(entity_id=hex(row['param']),name=name,mode=i,start=c['start'],end=c['end']))
            progress=True
        if not progress:
            row=left[0]
            witnesses=[r for r in doc['rows']if r['stream']==2 and r['param']==row['param'] and len(r['candidates'])==1]
            if len(witnesses)!=1:raise ValueError('Unresolved model names: '+str(len(left)))
            name=witnesses[0]['candidates'][0]['name']
            row['candidates']=[c for c in row['candidates']if c['name']==name]
            if len(row['candidates'])!=1:raise ValueError('Keyframe witness did not resolve name')
            extra_keyframes.append(dict(entity_id=hex(row['param']),name=name,source=witnesses[0]))
        pending=left
    names_by_id={int(r['entity_id'],16):r['name']for r in resolved}
    codec_extensions=[]
    for row in doc['rows']:
        if row['stream']!=2:continue
        cs=[c for c in row['candidates']if c['name']==names_by_id[row['param']]]
        if len(cs)!=1:raise ValueError('Ambiguous repeated-entity model witness')
        c=cs[0];i=c['mode'];name=c['name']
        wire=reorder(bytes.fromhex(row['payload'])[c['start']:c['end']],doc['tables'][i]['order'])
        table=compatible(name,wire,tables[i])
        if table is None:raise ValueError('Keyframe string conflict')
        if table!=tables[i] or c['length_wire'] not in lengths[i]:
            codec_extensions.append(dict(entity_id=hex(row['param']),mode=i,name=name,source=row))
        if lengths[i].get(c['length_wire'],len(name))!=len(name):raise ValueError('Length conflict')
        tables[i]=table;lengths[i][c['length_wire']]=len(name)
    used_kf={r['entity_id']for r in extra_keyframes+codec_extensions}
    mode_map={0:0,1:2,2:3}
    profile=dict(version='16.20.824.8524',header_mode_bit=12,
        modes={str(mode_map[i]):dict(byte_pairs=tables[i],length_pairs=lengths[i],order=doc['tables'][i]['order'])for i in range(3)},
        model_names=sorted({r['name']for r in resolved}),
        calibration_scope=f'22 live neutral creations plus {len(used_kf)} repeated-entity keyframes from HN1-11363093470; remaining {22-len(used_kf)} keyframes and other replay withheld',
        character_reference='data/raw/68aec4f56ef93e8f35b49b2ab4ea345d838945a13dc549090a673bb3c7528317.bin',
        unresolved=['Entity instance-name field','Other encoding modes','Unobserved neutral model letters'])
    (ROOT/'lol_coach/profiles/neutral_names_16_20.json').write_text(json.dumps(profile,indent=2)+'\n',encoding='utf8')
    (ROOT/'data/private/replay_completion/neutral_name_calibration.json').write_text(json.dumps(dict(resolved=resolved,lengths=lengths,extra_keyframes=extra_keyframes,codec_extensions=codec_extensions,used_keyframe_entities=sorted(used_kf)),indent=2))
    print(json.dumps(dict(live_anchors=len(resolved),models=profile['model_names'],lengths=lengths)))


if __name__=='__main__':main()
