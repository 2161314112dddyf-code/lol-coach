"""Bounded two-S-box hypothesis motivated by the cached client disassembly."""
import json,struct
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]


def rol(x,r):return ((x<<r)|(x>>(8-r)))&255
def swap(x):return ((x&85)<<1)|((x>>1)&85)


def main():
    doc=json.loads((ROOT/'data/private/replay_completion/windows_permutations.json').read_text())
    pairs={int(k):v for k,v in json.loads((ROOT/'data/private/replay_completion/creation_reference_research.json').read_text())['pairs'].items()}
    xs=np.array(list(pairs)[:5],dtype=np.int32);ys=np.array(list(pairs.values())[:5],dtype=np.int32)
    aa=np.arange(256)[:,None,None];bb=np.arange(256)[None,:,None]
    inputs=(((xs+aa)&255)^bb)
    states=json.loads((ROOT/'data/private/replay_targets/HN1-11360086609-state-fields.json').read_text())['events']
    anchors=[r for r in states if r['entity_id']=='0x40000035' and r['source']['stream']==2 and r['slot']['index']==4 and r['numeric_fields'][0]['wire_hex']]
    rows=[];seen=set();tested=0
    for offset in doc['offsets']:
        t=np.array(doc['tables'][str(offset)],dtype=np.int32);inv=np.argsort(t)
        for first_inverse in (False,True):
            for second_inverse in (False,True):
                t1=inv if first_inverse else t;t2=inv if second_inverse else t
                for r in range(8):
                    for swapped in (False,True):
                        middle=rol(t1,r)
                        if swapped:middle=swap(middle)
                        composed=t2[middle]
                        signature=composed.tobytes()
                        if signature in seen:continue
                        seen.add(signature);tested+=1
                        values=composed[inputs]
                        mask=np.all((values[:,:,1:]^values[:,:,:1])==(ys[1:]^ys[0]),axis=2)
                        for a,b in zip(*np.where(mask)):
                            d=int(values[a,b,0])^int(ys[0])
                            table=(composed[((np.arange(256)+a)&255)^b]^d).tolist()
                            if not all(table[k]==v for k,v in pairs.items()):continue
                            samples=[]
                            for q in []:
                                value=struct.unpack('<f',bytes(table[n]for n in bytes.fromhex(q['numeric_fields'][0]['wire_hex'])))[0]
                                samples.append(dict(time=q['time_seconds'],value=value))
                            rows.append(dict(offset=offset,first_inverse=first_inverse,second_inverse=second_inverse,
                                rotation=r,swap=swapped,a=int(a),b=int(b),xor=d,inverse_table=table,checks=samples))
        print(json.dumps(dict(offset=hex(offset),tested=tested,models=len(rows))),flush=True)
        (ROOT/'data/private/replay_completion/reference_double_table_models.json').write_text(json.dumps(dict(
            anchors=pairs,
            tested=tested,models=rows,accepted=False),indent=2))


if __name__=='__main__':main()
