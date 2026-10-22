"""Finite byte-codec hypotheses for the 0x3d7 array; no semantic claims."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'vendor/reverse-tools'))
import z3


def main():
    rows=json.loads((ROOT/'data/private/replay_completion/array_candidates.json').read_text())['candidates']
    out=[]
    for row in rows:
        if row['opcode']!='0x3d7':continue
        pairs={int(k):v for k,v in row['pairs'].items()}
        if 0 in pairs and pairs[0]!=0xbd:continue
        pairs[0]=0xbd
        for mode in range(8):
            a,b,c,d,e,r,s=z3.BitVecs('a b c d e r s',8)
            def swap(x):return ((x&85)<<1)|(z3.LShR(x,1)&85)
            def f(x):
                if mode&1:x=swap(x)
                x=z3.RotateLeft(x+a,r)
                if mode&2:x=swap(x)
                x=(x^b)+c
                x=z3.RotateLeft(x,s)^d
                if mode&4:x=swap(x)
                return x+e
            solver=z3.Solver();solver.set(timeout=2000)
            solver.add(z3.ULE(r,7),z3.ULE(s,7))
            for x,y in pairs.items():solver.add(f(z3.BitVecVal(x,8))==y)
            status=solver.check();result=dict(tail=row['tail'],mode=mode,status=str(status))
            if status==z3.sat:
                model=solver.model();table=[model.eval(f(z3.BitVecVal(x,8)),model_completion=True).as_long()for x in range(256)]
                result['table']=table
                result['parameters']={str(v):model.eval(v,model_completion=True).as_long()for v in(a,b,c,d,e,r,s)}
            out.append(result)
            print(json.dumps({k:v for k,v in result.items()if k!='table'}),flush=True)
        (ROOT/'data/private/replay_completion/3d7_array_models.json').write_text(json.dumps(out,indent=2))


if __name__=='__main__':main()
