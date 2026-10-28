"""Exact-build 0x1f3 model names and bounded creation coordinates.

This does not assert that every created object grants vision. A serialized
reference is not necessarily an owner; lifetime and sight remain separate.
"""
import json,math,struct
from pathlib import Path
from .replay_inventory import VERSION


def load_profile():
    return json.loads((Path(__file__).with_name('profiles')/'created_objects_16_20.json').read_text())


def decode_affiliation(payload, position_offset, *, version=VERSION):
    """Observed team labels/reference bytes, without inferred ownership."""
    profile=json.loads((Path(__file__).with_name('profiles')/'created_affiliation_16_20.json').read_text())
    if version!=VERSION or profile['version']!=version:raise ValueError('Unsupported affiliation version')
    off=position_offset
    if off<8 or off+12>=len(payload):raise ValueError('Affiliation boundary outside payload')
    label=profile['team_byte_labels'].get(str(payload[off+12]))
    value=dict(team_id=label if isinstance(label,int)else None,team_label=label,
        team_byte_offset=off+12,team_wire_hex=payload[off+12:off+13].hex(),
        reference_entity_id=None,reference_byte_range=[7,off-1],reference_error=None,
        affiliation_evidence='cross_checked_binary_inference')
    if payload[off-1]!=0x43:
        value['reference_error']='Unknown vector prefix';return value
    raw=payload[7:off-1]
    if not raw:
        value['reference_error']='Omitted reference semantics unknown';return value
    inverse={v:int(k)for k,v in profile['reference_byte_pairs'].items()}
    number=0
    for index,byte in enumerate(raw):
        if byte not in inverse:
            value['reference_error']='Unobserved reference byte';return value
        b=inverse[byte];number|=(b&127)<<(index*7)
        if index>=5 or (index==len(raw)-1)==bool(b&128) or index==len(raw)-1 and index and b==0:
            value['reference_error']='Noncanonical reference';return value
    if number>=0x40000000:
        value['reference_error']='Reference outside observed dynamic ID range';return value
    value['reference_entity_id']=hex(0x40000000|number)
    return value


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
    value.update(decode_affiliation(payload,off,version=version))
    try:
        x,z=(struct.unpack('<f',bytes(inv[b]for b in payload[p:p+4][::-1]))[0]for p in (off,off+8))
    except KeyError:value['position_error']='Unobserved position byte';return value
    if not all(math.isfinite(v)and -1000<=v<=17000 for v in (x,z)):
        value['position_error']='Coordinate out of supported bounds';return value
    value.update(position_xz=[x,z],position_byte_offsets=[off,off+8])
    return value
