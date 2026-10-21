"""Actual corpus crosschecks; preserve missing coverage instead of forcing passes."""
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lol_coach.inventory_sync import decode_item_tail,decode_sync
from lol_coach.replay_inventory import decode_raw
from lol_coach.spell_activity import decode_activity,load_profile,prefix_events
from lol_coach.replay_fields import read_metadata
from export_replay_state import ACTORS
from export_replay_ten import load_reviewed

SPELL_GROUPS=[
 [['ApheliosCalibrumQ','ApheliosSeverumQ','ApheliosGravitumQ','ApheliosInfernumQ','ApheliosCrescendumQ'],['ApheliosW'],[],['ApheliosR']],
 [['ZyraQ'],['ZyraW'],['ZyraE'],['ZyraR']],
 [['LeblancQ'],['LeblancW','LeblancWReturn'],['LeblancE'],['LeblancRQ','LeblancRW','LeblancRWReturn','LeblancRE']],
 [['VeigarBalefulStrike'],['VeigarDarkMatter'],['VeigarEventHorizon'],['VeigarR']],
 [['KarthusLayWasteA1'],['KarthusWallOfPain','KarthusWallOfPain2'],['KarthusDefile'],['KarthusFallenOne','KarthusFallenOne2']],
 [['AlphaStrike'],['Meditate'],['WujuStyle'],['Highlander']],
 [['JhinQ'],['JhinW'],['JhinE'],['JhinR','JhinRShot']],
 [['KayleQ'],['KayleW'],['KayleE'],['KayleR']],
 [['RyzeQWrapper'],['RyzeW'],['RyzeE'],['RyzeR']],
 [['FizzQ'],['FizzW'],['FizzE','FizzETwo','FizzEBuffer'],['FizzR']]]


def read(path):return json.loads((ROOT/path).read_text(encoding='utf8'))


