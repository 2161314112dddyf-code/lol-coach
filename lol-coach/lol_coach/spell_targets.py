"""Observed explicit hero target codes, restricted to the discovery replay.

This is an anchored subfield decoder, not the full CastSpell grammar. Missing
anchors and unknown entities never mean no target. Nine IDs have self-activity
witnesses; the remaining hero and nonhero codes are deliberately unmapped.
"""
from .skill_ranks import VERSION
from .spell_slots import decode_slot

DISCOVERY_SHA256 = 'c08c6f1a4a87f1670a6156c6badfca15a21aa13c74eaa18dff5efdc26b94e7e0'
HERO_CODES = {0x6d: 0x40000034, 0xdb: 0x40000035, 0x10: 0x40000037,
              0xf6: 0x40000038, 0x5c: 0x40000039, 0x1c: 0x4000003a,
              0xbe: 0x4000003b, 0xf2: 0x4000003c, 0xbb: 0x4000003d}


def candidate_anchors(payload):
    slot = decode_slot(payload)
    start = 14+int(slot['selector'] in (1, 2, 5, 6))
    return [i for i in range(start, min(40, len(payload)-4))
            if payload[i] == 0x6f and payload[i+1] in (0x02, 0x0a, 0x12, 0x2a, 0x32, 0x3a)]


def decode_target(payload, *, version=VERSION, source_sha256):
    if version != VERSION:
        raise ValueError('Unsupported exact build')
    if source_sha256 != DISCOVERY_SHA256:
        raise ValueError('Target codebook is only witnessed in the discovery replay')
    positions = candidate_anchors(payload)
    result = dict(target_entity=None, candidate_offsets=positions,
                  status='no_supported_explicit_target', new_cast=None, hit_confirmed=None)
    if len(positions) > 1:
        result['status'] = 'ambiguous_target_anchor'
    elif len(positions) == 1:
        pos = positions[0]
        result.update(anchor_payload_offset=pos, code_payload_offset=pos+2,
                      raw_candidate_hex=payload[pos:pos+8].hex())
        # These following-field prefixes establish the end of a one-byte ID.
        # A known byte at the start of a longer ID must NOT be decoded alone.
        if payload[pos+3:pos+5] not in (b'\xdc\xdc', b'\xed\xe6'):
            result['status'] = 'unresolved_target_record_boundary'
        elif payload[pos+2] not in HERO_CODES:
            result['status'] = 'unmapped_target_code'
        else:
            result.update(target_entity=hex(HERO_CODES[payload[pos+2]]),
                          status='observed_explicit_hero_target', code_length=1)
    return result
