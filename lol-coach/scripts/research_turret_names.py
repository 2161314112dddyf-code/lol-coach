"""Fit two string layouts from static tower names; preserve the third as unknown."""
import collections
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.export_replay_ten import load_reviewed,reference
from scripts.research_object_name_patterns import shape
from lol_coach.http import save_json

MAP_SHA='240de083663f446ffbb9a35ec44849df773522b5d936acecaf9e1d97412b8830'


def units(value):
    if isinstance(value,dict):
        if value.get('__type')=='{ad65d8c4}' and value.get('AttackableUnit',{}).get('type')==0:
            yield value
        for child in value.values():yield from units(child)
    elif isinstance(value,list):
        for child in value:yield from units(child)


def compatible(mapping,plain,wire):
    inverse={v:k for k,v in mapping.items()}
    return len(plain)==len(wire) and all(mapping.get(p,w)==w and inverse.get(w,p)==p for p,w in zip(plain,wire))


def main():
    map_path=ROOT/'data/research/object_sources/raw'/f'{MAP_SHA}.bin'
    if reference(map_path)['sha256']!=MAP_SHA:raise ValueError('Changed reference')
    static=list(units(json.loads(map_path.read_bytes())))
    candidates=[]
    for u in static:
        lane=u['AttackableUnit']['LaneDefinition']
        for team in ('Order','Chaos'):
            for position in ([lane['Position']] if 'Position' in lane else range(6)):
                name=f"Turret_T{team}_L{lane['lane']}_P{position}_{int(u['name'][1:-1],16)}_0"
                candidates.append(dict(name=name,team=100 if team=='Order' else 200,
                    lane=lane['lane'],position=position,static_name=u['name'],
                    character_record=u['Character']['CharacterRecord'],
                    map_reference_position=u['transform'][3][:3],
                    explicit_reference_team=u.get('Team',{}).get('Team'),
                    position_default_in_reference='Position' not in lane))
    replay=Path(r'C:\Users\21613\Documents\League of Legends\Replays\HN1-11360086609.rofl')
    framer,_,_,deps=load_reviewed(ROOT.parent)
    packets=[p for p in framer.packets(replay) if p['opcode']==0xd8]
    # Calibration on initial records except held-out 0x32, plus a later example of 0x31.
    selected=[p for p in packets if (p['time']==0 and p['param']!=0x40000032)
              or (120<p['time']<121 and p['param']==0x40000031)]
    tables={0:{},1:{}};lengths={0:{},1:{}};anchors=[];remaining=selected[:]
    while True:
        changed=False
        for p in remaining[:]:
            b=p['payload'];mode=b[0]&3
            if mode not in tables:continue
            matches=[]
            for c in candidates:
                word=c['name'].encode()[::-1];wire=b[5:5+len(word)]
                if shape(word)==shape(wire) and compatible(tables[mode],word,wire):matches.append(c)
            if len(matches)!=1:continue
            c=matches[0];word=c['name'].encode()[::-1];wire=b[5:5+len(word)]
            tables[mode].update(zip(word,wire))
            if b[4] in lengths[mode] and lengths[mode][b[4]]!=len(word):raise ValueError('Conflicting length')
            lengths[mode][b[4]]=len(word)
            anchors.append(dict(time_seconds=p['time'],entity_id=hex(p['param']),mode=mode,
                payload_hex=b.hex(),offset=p['offset'],chunk=p['chunk'],name=c['name']))
            remaining.remove(p);changed=True
        if not changed:break
    known={a['name'] for a in anchors}
    # Static candidates remain separate: this does not assign a runtime ID.
    profile=dict(schema='turret-name-profile/v1',version='16.20.824.8524',opcode=0xd8,
        name_format='Turret_T%s_L%u_P%u_%u_%u',
        format_source=reference(ROOT/'data/research/client_16.20.824.8524_mac/LeagueofLegends'),
        reference=reference(map_path),decoder_dependencies=deps,calibration_replay=reference(replay),
        byte_tables={str(k):{str(p):w for p,w in sorted(v.items())} for k,v in tables.items()},
        length_tables={str(k):{str(w):n for w,n in sorted(v.items())} for k,v in lengths.items()},
        anchors=anchors,static_candidates=candidates,
        limitations=['Only modes 0 and 1; mode 2 remains opaque',
                     'Static map position is not a decoded runtime coordinate',
                     'Map12 reference association is not a decoded map ID, mode or skin',
                     'No nonhero visibility or full objective state claimed'])
    save_json(ROOT/'lol_coach/profiles/turret_names_16_20.json',profile)
    print(json.dumps(dict(anchors=len(anchors),names=len(known),unknown_calibration=len(remaining),
        table_sizes={k:len(v) for k,v in tables.items()},lengths=lengths)))


if __name__=='__main__':main()
