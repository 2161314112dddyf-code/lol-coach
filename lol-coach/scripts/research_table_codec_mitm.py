"""Meet-in-the-middle codec search including an outer carry after bit swap."""
import json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];F=ROOT/'data/private/replay_completion'
def rol(x,r):return ((x<<r)|(x>>(8-r)))&255
def swap(x):return ((x&85)<<1)|((x>>1)&85)
def key(z):
    d=((z[...,1:5]-z[...,:1])&255).astype(np.uint64)
    return d[...,0]|d[...,1]<<8|d[...,2]<<16|d[...,3]<<24
def main():
    label=sys.argv[1]if len(sys.argv)>1 else 'stat'
    doc=json.loads((F/('item_stat_pairs_hubris.json'if label=='stat'else 'creation_reference_research.json')).read_text())
    pairs={int(k):v for k,v in (doc if label=='stat'else doc['pairs']).items()}
    xs=np.array(list(pairs),dtype=np.int32);ys=np.array(list(pairs.values()),dtype=np.int32)
    tables=json.loads((F/'windows_permutations.json').read_text())['tables'];results=[]
    aa=np.arange(256)[:,None,None];bb=np.arange(256)[None,:,None]
    for output_swap in (False,True):
        right_keys=[];right_params=[]
        for e in range(256):
            y=(ys[:5]-e)&255
            if output_swap:y=swap(y)
            for s in range(8):
                z=rol(y[None,:]^np.arange(256)[:,None],(8-s)%8)
                right_keys.extend(key(z).tolist())
                right_params.extend((e,s,d,int(z[d,0]))for d in range(256))
        order=np.argsort(np.array(right_keys,dtype=np.uint64));keys=np.array(right_keys,dtype=np.uint64)[order]
        print(label,'right',output_swap,len(keys),flush=True)
        for ti,(offset,values)in enumerate(tables.items()):
            for invert in (False,True):
                table=np.argsort(values)if invert else np.array(values)
                for input_swap in (False,True):
                    x=swap(xs[:5])if input_swap else xs[:5]
                    for r in range(8):
                        z=table[rol((x[None,None,:]+aa)&255,r)^bb]
                        k=key(z);lo=np.searchsorted(keys,k,side='left');hi=np.searchsorted(keys,k,side='right')
                        for a,b in zip(*np.where(lo<hi)):
                            for index in range(lo[a,b],hi[a,b]):
                                e,s,d,z0=right_params[order[index]];c=(z0-int(z[a,b,0]))&255
                                xx=swap(xs)if input_swap else xs
                                predicted=rol((table[rol((xx+int(a))&255,r)^int(b)]+c)&255,s)^d
                                if output_swap:predicted=swap(predicted)
                                predicted=(predicted+e)&255
                                if not np.array_equal(predicted,ys):continue
                                xx=np.arange(256)
                                if input_swap:xx=swap(xx)
                                allv=rol((table[rol((xx+int(a))&255,r)^int(b)]+c)&255,s)^d
                                if output_swap:allv=swap(allv)
                                results.append(dict(offset=offset,invert=invert,input_swap=input_swap,output_swap=output_swap,
                                    a=int(a),b=int(b),c=c,d=d,e=e,r=r,s=s,table=((allv+e)&255).tolist()))
            if ti%10==0:print(label,'table',ti,'matches',len(results),flush=True)
            (F/f'{label}_table_mitm.json').write_text(json.dumps(dict(pairs=pairs,models=results,accepted=False),indent=2))
    print('complete',len(results),flush=True)
if __name__=='__main__':main()
