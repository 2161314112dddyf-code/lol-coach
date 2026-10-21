"""Bounded exact-build tower identities; no observer visibility is implied."""
import json
import math
from pathlib import Path
import re

from .replay_state import VERSION, floating

PROFILE=Path(__file__).with_name('profiles')/'turret_names_16_20.json'
NAME=re.compile(r'Turret_T(Order|Chaos)_L(\d+)_P(\d+)_(\d+)_(\d+)\Z')


def load_profile():
    profile=json.loads(PROFILE.read_text(encoding='utf8'))
    if profile['version']!=VERSION:raise ValueError('Invalid profile version')
    for table in profile['byte_tables'].values():
        if len(set(table.values()))!=len(table):raise ValueError('Nonbijective partial table')
    return profile


def decode_name(payload,*,version=VERSION,profile=None):
    if version!=VERSION:raise ValueError('Unsupported replay version')
    profile=load_profile() if profile is None else profile
    if len(payload)<7:raise ValueError('Truncated turret creation packet')
    mode=str(payload[0]&3)
    if mode not in profile['byte_tables']:raise ValueError('Unsupported turret name encoding mode')
    inverse={v:int(k) for k,v in profile['byte_tables'][mode].items()}
    matches=[]
    # A preceding opaque variable-length header occupies 3 or 4 bytes in the
    # observed packets. Require the complete length, grammar and static identity;
    # never search arbitrary offsets or silently infer a missing length.
    for length_at in (3,4):
        size=profile['length_tables'][mode].get(str(payload[length_at]))
        if size is None or len(payload)<length_at+1+size+1:continue
        start=length_at+1;wire=payload[start:start+size]
        try:name=bytes(inverse[b] for b in wire[::-1]).decode('ascii')
        except (KeyError,UnicodeDecodeError):continue
        match=NAME.fullmatch(name)
        if match is not None:matches.append((name,match,start,size))
    if len(matches)!=1:raise ValueError('Unknown, truncated or ambiguous turret name layout')
    name,match,start,size=matches[0]
    team_text,lane,position,static_hash,instance=match.groups()
    team=100 if team_text=='Order' else 200
    refs=[r for r in profile['static_candidates'] if r['name']==name]
    if len(refs)!=1:raise ValueError('Unmatched or ambiguous static reference')
    ref=refs[0]
    if ref['explicit_reference_team'] is not None and ref['explicit_reference_team']!=team:
        raise ValueError('Name conflicts with explicit static team')
    # Roles come from the referenced character record; position enums are not guessed.
    record=ref['character_record']
    role=('fountain_turret' if 'Shrine' in record else record.rsplit('/',1)[-1])
    return dict(name=name,team=team,lane=int(lane),position_code=int(position),
        static_object_hash=f'{{{int(static_hash):08x}}}',instance=int(instance),role=role,
        character_record=record,map_reference_position=ref['map_reference_position'],
        map_reference='Map12',map_id_decoded=None,mode_decoded=None,skin_decoded=None,
        name_byte_range=[start,start+size],encoding_mode=int(mode),
        opaque_prefix_hex=payload[:start-1].hex(),
        opaque_suffix_hex=payload[start+size:].hex(),identity_method='decoded_name_and_static_reference')


def health_fields(record):
    """Call only after identifying the entity as a tower; other classes differ."""
    result={};evidence=[]
    for group in record['groups']:
        if group['group']!=32:continue
        data=bytes.fromhex(group['decoded_data_hex']);cursor=0
        for bit,key in ((0,'health'),(1,'max_health')):
            if not group['field_mask']>>bit&1:continue
            start=cursor;value,cursor=floating(data,cursor)
            if value<0:raise ValueError('Negative tower health')
            result[key]=value
            evidence.append(dict(field=key,group=32,bit=bit,
                decoded_payload_offset=group['payload_offset']+start,byte_length=cursor-start))
    return result,evidence


def prefix_state(bundle,cutoff):
    if not math.isfinite(cutoff) or cutoff<0:raise ValueError('Invalid cutoff')
    objects={}
    for event in bundle['identity_events']:
        if event['time_seconds']<=cutoff:
            objects.setdefault(event['entity_id'],dict(identity=event,latest_health={},destruction=None))
    for sample in bundle['health_samples']:
        if sample['time_seconds']>cutoff or sample['entity_id'] not in objects:continue
        state=objects[sample['entity_id']]
        if sample['time_seconds']<state['identity']['time_seconds']:continue
        for key,value in sample['values'].items():
            state['latest_health'][key]=dict(value=value,observed_at=sample['time_seconds'],source=sample['source'])
    for event in bundle['destruction_events']:
        if event['time_seconds']<=cutoff and event['entity_id'] in objects:
            state=objects[event['entity_id']]
            if event['time_seconds']>=state['identity']['time_seconds']:state['destruction']=event
    return dict(cutoff=cutoff,objects=objects,decision_input_eligible=False,
                limitation='Retrospective prefix only. Nonhero observer visibility remains unresolved.')
