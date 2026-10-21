"""Slot subfield of observed 0x2a1 activities, not proof of a new cast."""
from .skill_ranks import VERSION


def decode_slot(payload, *, version=VERSION):
    if version != VERSION:
        raise ValueError('Unsupported exact build')
    if len(payload) < 14 or payload[0] not in (0xa5, 0xb5) or payload[12:14] != b'\xb0\x15':
        raise ValueError('Unobserved activity header')
    selector = (payload[11] >> 5) & 7
    result = dict(selector=selector, header_bit=93, slot=None, slot_label=None,
                  variable_byte=None, new_cast=None, cooldown_ready_at=None, target_entity=None)
    if selector in (0, 7, 3):
        result['slot'] = {0: 0, 7: 1, 3: 2}[selector]
    elif selector in (1, 2, 5, 6):
        if len(payload) < 15:
            raise ValueError('Truncated variable activity slot')
        result['variable_byte'] = hex(payload[14])
        result['variable_payload_offset'] = 14
        result['slot'] = {0xa9: 3, 0x6b: 4, 0x27: 5}.get(payload[14])
    else:
        raise ValueError('Unobserved activity slot selector')
    if result['slot'] is not None:
        result['slot_label'] = ('Q', 'W', 'E', 'R', 'summoner_1', 'summoner_2')[result['slot']]
    result['status'] = 'observed_slot_mapping' if result['slot'] is not None else 'unmapped_internal_slot'
    return result
