"""Locate names by repetition constraints; matches alone remain hypotheses."""
import collections
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.export_replay_ten import load_reviewed,reference
from scripts.research_object_name_patterns import shape
from lol_coach.http import save_json


def objects(value):
    if isinstance(value,dict):
        if value.get('__type')=='{ad65d8c4}':yield value
        for child in value.values():yield from objects(child)
    elif isinstance(value,list):
        for child in value:yield from objects(child)


def pattern(word):
    seen={};result=b''
    for c in word:
        if c not in seen:
            seen[c]=len(seen)+1;result+=b'(.)'
        else:result+=b'\\'+str(seen[c]).encode()
    return re.compile(result,re.S)


def main():
    path=ROOT/'data/research/object_sources/raw/240de083663f446ffbb9a35ec44849df773522b5d936acecaf9e1d97412b8830.bin'
    words=set()
    for obj in objects(json.loads(path.read_bytes())):
        kind=obj.get('AttackableUnit',{}).get('type')
        if kind not in (1,2):continue
        h=int(obj['name'][1:-1],16)
        for team in ('Order','Chaos'):
            word=f'Nexus_T{team}_{h}_0' if kind==2 else f'Barracks_T{team}_L1_{h}_0'
            words.add(word)
    patterns=[(w,rev,pattern(w[::-1] if rev else w)) for w in sorted(words) for rev in (False,True)]
    replay=Path(r'C:\Users\21613\Documents\League of Legends\Replays\HN1-11360086609.rofl')
    framer,_,_,deps=load_reviewed(ROOT.parent);matches=[]
    for p in framer.packets(replay):
        if p['time']!=0:continue
        for word,rev,pat in patterns:
            for m in pat.finditer(p['payload']):
                if shape(m.group())!=shape(word[::-1] if rev else word):continue
                matches.append(dict({k:p[k] for k in ('stream','chunk','offset','time','opcode','param')},
                    candidate_name=word,reversed=rev,name_offset=m.start(),wire_hex=m.group().hex(),payload_hex=p['payload'].hex()))
    output=dict(schema='special-name-research/v1',status='INSUFFICIENT_EVIDENCE',
        reference=reference(path),replay=reference(replay),dependencies=deps,candidate_words=sorted(words),matches=matches)
    save_json(ROOT/'data/private/world_objects/special_name_candidates.json',output)
    print(json.dumps(dict(matches=len(matches),opcodes=collections.Counter(hex(r['opcode']) for r in matches))))
    for m in matches[:15]:print(json.dumps({k:m[k] for k in ('opcode','param','name_offset','candidate_name','reversed')}))


if __name__=='__main__':main()
