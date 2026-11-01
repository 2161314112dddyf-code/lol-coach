"""Bounded, offline identity attempts on the four exact-build replay files.

No raw file, decoder, production identity directory or model input is changed.
All correlations remain candidates; known main-game metadata supplies labels.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from export_replay_ten import load_reviewed
from lol_coach.replay_fields import read_metadata, VERSION
from lol_coach.spell_activity import decode_activity, load_profile

STEMS = ('HN1-11360086609','HN1-11363048522','HN1-11363093470','HN1-11372643015')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def anchor(p):
    return dict(time_seconds=p['time'],entity_id=hex(p['param']),source=dict(
        stream=p['stream'],chunk=p['chunk'],decompressed_offset=p['offset'],
        opcode=hex(p['opcode']),payload_length=len(p['payload']),
        payload_sha256=hashlib.sha256(p['payload']).hexdigest()))


def scan_team_byte_hypotheses(packets, teams):
    """Post-hoc fixed offsets, with all changing/contradictory trials retained."""
    families=defaultdict(lambda:defaultdict(list))
    for p in packets:
        if p['param'] in teams:
            families[(p['stream'],p['opcode'])][p['param']].append(p)
    result=[]
    for (stream,opcode), actors in families.items():
        if set(actors)!=set(teams):
            continue
        first={e:rows[0]['payload'] for e,rows in actors.items()}
        for offset in range(min(160,min(map(len,first.values())))):
            for direction in ('from_start','from_end'):
                i=offset if direction=='from_start' else -offset-1
                values={team:{b[i] for e,b in first.items() if teams[e]==team} for team in (100,200)}
                if any(len(v)!=1 for v in values.values()) or values[100]==values[200]:
                    continue
                labels={t:next(iter(v)) for t,v in values.items()}
                seen=matched=short=0; examples=[]
                for entity,rows in actors.items():
                    for p in rows:
                        if len(p['payload'])<=offset:
                            short+=1;continue
                        seen+=1
                        if p['payload'][i]==labels[teams[entity]]:
                            matched+=1
                        elif len(examples)<3:
                            examples.append(dict(**anchor(p),wire_byte=p['payload'][i],
                                                 expected=labels[teams[entity]]))
                result.append(dict(stream=stream,opcode=hex(opcode),offset=offset,
                    direction=direction,team_to_wire=labels,matched=matched,eligible_rows=seen,
                    too_short=short,counterexamples=examples,
                    status='CORRELATION_ONLY' if matched==seen and not short else 'REJECTED_AS_STATIC_TEAM_FIELD'))
    return result


def candidate_patterns(profile):
    patterns=[]
    names=('Pantheon','pantheon','MasterYi','masteryi','TargetDummy','PracticeTool_TargetDummy')
    for name in names:
        patterns.append(dict(name=name,codec='literal_ascii',wire=name.encode('ascii')))
        patterns.append(dict(name=name,codec='literal_utf16le',wire=name.encode('utf-16le')))
    for mode,spec in enumerate(profile['name_modes']):
        table={int(k):v for k,v in spec['table'].items()}
        for name in names:
            if not all(b in table for b in name.encode('ascii')):
                continue
            b=bytes(table[x] for x in name.encode('ascii'))
            if spec['order']==1:
                wire=b[::-1]
            elif spec['order']==2:
                n=len(b);a,c=b[:(n+1)//2],b[(n+1)//2:][::-1]
                wire=bytes(a[j//2] if j%2==0 else c[j//2] for j in range(n))
            else:
                raise ValueError('Unknown existing name codec')
            patterns.append(dict(name=name,codec=f'created_object_mode_{mode}',wire=wire))
    return patterns


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    out=args.output.resolve(); allowed=(ROOT/'data/private').resolve()
    if not out.is_relative_to(allowed) or out==allowed:
        raise ValueError('Output must be a new private child')
    out.mkdir(parents=True,exist_ok=False)
    dependencies={}
    def tracked(path):
        path=path.resolve(); dependencies[str(path)]=sha(path)
        return json.loads(path.read_text(encoding='utf8'))
    framer,_,_,refs=load_reviewed(ROOT.parent)
    dependencies.update({r['path']:r['sha256'] for r in refs.values()})
    profile=tracked(ROOT/'lol_coach/profiles/created_objects_16_20.json')
    spell_profile=load_profile()
    for path in ('lol_coach/profiles/spell_activity_16_20.json','lol_coach/spell_activity.py',
                 'lol_coach/replay_fields.py','scripts/research_travel_identity_evidence.py'):
        dependencies[str((ROOT/path).resolve())]=sha(ROOT/path)
    patterns=candidate_patterns(profile); all_packets={}; bundles={}; results=[]
    for stem in STEMS:
        source=Path('C:/Users/21613/Documents/League of Legends/Replays')/(stem+'.rofl')
        dependencies[str(source)]=sha(source)
        raw=source.read_bytes();version,metadata,stats=read_metadata(raw)
        ten=tracked(ROOT/f'data/private/replay_ten/{stem}.json')
        slots=tracked(ROOT/f'data/private/spell_slots/{stem}.json')
        activity=tracked(ROOT/f'data/private/spell_activity/{stem}.json')
        vision=tracked(ROOT/f'data/private/replay_vision/{stem}.json')
        digest=hashlib.sha256(raw).hexdigest()
        if version!=VERSION or ten['replay_sha256']!=digest or any(
                b['source_sha256']!=digest for b in (slots,activity,vision)):
            raise ValueError('Evidence replay binding mismatch')
        packets=list(framer.packets(source)); all_packets[stem]=packets; bundles[stem]=ten
        owners={int(a['entity_id'],16) for a in ten['identity_directory']['owners']}
        by_anchor={(p['stream'],p['chunk'],p['offset']):p for p in packets}
        redecode=[]
        for e in activity['events']:
            src=e['source']; p=by_anchor[(src['stream'],src['chunk'],src['decompressed_offset'])]
            decoded=decode_activity(p['payload'],profile=spell_profile)
            if decoded['spell_name']!=e['spell_name'] or hashlib.sha256(p['payload']).hexdigest()!=src['payload_sha256']:
                raise ValueError('Activity evidence changed')
            redecode.append(dict(**anchor(p),spell_name=decoded['spell_name'],
                hash_payload_offset=decoded['hash_payload_offset'],wire=decoded['wire']))
        first_directory={}
        for p in packets:
            if p['opcode']==0x445 and p['param'] in owners:
                first_directory.setdefault(p['param'],dict(**anchor(p),payload_hex=p['payload'].hex()))
        name_hits=[]
        if stem!=STEMS[0]:
            for p in packets:
                for pattern in patterns:
                    at=p['payload'].find(pattern['wire'])
                    if at>=0:
                        name_hits.append(dict(**anchor(p),name=pattern['name'],codec=pattern['codec'],payload_offset=at))
        candidate_rows=[]
        for p in packets:
            if p['opcode']==0x355 and p['param'] in owners:
                byte=p['payload'][67] if len(p['payload'])>67 else None
                candidate_rows.append(dict(**anchor(p),payload_offset=67,wire_byte=byte,
                    context_payload_range=[60,75],context_hex=p['payload'][60:75].hex(),
                    team_correlation_candidate={0x26:100,0x66:200}.get(byte),
                    decoder_accepted=False,decision_input_eligible=False,
                    availability='checkpoint observation only; cannot backfill the live decision prefix'))
        results.append(dict(replay_id=stem,source_sha256=digest,version=version,
            packet_count=len(packets),metadata_keys=sorted(metadata),metadata_participants=len(stats),
            owners=[first_directory[e] for e in sorted(first_directory)],
            known_team_mapping=ten['entity_to_participant'],
            activity_redecoded=redecode,named_activity_counts=dict(Counter(e['spell_name'] for e in redecode)),
            spell_slot_counts=dict(Counter(str(e.get('slot_label')) for e in slots['events'])),
            named_pattern_hits=name_hits if stem!=STEMS[0] else None,
            visibility_events=vision['events'] if stem!=STEMS[0] else None,
            team_field_candidate_rows=candidate_rows,
            accepted_champion_from_payload=False,accepted_team_from_payload=False))
    main_ten=bundles[STEMS[0]]
    teams={int(entity,16):main_ten['categories']['participants'][index]['team_id']
           for entity,index in main_ten['entity_to_participant'].items()}
    trials=scan_team_byte_hypotheses(all_packets[STEMS[0]],teams)
    yi=next(p['payload'] for p in all_packets[STEMS[0]] if p['opcode']==0x445 and p['param']==0x40000039)
    similarities=[]
    for stem in STEMS[1:]:
        target=next(p['payload'] for p in all_packets[stem] if p['opcode']==0x445 and p['param']==0x400000ae)
        match=SequenceMatcher(None,yi,target,autojunk=False).find_longest_match()
        similarities.append(dict(replay_id=stem,known_main_actor='MasterYi',unknown_actor='0x400000ae',
            main_payload_offset=match.a,short_payload_offset=match.b,length=match.size,
            shared_hex=yi[match.a:match.a+match.size].hex(),
            verdict='Shared payload span cannot establish champion identity; spell activity in 48522 identifies Pantheon-named abilities'))
    unchanged={path:sha(Path(path))==digest for path,digest in dependencies.items()}
    if not all(unchanged.values()):
        raise ValueError('An input changed during read-only research')
    result=dict(schema='travel-identity-evidence-attempt/v1',task='ROUND-008-EVIDENCE',
        created_at_utc=datetime.now(timezone.utc).isoformat(),version=VERSION,inputs=dependencies,
        inputs_unchanged=unchanged,cohort=results,posthoc_fixed_team_byte_trials=trials,
        name_patterns=[dict(name=p['name'],codec=p['codec'],wire_hex=p['wire'].hex()) for p in patterns],
        shared_445_counterexamples=similarities,
        conclusions=dict(metadata_short_rosters_missing=True,
            strongest_new_team_candidate='0x355 payload offset 67: 0x26/0x66 correlates with team100/200 across all 150 main-game keyframes',
            team_candidate_is_explicit_decoded_field=False,
            short_pantheon_ability_support='48522 only, from 19.73005194091797s; not authoritative hero creation or immunity to copied abilities',
            visibility_inverse_not_independent=True,
            short_identity_binding_status='INSUFFICIENT_EVIDENCE',
            offline_duration_validation_does_not_require_team_permission=True,
            model_integration_permitted=False),
        scope='Bounded post-hoc corpus research; no new name/team decoder accepted; no source or model input mutations')
    with (out/'research.json').open('x',encoding='utf8') as handle:
        json.dump(result,handle,ensure_ascii=False,indent=2,allow_nan=False)
    summary=dict(replays=len(results),shorts=[dict(replay=r['replay_id'],owners=len(r['owners']),
        named_activity_counts=r['named_activity_counts'],raw_name_hits=len(r['named_pattern_hits']),
        team_candidate_values=dict(Counter(str(x['team_correlation_candidate']) for x in r['team_field_candidate_rows'])))
        for r in results[1:]],team_trials=len(trials),
        static_trial_rejections=sum(t['status']=='REJECTED_AS_STATIC_TEAM_FIELD' for t in trials),
        input_hash_checks=len(unchanged),short_identity_binding_status='INSUFFICIENT_EVIDENCE')
    with (out/'summary.json').open('x',encoding='utf8') as handle:
        json.dump(summary,handle,ensure_ascii=False,indent=2)
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':
    main()
