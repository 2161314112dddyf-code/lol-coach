"""Bounded synthesis with public-client S-box; hypotheses retained as candidates."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'vendor/reverse-tools'))
import z3


def main():
    raw=(ROOT/'data/research/client_16.20.824.8524_mac/LeagueofLegends').read_bytes()[16384:]
    pairs={0:0xc9,64:0xdf,**dict(zip(range(52,62),bytes.fromhex('a9b7a0e2854dec196611')))}
    results=[]
    for offset in (0x232da30,0x232db30):
        t=raw[offset:offset+256]
        lut=z3.K(z3.BitVecSort(8),z3.BitVecVal(0,8))
        for i,v in enumerate(t):lut=z3.Store(lut,z3.BitVecVal(i,8),z3.BitVecVal(v,8))
        for swap_position in range(4):
            a,b,c,d,r,s=z3.BitVecs('a b c d r s',8)
            def swap(x):return ((x&85)<<1)|(z3.LShR(x,1)&85)
            def expr(x):
                if swap_position&1:x=swap(x)
                x=z3.RotateLeft(x+a,r)^b
                x=z3.Select(lut,x)
                x=z3.RotateLeft(x+c,s)^d
                if swap_position&2:x=swap(x)
                return x
            solver=z3.Solver();solver.set(timeout=10000)
            solver.add(z3.ULE(r,7),z3.ULE(s,7))
            for x,y in pairs.items():solver.add(expr(z3.BitVecVal(x,8))==y)
            status=solver.check();row={'sbox_offset':hex(offset),'swap_position':swap_position,'status':str(status)}
            if status==z3.sat:
                m=solver.model();row['parameters']={str(v):m.eval(v,model_completion=True).as_long() for v in (a,b,c,d,r,s)}
                row['table']=[m.eval(expr(z3.BitVecVal(x,8)),model_completion=True).as_long() for x in range(256)]
            results.append(row);print({k:v for k,v in row.items() if k!='table'},flush=True)
    (ROOT/'data/research/replication_sbox_models.json').write_text(json.dumps({'pairs':pairs,'models':results},indent=2),encoding='utf8')


if __name__=='__main__':main()
