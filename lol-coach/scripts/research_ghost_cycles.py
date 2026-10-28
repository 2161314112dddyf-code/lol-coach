"""Test one shared Ghost duration across four observed activity cycles.

This is a falsifiable numeric hypothesis, never an accepted cooldown decoder.
"""
import json,sys,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'vendor/reverse-tools'))
import z3


def main():
    folder=ROOT/'data/private/replay_completion'
    data=json.loads((ROOT/'data/private/replay_targets/HN1-11360086609-state-fields.json').read_text())['events']
    activities=json.loads((ROOT/'data/private/spell_slots/HN1-11360086609.json').read_text())['events']
    casts=sorted({r['time_seconds']for r in activities if r['entity_id']=='0x40000035'and r['slot']==4})
    rows=[]
    for r in data:
        wire=r['numeric_fields'][0]['wire_hex']
        if r['entity_id']!='0x40000035'or r['slot']['index']!=4 or not wire or r['time_seconds']==0:continue
        prior=[t for t in casts if t<=r['time_seconds']]
        if prior:rows.append(dict(time=r['time_seconds'],last_activity=prior[-1],wire=wire,source=r['source']))
    variables={b:z3.BitVec(f'b_{b}',8)for row in rows for b in bytes.fromhex(row['wire'])}
    mode=int(sys.argv[1])if len(sys.argv)>1 else None
    so=z3.Solver();so.set(timeout=20000 if mode is not None else 50000);so.add(z3.Distinct(*variables.values()))
    if mode is not None:
        a,b,c,d,e,r,s=z3.BitVecs('a b c d e r s',8)
        def swap(x):return ((x&85)<<1)|(z3.LShR(x,1)&85)
        def transform(x):
            if mode&1:x=swap(x)
            x=z3.RotateLeft(x+a,r)
            if mode&2:x=swap(x)
            x=z3.RotateLeft((x^b)+c,s)^d
            if mode&4:x=swap(x)
            return x+e
        so.add(z3.ULE(r,7),z3.ULE(s,7))
        for byte,value in variables.items():so.add(value==transform(z3.BitVecVal(byte,8)))
    # Anchors remain explicit hypotheses; they are not imported into profiles.
    for b,v in {0xb9:0,0x0f:0x70,0xc0:0x41}.items():
        if b in variables:so.add(variables[b]==v)
    duration=z3.BitVec('duration',64);scale=1<<30
    so.add(z3.UGE(duration,100*scale),z3.ULE(duration,200*scale))
    for i,row in enumerate(rows):
        w=z3.Concat(*(variables[b]for b in bytes.fromhex(row['wire'])[::-1]));e=z3.Extract(30,23,w)
        so.add(z3.Extract(31,31,w)==0,z3.UGE(e,120),z3.ULE(e,136))
        m=z3.ZeroExt(41,z3.Extract(22,0,w))|z3.BitVecVal(1<<23,64)
        value=(m<<z3.ZeroExt(56,e-120))+int((row['time']-row['last_activity'])*scale)
        so.assert_and_track(z3.And(z3.UGE(value+int(.15*scale),duration),z3.ULE(value,duration+int(.15*scale))),f'cycle_{i}')
    status=so.check();result=dict(status=str(status),accepted=False,rows=rows,
        assumptions=['Numeric B is byte-substituted float32 remaining seconds','All four Ghost activities start the same duration',
                     'No unobserved timer reset or rate change','b9b90fc0 is 15 seconds'],tolerance_seconds=.15)
    if status==z3.sat:
        model=so.model();table={b:model.eval(v,model_completion=True).as_long()for b,v in variables.items()}
        result.update(candidate_inverse=table,duration_candidate=model.eval(duration).as_long()/scale)
        for row in rows:row['candidate_value']=struct.unpack('<f',bytes(table[b]for b in bytes.fromhex(row['wire'])))[0]
        # A second duration model establishes non-identifiability, if one exists.
        d=model.eval(duration).as_long();so.add(z3.Or(z3.UGT(duration,d+int(.3*scale)),z3.ULT(duration,d-int(.3*scale))))
        result['different_duration_status']=str(so.check())
    elif status==z3.unsat:result['unsat_core']=[str(x)for x in so.unsat_core()]
    else:result['reason']=so.reason_unknown()
    suffix=''if mode is None else f'_arx{mode}'
    result['arithmetic_mode']=mode
    (folder/f'ghost_cycle_constraints{suffix}.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({k:v for k,v in result.items()if k not in ('rows','candidate_inverse')},indent=2))


if __name__=='__main__':main()
