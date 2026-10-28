"""Test simple relations to cached static substitution tables; research only."""
import json
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'data/private/replay_completion'

def rol(x,r):return ((x<<r)|(x>>(8-r)))&255
def swap(x):return ((x&85)<<1)|((x>>1)&85)

def main():
    pairs={int(k):v for k,v in json.loads((FOLDER/'item_stat_pairs_new.json').read_text()).items()}
    xs=np.array(list(pairs),dtype=np.int32);ys=np.array(list(pairs.values()),dtype=np.int32)
    params=np.arange(256)[:,None];right={};results=[]
    for mode in range(4):
        for r in range(8):
            y=swap(ys)if mode&1 else ys
            z=rol((y+params)&255,r)
            if mode&2:z=swap(z)
            for a,row in enumerate((z^z[:,:1]).astype(np.uint8)):
                right.setdefault(row.tobytes(),[]).append((mode,r,a,int(z[a,0])))
    for filename in ('windows_permutations.json','mac_permutations.json'):
        data=json.loads((FOLDER/filename).read_text());tables=data['tables']
        for label,values in tables.items():
            for inverse in (False,True):
                table=np.argsort(values)if inverse else np.array(values)
                for mode in range(4):
                    for r in range(8):
                        x=swap(xs)if mode&1 else xs
                        z=rol((x+params)&255,r)
                        if mode&2:z=swap(z)
                        z=table[z]
                        for a,row in enumerate((z^z[:,:1]).astype(np.uint8)):
                            for rm,rr,ra,z0 in right.get(row.tobytes(),[]):
                                results.append(dict(file=filename,label=label,inverse=inverse,
                                    input_mode=mode,input_rotation=r,input_add=a,
                                    output_mode=rm,output_rotation=rr,output_add=ra,xor=int(z[a,0])^z0))
        print(filename,'tables',len(tables),'matches',len(results),flush=True)
    (FOLDER/'item_stat_table_relations.json').write_text(json.dumps(dict(pairs=pairs,results=results,accepted=False),indent=2))

if __name__=='__main__':main()
