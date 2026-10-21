"""Compare candidate item byte codes with the recovered replication permutation."""
import json
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from research_item_byte_model import ITEMS


def rol(x,r):return ((x<<r)|(x>>(8-r)))&255
def swap(x):return ((x&85)<<1)|((x>>1)&85)


def main():
    table=json.loads((ROOT/'lol_coach/profiles/replication_16_20.json').read_text())['encoding_table']
    results=[]
    rejected=[]
    for representation in ('leb','u16'):
        pairs={}
        conflict=False
        for item,wire in ITEMS.items():
            plain=((item&127)|128,item>>7) if representation=='leb' else (item&255,item>>8)
            for x,y in zip(plain,bytes.fromhex(wire)):
                if x in pairs and pairs[x]!=y:
                    rejected.append(dict(representation=representation,plain=x,previous=pairs[x],wire=y,item=item));conflict=True
                pairs[x]=y
        if conflict:continue
        xs=np.array(list(pairs),dtype=np.int32);ys=np.array(list(pairs.values()),dtype=np.int32)
        for inverse in (False,True):
            t=np.array([table.index(i) for i in range(256)] if inverse else table,dtype=np.int32)
            for mode in range(4):
                x=swap(xs) if mode&1 else xs;y=swap(ys) if mode&2 else ys
                right={}
                for s in range(8):
                    for d in range(256):
                        z=rol(y^d,(8-s)%8)
                        key=bytes(((z[1:]-z[0])&255).astype(np.uint8))
                        right.setdefault(key,[]).append((s,d,int(z[0])))
                bs=np.arange(256)[:,None]
                for r in range(8):
                    for a in range(256):
                        z=t[rol((x+a)&255,r)^bs]
                        diffs=((z[:,1:]-z[:,0:1])&255).astype(np.uint8)
                        for b,row in enumerate(diffs):
                            for s,d,z0 in right.get(row.tobytes(),[]):
                                c=(z0-int(z[b,0]))&255
                                v=np.arange(256)
                                if mode&1:v=swap(v)
                                v=rol((t[rol((v+a)&255,r)^b]+c)&255,s)^d
                                if mode&2:v=swap(v)
                                candidate=v.tolist()
                                assert all(candidate[k]==w for k,w in pairs.items())
                                results.append(dict(representation=representation,inverse=inverse,mode=mode,a=a,b=b,c=c,d=d,r=r,s=s,table=candidate))
                print(representation,inverse,mode,'models',len(results),flush=True)
    (ROOT/'data/research/item_sbox_models.json').write_text(json.dumps(dict(status='research_only',items=ITEMS,models=results,rejected=rejected),indent=2),encoding='utf8')


if __name__=='__main__':main()
