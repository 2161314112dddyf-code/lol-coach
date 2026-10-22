"""Constrain 0x1f3 model strings from repeated observed creations.

Anchor names are hypotheses until their whole-string and repeated-entity
checks are examined. This research file does not authorize visibility radii.
"""
import json,sys,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from export_replay_ten import load_reviewed,reference
from export_skill_ranks import STEMS
from research_neutral_strings import compatible,reorder


def main():
    f,*_=load_reviewed(ROOT.parent);rows=[];sources=[]
    for stem in STEMS:
        p=Path('C:/Users/21613/Documents/League of Legends/Replays')/(stem+'.rofl')
        sources.append(reference(p))
        for r in f.packets(p):
            if r['opcode']==0x1f3:rows.append({**r,'replay':stem,'payload':r['payload'].hex()})
    def row(actor):return next(r for r in rows if r['replay']==STEMS[0] and r['stream']==1 and r['param']==actor)
    specs=[];anchors=[]
    for actor,order in [(0x4000010c,2),(0x40000124,1),(0x400005a2,2)]:
        r=row(actor);d=bytes.fromhex(r['payload']);name='ZyraSeed'
        specs.append(dict(order=order,table=compatible(name,reorder(d[24:32],order),{}),lengths={d[23]:8}))
        anchors.append(dict(name=name,start=24,source=r))
    initial_names={'ZyraSeed','ZyraThornPlant','ZyraGraspingPlant','HA_AP_Poro','HA_AP_PoroSpawner'}
    names=set(initial_names)
    for folder in ('data/raw','data/research/world_sources/raw'):
        for path in (ROOT/folder).glob('*.bin'):
            for word in re.findall(rb'Characters/([^/"\\]+)',path.read_bytes()):
                try:name=word.decode('ascii')
                except UnicodeDecodeError:continue
                if 8<=len(name)<=45:names.add(name)
    names=sorted(names)
    names=sorted(set(names)|{'JhinTrap','TestCube','TestCubeRender','TestCubeRenderNoFOW','URF_Feeneypult','ApheliosTurret'})
    resolved=[];pending=rows[:]
    for turn in range(8):
        left=[];progress=0
        for r in pending:
            d=bytes.fromhex(r['payload']);cs=[]
            for i,s in enumerate(specs):
                for name in names:
                    if turn==0 and name not in initial_names:continue
                    if name not in initial_names and sum(ord(ch) not in s['table'] for ch in name)>3:continue
                    for start in range(20,min(35,len(d)-len(name)-4)):
                        if s['lengths'].get(d[start-1],len(name))!=len(name):continue
                        if any(n==len(name) and w!=d[start-1] for w,n in s['lengths'].items()):continue
                        t=compatible(name,reorder(d[start:start+len(name)],s['order']),s['table'])
                        if t is not None:cs.append(dict(name=name,start=start,mode=i,table=t,length_wire=d[start-1]))
            if len(cs)!=1:left.append(r);continue
            c=cs[0];s=specs[c['mode']];new=c['table']!=s['table'] or c['length_wire'] not in s['lengths']
            s['table']=c.pop('table');s['lengths'][c['length_wire']]=len(c['name'])
            if new:anchors.append(dict(name=c['name'],start=c['start'],source=r))
            resolved.append(dict(**r,identity=c));progress+=1
        pending=left
        if not progress:break
    # Determine header selector, if a bit field alone separates the three modes.
    selectors=[]
    for width in (2,3):
        for shift in range(33-width):
            pairs={};conflict=False
            for r in resolved:
                key=int.from_bytes(bytes.fromhex(r['payload'])[:4],'little')>>shift&((1<<width)-1)
                mode=r['identity']['mode']
                if key in pairs and pairs[key]!=mode:conflict=True;break
                pairs[key]=mode
            if not conflict:selectors.append(dict(shift=shift,width=width,cases=pairs))
    result=dict(sources=sources,specs=specs,anchors=anchors,rows=resolved,unresolved=pending,selectors=selectors,accepted_decoder=False)
    (ROOT/'data/private/replay_completion/pet_names_research.json').write_text(json.dumps(result,indent=2))
    from collections import Counter
    print(json.dumps(dict(total=len(rows),resolved=len(resolved),unknown=len(pending),anchors=len(anchors),selectors=selectors,names=dict(Counter(r['identity']['name']for r in resolved)),unknown_examples=[r for r in pending[:8]])))


if __name__=='__main__':main()
