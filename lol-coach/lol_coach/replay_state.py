"""Exact-build replication state decoding; never visibility-filtered game knowledge."""
import json
import math
from pathlib import Path
import struct

VERSION = '16.20.824.8524'
PROFILE = Path(__file__).with_name('profiles') / 'replication_16_20.json'
FLOAT_BITS = frozenset((0,1,2,3,4,5,6,7,8,9,11,12,13,14,15,16,19,20,25,26,27))
NAMES = {1: {0:'current_gold', 1:'total_gold'},
         32: {0:'health', 1:'max_health', 11:'experience', 15:'resource',
              16:'max_resource', 28:'level'}}


def inverse_table():
    profile = json.loads(PROFILE.read_text(encoding='utf8'))
    table = profile['encoding_table']
    if profile['version'] != VERSION or sorted(table) != list(range(256)):
        raise ValueError('Invalid replication profile')
    return bytes(table.index(i) for i in range(256))


def varuint(data, pos, *, defaultable=False):
    if defaultable and pos < len(data) and data[pos] == 255:
        return 0, pos+1
    value = 0
    for shift in range(0,35,7):
        if pos >= len(data):
            raise ValueError('Truncated varuint')
        b = data[pos];pos += 1
        if shift == 28 and b > 15:
            raise ValueError('Varuint overflow')
        value |= (b & 127) << shift
        if not b & 128:
            if shift and b == 0:
                raise ValueError('Noncanonical varuint')
            return value,pos
    raise ValueError('Unterminated varuint')


def floating(data,pos):
    if pos >= len(data):
        raise ValueError('Truncated float')
    if data[pos] == 255:
        return 0.0,pos+1
    if data[pos] == 254:
        pos += 1
    if pos+4 > len(data):
        raise ValueError('Truncated float')
    value = struct.unpack_from('<f',data,pos)[0]
    if not math.isfinite(value):
        raise ValueError('Nonfinite float')
    return value,pos+4


def decode_group(group,mask,data):
    """Decode known types; preserve unsupported economy suffix explicitly."""
    if group not in NAMES:
        return {},0
    cursor = 0
    fields = {}
    for bit in range(32):
        if not (mask >> bit) & 1:
            continue
        if group == 1 and bit > 1:
            return fields,cursor
        start = cursor
        value,cursor = (floating(data,cursor) if group == 1 or bit in FLOAT_BITS
                        else varuint(data,cursor,defaultable=True))
        if bit in NAMES[group]:
            if value < 0 or (bit == 28 and group == 32 and not 1 <= value <= 18):
                raise ValueError('Out-of-domain named state value')
            fields[NAMES[group][bit]] = dict(value=value,bit=bit,data_offset=start,byte_length=cursor-start)
    if cursor != len(data):
        raise ValueError('Group has unconsumed bytes')
    return fields,cursor


def decode_payload(payload,*,version=VERSION,inverse=None):
    if version != VERSION:
        raise ValueError('Unsupported replay version')
    inverse = inverse_table() if inverse is None else inverse
    if len(inverse)!=256 or len(set(inverse))!=256:
        raise ValueError('Invalid inverse table')
    plain=payload.translate(inverse)
    size,start=varuint(plain,2)
    end=start+size
    if end>len(plain):
        raise ValueError('Replication vector exceeds payload')
    cursor=start
    records=[]
    while cursor<end:
        record_at=cursor
        if cursor+5>end:
            raise ValueError('Truncated record header')
        mask=plain[cursor]
        if not 0<mask<128:
            raise ValueError('Unsupported record mask or wrapper')
        entity=int.from_bytes(plain[cursor+1:cursor+5],'little')
        cursor+=5
        groups=[]
        for group in (1,2,4,8,16,32,64):
            if not mask & group:
                continue
            if cursor+5>end:
                raise ValueError('Truncated group header')
            field_mask=int.from_bytes(plain[cursor:cursor+4],'little')
            length=plain[cursor+4]
            data_at=cursor+5
            cursor=data_at+length
            if cursor>end:
                raise ValueError('Group exceeds vector boundary')
            data=plain[data_at:cursor]
            try:
                fields,consumed=decode_group(group,field_mask,data)
                error=None
            except ValueError as exc:
                fields,consumed,error={},0,str(exc)
            groups.append(dict(group=group,field_mask=field_mask,payload_offset=data_at,
                               decoded_data_hex=data.hex(),fields=fields,
                               unparsed_suffix_hex=data[consumed:].hex(),error=error))
        records.append(dict(entity_id=entity,payload_offset=record_at,group_mask=mask,groups=groups))
    return dict(vector_start=start,vector_end=end,records=records,
                opaque_prefix_hex=payload[:2].hex(),opaque_tail_hex=payload[end:].hex())


def prefix_state(updates,cutoff):
    if not math.isfinite(cutoff) or cutoff<0:
        raise ValueError('Invalid cutoff')
    actors={}
    for update in updates:
        if update['time_seconds']>cutoff:
            continue
        actor=actors.setdefault(update['entity_id'],{})
        for name,value in update['values'].items():
            actor[name]=dict(value=value,observed_at=update['time_seconds'],source=update['source'])
    return dict(cutoff=cutoff,actors=actors,decision_input_eligible=False,
                limitation='Last replicated values, not interpolation; enemy visibility is unresolved.')
