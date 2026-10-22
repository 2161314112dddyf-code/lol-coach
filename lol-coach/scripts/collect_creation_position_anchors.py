"""Join creation messages to same-time stationary compound state, no lookahead."""
import json,sys,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from export_replay_ten import load_reviewed
from export_skill_ranks import STEMS
from lol_coach.neutral_identity import stationary_position


def main():
    folder=ROOT/'data/private/replay_completion'
    names=json.loads((folder/'pet_names_research.json').read_text())['rows']
    f,*_=load_reviewed(ROOT.parent);anchors=[]
    for stem in STEMS:
        by={(r['stream'],r['chunk'],r['param']):r for r in names if r['replay']==stem}
        for p in f.packets(Path('C:/Users/21613/Documents/League of Legends/Replays')/(stem+'.rofl')):
            if p['opcode']!=0x37d:continue
            r=by.get((p['stream'],p['chunk'],p['param']))
            if not r or abs(r['time']-p['time'])>.001 or p['offset']<r['offset']:continue
            try:value=stationary_position(p['payload'])
            except ValueError:continue
            anchors.append(dict(replay=stem,entity_id=hex(p['param']),name=r['identity']['name'],
                time=p['time'],x_plain=struct.pack('<f',value['position_xz'][0]).hex(),
                z_plain=struct.pack('<f',value['position_xz'][1]).hex(),creation=r,
                compound={**p,'payload':p['payload'].hex()}))
    (folder/'pet_position_codec.json').write_text(json.dumps(dict(anchors=anchors),indent=2))
    print(json.dumps(dict(anchors=len(anchors))))


if __name__=='__main__':main()
