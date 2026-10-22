"""Test extra bit-lane permutations seen in the read-only mac client.

Positive countdown anchors remain hypotheses. SAT alone is never acceptance.
"""
import json,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'vendor/reverse-tools'))
import z3


def main():
    pairs={0:0xb9,0x3f:0x9f,0x40:0xeb,0x41:0xc0,0x42:0xb0,0x43:0xcf,0x70:0x0f,0xa0:0xf6}
    rows=[]
    for permutation in ('even_left','even_right','odd_left','odd_right','pairs','reverse'):
        for mode in range(8):
            a,b,c,d,e,r,s=z3.BitVecs('a b c d e r s',8)
            def perm(x):
                if permutation=='even_left':return (x&170)|((x<<2)&84)|(z3.LShR(x,6)&1)
                if permutation=='even_right':return (x&170)|(z3.LShR(x,2)&21)|((x<<6)&64)
                if permutation=='odd_left':return (x&85)|((x<<2)&168)|(z3.LShR(x,6)&2)
                if permutation=='odd_right':return (x&85)|(z3.LShR(x,2)&42)|((x<<6)&128)
                if permutation=='pairs':return ((x&51)<<2)|(z3.LShR(x,2)&51)
                return z3.Concat(*(z3.Extract(i,i,x)for i in range(8)))
            def f(x):
                if mode&1:x=perm(x)
                x=z3.RotateLeft(x+a,r)
                if mode&2:x=perm(x)
                x=(x^b)+c
                x=z3.RotateLeft(x,s)^d
                if mode&4:x=perm(x)
                return x+e
            solver=z3.Solver();solver.set(timeout=2000)
            solver.add(z3.ULE(r,7),z3.ULE(s,7))
            for x,y in pairs.items():solver.add(f(z3.BitVecVal(x,8))==y)
            status=solver.check();row=dict(permutation=permutation,mode=mode,status=str(status))
            if status==z3.sat:
                model=solver.model();row['table']=[model.eval(f(z3.BitVecVal(x,8)),model_completion=True).as_long()for x in range(256)]
            rows.append(row);print(json.dumps({k:v for k,v in row.items()if k!='table'}),flush=True)
            (ROOT/'data/private/replay_completion/numeric_bitlane_models.json').write_text(json.dumps(dict(pairs=pairs,models=rows,accepted=False),indent=2))


if __name__=='__main__':main()
