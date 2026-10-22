"""Bounded 0x43e structure. Numeric values/time units remain undecoded."""
from .skill_ranks import VERSION

SLOT_CONSTANTS = {3: 0, 0: 1, 6: 2}
# Only Q/W/E/R and the two initial summoner positions are labelled. Other
# slots retain their wire byte; initial serialization order is not an ID proof.
SLOT_BYTES = {0x4a: 3, 0xb9: 4, 0x52: 5}


def decode_fields(payload, *, version=VERSION):
    if version != VERSION:
        raise ValueError('Unsupported exact build')
    if len(payload) < 2:
        raise ValueError('Truncated state header')
    h = int.from_bytes(payload[:2], 'little')
    if h & 0x70 != 0x30:
        raise ValueError('Unobserved state envelope')
    pos = 2

    def numeric(shift, constants, variable):
        nonlocal pos
        selector = (h >> shift) & 7
        result = dict(selector=selector, header_bit=shift, value=None, wire_hex=None)
        if selector in constants:
            result['encoding'] = 'uninterpreted_constant_case'
        elif selector in variable:
            if pos+4 > len(payload):
                raise ValueError('Truncated numeric field')
            result.update(encoding='four_byte_value', payload_offset=pos, wire_hex=payload[pos:pos+4].hex())
            pos += 4
        else:
            raise ValueError('Unobserved numeric selector')
        return result

    first = numeric(7, {2, 5}, {0, 1, 3, 7})
    selector = (h >> 10) & 7
    slot = dict(selector=selector, header_bit=10, index=None, wire_hex=None)
    if selector in SLOT_CONSTANTS:
        slot['index'] = SLOT_CONSTANTS[selector]
    elif selector in (2, 4, 5, 7):
        if pos == len(payload):
            raise ValueError('Truncated state slot')
        slot.update(index=SLOT_BYTES.get(payload[pos]), wire_hex=payload[pos:pos+1].hex(), payload_offset=pos)
        pos += 1
    else:
        raise ValueError('Unobserved state slot selector')
    second = numeric(1, {0}, {1, 3, 4, 7})
    third = numeric(13, {1, 2, 7}, {0, 3, 4, 6})
    if pos != len(payload):
        raise ValueError('Unconsumed state bytes')
    return dict(slot=slot, raw_flag_bit0=h & 1, numeric_fields=[first, second, third], cooldown_seconds=None,
                ready_at=None, semantic_status='bounded_fields_only; numeric_encoding_and_time_semantics_unresolved')
