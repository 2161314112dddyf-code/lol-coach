"""Learn bounded creation-position bytes from simultaneous compound positions."""
import json,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'vendor/reverse-tools'))
import z3


def main():
    path=ROOT/'data/private/replay_completion'
    doc=json.loads((path/'pet_position_codec.json').read_text());table={};inverse={};rows=[];conflicts=[]
    pending=sorted(doc['anchors'],key=lambda r:r['name']!='ZyraSeed')
    for r in pending:
        raw=bytes.fromhex(r['creation']['payload']);start=r['creation']['identity']['start'];candidates=[]
        for off in ([start-15]if r['name']=='ZyraSeed'else range(start-18,start-13)):
            pairs=[(a,b)for key,pos in [('x',off),('z',off+8)]for a,b in zip(bytes.fromhex(r[key+'_plain']),raw[pos:pos+4][::-1])]
            if any(a in table and table[a]!=b or b in inverse and inverse[b]!=a for a,b in pairs):continue
            # Enforce bijection within new pairs, not only against prior anchors.
            t=dict(table);iv=dict(inverse);valid=True
            for a,b in pairs:
                if a in t and t[a]!=b or b in iv and iv[b]!=a:valid=False;break
                t[a]=b;iv[b]=a
            if valid:candidates.append((off,t,iv))
        if len(candidates)!=1:conflicts.append(r);continue
        off,table,inverse=candidates[0]
        rows.append(dict(entity_id=r['entity_id'],time=r['time'],offset=off,name=r['name']))
    print(json.dumps(dict(anchors=len(rows),conflicts=len(conflicts),known_bytes=len(table))),flush=True)
    models=[]
    for mode in range(4):
        a,b,c,d,r,s=z3.BitVecs('a b c d r s',8)
        def perm(x):return z3.Concat(*(z3.Extract(i,i,x)for i in range(8)))
        def fun(x):
            if mode&1:x=perm(x)
            x=z3.RotateLeft(x+a,r)^b
            if mode&2:x=perm(x)
            return z3.RotateLeft(x+c,s)^d
        solver=z3.Solver();solver.set(timeout=5000);solver.add(z3.ULE(r,7),z3.ULE(s,7))
        for x,y in table.items():solver.add(fun(z3.BitVecVal(x,8))==y)
        status=solver.check();m=dict(mode=mode,status=str(status))
        if status==z3.sat:
            model=solver.model();m['table']=[model.eval(fun(z3.BitVecVal(x,8)),model_completion=True).as_long()for x in range(256)]
            m['parameters']={str(k):model.eval(k,model_completion=True).as_long()for k in (a,b,c,d,r,s)}
        models.append(m);print(json.dumps({k:v for k,v in m.items()if k!='table'}),flush=True)
    # The observed single-bit deltas isolate an adjacent-bit swap, rotate,
    # and a carry in the output byte. Validate all known pairs, not just seeds.
    def permutation(x):
        x=((x&85)<<1)|((x>>1)&85)
        return ((x<<6)|(x>>2))&255
    carry_models=[]
    for bx in range(256):
        for add in range(256):
            xor=((bx+add)&255)^table[0]
            if all(((((permutation(x)^bx)+add)&255)^xor)==y for x,y in table.items()):
                carry_models.append(dict(input_xor=bx,add=add,output_xor=xor,
                    table=[((((permutation(x)^bx)+add)&255)^xor)for x in range(256)]))
    result=dict(anchors=rows,conflicts=conflicts,byte_pairs=table,models=models,
        carry_models=carry_models,accepted_decoder=False)
    (path/'creation_positions_research.json').write_text(json.dumps(result,indent=2))


if __name__=='__main__':main()
