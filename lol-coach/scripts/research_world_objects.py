"""Reproducible class-layout survey; unknown objects are not promoted to minions."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lol_coach.replay_state import decode_payload, inverse_table, floating, varuint, FLOAT_BITS
from lol_coach.replay_fields import read_metadata
from export_replay_state import ACTORS
from export_replay_ten import load_reviewed


def main():
    framer,movement,movement_inverse,refs=load_reviewed(ROOT.parent)
    inverse=inverse_table();results=[]
    out=ROOT/'data/private/world_objects';out.mkdir(exist_ok=True)
    for stem in ('HN1-11360086609','HN1-11363048522','HN1-11363093470','HN1-11372643015'):
        source=Path('C:/Users/21613/Documents/League of Legends/Replays')/(stem+'.rofl')
        raw=source.read_bytes();digest=hashlib.sha256(raw).hexdigest()
        version,_,_=read_metadata(raw);actors=ACTORS[digest]
        births={};samples=[];spawn_packets=[];hero_stats=[];speed_state={};comparisons=Counter();diffs=[]
        bit10={};moves=[]
        for p in framer.packets(source):
            if p['stream']!=1:continue
            ref=dict(stream=1,chunk=p['chunk'],decompressed_offset=p['offset'],opcode=hex(p['opcode']),
                     payload_sha256=hashlib.sha256(p['payload']).hexdigest())
            if p['opcode']==0x10a:
                spawn_packets.append(dict(time_seconds=p['time'],source=ref,payload_hex=p['payload'].hex()))
            elif p['opcode']==0x3df:
                decoded=decode_payload(p['payload'],version=version,inverse=inverse)
                for record in decoded['records']:
                    entity=record['entity_id']
                    if entity in actors:
                        for g in record['groups']:
                            if g['group']!=32:continue
                            data=bytes.fromhex(g['decoded_data_hex']);cursor=0
                            try:
                                for bit in range(32):
                                    if not g['field_mask']>>bit&1:continue
                                    offset=cursor
                                    value,cursor=(floating(data,cursor) if bit in FLOAT_BITS else varuint(data,cursor,defaultable=True))
                                    if bit==10:bit10[hex(entity)]=value
                                    if bit==25:
                                        speed_state[hex(entity)]=value
                                        hero_stats.append(dict(time_seconds=p['time'],entity_id=hex(entity),
                                            movement_speed_stat_candidate=value,source=dict(**ref,group=32,bit=25,
                                                decoded_payload_offset=g['payload_offset']+offset)))
                            except ValueError:pass
                        continue
                    if entity not in births:
                        births[entity]=dict(entity_id=hex(entity),first_state_time=p['time'],source=ref,
                            group_mask=record['group_mask'],groups=record['groups'],object_type=None,team=None)
                    for g in record['groups']:
                        # This layout is deliberately distinct from the hero group-32 layout.
                        if g['group']!=8 or not g['field_mask']&3:continue
                        data=bytes.fromhex(g['decoded_data_hex']);cursor=0;values={}
                        try:
                            for bit,label in ((0,'health_candidate'),(1,'max_health_candidate')):
                                if g['field_mask']>>bit&1:
                                    value,cursor=floating(data,cursor);values[label]=value
                        except ValueError:continue
                        samples.append(dict(time_seconds=p['time'],entity_id=hex(entity),values=values,
                            source=dict(**ref,group=8,field_mask=g['field_mask'],decoded_payload_offset=g['payload_offset']),
                            status='candidate_class_layout; object_identity_unresolved'))
                        birth=births[entity]
                        if p['time']==birth['first_state_time']:birth.update(values)
            elif p['opcode']==0xc9:
                try: records=movement.decode_packet(p['payload'],movement_inverse)['records']
                except (ValueError,IndexError,KeyError):continue
                for r in records:
                    actor=r['entity_id'];value=speed_state.get(actor)
                    if value is not None:
                        speed=r['speed']
                        label='equal' if abs(speed-value)<.02 else 'movement_packet_zero' if speed==0 else 'nonzero_difference'
                        comparisons[label]+=1
                        if label=='nonzero_difference':diffs.append(dict(time_seconds=p['time'],entity_id=actor,stat=value,path_speed=speed,source=ref))
                    elif int(actor,16) not in actors and r.get('relative_waypoints'):
                        moves.append(dict(time_seconds=p['time'],entity_id=actor,speed=r['speed'],
                            first_relative_waypoint=r['relative_waypoints'][0],source=ref,
                            interpretation='path_start_candidate; not current position or arrival'))
        born=list(births.values())
        # Selection is a research filter, not an identity decoder. Preserve the alternatives.
        candidates=[b for b in born if b.get('health_candidate')==b.get('max_health_candidate')
                    and b.get('health_candidate',0)>=290 and b['first_state_time']>=40
                    and b['group_mask']&8]
        pairs=[]
        for i,b in enumerate(candidates):
            peers=[x for x in candidates[i+1:] if abs(x['first_state_time']-b['first_state_time'])<.001
                   and x.get('health_candidate')==b.get('health_candidate')]
            if len(peers)==1:pairs.append(dict(time_seconds=b['first_state_time'],entities=[b['entity_id'],peers[0]['entity_id']],
                initial_health_candidate=b['health_candidate'],identity=None))
        initial_speed={}
        for r in hero_stats:initial_speed.setdefault(r['entity_id'],r['movement_speed_stat_candidate'])
        bundle=dict(schema='world-object-research/v1',version=version,source_sha256=digest,
            object_births=born,candidate_health_samples=samples,nonhero_path_starts=moves,
            birth_pair_candidates=pairs,creation_family_packets=spawn_packets,hero_speed_stat_samples=hero_stats,
            speed_crosscheck=dict(counts=dict(comparisons),nonzero_differences=diffs,initial=initial_speed),
            rejected_creep_score_hypothesis=dict(group=32,bit=10,terminal=bit10,status='NOT_ACCEPTED'),
            decision_input_eligible=False,dependencies=refs,
            limitations=['No object-name/team/map decoder; wave candidates do not prove lane identity',
                'Nonhero visibility unresolved; these samples must not enter time-t known state',
                'Group 8 first floats are health candidates, not validated for every object class',
                'Movement stat/command speed is not measured route duration'])
        if hashlib.sha256(source.read_bytes()).hexdigest()!=digest:raise ValueError('Input changed')
        (out/(stem+'.json')).write_text(json.dumps(bundle,ensure_ascii=False,indent=2),encoding='utf8')
        results.append(dict(replay=stem,objects=len(born),candidate_health_samples=len(samples),
            birth_pairs=len(pairs),nonhero_path_starts=len(moves),hero_speed_stats=len(hero_stats),
            speed_crosscheck=dict(comparisons)))
    (ROOT/'reports/world_object_counts.json').write_text(json.dumps(results,indent=2),encoding='utf8')
    print(json.dumps(results))


if __name__=='__main__':main()
