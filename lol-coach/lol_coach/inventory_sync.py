"""Bounded item observations inside six actual 16.20 resync packets.

Only the observed fixed wrapper is accepted. Opaque modifiers stay opaque;
missing slots are unknown, never implicitly empty. Not a full inventory codec.
"""
import re

from .replay_inventory import VERSION, SLOTS, SLOT_CONSTANTS, STACK_BYTES, load_profile

COUNTS = {0xf3: 2, 0x73: 3, 0xb1: 5, 0xf1: 6, 0xf2: 10, 0x71: 7, 0x33: 8, 0x32: 4}
WRAPPER = re.compile(rb'[\xc4\xc5]\xff\xd5\xe8')


def decode_item_tail(data, *, profile=None):
    profile = load_profile() if profile is None else profile
    if len(data) < 3:
        raise ValueError('Truncated nested item')
    if data[2] not in (0x24, 0x25, 0x26, 0x27, 0x34, 0x35, 0x36, 0x37):
        raise ValueError('Unobserved nested item form')
    header = int.from_bytes(data[:3], 'little')
    cursor = len(data)
    selector = (header >> 11) & 7
    if selector in SLOT_CONSTANTS:
        slot = SLOT_CONSTANTS[selector]
    else:
        cursor -= 1
        if data[cursor] not in SLOTS:
            raise ValueError('Unknown trailing slot')
        slot = SLOTS[data[cursor]]
    if slot == 255:
        raise ValueError('Sentinel slot unsupported')
    count_selector = header & 7
    count_wire = None
    if count_selector in (1, 2, 6, 7):
        cursor -= 1
        if cursor < 3:
            raise ValueError('Truncated stack count')
        count_wire = data[cursor]
    count = {3: 1, 4: 0, 5: 2}.get(count_selector)
    if count_wire is not None:
        count = STACK_BYTES.get(count_wire)
    item_selector = (header >> 4) & 7
    if item_selector == 4:
        code = None
        item_id = 0
        name = None
    elif item_selector in (0, 2, 3, 6):
        cursor -= 2
        if cursor < 3:
            raise ValueError('Truncated item identity')
        code = data[cursor:cursor+2].hex()
        label = profile['items'].get(code)
        item_id = label['item_id'] if label else None
        name = label['name'] if label else None
    else:
        raise ValueError('Unsupported item identity selector')
    if cursor < 3:
        raise ValueError('Invalid tail bounds')
    return dict(slot=slot, item_id=item_id, item_name=name, item_wire=code,
        empty=code is None, count_candidate=count, count_verified=False,
        count_wire=None if count_wire is None else f'{count_wire:02x}',
        opaque_modifier_region_hex=data[3:cursor].hex(), identity_payload_offset=cursor if code else None,
        interpretation='observed_item_identity; opaque price/charges/modifiers not interpreted')


def decode_sync(payload, *, version=VERSION, profile=None):
    if version != VERSION:
        raise ValueError('Unsupported build')
    if len(payload) < 7 or payload[:2] != b'\x4d\x38' or payload[2] not in COUNTS:
        raise ValueError('Unknown sync envelope')
    matches = list(WRAPPER.finditer(payload, 3))
    if len(matches) != COUNTS[payload[2]] or matches[0].start() != 3:
        raise ValueError('Wrapper count/boundary mismatch; extended wrappers not supported')
    items = []
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i+1].start() if i+1 < len(matches) else len(payload)
        row = decode_item_tail(payload[start:end], profile=profile)
        row['payload_range'] = [start, end]
        if row['identity_payload_offset'] is not None:
            row['identity_payload_offset'] += start
        items.append(row)
    slots = [r['slot'] for r in items]
    if slots != sorted(set(slots)):
        raise ValueError('Ambiguous or unordered slot identities')
    return dict(items=items, missing_slots='unknown', complete_inventory_state=False)
