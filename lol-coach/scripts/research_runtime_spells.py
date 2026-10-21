"""Extend hash vocabulary using versioned client SpellObject names, not guesses."""
from collections import Counter,defaultdict
import hashlib,json,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from research_spell_hashes import elf
from research_inventory_constraints import leb,compatible,extend
from lol_coach.replay_fields import read_metadata


def main():
    original=json.loads((ROOT/'data/research/spell_hashes_1620.json').read_text(encoding='utf8'))
    raw=json.loads((ROOT/'data/research/spell_vision_anchors.json').read_text(encoding='utf8'))
    sources=json.loads((ROOT/'reports/world_character_sources_corrected.json').read_text(encoding='utf8'))
    names=['Aphelios','Zyra','Leblanc','Veigar','Karthus','MasterYi','Jhin','Kayle','Ryze','Fizz']
    dictionary={};source_refs={}
    for source in sources:
        if source['http_status']!=200:continue
        path=ROOT/'data/research/world_sources'/source['evidence_path'];data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=source['sha256']:raise ValueError('Source changed')
        champ=source['requested_url'].split('/')[-2]
        entries=json.loads(data)
        spells={v['mScriptName']:dict(object_key=k,has_cast_data='mSpell' in v,
                    sha256=source['sha256'],url=source['requested_url'])
                for k,v in entries.items() if isinstance(v,dict) and v.get('__type')=='SpellObject' and v.get('mScriptName')}
        dictionary[champ]=spells;source_refs.update(spells)
    encoding={int(k):v for k,v in original['encoding_pairs'].items()}
    words=dict(original['accepted_word_hypotheses']);rounds=[]
    packets=raw['games'][0]['hero_candidate_packets']
    # ZyraR and ZyraP initially share the same unconstrained hash suffix.
    # Seven nearby -100 resource transitions distinguish the source R cost
    # (100) from the source P cost (70). One activity has no such transition.
    state=json.loads((ROOT/'data/private/replay_state/HN1-11360086609.json').read_text(encoding='utf8'))
    updates=[u for u in state['updates'] if u['entity_id']=='0x40000035' and 'resource' in u['values']]
    cost_anchors=[]
    for p in packets:
        d=bytes.fromhex(p['payload_hex']);a=d.rfind(b'\xed'*4)
        if p['entity_id']!='0x40000035' or not any(d[a+off:a+off+4]==bytes.fromhex('20dfccad') for off in range(5,12)):continue
        t=p['time_seconds'];deltas=[]
        for before,after in zip(updates,updates[1:]):
            if 0<=after['time_seconds']-t<=.4 and after['time_seconds']-before['time_seconds']<.7:
                delta=before['values']['resource']-after['values']['resource']
                if abs(delta-100)<.01:deltas.append(dict(before=before,after=after,resource_spend=delta))
        cost_anchors.append(dict(time_seconds=t,matched_resource_transitions=deltas))
    if sum(bool(a['matched_resource_transitions']) for a in cost_anchors)!=7:
        raise ValueError('Zyra R/P disambiguation evidence changed')
    extend(encoding,leb(elf('ZyraR')),bytes.fromhex('20dfccad'));words['ZyraR']='20dfccad'
    for turn in range(15):
        proposed={}
        for i,name in enumerate(names):
            candidates=[p for p in packets if p['entity_id']==hex(0x40000034+i)]
            for spell in dictionary[name.lower()]:
                if spell in words:continue
                plain=leb(elf(spell));counts=Counter()
                for p in candidates:
                    d=bytes.fromhex(p['payload_hex']);a=d.rfind(b'\xed'*4)
                    if a<0:continue
                    for off in range(5,12):
                        wire=d[a+off:a+off+len(plain)]
                        if compatible(encoding,plain,wire):counts[wire.hex()]+=1
                fits={w:n for w,n in counts.items() if n>=3 and w not in words.values()}
                if len(fits)==1:proposed[spell]=next(iter(fits))
        counts=Counter(proposed.values());proposed={k:v for k,v in proposed.items() if counts[v]==1}
        if not proposed:break
        accepted={}
        for spell,wire in proposed.items():
            if compatible(encoding,leb(elf(spell)),bytes.fromhex(wire)):
                extend(encoding,leb(elf(spell)),bytes.fromhex(wire));words[spell]=wire;accepted[spell]=wire
        if not accepted:break
        rounds.append(dict(round=turn,added=accepted))
    # Fully constrained names are decoded without requiring three occurrences.
    for champ,spells in dictionary.items():
        for spell in spells:
            plain=leb(elf(spell))
            if all(b in encoding for b in plain):
                wire=bytes(encoding[b] for b in plain).hex()
                if wire not in words.values():words[spell]=wire
    matches=[];counts=defaultdict(Counter)
    for game in raw['games']:
        for p in game['hero_candidate_packets']:
            d=bytes.fromhex(p['payload_hex']);a=d.rfind(b'\xed'*4)
            if a<0:continue
            found=[]
            for spell,wire in words.items():
                word=bytes.fromhex(wire)
                for off in range(5,12):
                    if d[a+off:a+off+len(word)]==word:found.append((spell,a+off))
            if len(found)==1:
                spell,offset=found[0]
                matches.append(dict(**p,replay_source=game['source'],spell_name=spell,hash_payload_offset=offset,
                    first_byte=d[0],primary_flag_candidate=bool(d[0]&16)))
                counts[spell][hex(d[0])]+=1
    result=dict(status='BOUNDED_HASH_VOCABULARY',encoding_pairs=encoding,words=words,rounds=rounds,
        source_refs=source_refs,phase_counts={k:dict(v) for k,v in counts.items()},matches=matches,
        zyra_r_resource_calibration=cost_anchors,
        limitations=['Original 33-word calibration retained', 'Unknown hash bytes are not guessed',
            'Primary/followup indicator is a candidate; complete counts and cooldowns unresolved'])
    (ROOT/'data/research/runtime_spell_hashes.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(byte_pairs=len(encoding),vocabulary=len(words),matched_names=len(counts),matches=len(matches),rounds=rounds,phases=result['phase_counts']),ensure_ascii=False))


if __name__=='__main__':main()
