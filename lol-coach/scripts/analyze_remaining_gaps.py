"""Evidence and counterexamples for every remaining replay-decoding category."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from lol_coach.http import save_json
from lol_coach.spell_activity import leb128, load_profile as spell_profile
from lol_coach.replay_state import inverse_table
from scripts.export_replay_ten import load_reviewed, reference


def read(path):return json.loads((ROOT/path).read_text(encoding='utf8'))


def main():
    full=read('data/private/remaining_decode/HN1-11360086609.json')
    attrs=full['hero_attribute_groups']
    operations=read('data/private/replay_inventory/HN1-11360086609.json')['events']
    cat_path=Path('data/research/inventory_sources/raw/bcd7100b7f6c336f585fccaa28324b9d676bf1b2932ae3bb79ee56b5775c47d6.bin')
    cat=read(cat_path)['data']; purchase_checks=[]; initial_checks=[]
    # Static comparison is a hypothesis check. Keep every disagreement.
    names=['Aphelios','Zyra','Leblanc','Veigar','Karthus','MasterYi','Jhin','Kayle','Ryze','Fizz']
    for index,name in enumerate(names):
        ref=read(f'data/normalized/16.20.1/en_US/catalog/{name}.json')['source']
        source=ROOT/'data/research/champion_catalog'/ref['evidence_path']
        assert reference(source)['sha256']==ref['sha256']
        stats=json.loads(source.read_bytes())['data'][name]['stats']
        initial={f['bit']:f['value'] for u in attrs if u['time_seconds']==0 and u['entity_id']==hex(0x40000034+index)
                 for f in u['fields'] if f['group']==4}
        for bit,field in [(3,'attackdamage'),(7,'armor'),(8,'spellblock'),(11,'attackrange')]:
            initial_checks.append(dict(champion=name,bit=bit,field=field,observed=initial[bit],static=stats[field],
                equal=abs(initial[bit]-stats[field])<.01,reference=ref))
    for event in operations:
        if event['kind']!='slot_update' or not event.get('outer_flag') or str(event.get('item_id')) not in cat:continue
        item=cat[str(event['item_id'])]
        if item.get('from'):continue
        t=event['time_seconds'];actor=event['entity_id']
        if any(e is not event and e['entity_id']==actor and abs(e['time_seconds']-t)<=.3 for e in operations):continue
        for key,bit in [('FlatPhysicalDamageMod',12),('FlatMagicDamageMod',14),('FlatArmorMod',7),('FlatSpellBlockMod',8)]:
            if not item['stats'].get(key):continue
            observations=[(u,f) for u in attrs if u['entity_id']==actor for f in u['fields'] if f['group']==4 and f['bit']==bit]
            before=[x for x in observations if x[0]['time_seconds']<t]
            after=[x for x in observations if t<=x[0]['time_seconds']<=t+.3]
            delta=after[0][1]['value']-before[-1][1]['value'] if before and after else None
            purchase_checks.append(dict(event=event,stat=key,group=4,bit=bit,static_delta=item['stats'][key],
                observed_delta=delta,status='INSUFFICIENT_EVIDENCE' if delta is None else 'PASS' if abs(delta-item['stats'][key])<.02 else 'FAIL',
                before=before[-1] if before else None,after=after[0] if after else None))
    # Reconcile prior checkpoint plus operations against the next checkpoint.
    timeline=[(e['time_seconds'],0,e) for e in full['inventory_checkpoints']]
    timeline += [(e['time_seconds'],1,e) for e in operations]
    states={}; comparisons=Counter(); mismatches=[]
    for _,kind,e in sorted(timeline,key=lambda x:(x[0],x[1],x[2]['source'].get('offset',x[2]['source'].get('decompressed_offset',0)))):
        state=states.setdefault(e['entity_id'],{})
        if kind==0:
            for item in e['items']:
                now=item['item_wire'] or 'empty';old=state.get(item['slot'])
                if old is not None:
                    comparisons['equal' if now==old else 'different']+=1
                    if now!=old:mismatches.append(dict(time_seconds=e['time_seconds'],entity_id=e['entity_id'],slot=item['slot'],predicted=old,observed=now,
                        source=e['source'],reason=None))
            # A checkpoint only establishes explicitly represented slots.
            states[e['entity_id']]={i['slot']:i['item_wire'] or 'empty' for i in e['items']}
        elif e['kind']=='slot_update':state[e['slot']]=e['item_wire'] or 'empty'
        elif e['kind']=='slot_clear':state[e['slot']]='empty'
        elif e['other_slot'] is None:state.clear()
        else:
            a=e['slot'];b=e['other_slot'];state[a],state[b]=state.get(b),state.get(a)
    # New object-field attempt: do established byte tables encode runtime IDs
    # inside candidate creation records? No guessed new substitution is trained.
    f,_,_,_=load_reviewed(ROOT.parent)
    replay=Path(full['source']['path']);packets=list(f.packets(replay))
    index={(p['chunk'],p['offset']):p for p in packets if p['stream']==1 and p['opcode']==0x10a}
    prior=read('data/private/world_objects/spawn_id_models16.json')
    pairs=prior['training_pairs']+prior['heldout_pairs']
    rep=read('lol_coach/profiles/replication_16_20.json')['encoding_table']
    spell={int(k):v for k,v in spell_profile()['encoding_pairs'].items()}
    probes=Counter(); examples=[]
    for row in pairs:
        payload=index[(row['chunk'],row['offset'])]['payload'];actor=row['entity_id']
        for representation,raw in [('u32le',actor.to_bytes(4,'little')),('leb128',leb128(actor))]:
            for name,table in [('plain',dict(enumerate(range(256)))),('replication',dict(enumerate(rep))),('spell_hash',spell)]:
                key=name+':'+representation
                if not all(x in table for x in raw):probes[key+':unmapped']+=1;continue
                word=bytes(table[x] for x in raw)
                offsets=[i for i in range(len(payload)-len(word)+1) if payload[i:i+len(word)]==word]
                probes[key+':tested']+=1;probes[key+':found']+=bool(offsets)
                if offsets:examples.append(dict(pair=row,model=key,offsets=offsets))
    # Spell-start/cooldown candidate pairing: preserve ambiguity rather than
    # declaring adjacent opcode 0x360 to be a cast or cooldown field.
    acts=read('data/private/spell_activity/HN1-11360086609.json')['events']; by_time=defaultdict(list)
    for e in acts:by_time[(e['entity_id'],e['time_seconds'])].append(e)
    correlations=Counter();spell_names=Counter();ambiguous=[]
    for p in packets:
        if p['stream']!=1 or p['opcode']!=0x360 or not 0x40000034<=p['param']<=0x4000003d:continue
        matches=by_time.get((hex(p['param']),p['time']),[])
        unique=set(e['spell_name'] for e in matches)
        category='unique_name' if len(unique)==1 else 'ambiguous' if unique else 'unmatched'
        correlations[category]+=1
        if len(unique)==1:spell_names[next(iter(unique))]+=1
        elif len(ambiguous)<20:ambiguous.append(dict(time=p['time'],entity=hex(p['param']),names=sorted(unique),payload_hex=p['payload'].hex()))
    # A 12-record-per-hero keyframe family was another potential spell-slot
    # source. It has no live updates here, so it cannot prove live cooldowns.
    slot_family=Counter(f"stream{p['stream']}:length{len(p['payload'])}" for p in packets if p['opcode']==0x2b6)
    ward_path=ROOT/'data/research/dynamic_tools/rofl-parser/patches/16.15/wards.json'
    ward=json.loads(ward_path.read_text(encoding='utf8'))
    prefix=bytes(ward['initialState']['selectorPrefix'])
    ward_matches=sum(p['payload'].startswith(prefix) for p in packets)
    # Named buildings and the previously selected candidate wave objects are
    # audited separately from the many effect objects in the global channel.
    tower=read('data/private/turret_state/HN1-11360086609.json')
    tower_ids={int(e['entity_id'],16) for e in tower['identity_events']}
    wave_ids={r['entity_id'] for r in pairs}; vision={}; last={}
    for p in sorted(packets,key=lambda p:(p['time'],p['chunk'],p['offset'])):
        if p['stream']!=1 or p['opcode'] not in (0x484,0x3cd):continue
        group='named_towers' if p['param'] in tower_ids else 'wave_candidates' if p['param'] in wave_ids else None
        if group is None:continue
        c=vision.setdefault(group,Counter());kind='enter' if p['opcode']==0x484 else 'leave';key=(p['param'],p['payload'].hex())
        c[kind]+=1
        if last.get(key)==kind:c['repeated_'+kind]+=1
        last[key]=kind
    map_rows=read('reports/remaining_decode_collection.json')['map_probe']
    stable_differences=[]
    for opcode,values in map_rows[0]['initial_short_param0_packets'].items():
        short=[r['initial_short_param0_packets'].get(opcode) for r in map_rows[1:]]
        if all(x is not None and x==short[0] for x in short) and values!=short[0]:
            stable_differences.append(dict(opcode=opcode,full_values=values,short_values=short[0],semantic_name=None))
    summary=dict(task='RPL-005',scope='Existing four replays; self-checks and explicit failed hypotheses',
        source=full['source'],item_catalog=reference(ROOT/cat_path),
        initial_attribute_checks=initial_checks,purchase_attribute_checks=purchase_checks,
        inventory_reconciliation=dict(counts=dict(comparisons),mismatches=mismatches,
            interpretation='Differences are missing/unsupported transitions, not proof of consumption'),
        spawn_id_probe=dict(counts=dict(probes),matches=examples,accepted_decoder=False),
        spell_candidate_pairing=dict(counts=dict(correlations),per_name=dict(spell_names),counterexamples=ambiguous,
            slot_family_counts=dict(slot_family),accepted_cast_or_cooldown_decoder=False),
        ward_probe=dict(reference=reference(ward_path),reference_build=ward['gameVersion'],
            target_build=full['version'],raw_prefix_matches=ward_matches,accepted_decoder=False,
            reason='Old-build initial-state profile is incompatible by version; prefix coincidence cannot establish ward identity'),
        nonhero_vision_subsets={k:dict(v) for k,v in vision.items()},
        map_probe=dict(stable_different_packet_families=stable_differences,accepted_map_id=None,
            reason='Map/mode/rules covary across available samples; consistent bytes alone do not establish a map ID'),
        limits=['Static mismatch may reflect mode/weapon/runes; no unexplained modifier is invented',
            'Identifying a Recall inventory record does not decode recall begin/finish',
            'Inventory charges/counts and intervening consumption remain unresolved',
            'No regional fog, ward identity, object team/lane or timer inferred from repeated visibility markers'])
    assert reference(replay)==full['source']
    save_json(ROOT/'reports/remaining_decode_gap_analysis.json',summary)
    print(json.dumps(dict(initial_equal=sum(x['equal'] for x in initial_checks),initial_total=len(initial_checks),
        item_deltas=dict(Counter(x['status'] for x in purchase_checks)),inventory=dict(comparisons),
        spawn_probe=dict(probes),spell_pairing=dict(correlations),vision=summary['nonhero_vision_subsets']),ensure_ascii=False))


if __name__=='__main__':main()
