"""Fit bounded byte models from modal lengths, retaining all contradictions."""
from pathlib import Path
import collections
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT.parent/'vendor/reverse-tools')]
from export_replay_ten import load_reviewed
import z3


def main():
    fr, _, _, _ = load_reviewed(ROOT.parent)
    source=Path('C:/Users/21613/Documents/League of Legends/Replays/HN1-11360086609.rofl')
    distributions=collections.defaultdict(collections.Counter)
    for p in fr.packets(source):
        d=p['payload']
        if p['stream']==1 and p['opcode']==0x3df and d[5:8]==bytes.fromhex('c9c9df'):
            distributions[d[2]][len(d)-3]+=1
    modes=sorted(distributions.items(),key=lambda kv:-sum(kv[1].values()))[:20]
    pairs={c.most_common(1)[0][0]-8:wire for wire,c in modes}
    pairs.update({0:0xc9,64:0xdf})
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
        status=solver.check();result={'swap_position':location,'status':str(status)}
        if status==z3.sat:
            m=solver.model();result['parameters']={str(v):m.eval(v,model_completion=True).as_long() for v in (a,b,c,d,e,r,s)}
            table=[m.eval(expression(z3.BitVecVal(x,8)),model_completion=True).as_long() for x in range(256)]
            result['table']=table
        print({k:v for k,v in result.items() if k!='table'},flush=True);results.append(result)
    (ROOT/'data/research/replication_synthesis_1620.json').write_text(json.dumps({'training_pairs':pairs,'models':results},indent=2),encoding='utf8')


if __name__=='__main__':main()
