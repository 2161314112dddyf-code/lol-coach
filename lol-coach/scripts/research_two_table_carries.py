"""Two static lookup tables with an intermediate carry; bounded search."""
import json,sys
from pathlib import Path
import numpy as np
from research_table_codec_mitm import rol,swap,key
ROOT=Path(__file__).resolve().parents[1];F=ROOT/'data/private/replay_completion'

def main():
    label=sys.argv[1]if len(sys.argv)>1 else 'reference'
    doc=json.loads((F/('item_stat_pairs_hubris.json'if label=='stat'else 'creation_reference_research.json')).read_text())
    pairs={int(k):v for k,v in (doc if label=='stat'else doc['pairs']).items()}
    xs=np.array(list(pairs),dtype=np.int32);ys=np.array(list(pairs.values()),dtype=np.int32)
    source=json.loads((F/'windows_permutations.json').read_text())['tables'];tables={}
    for offset,values in source.items():
        for inverse in(False,True):
            t=tuple(np.argsort(values).tolist())if inverse else tuple(values)
            tables.setdefault(t,f'{offset}:{inverse}')
    entries=[(label,np.array(t,dtype=np.int32))for t,label in tables.items()]
    aa=np.arange(256)[:,None,None];bb=np.arange(256)[None,:,None];results=[]
    for t2label,t2 in entries:
        t2inv=np.argsort(t2)
        for middle_swap in(False,True):
            rk=[];rp=[]
            for e in range(256):
                y=t2inv[(ys[:5]-e)&255]
                z=y[None,:]^np.arange(256)[:,None]
                if middle_swap:z=swap(z)
                for r in range(8):
                    zz=rol(z,(8-r)%8);rk.extend(key(zz).tolist())
                    rp.extend((e,r,d,int(zz[d,0]))for d in range(256))
            order=np.argsort(np.array(rk,dtype=np.uint64));keys=np.array(rk,dtype=np.uint64)[order]
            for t1label,t1 in entries:
                for input_swap in(False,True):
                    x=swap(xs[:5])if input_swap else xs[:5]
                    z=t1[((x[None,None,:]+aa)&255)^bb];k=key(z)
                    lo=np.searchsorted(keys,k,side='left');hi=np.searchsorted(keys,k,side='right')
                    for a,b in zip(*np.where(lo<hi)):
                        for i in range(lo[a,b],hi[a,b]):
                            e,r,d,z0=rp[order[i]];c=(z0-int(z[a,b,0]))&255
                            def transform(x):
                                if input_swap:x=swap(x)
                                x=rol((t1[((x+int(a))&255)^int(b)]+c)&255,r)
                                if middle_swap:x=swap(x)
                                return(t2[x^d]+e)&255
                            if not np.array_equal(transform(xs),ys):continue
                            results.append(dict(t1=t1label,t2=t2label,input_swap=input_swap,middle_swap=middle_swap,
                                a=int(a),b=int(b),c=c,d=d,e=e,r=r,table=transform(np.arange(256)).tolist()))
            print(label,t2label,middle_swap,'matches',len(results),flush=True)
            (F/f'{label}_two_table_carries.json').write_text(json.dumps(dict(pairs=pairs,models=results,accepted=False),indent=2))
    print('complete',len(results),flush=True)

if __name__=='__main__':main()
