"""Infer candidate byte maps from elapsed time, without assuming Ghost haste."""
import json,sys,collections,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];F=ROOT/'data/private/replay_completion'
sys.path.insert(0,str(ROOT.parent/'vendor/reverse-tools'))
import z3

def main():
    states=json.loads((ROOT/'data/private/replay_targets/HN1-11360086609-state-fields.json').read_text())['events']
    casts=json.loads((ROOT/'data/private/spell_slots/HN1-11360086609.json').read_text())['events']
    by=collections.defaultdict(list);activities=collections.defaultdict(list)
    for r in casts:activities[r['entity_id'],r['slot']].append(r['time_seconds'])
    for r in states:
        if r['source']['stream']==2 and r['slot']['index']in(3,4,5):by[r['entity_id'],r['slot']['index']].append(r)
    pairs=[]
    for key,rows in by.items():
        rows.sort(key=lambda r:r['time_seconds'])
        for a,b in zip(rows,rows[1:]):
            wa=a['numeric_fields'][0]['wire_hex'];wb=b['numeric_fields'][0]['wire_hex']
            if not wa or not wb or any(a['time_seconds']<t<=b['time_seconds']for t in activities[key]):continue
            if a['time_seconds']==0:continue
            pairs.append(dict(actor=key[0],slot=key[1],time_a=a['time_seconds'],time_b=b['time_seconds'],wire_a=wa,wire_b=wb))
    # R has resets/reduction effects. First use summoners only; do not silently
    # turn their duration model into accepted semantics.
    selection=sys.argv[1]if len(sys.argv)>1 else 'all'
    pairs=[p for p in pairs if p['slot']in(4,5) and (selection=='all' or p['actor']=='0x40000035'and p['slot']==4)]
    variables={b:z3.BitVec(f'b_{b}',8)for p in pairs for key in('wire_a','wire_b')for b in bytes.fromhex(p[key])}
    so=z3.Solver();so.set(timeout=50000);so.add(z3.Distinct(*variables.values()))
    for b,value in {0xb9:0,0x0f:0x70,0xc0:0x41}.items():
        if b in variables:so.add(variables[b]==value)
    words={}
    def scaled(wire):
        if wire in words:return words[wire]
        w=z3.Concat(*(variables[b]for b in bytes.fromhex(wire)[::-1]));e=z3.Extract(30,23,w)
        so.add(z3.Extract(31,31,w)==0,z3.UGE(e,120),z3.ULE(e,136))
        mantissa=z3.ZeroExt(41,z3.Extract(22,0,w))|z3.BitVecVal(1<<23,64)
        out=mantissa<<z3.ZeroExt(56,e-120);words[wire]=out;return out
    for i,p in enumerate(pairs):
        delta=p['time_b']-p['time_a'];a=scaled(p['wire_a']);b=scaled(p['wire_b'])
        so.assert_and_track(z3.And(z3.UGT(a,b),z3.UGE(a-b,int((delta-.15)*(1<<30))),z3.ULE(a-b,int((delta+.15)*(1<<30)))),f'pair_{i}')
    print('pairs',len(pairs),'byte_variables',len(variables),flush=True)
    status=so.check();out=dict(pairs=pairs,status=str(status),accepted=False,
        assumptions=['Numeric B is a float32 countdown','No observed summoner activity implies no reset',
                     'One bijective byte substitution','Initial b9b90fc0 represents 15 seconds'],tolerance_seconds=.15)
    if status==z3.sat:
        m=so.model();table={b:m.eval(v,model_completion=True).as_long()for b,v in variables.items()};out['candidate_inverse']=table
        for p in pairs:
            for key in('a','b'):p['decoded_'+key]=struct.unpack('<f',bytes(table[b]for b in bytes.fromhex(p['wire_'+key])))[0]
    elif status==z3.unsat:out['unsat_core']=[str(x)for x in so.unsat_core()]
    else:out['reason']=so.reason_unknown()
    (F/f'countdown_differences_{selection}.json').write_text(json.dumps(out,indent=2));print(status,flush=True)

if __name__=='__main__':main()
