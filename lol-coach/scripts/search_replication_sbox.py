"""Finite meet-in-the-middle search; uses no client process or game execution."""
from pathlib import Path
import json
import numpy as np

ROOT=Path(__file__).resolve().parents[1]


def rol(x,r):return ((x<<r)|(x>>(8-r)))&255
def swap(x):return ((x&85)<<1)|((x>>1)&85)


def main():
    raw=(ROOT/'data/research/client_16.20.824.8524_mac/LeagueofLegends').read_bytes()[16384:]
    pairs={0:0xc9,64:0xdf,**dict(zip(range(52,62),bytes.fromhex('a9b7a0e2854dec196611')))}
    xs=np.array(list(pairs),dtype=np.int32);ys=np.array(list(pairs.values()),dtype=np.int32)
    results=[]
    tables={}
    indices=np.arange(256)
    for offset in (0x232da30,0x232db30):
        original=np.frombuffer(raw[offset:offset+256],dtype=np.uint8).astype(np.int32)
        for repetitions in (1,2,3):
            t=indices.copy()
            for _ in range(repetitions):t=original[t]
            for inner_swap in range(4):
                variant=t[swap(indices)] if inner_swap&1 else t
                if inner_swap&2:variant=swap(variant)
                tables[tuple(variant)]=(f'{hex(offset)}:repeat{repetitions}:swap{inner_swap}',variant)
    for label,t in tables.values():
        for mode in range(4):
            x=swap(xs) if mode&1 else xs;y=swap(ys) if mode&2 else ys
            right={}
            for s in range(8):
                for d in range(256):
                    z=rol(y^d,(8-s)%8);key=bytes(((z[1:]-z[0])&255).astype(np.uint8))
                    right.setdefault(key,[]).append((s,d,int(z[0])))
            bs=np.arange(256)[:,None]
            for r in range(8):
                for a in range(256):
                    z=t[rol((x+a)&255,r)^bs]
                    diffs=((z[:,1:]-z[:,0:1])&255).astype(np.uint8)
                    for b,row in enumerate(diffs):
                        for s,d,z0 in right.get(row.tobytes(),[]):
                            c=(z0-int(z[b,0]))&255
                            values=np.arange(256)
                            if mode&1:values=swap(values)
                            values=rol((t[rol((values+a)&255,r)^b]+c)&255,s)^d
                            if mode&2:values=swap(values)
                            table=values.tolist()
                            assert all(table[k]==v for k,v in pairs.items())
                            result=dict(sbox_variant=label,mode=mode,a=a,b=b,c=c,d=d,r=r,s=s,table=table)
                            results.append(result);print({k:v for k,v in result.items() if k!='table'},flush=True)
        print('finished',label,flush=True)
    (ROOT/'data/research/replication_sbox_search.json').write_text(json.dumps({'pairs':pairs,'models':results},indent=2),encoding='utf8')


if __name__=='__main__':main()
