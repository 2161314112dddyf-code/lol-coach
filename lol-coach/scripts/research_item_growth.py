"""Cross-constrain serialized item growth counters with three stat increments."""
import json,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def main():
    folder=ROOT/'data/private/replay_completion'
    rows=json.loads((folder/'4e9_decoded.json').read_text())['rows'];unique={};observations=[]
    for row in rows:
        for item in row['decoded']['items']:
            if item['item_id']!=6657:continue
            raw=bytes.fromhex(item['opaque_modifier_region_hex']);at=raw.find(b'\x3a');stats=raw[at+1:]
            if len(stats)!=18:continue
            if [stats[i]for i in (5,11,17)]!=[0x56,0xd6,0x62]:raise ValueError('Stat key order changed')
            header=int.from_bytes(bytes.fromhex(row['payload'])[item['payload_range'][0]:item['payload_range'][0]+3],'little')
            selector=header>>15&7;constant={0:0,1:2,7:1}.get(selector)
            wire='constant_'+str(constant)if constant is not None else raw[:at-4].hex()
            values=[stats[i:i+4]for i in (1,7,13)]
            previous=unique.get(wire)
            if previous and previous['values']!=[v.hex()for v in values]:raise ValueError('Growth counter/stat inconsistency')
            unique[wire]=dict(wire=wire,constant=constant,values=[v.hex()for v in values])
            observations.append(dict(time=row['time'],entity_id=hex(row['param']),wire=wire,modifier_hex=raw.hex()))
    cases=sorted(unique.values(),key=lambda r:r['constant']is None);solutions=[]
    def extend(table,n,row):
        inv={v:k for k,v in table.items()};out=dict(table)
        for multiplier,encoded in zip((3.,30.,10.),row['values']):
            for x,y in zip(struct.pack('<f',multiplier*n),bytes.fromhex(encoded)):
                if x in out and out[x]!=y or y in inv and inv[y]!=x:return None
                out[x]=y;inv[y]=x
        return out
    def search(index,table,counts):
        if index==len(cases):solutions.append(dict(counts=counts,stat_float_pairs=table));return
        row=cases[index]
        for n in ([row['constant']]if row['constant']is not None else range(1,11)):
            if n in counts.values():continue
            out=extend(table,n,row)
            if out is not None:search(index+1,out,{**counts,row['wire']:n})
    search(0,{},{});result=dict(cases=cases,observations=observations,solutions=solutions,
        assumptions=['Three serialized stats are AP, mana, health in key order 0x56,0xd6,0x62',
            'Item 6657 adds 3 AP,30 mana,10 health per counter, capped at 10',
            'One byte substitution for stat floats; independent cached keyframes are not assigned live time'])
    (folder/'item_growth_research.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(dict(solutions=len(solutions),models=solutions[:3])))


if __name__=='__main__':main()
