"""Read-only PROP v3 research for locally extracted object configurations.

Format reference: https://github.com/CommunityDragon/CDTB/blob/master/cdtb/binfile.py
Restricted to the observed 16.20 field kinds; unknown kinds fail explicitly.
"""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


sys.path.insert(0, str(ROOT))
from lol_coach.prop_reader import Reader, fnv


def main():
    names={};keys=set()
    def collect(v):
        if isinstance(v,dict):
            for k,x in v.items():keys.add(k);collect(x)
        elif isinstance(v,list):
            for x in v:collect(x)
        elif isinstance(v,str)and len(v)<200:keys.add(v)
    for folder in ('data/raw','data/research/world_sources/raw'):
        for p in (ROOT/folder).glob('*.bin'):
            b=p.read_bytes()
            if not b.startswith(b'{'):continue
            try:collect(json.loads(b))
            except (ValueError,UnicodeDecodeError):continue
    for k in keys:
        if not k.startswith('{'):names[fnv(k)]=k
    folder=ROOT/'data/private/replay_completion/character_sources';results=[]
    for p in folder.glob('*.bin'):
        try:
            result=Reader(p.read_bytes(),names).parse();(folder/(p.stem+'.json')).write_text(json.dumps(result,indent=2));results.append(dict(name=p.stem,status='parsed'))
            def vision(v,path=''):
                if not isinstance(v,dict):return
                for k,x in v.items():
                    if any(s in k.lower()for s in ('vision','sight','reveal')):print(p.stem,path+'/'+k,json.dumps(x))
                    vision(x,path+'/'+k)
            vision(result)
        except ValueError as exc:results.append(dict(name=p.stem,error=str(exc)))
    (folder/'parse_results.json').write_text(json.dumps(results,indent=2));print(json.dumps(results))


if __name__=='__main__':main()
