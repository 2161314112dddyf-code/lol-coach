"""String-pattern research for the new 0x2df neutral creation observations."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def reorder(w,mode):
    if mode==0:return w
    if mode==1:return w[::-1]
    v=w[::2]+w[1::2][::-1]
    return v if mode==2 else v[::-1]


def compatible(name,wire,table):
    inverse={v:k for k,v in table.items()};result=dict(table)
    for ch,b in zip(name.encode(),wire):
        if ch in result and result[ch]!=b or b in inverse and inverse[b]!=ch:return None
        result[ch]=b;inverse[b]=ch
    return result


def main():
    rows=json.loads((ROOT/'data/private/replay_completion/neutral_2df_packets.json').read_text())
    anchors=[(0x40000231,'SRU_Razorbeak',37,0),(0x40000233,'SRU_RazorbeakMini',41,2),(0x40000235,'SRU_RazorbeakMini',41,2)]
    tables=[]
    for actor,name,start,mode in anchors:
        row=next(r for r in rows if r['param']==actor and r['stream']==1)
        wire=reorder(bytes.fromhex(row['payload'])[start:start+len(name)],mode)
        table=compatible(name,wire,{})
        if table is None:raise ValueError('Contradictory character anchor')
        tables.append(dict(anchor=actor,table=table,order=mode))
    names=['SRU_Blue','SRU_Red','SRU_Gromp','SRU_Murkwolf','SRU_MurkwolfMini','SRU_Razorbeak','SRU_RazorbeakMini','SRU_Krug','SRU_KrugMini','SRU_KrugMiniMini','SRU_Crab']
    output=[]
    for row in rows:
        data=bytes.fromhex(row['payload']);candidates=[]
        for i,table in enumerate(tables):
            for name in names:
                for start in range(4,min(80,len(data)-len(name)+1)):
                    wire=reorder(data[start:start+len(name)],table['order'])
                    new=compatible(name,wire,table['table'])
                    if new is None:continue
                    candidates.append(dict(name=name,start=start,end=start+len(name),mode=i,
                        header=int.from_bytes(data[:4],'little'),length_wire=data[start-1],table=new))
        output.append(dict(**row,candidates=candidates))
    result=dict(anchors=anchors,tables=tables,rows=output,accepted_decoder=False)
    (ROOT/'data/private/replay_completion/neutral_string_candidates.json').write_text(json.dumps(result,indent=2))
    print(json.dumps([(hex(r['param']),r['stream'],[{k:v for k,v in c.items()if k!='table'}for c in r['candidates']])for r in output]))


if __name__=='__main__':main()