def main():
    framer,_,_,_=load_reviewed(ROOT.parent);profile=load_profile();corpus=[];tail_checks=0
    for stem in ('HN1-11360086609','HN1-11363048522','HN1-11363093470','HN1-11372643015'):
        source=Path('C:/Users/21613/Documents/League of Legends/Replays')/(stem+'.rofl')
        digest=hashlib.sha256(source.read_bytes()).hexdigest()
        sync=read(Path('data/private/inventory_sync')/(stem+'.json'))
        activity=read(Path('data/private/spell_activity')/(stem+'.json'))
        if not sync['source_sha256']==activity['source_sha256']==digest:raise ValueError('Source mismatch')
        keyed={(e['source']['chunk'],e['source']['decompressed_offset']):e for e in sync['events']+activity['events']}
        checked=0
        for p in framer.packets(source):
            if p['stream']!=1:continue
            key=(p['chunk'],p['offset'])
            if key in keyed:
                e=keyed[key]
                if e['source']['payload_sha256']!=hashlib.sha256(p['payload']).hexdigest():raise ValueError('Payload changed')
                if p['opcode']==0x2ef:
                    if decode_sync(p['payload'])['items']!=e['items']:raise ValueError('Sync output mismatch')
                elif decode_activity(p['payload'],profile=profile)['spell_name']!=e['spell_name']:raise ValueError('Name changed')
                checked+=1
            if p['opcode']==0x25f and p['param'] in ACTORS[digest]:
                try:old=decode_raw(0x25f,p['payload'])
                except ValueError:continue
                tail=decode_item_tail(p['payload'][old['payload_offset']:])
                if any(tail[k]!=old[k] for k in ('slot','item_wire','empty')):raise ValueError('Tail vs forward parser disagreement')
                tail_checks+=1
        if checked!=len(keyed):raise ValueError('Missing original packet')
        for t in (0,20,400):
            expected=[e for e in activity['events'] if e['time_seconds']<=t]
            if prefix_events(activity['events'],t)!=expected:raise ValueError('Future leakage')
        if hashlib.sha256(source.read_bytes()).hexdigest()!=digest:raise ValueError('Input mutated')
        corpus.append(dict(replay=stem,source_sha256=digest,real_packets_redecoded=checked,
            named_activities=len(activity['events']),unresolved_activity_packets=len(activity['unresolved']),
            item_sync_packets=len(sync['events']),prefix_checks=3,source_unchanged=True))
    full=read(Path('data/private/spell_activity/HN1-11360086609.json'))
    _,_,footer=read_metadata((Path('C:/Users/21613/Documents/League of Legends/Replays')/'HN1-11360086609.rofl').read_bytes())
    comparisons=[]
    for i,(stat,groups) in enumerate(zip(footer,SPELL_GROUPS)):
        counts=Counter(e['spell_name'] for e in full['events'] if e['entity_id']==hex(0x40000034+i))
        for slot,names in enumerate(groups):
            expected=int(stat[f'SPELL{slot+1}_CAST']);observed=sum(counts[n] for n in names)
            comparisons.append(dict(champion=stat['SKIN'],slot='QWER'[slot],names=names,
                named_activity_count=observed,footer_aggregate=expected,
                status='PASS' if names and observed==expected else 'INSUFFICIENT_EVIDENCE',
                scope='Aggregate crosscheck only; recasts/phases may be included by footer; not proof of completed casts'))
    state=read(Path('data/private/replay_state/HN1-11360086609.json'))
    gold=[u for u in state['updates'] if u['entity_id']=='0x4000003c' and 'current_gold' in u['values']]
    refunds=[]
    for a,b in zip(gold,gold[1:]):
        if 430.6<b['time_seconds']<431:
            refunds.append(dict(time_seconds=b['time_seconds'],gold_delta=b['values']['current_gold']-a['values']['current_gold'],before=a,after=b))
    if [r['gold_delta'] for r in refunds]!=[300,650]:raise ValueError('Refund evidence changed')
    world=read(Path('data/private/world_objects/HN1-11360086609.json'))
    base_speed=[]
    for i,stat in enumerate(footer):
        champion=stat['SKIN'];base=read(Path('data/normalized/16.20.1/en_US/catalog')/(champion+'.json'))['base_stats']['base_move_speed']['value']
        sampled=world['speed_crosscheck']['initial'][hex(0x40000034+i)]
        base_speed.append(dict(champion=champion,official_base=base,first_replication=sampled,match=base==sampled))
    if not all(r['match'] for r in base_speed):raise ValueError('Initial speed mismatch')
    result=dict(task='RPL-004',generated_at_utc=datetime.now(timezone.utc).isoformat(),
        executed_by='Codex developer self-check',independent_review=None,human_signoff=None,cost=None,tokens=None,
        corpus=corpus,tail_vs_forward_packet_checks=tail_checks,spell_aggregate_comparisons=comparisons,
        spell_aggregate_counts=dict(Counter(r['status'] for r in comparisons)),
        refund_crosscheck=refunds,initial_speed_crosscheck=base_speed,
        acceptance=[
            dict(id='W-01',status='INSUFFICIENT_EVIDENCE',reason='Object names/team/map not decoded'),
            dict(id='W-02',status='INSUFFICIENT_EVIDENCE',reason='Class-layout candidates preserved; no confirmed lane or objective state'),
            dict(id='W-03/named-activities-and-partial-sync',status='PASS',reason='Bounded names and slot observations reproduced; phases separate'),
            dict(id='W-03/complete-casts-cooldowns-inventory',status='INSUFFICIENT_EVIDENCE',reason='Unknown activities, cancellation/recast semantics, missing slots and consumption'),
            dict(id='W-04',status='PASS',reason='Research exports marked ineligible; existing decision snapshot unmodified; 12 activity prefix checks'),
            dict(id='W-05/static-sources',status='PASS',reason='173 official champion files and 17 runtime sources cached and hash-checked'),
            dict(id='W-05/measured-times-and-application',status='INSUFFICIENT_EVIDENCE',reason='Two historical source cards collected separately; no condition-complete measured clear or current-version application validation')])
    (ROOT/'reports/world_collection_real_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(corpus=corpus,tail_checks=tail_checks,aggregate_counts=result['spell_aggregate_counts'],initial_speed_matches=len(base_speed))))


if __name__=='__main__':main()
