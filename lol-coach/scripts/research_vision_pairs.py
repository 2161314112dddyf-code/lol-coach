"""Reproduce direction/team evidence and contrary examples from raw packets."""
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from export_replay_state import ACTORS
from export_replay_ten import load_reviewed
from lol_coach.replay_fields import read_metadata


def ref(p):
    return dict(time_seconds=p['time'],entity_id=hex(p['param']),stream=p['stream'],chunk=p['chunk'],
       decompressed_offset=p['offset'],opcode=hex(p['opcode']),payload_hex=p['payload'].hex())


def main():
    framer,movement,inverse,deps=load_reviewed(ROOT.parent);games=[]
    for game in ('11360086609','11363048522','11363093470','11372643015'):
        source=Path('C:/Users/21613/Documents/League of Legends/Replays')/f'HN1-{game}.rofl'
        raw=source.read_bytes();sha=hashlib.sha256(raw).hexdigest();version,_,stats=read_metadata(raw)
        if sha not in ACTORS:raise ValueError('Unsupported replay')
        counts=Counter();per=defaultdict(list);respawns=[];deaths=[];positions=[]
        for p in framer.packets(source):
            if p['stream']!=1:continue
            if p['opcode'] in (0x3cd,0x484):
                counts[f'{p["opcode"]:04x}:{p["payload"].hex()}']+=1
                if p['param'] in ACTORS[sha]:per[p['param']].append(ref(p))
            if p['param'] in ACTORS[sha] and p['opcode'] in (0x45e,0x28):
                (respawns if p['opcode']==0x45e else deaths).append(ref(p))
            if p['opcode']==0xc9 and (p['time']<0.2 or (game=='11363048522' and 33.6<p['time']<33.8)):
                for record in movement.decode_packet(p['payload'],inverse)['records']:
                    if int(record['entity_id'],16) in ACTORS[sha]:
                        positions.append(dict(time_seconds=p['time'],entity_id=record['entity_id'],
                          first_relative_waypoint=record['relative_waypoints'][0],
                          first_world_waypoint_legacy_origin=record['map_waypoints_assuming_legacy_origin'][0],source=ref(p)))
        repeat=[];actors=[]
        for entity,events in per.items():
            for a,b in zip(events,events[1:]):
                if a['opcode']==b['opcode']:repeat.append(dict(previous=a,current=b))
            actors.append(dict(entity_id=hex(entity),count=len(events),wire_values=sorted({x['payload_hex'] for x in events}),
               first=events[0],last=events[-1],team=int(stats[entity-0x40000034]['TEAM']) if stats else None))
        respawn_checks=[]
        for spawn in respawns:
            events=per[int(spawn['entity_id'],16)]
            before=[e for e in events if e['time_seconds']<=spawn['time_seconds']+1e-7]
            nearby=[e for e in events if abs(e['time_seconds']-spawn['time_seconds'])<0.15]
            following=next((e for e in events if e['time_seconds']>spawn['time_seconds']),None)
            respawn_checks.append(dict(respawn=spawn,last_transition=before[-1] if before else None,
              nearby=nearby,next_transition=following))
        raw_again=hashlib.sha256(source.read_bytes()).hexdigest()
        if raw_again!=sha:raise ValueError('Source changed')
        games.append(dict(source=str(source),source_sha256=sha,version=version,all_object_counts=dict(counts),
            actors=actors,hero_event_count=sum(map(len,per.values())),same_opcode_adjacencies=repeat,
            position_anchors=positions,respawn_checks=respawn_checks,
            death_marker_count=len(deaths),hero_events=[x for rows in per.values() for x in rows]))
    full=games[0];rc=full['respawn_checks']
    summary=dict(full_hero_events=full['hero_event_count'],full_hero_same_opcode_adjacencies=len(full['same_opcode_adjacencies']),
        respawns=len(rc),respawn_last_leave=sum(x['last_transition'] is not None and x['last_transition']['opcode']=='0x3cd' for x in rc),
        respawn_near_leave=sum(any(e['opcode']=='0x3cd' for e in x['nearby']) for x in rc),
        exceptions=[x for x in rc if x['last_transition'] is None or x['last_transition']['opcode']!='0x3cd'])
    result=dict(task='RPL-003D',dependencies=deps,games=games,summary=summary,
      interpretation={'0x03cd':'leave opposing-team visibility','0x0484':'enter opposing-team visibility',
        'a0f5':'observer team 200','a0c5':'observer team 100'},
      evidence_level='binary inference cross-checked against supplied spawn/respawn/position records',
      limits=['Numeric team enum is inferred semantically, not recovered from a general byte cipher.',
         'Nonhero repetition is not resolved: restrict accepted output to the verified hero directory.',
         'One respawn remains visible until the next real leave event; do not force invisibility at respawn.',
         'No region fog, ward coverage, stealth/true-sight classification or UI cross-check.'])
    path=ROOT/'data/research/vision_pairs.json'
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(summary=summary,games=[dict(source=g['source'],events=g['hero_event_count'],repeats=len(g['same_opcode_adjacencies'])) for g in games]),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
