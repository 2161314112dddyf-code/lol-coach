"""Exact-build 0x1f3 model names and bounded creation coordinates.

This does not assert that every created object grants vision. Runtime team,
owner, lifetime and sight radius remain separate fields.
"""
import json,math,struct
from pathlib import Path
from .replay_inventory import VERSION


def load_profile():
    return json.loads((Path(__file__).with_name('profiles')/'created_objects_16_20.json').read_text())


def decode_creation(payload,*,version=VERSION,profile=None):
    if version!=VERSION:raise ValueError('Unsupported exact build')
    profile=load_profile()if profile is None else profile
    if profile['version']!=version:raise ValueError('Profile version mismatch')
    if len(payload)<30:raise ValueError('Truncated object creation')
    choices=[]
    for mode,spec in enumerate(profile['name_modes']):
        inv={v:int(k)for k,v in spec['table'].items()}
        for start in range(20,min(35,len(payload))):
            n=spec['lengths'].get(str(payload[start-1]))
            if n is None or start+n+4>=len(payload):continue
            w=payload[start:start+n]
            if spec['order']==1:w=w[::-1]
            elif spec['order']==2:w=w[::2]+w[1::2][::-1]
            else:raise ValueError('Unknown model ordering')
            try:name=bytes(inv[b]for b in w).decode('ascii')
            except (KeyError,UnicodeDecodeError):continue
            if name in profile['model_names']:choices.append((name,start,n,mode))
    if len(choices)!=1:raise ValueError('Unknown or ambiguous object model')
    name,start,n,mode=choices[0]
    value=dict(model_name=name,model_byte_range=[start,start+n],name_encoding_mode=mode,
        position_xz=None,position_error=None,team_id=None,owner_entity_id=None,
        vision_radius=None,grants_vision=None,complete_vision_source=False)
    selector=(int.from_bytes(payload[:4],'little')>>6)&7
    gap=profile['position_gap_selector'].get(str(selector))
    if gap is None:value['position_error']='Unknown position-gap selector';return value
    off=start-gap;inv={v:int(k)for k,v in profile['position_byte_pairs'].items()}
    try:
        x,z=(struct.unpack('<f',bytes(inv[b]for b in payload[p:p+4][::-1]))[0]for p in (off,off+8))
    except KeyError:value['position_error']='Unobserved position byte';return value
    if not all(math.isfinite(v)and -1000<=v<=17000 for v in (x,z)):
        value['position_error']='Coordinate out of supported bounds';return value
    value.update(position_xz=[x,z],position_byte_offsets=[off,off+8])
    return value
