"""Fit charge integer codecs only against stat-constrained count candidates."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'vendor/reverse-tools'))
import z3


def main():
    folder=ROOT/'data/private/replay_completion';source=json.loads((folder/'item_growth_research.json').read_text());results=[]
    kind=sys.argv[1]if len(sys.argv)>1 else 'charge'
    if kind not in ('charge','stat'):raise ValueError('Expected charge or stat')
    for index,solution in enumerate(source['solutions']):
        pairs=({int(k):v for k,v in solution['stat_float_pairs'].items()}if kind=='stat'else
            {n:int(w,16)for w,n in solution['counts'].items()if not w.startswith('constant')})
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
            so=z3.Solver();so.set(timeout=2000);so.add(z3.ULE(r,7),z3.ULE(s,7))
            for x,y in pairs.items():so.add(f(z3.BitVecVal(x,8))==y)
            status=so.check();row=dict(candidate=index,mode=mode,status=str(status))
            if status==z3.sat:
                model=so.model();row['table']=[model.eval(f(z3.BitVecVal(x,8)),model_completion=True).as_long()for x in range(256)]
                row['parameters']={str(v):model.eval(v,model_completion=True).as_long()for v in (a,b,c,d,e,r,s)}
            results.append(row);print(json.dumps({k:v for k,v in row.items()if k!='table'}),flush=True)
            (folder/f'item_{kind}_codec_research.json').write_text(json.dumps(dict(results=results,accepted=False),indent=2))


if __name__=='__main__':main()
