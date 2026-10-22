"""Observed neutral model strings and stationary compound-state positions."""
import json,math,struct
from pathlib import Path
from .replay_inventory import VERSION
from .compound_inventory import decode_inventory


def decode_model(payload,*,version=VERSION,profile=None):
    if version!=VERSION:raise ValueError('Unsupported exact build')
    if len(payload)<20:raise ValueError('Truncated neutral creation')
    if profile is None:
        profile=json.loads((Path(__file__).with_name('profiles')/'neutral_names_16_20.json').read_text())
    if profile['version']!=version:raise ValueError('Profile mismatch')
    mode=(int.from_bytes(payload[:4],'little')>>12)&3
    spec=profile['modes'].get(str(mode))
    if spec is None:raise ValueError('Unobserved neutral name mode')
    inverse={v:int(k)for k,v in spec['byte_pairs'].items()};choices=[]
    for start in range(4,min(80,len(payload))):
        n=spec['length_pairs'].get(str(payload[start-1]))
        if n is None or start+n>=len(payload):continue
        w=payload[start:start+n]
        if spec['order']==2:w=w[::2]+w[1::2][::-1]
        elif spec['order']!=0:raise ValueError('Unsupported neutral string order')
        try:name=bytes(inverse[b]for b in w).decode('ascii')
        except (KeyError,UnicodeDecodeError):continue
        if name not in profile['model_names']:continue
        choices.append(dict(model_name=name,model_byte_range=[start,start+n],encoding_mode=mode,
            character_record=profile.get('character_records',{}).get(name,f'Characters/{name}/CharacterRecords/Root'),
            instance_name=None,camp_id=None,
            opaque_prefix_hex=payload[:start-1].hex(),opaque_suffix_hex=payload[start+n:].hex()))
    if len(choices)!=1:raise ValueError('Unknown or ambiguous neutral model')
    return choices[0]


def stationary_position(payload,*,version=VERSION):
    decoded=decode_inventory(payload,version=version)
    d=bytes.fromhex(decoded['uninterpreted_state_hex'])
    prefix=bytes.fromhex('00000000000000000000803f0000000000000000000000000003')
    if len(d)!=47 or d[:26]!=prefix or d[30]!=0:
        raise ValueError('Unobserved stationary compound layout')
    x,z,dx,dz=struct.unpack_from('<4f',d,31)
    if not all(math.isfinite(v)for v in (x,z,dx,dz)) or not (0<=x<=16000 and 0<=z<=16000):
        raise ValueError('Invalid stationary coordinates')
    if abs(dx*dx+dz*dz-1)>.02:raise ValueError('Invalid facing vector')
    return dict(position_xz=[x,z],facing_xz=[dx,dz],
        position_decoded_offset=decoded['decoded_item_end']+31,
        evidence='stationary compound layout crosschecked across repeated neutral identities',
        arbitrary_moving_object_supported=False)
