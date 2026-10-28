"""Cross-field calibration hypotheses using simultaneous raw keyframes."""
import collections,json,struct,sys,bisect
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from export_replay_ten import load_reviewed
from lol_coach.replay_state import decode_payload,floating,varuint,FLOAT_BITS
from lol_coach.replay_extensions import attribute_group
from lol_coach.spell_state_fields import decode_fields

def main():
    f,*_=load_reviewed(ROOT.parent);attributes={};states=[];extra=[]
    source=Path('C:/Users/21613/Documents/League of Legends/Replays/HN1-11360086609.rofl')
    for p in f.packets(source):

        if p['opcode']==0x3df:
            for record in decode_payload(p['payload'])['records']:
                if not 0x40000034<=record['entity_id']<=0x4000003d:continue
                row=attributes.setdefault((p['chunk'],record['entity_id']),{})
                for group in record['groups']:
                    if group['group']not in(4,8,32):continue
                    try:
                        if group['group']==32:
                            fields=[];raw=bytes.fromhex(group['decoded_data_hex']);cursor=0
                            for bit in range(32):
                                if not group['field_mask']>>bit&1:continue
                                v,cursor=(floating(raw,cursor)if bit in FLOAT_BITS else varuint(raw,cursor,defaultable=True))
                                fields.append(dict(group=32,bit=bit,value=v))
                            if cursor!=len(raw):raise ValueError('Group32 tail')
                        else:fields=attribute_group(group)
                    except ValueError:continue
                    if p['stream']==1:
                        extra.append(dict(time_seconds=p['time'],entity_id=hex(record['entity_id']),fields=fields));continue
                    row.update({(x['group'],x['bit']):x['value']for x in fields})
        elif p['stream']==2 and p['opcode']==0x43e and 0x40000034<=p['param']<=0x4000003d:
            fields=decode_fields(p['payload'])
            if fields['slot']['index']in(0,1,2):states.append((p,fields))
    # Earlier keyframes omit hero attributes; use independently decoded live prefix.
    live=json.loads((ROOT/'data/private/remaining_decode/HN1-11360086609.json').read_text())['hero_attribute_groups']
    histories={}
    for row in extra:
        for field in row['fields']:
            key=(int(row['entity_id'],16),field['group'],field['bit'])
            histories.setdefault(key,[]).append((row['time_seconds'],field['value']))
    for p,_ in states:
        values=attributes.setdefault((p['chunk'],p['param']),{})
        for (actor,g,b),history in histories.items():
            if actor!=p['param']:continue
            index=bisect.bisect_right([t for t,v in history],p['time'])-1
            if index>=0:values[g,b]=history[index][1]
    results=[]
    for field_index in (0,1,2):
        for key in sorted({k for v in attributes.values()for k in v}):
            for transform,fun in [('identity',lambda x:x),('negative',lambda x:-x),('percent',lambda x:x*100),('fraction',lambda x:x/100),('cooldown_multiplier',lambda x:100/(100+x))]:
                table={};inverse={};samples=[];bad=[]
                for p,fields in states:
                    value=attributes.get((p['chunk'],p['param']),{}).get(key)
                    wire=fields['numeric_fields'][field_index]['wire_hex']
                    if value is None or not wire:continue
                    try:plain=struct.pack('<f',fun(value))
                    except (OverflowError,ZeroDivisionError):continue
                    good=True;t=dict(table);iv=dict(inverse)
                    for x,y in zip(plain,bytes.fromhex(wire)):
                        if x in t and t[x]!=y or y in iv and iv[y]!=x:good=False;break
                        t[x]=y;iv[y]=x
                    row=dict(time=p['time'],actor=hex(p['param']),slot=fields['slot']['index'],value=value,wire=wire)
                    if good:table=t;inverse=iv;samples.append(row)
                    else:bad.append(row)
                if samples:results.append(dict(field_index=field_index,group=key[0],bit=key[1],transform=transform,pairs=table,good=len(samples),bad=len(bad),examples=samples[:8],conflicts=bad[:3]))
    results.sort(key=lambda r:(r['bad']/(r['good']+r['bad']),-r['good']))
    folder=ROOT/'data/private/replay_completion'
    (folder/'spell_all_attribute_join.json').write_text(json.dumps(dict(results=results,accepted=False),indent=2))
    print(json.dumps([{k:v for k,v in r.items()if k not in ('examples','conflicts','pairs')} for r in results[:30]],indent=2))

if __name__=='__main__':main()
