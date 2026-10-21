"""Test a candidate spawn-ID field against independently framed actor IDs."""
import collections
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT.parent/'vendor/reverse-tools')]
from scripts.export_replay_ten import load_reviewed,reference
from lol_coach.http import save_json
import z3


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--bits',type=int,choices=[16,32],default=32)
    args=parser.parse_args();bits=args.bits
    replay=Path(r'C:\Users\21613\Documents\League of Legends\Replays\HN1-11360086609.rofl')
    world=json.loads((ROOT/'data/private/world_objects/HN1-11360086609.json').read_text())
    framer,_,_,_=load_reviewed(ROOT.parent);packets=list(framer.packets(replay))
    ps=[p for p in packets if p['opcode']==0x10a and p['stream']==1]
    enters=collections.defaultdict(list)
    for p in packets:
        if p['stream']==1 and p['opcode']==0x484:enters[p['param']].append(p)
    pairs=[]
    for birth in world['birth_pair_candidates']:
        if birth['time_seconds']>=150:continue
        entities={}
        for entity in birth['entities']:
            actor=int(entity,16)
            before=[p for p in enters[actor] if 0<=birth['time_seconds']-p['time']<.11]
            if len(before)==1 and before[0]['payload'].hex() in ('a0c5','a0f5'):
                entities[before[0]['payload'].hex()]=actor
        if len(entities)!=2:continue
        for p in ps:
            if not 0<=birth['time_seconds']-p['time']<.11:continue
            d=p['payload'];cursor=0;found=[]
            while (cursor:=d.find(bytes.fromhex('831a'),cursor))>=0:
                marker=d[cursor+2:cursor+5].hex()
                if cursor>=2 and marker in ('feeeed','fefeed'):
                    actor=entities['a0c5' if marker=='feeeed' else 'a0f5']
                    found.append(dict(entity_id=actor,wire_hex=d[cursor-2:cursor+2].hex(),
                        time_seconds=p['time'],payload_offset=cursor-2,chunk=p['chunk'],offset=p['offset']))
                cursor+=2
            if len(found)==2:pairs+=found
    print('candidate pairs',len(pairs),flush=True)
    models=[]
    train=pairs[:16];held=pairs[16:]
    for location in range(8):
        a,b,c,d,e,r,s=z3.BitVecs('a b c d e r s',bits)
        swap_mask=0x5555 if bits==16 else 0x55555555
        def swap(x):return ((x&swap_mask)<<1)|(z3.LShR(x,1)&swap_mask)
        def expression(x):
            if location&1:x=swap(x)
            x=z3.RotateLeft(x+a,r)
            if location&2:x=swap(x)
            x=(x^b)+c
            x=z3.RotateLeft(x,s)^d
            if location&4:x=swap(x)
            return x+e
        solver=z3.Solver();solver.set(timeout=8000 if bits==16 else 4000)
        solver.add(z3.ULE(r,bits-1),z3.ULE(s,bits-1))
        for row in train:solver.add(expression(z3.BitVecVal(row['entity_id'],bits))==int.from_bytes(bytes.fromhex(row['wire_hex'])[:bits//8],'little'))
        status=solver.check();result=dict(swap_position=location,status=str(status))
        if status==z3.sat:
            m=solver.model();result['parameters']={str(v):m.eval(v,model_completion=True).as_long() for v in (a,b,c,d,e,r,s)}
            result['heldout_matches']=sum(m.eval(expression(z3.BitVecVal(row['entity_id'],bits))).as_long()==int.from_bytes(bytes.fromhex(row['wire_hex'])[:bits//8],'little') for row in held)
        print(result,flush=True);models.append(result)
    save_json(ROOT/'data/private/world_objects'/f'spawn_id_models{bits}.json',dict(replay=reference(replay),bits=bits,
        training_pairs=train,heldout_pairs=held,models=models,status='research_only; not an accepted decoder'))


if __name__=='__main__':main()
