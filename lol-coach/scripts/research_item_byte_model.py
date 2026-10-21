"""Bounded synthesis from explicit, provisional item-code correspondences."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'vendor/reverse-tools'))
import z3

# The 2-byte signature may be an encoded LEB128 item ID. These identities are
# post-hoc hypotheses from purchases/final inventory, not independent labels.
ITEMS={1058:'2784',1036:'3284',1001:'a4ec',1018:'86ec',2031:'7159',
       6653:'8762',3020:'d84a',4645:'0736',3118:'a77c',
       2503:'e0fd',3116:'f07c',6676:'3efe',3140:'ff7c',3111:'6f7c'}


def main():
    pairs={}
    for item,code in ITEMS.items():
        for x,y in zip(((item&127)|128,item>>7),bytes.fromhex(code)):
            if x in pairs and pairs[x]!=y:raise ValueError('Seed conflict')
            pairs[x]=y
    results=[]
    for location in range(8):
        a,b,c,d,e,r,s=z3.BitVecs('a b c d e r s',8)
        def swap(x):return ((x&0x55)<<1)|(z3.LShR(x,1)&0x55)
        def expression(x):
            if location&1:x=swap(x)
            x=z3.RotateLeft(x+a,r)
            if location&2:x=swap(x)
            x=(x^b)+c
            x=z3.RotateLeft(x,s)^d
            if location&4:x=swap(x)
            return x+e
        solver=z3.Solver();solver.set(timeout=5000)
        solver.add(z3.ULE(r,7),z3.ULE(s,7))
        for x,y in pairs.items():solver.add(expression(z3.BitVecVal(x,8))==y)
        status=solver.check();result=dict(location=location,status=str(status))
        if status==z3.sat:
            model=solver.model()
            table=[model.eval(expression(z3.BitVecVal(x,8)),model_completion=True).as_long() for x in range(256)]
            result['table']=table
            result['parameters']={str(v):model.eval(v,model_completion=True).as_long() for v in (a,b,c,d,e,r,s)}
        results.append(result);print({k:v for k,v in result.items() if k!='table'},flush=True)
    (ROOT/'data/research/item_byte_models.json').write_text(json.dumps(dict(status='hypotheses_only',items=ITEMS,pairs=pairs,models=results),indent=2),encoding='utf8')


if __name__=='__main__':main()
