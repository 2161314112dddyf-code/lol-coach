"""Constrain candidate numeric codecs with observed cast/keyframe intervals."""
from pathlib import Path
import json
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'vendor/reverse-tools'))
import z3


def bits(value):
    return struct.unpack('<I',struct.pack('<f',value))[0]


def main():
    states=json.loads((ROOT/'data/private/replay_targets/HN1-11360086609-state-fields.json').read_text())['events']
    casts=json.loads((ROOT/'data/private/spell_slots/HN1-11360086609.json').read_text())['events']
    times=[r['time_seconds'] for r in casts if r['entity_id']=='0x40000035' and r['slot']==4]
    anchors=[]
    for row in states:
        if row['entity_id']!='0x40000035' or row['source']['stream']!=2 or row['slot']['index']!=4:
            continue
        wire=row['numeric_fields'][0]['wire_hex']
        prior=[t for t in times if t<row['time_seconds']]
        if wire and prior:
            value=240/1.7+prior[-1]-row['time_seconds']
            if value>0:
                anchors.append(dict(wire=wire,time=row['time_seconds'],last_activity=prior[-1],expected=value))
    results=[]
    for swap_kind in ('adjacent','pairs','reverse'):
        for mode in range(8):
            a,b,c,d,e,r,s=z3.BitVecs('a b c d e r s',8)
            word_rotation=z3.BitVec('word_rotation',32)
            def swap(x):
                if swap_kind=='adjacent':
                    return ((x&85)<<1)|(z3.LShR(x,1)&85)
                if swap_kind=='pairs':
                    return ((x&51)<<2)|(z3.LShR(x,2)&51)
                return z3.Concat(*(z3.Extract(i,i,x) for i in range(8)))
            def f(x):
                if mode&1:x=swap(x)
                x=z3.RotateLeft(x+a,r)
                if mode&2:x=swap(x)
                x=(x^b)+c
                x=z3.RotateLeft(x,s)^d
                if mode&4:x=swap(x)
                return x+e
            solver=z3.Solver();solver.set(timeout=5000)
            solver.add(z3.ULE(r,7),z3.ULE(s,7))
            solver.add(z3.ULE(word_rotation,31))
            for item in anchors[:6]:
                word=z3.Concat(*(f(z3.BitVecVal(b,8)) for b in bytes.fromhex(item['wire'])[::-1]))
                word=z3.RotateRight(word,word_rotation)
                solver.add(z3.UGE(word,bits(item['expected']-.15)),z3.ULE(word,bits(item['expected']+.15)))
            status=solver.check();result=dict(swap_kind=swap_kind,mode=mode,status=str(status))
            if status==z3.sat:
                model=solver.model()
                inverse=bytes(model.eval(f(z3.BitVecVal(x,8)),model_completion=True).as_long() for x in range(256))
                result['inverse']=list(inverse)
                rotation=model.eval(word_rotation,model_completion=True).as_long()
                result['word_rotation']=rotation
                result['parameters']={str(v):model.eval(v,model_completion=True).as_long() for v in (a,b,c,d,e,r,s)}
                def decode(q):
                    word=int.from_bytes(bytes.fromhex(q['wire']).translate(inverse),'little')
                    word=((word>>rotation)|(word<<(32-rotation)))&0xffffffff
                    return struct.unpack('<f',word.to_bytes(4,'little'))[0]
                result['checks']=[dict(**q,decoded=decode(q)) for q in anchors]
            print(json.dumps({k:v for k,v in result.items() if k!='inverse'}),flush=True)
            results.append(result)
    out=dict(hypothesis='First numeric field is remaining Ghost cooldown with 240 base and 70 summoner haste; not established truth',
        tolerance_seconds=.15,anchors=anchors,models=results,
        accepted_decoder=False)
    (ROOT/'data/private/replay_completion/countdown_word_models.json').write_text(json.dumps(out,indent=2),encoding='utf8')


if __name__=='__main__':main()
