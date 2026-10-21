"""Observed 0x322 skill allocation fields, restricted to one replay build.

Keyframe timestamps do not establish when an allocation happened. Aphelios
uses allocation slots differently; Q/W/E/R are wire slots, not spell names.
"""
import math

VERSION = '16.20.824.8524'
SLOT_CONSTANTS = {5: 0, 0: 1, 4: 2}
RANK_CONSTANTS = {1: 0, 4: 1, 0: 2}
POINT_CONSTANTS = {6: 0, 2: 1, 4: 2}
SLOT_BYTES = {0xdb: 3}
RANK_BYTES = {0xe7: 3, 0xcf: 4, 0xcb: 5, 0xc3: 6}
POINT_BYTES = {0x18: 3, 0x40: 4, 0x50: 5, 0x48: 6, 0x58: 7,
               0x20: 8, 0x30: 9, 0x28: 10, 0x38: 11, 0x60: 12}


def decode_payload(payload, *, version=VERSION):
    if version != VERSION:
        raise ValueError('Unsupported exact build')
    if len(payload) < 2:
        raise ValueError('Truncated skill header')
    header = int.from_bytes(payload[:2], 'little')
    offset = 2
    fields = {}
    # Optional bytes occur in slot, unspent points, rank order.
    specs = (
        ('slot', 0, SLOT_CONSTANTS, SLOT_BYTES, {1, 2, 6, 7}),
        ('unspent_points_observation', 3, POINT_CONSTANTS, POINT_BYTES, {3, 5, 7}),
        ('rank', 7, RANK_CONSTANTS, RANK_BYTES, {2, 3, 5, 6, 7}),
    )
    sources = {}
    for name, shift, constants, table, variables in specs:
        selector = (header >> shift) & 7
        source = dict(header_bit=shift, selector=selector)
        if selector in constants:
            value = constants[selector]
        elif selector in variables:
            if offset >= len(payload):
                raise ValueError('Truncated ' + name)
            if payload[offset] not in table:
                raise ValueError('Unobserved byte for ' + name + ': ' + hex(payload[offset]))
            value = table[payload[offset]]
            source['payload_offset'] = offset
            offset += 1
        else:
            raise ValueError('Unobserved selector for ' + name)
        fields[name] = value
        sources[name] = source
    if offset != len(payload):
        raise ValueError('Unconsumed skill payload')
    return dict(**fields, slot_label='QWER'[fields['slot']], field_sources=sources,
                opaque_header_bits=header & ~0x3bf)


def prefix_ranks(events, cutoff):
    """Only observed live fields. No keyframe/future or implicit rank zero."""
    if not math.isfinite(cutoff) or cutoff < 0:
        raise ValueError('Invalid cutoff')
    result = {}
    for event in sorted(events, key=lambda e: e['time_seconds']):
        if event['source']['stream'] != 1 or event['time_seconds'] > cutoff:
            continue
        result.setdefault(event['entity_id'], {})[event['slot_label']] = event
    return result
