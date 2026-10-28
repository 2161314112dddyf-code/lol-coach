"""Derive reference-byte constraints from same-time parent/child creations."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT.parent/'vendor/reverse-tools'))
import z3
from lol_coach.spell_activity import leb128

def main():
    folder=ROOT/'data/private/replay_completion'
    rows=json.loads((folder/'HN1-11360086609-created-objects.json').read_text())['events']
    pairs={};inverse={};anchors=[]
    def wire(row):
        raw=bytes.fromhex(row['source']['payload_hex']);off=row['identity']['position_byte_offsets'][0]
        if raw[off-1]!=0x43:raise ValueError('Unobserved vector prefix')
        return raw[7:off-1]
    for row in rows:
        if row['source']['stream']!=1:continue
        model=row['identity']['model_name'];parent=None;basis=None
        hero={'ZyraSeed':0x40000035,'ZyraThornPlant':0x40000035,'ZyraGraspingPlant':0x40000035,
              'JhinTrap':0x4000003a,'FizzShark':0x4000003d,'ApheliosTurret':0x40000034}.get(model)
        if hero is not None:parent=hero;basis='unique hero with model-specific summon'
        elif model=='TestCubeRenderNoFOW':
            candidates=[r for r in rows if r['source']['stream']==1 and
                r['identity']['model_name']=='Cherry_Plant_Powerup'and
                r['time_seconds']==row['time_seconds']and
                r['identity']['position_xz']==row['identity']['position_xz']]
            if len(candidates)==1:parent=int(candidates[0]['entity_id'],16);basis='unique same-time same-position plant'
        if parent is None:continue
        plain=leb128(parent&0x3fffffff);encoded=wire(row)
        if len(plain)!=len(encoded):raise ValueError('Reference length conflict')
        for x,y in zip(plain,encoded):
            if x in pairs and pairs[x]!=y or y in inverse and inverse[y]!=x:raise ValueError('Reference byte conflict')
            pairs[x]=y;inverse[y]=x
        anchors.append(dict(entity_id=row['entity_id'],time=row['time_seconds'],parent=hex(parent),wire=encoded.hex(),basis=basis))
    print('anchors',len(anchors),'bytes',len(pairs),flush=True)
    models=[]
    for mode in range(8):
        a,b,c,d,e,r,s=z3.BitVecs('a b c d e r s',8)
        def swap(x):return ((x&85)<<1)|(z3.LShR(x,1)&85)
        def f(x):
            if mode&1:x=swap(x)
            x=z3.RotateLeft(x+a,r)
            if mode&2:x=swap(x)
            x=z3.RotateLeft((x^b)+c,s)^d
            if mode&4:x=swap(x)
            return x+e
        so=z3.Solver();so.set(timeout=5000);so.add(z3.ULE(r,7),z3.ULE(s,7))
        for x,y in pairs.items():so.add(f(z3.BitVecVal(x,8))==y)
        status=so.check();m=dict(mode=mode,status=str(status))
        if status==z3.sat:
            model=so.model();m['table']=[model.eval(f(z3.BitVecVal(x,8)),model_completion=True).as_long()for x in range(256)]
            m['parameters']={str(v):model.eval(v,model_completion=True).as_long()for v in(a,b,c,d,e,r,s)}
        models.append(m);print({k:v for k,v in m.items()if k!='table'},flush=True)
    (folder/'creation_reference_research.json').write_text(json.dumps(dict(pairs=pairs,anchors=anchors,models=models,accepted=False),indent=2))

if __name__=='__main__':main()
