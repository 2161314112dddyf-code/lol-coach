"""Recover observed spell-name varuint substitutions from raw packet anchors.

Pantheon cost-associated Q/W/E are training seeds, not independent labels.
Cross-champion unique matches extend the table; phase/new-cast stays separate.
"""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from research_inventory_constraints import leb, compatible, extend


def elf(name):
    value=0
    for c in name.lower().encode('ascii'):
        value=(value<<4)+c
        high=value&0xf0000000
        value^=high>>24
        value&=~high
    return value


def main():
    anchors=ROOT/'data/research/spell_vision_anchors.json'
    source=json.loads(anchors.read_text(encoding='utf8'))
    names=['Aphelios','Zyra','Leblanc','Veigar','Karthus','MasterYi','Jhin','Kayle','Ryze','Fizz']
    static={};sources=[]
    for path in (ROOT/'data/research/spell_sources/raw').glob('*.bin'):
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=path.stem:raise ValueError('Static cache hash changed')
        value=json.loads(raw)
        for name,champ in value.get('data',{}).items():
            if 'spells' in champ:
                static[name]=[s['id'] for s in champ['spells']]
                sources.append(dict(champion=name,sha256=path.stem,version=value['version']))
    from lol_coach.replay_fields import read_metadata
    summoner_path=ROOT/'data/research/world_sources/raw/faf271429f8cda1fbdae1e8dc9e2354032c3dc878cfa40a2a19188290fcbaabc.bin'
    if hashlib.sha256(summoner_path.read_bytes()).hexdigest()!=summoner_path.stem:raise ValueError('Summoner cache changed')
    summons=json.loads(summoner_path.read_text(encoding='utf8'))['data']
    by_id={s['key']:s['id'] for s in summons.values()}
    _,_,stats=read_metadata(Path(source['games'][0]['source']).read_bytes())
    for champion in stats:
        static[champion['SKIN']]+=[by_id[champion[f'SUMMONER_SPELL_{i}']] for i in (1,2)]
    sources.append(dict(champion=None,sha256=summoner_path.stem,version='16.20.1',
        calibration='Final summoner IDs restrict research candidates; not used as time-t cooldown or ownership facts'))
    encoding={};accepted={};seeds=[]
    for spell,wire in [('PantheonQ','4bbd79aa'),('PantheonW','62bd79aa'),('PantheonE','54bd79aa')]:
        extend(encoding,leb(elf(spell)),bytes.fromhex(wire));accepted[spell]=wire
        seeds.append(dict(spell=spell,wire=wire,plain_varuint_hex=leb(elf(spell)).hex(),basis='Training resource cost association; ELF-varuint hypothesis'))
    rows=source['games'][0]['hero_candidate_packets']
    candidates={};rounds=[]
    for turn in range(15):
        added={}
        for i,name in enumerate(names):
            packets=[p for p in rows if p['entity_id']==hex(0x40000034+i)]
            for spell in static[name]:
                plain=leb(elf(spell));counts=Counter()
                for p in packets:
                    d=bytes.fromhex(p['payload_hex']);a=d.rfind(b'\xed'*4)
                    if a<0:continue
                    for off in (6,7):
                        wire=d[a+off:a+off+len(plain)]
                        if compatible(encoding,plain,wire):counts[wire.hex()]+=1
                # Singleton coincidence is not enough to extend the byte table.
                fits={w:n for w,n in counts.items() if n>=3}
                candidates[spell]=fits
                if len(fits)==1 and spell not in accepted:
                    added[spell]=next(iter(fits))
        # Absence/replaced spell variants are possible. Two names proposing the
        # same wire word cannot both train a bijection; retain the ambiguity.
        uses=Counter(added.values())
        added={name:wire for name,wire in added.items() if uses[wire]==1}
        if not added:break
        for spell,wire in added.items():
            if not compatible(encoding,leb(elf(spell)),bytes.fromhex(wire)):
                failure=dict(status='FAIL',reason='Greedy unique candidate conflicts with another candidate',
                    spell=spell,wire=wire,encoding_pairs=encoding,accepted=accepted,round=turn,proposed=added)
                (ROOT/'data/research/spell_hashes_conflict.json').write_text(json.dumps(failure,indent=2),encoding='utf8')
                print(json.dumps(failure,indent=2));return
            extend(encoding,leb(elf(spell)),bytes.fromhex(wire));accepted[spell]=wire
        rounds.append(dict(round=turn,new_unique_matches=added))
    matches=[];phases=defaultdict(Counter)
    for game in source['games']:
        for p in game['hero_candidate_packets']:
            d=bytes.fromhex(p['payload_hex']);a=d.rfind(b'\xed'*4)
            if a<0:continue
            for spell,wire in accepted.items():
                word=bytes.fromhex(wire)
                for off in (6,7):
                    if d[a+off:a+off+len(word)]==word:
                        matches.append(dict(**p,replay_source=game['source'],spell_name_candidate=spell,hash_payload_offset=a+off,
                            first_byte=hex(d[0]),first_bit4_candidate=bool(d[0]&16),
                            spelling_hash=elf(spell),stage_semantics_verified=False))
                        phases[spell][hex(d[0])]+=1
    result=dict(status='RESEARCH_CANDIDATES',source_sha256=hashlib.sha256(anchors.read_bytes()).hexdigest(),
        sources=sources,seeds=seeds,encoding_pairs=encoding,rounds=rounds,accepted_word_hypotheses=accepted,
        remaining_candidates={k:v for k,v in candidates.items() if k not in accepted},
        phase_bytes={k:dict(v) for k,v in phases.items()},matches=matches,
        limitation='Variable hash boundary uses two observed offsets; not a full packet grammar; no new-cast events accepted yet')
    out=ROOT/'data/research/spell_hashes_1620.json';out.write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps(dict(pairs=len(encoding),accepted=accepted,rounds=rounds,phases=result['phase_bytes'],matches=len(matches)),indent=2))


if __name__=='__main__':main()
