"""Observed 16.20 inventory operation forms; incomplete inventory coverage."""
import json
from pathlib import Path

VERSION = '16.20.824.8524'
PROFILE = Path(__file__).with_name('profiles') / 'inventory_16_20.json'

SLOTS = {0xf0:3, 0x46:4, 0x33:5, 0xdc:6, 0x0a:7, 0xfb:8, 0xe1:9}
SLOT_CONSTANTS = {0:1, 1:0, 6:2, 7:255}
# Two observed Poro stack codes, crosschecked with grants/use results and the
# final compound counter. This is not a general byte transform.
STACK_BYTES = {0x1b:3, 0xb5:4}


def take(data, pos, size):
    if pos + size > len(data):
        raise ValueError('Truncated inventory field')
    return data[pos:pos+size], pos+size


def slot(data, pos, selector):
    if selector in SLOT_CONSTANTS:
        value = SLOT_CONSTANTS[selector]
    else:
        raw,pos = take(data,pos,1)
        if raw[0] not in SLOTS:
            raise ValueError('Unknown slot byte')
        value = SLOTS[raw[0]]
    if value == 255:
        raise ValueError('Sentinel slot is not an inventory index')
    return value,pos


def item(data, pos):
    start = pos
    raw,pos = take(data,pos,3)
    header = int.from_bytes(raw,'little')
    extras = ''
    if raw[2] in (0x35,0x36):
        extra,pos = take(data,pos,2)
        extras = extra.hex()
    elif raw[2] != 0x34:
        raise ValueError('Unsupported nested item header')
    price_selector = (header >> 7) & 7
    if price_selector in (2,3,6,7):
        price,pos = take(data,pos,4)
    elif price_selector == 0:
        price = b''
    else:
        raise ValueError('Unsupported price selector')
    item_selector = (header >> 4) & 7
    if item_selector in (0,2,3,6):
        # Only the observed two-byte ID form is supported; exact end required.
        code,pos = take(data,pos,2)
    elif item_selector == 4:
        code = b''
    else:
        raise ValueError('Unsupported item selector')
    count_selector = header & 7
    count = {3:1,5:2,4:0}.get(count_selector)
    count_wire = None
    if count_selector in (1,2,6,7):
        value,pos = take(data,pos,1)
        count_wire = value.hex()
        count = STACK_BYTES.get(value[0])
    elif count_selector not in (0,3,4,5):
        raise ValueError('Unsupported count selector')
    index,pos = slot(data,pos,(header >> 11)&7)
    return dict(slot=index,item_wire=code.hex() or None,empty=not code,
                price_wire=price.hex() or None,count_candidate=count,count_wire=count_wire,
                opaque_prefix_hex=extras,payload_offset=start),pos


def decode_raw(opcode, data, *, swap_b=None):
    swap_b = {} if swap_b is None else swap_b
    if opcode == 0x25f:
        first,pos = take(data,0,1)
        selector = (first[0] >> 3)&7
        if selector in (1,2,5,6):
            gold,pos = take(data,pos,4)
        elif selector == 7:
            gold = b''
        else:
            raise ValueError('Unsupported outer gold selector')
        result,pos = item(data,pos)
        result.update(kind='slot_update',gold_wire=gold.hex() or None,outer_flag=first[0]&1)
    elif opcode == 0x132:
        raw,pos = take(data,0,2)
        index,pos = slot(data,pos,(int.from_bytes(raw,'little')>>7)&7)
        opaque,pos = take(data,pos,4)
        result = dict(kind='slot_clear',slot=index,opaque_hex=opaque.hex())
    elif opcode == 0x66:
        raw,pos = take(data,0,1)
        first,pos = slot(data,pos,raw[0]&7)
        sel = (raw[0]>>3)&7
        second = {1:1,4:0,7:2}.get(sel)
        b_wire = None
        if second is None:
            if sel not in (0,6):
                raise ValueError('Unsupported second swap selector')
            b,pos = take(data,pos,1)
            b_wire = b.hex()
            second = swap_b.get(b[0])
        result = dict(kind='slot_swap',slot=first,other_slot=second,other_slot_wire=b_wire)
    else:
        raise ValueError('Unsupported inventory opcode')
    if pos != len(data):
        raise ValueError(f'Unconsumed bytes: {len(data)-pos}')
    return result


def load_profile():
    profile=json.loads(PROFILE.read_text(encoding='utf8'))
    if profile['version']!=VERSION:raise ValueError('Invalid inventory profile version')
    return profile


def decode_payload(opcode,payload,*,version=VERSION,profile=None):
    if version!=VERSION:raise ValueError('Unsupported replay version')
    profile=load_profile() if profile is None else profile
    if profile['version']!=VERSION:raise ValueError('Unsupported inventory profile')
    result=decode_raw(opcode,payload,swap_b={int(k,16):v for k,v in profile['swap_b'].items()})
    if result['kind']=='slot_update':
        label=profile['items'].get(result['item_wire'])
        result['item_id']=0 if result['empty'] else label['item_id'] if label else None
        result['item_name']=label['name'] if label else None
        result['item_identity_status']='mapped_observed_code' if label else 'empty' if result['empty'] else 'unknown'
    result['transaction_reason']=None
    return result

