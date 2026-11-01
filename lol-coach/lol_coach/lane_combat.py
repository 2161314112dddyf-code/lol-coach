"""Bounded 16.20 minion health-loss components in opcode 0x167.

The embedded recipient reference is checked against the outer actor. The
unresolved middle fields are not an attacker decoder. Multiple components may
belong to one attack, and a component can exceed remaining HP (overkill).
"""
import json
import math
from pathlib import Path
import struct

VERSION = '16.20.824.8524'
PROFILE = Path(__file__).with_name('profiles')/'lane_combat_16_20.json'


def load_profile():
    return json.loads(PROFILE.read_text(encoding='utf-8'))


def _inverse(pairs):
    try:
        table = {int(key): value for key, value in pairs.items()}
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError('Invalid lane-combat byte profile') from exc
    if any(type(v) is not int or not 0 <= v < 256 or not 0 <= k < 256
           for k, v in table.items()) or len(set(table.values())) != len(table):
        raise ValueError('Invalid lane-combat byte profile')
    return {wire: plain for plain, wire in table.items()}


def decode_health_loss(payload, *, entity_id, version=VERSION, profile=None):
    """Decode a supported named-minion packet, without inferring an attacker.

    Caller must establish a lane identity and opcode 0x167. Unknown byte pairs,
    lengths, truncated references, actor mismatches and out-of-scope magnitudes
    reject the whole component. This function does not change lifecycle state.
    """
    if version != VERSION:
        raise ValueError('Unsupported exact build')
    profile = load_profile() if profile is None else profile
    if profile.get('version') != version or profile.get('schema') != 'lane-combat-profile/v1':
        raise ValueError('Unsupported lane-combat profile')
    if not isinstance(payload, bytes) or len(payload) not in profile['supported_payload_lengths']:
        raise ValueError('Unobserved lane-combat payload length')
    try:
        actor = int(entity_id, 16) if isinstance(entity_id, str) else -1
    except ValueError:
        actor = -1
    if actor >> 30 != 1 or hex(actor) != entity_id:
        raise ValueError('Expected canonical class-1 entity ID')
    inverse = _inverse(profile['actor_reference_byte_pairs'])
    start = profile['actor_reference_offset']
    cursor, number = start, 0
    for shift in range(0, 35, 7):
        if cursor >= len(payload)-4:
            raise ValueError('Truncated embedded actor reference')
        if payload[cursor] not in inverse:
            raise ValueError('Unobserved embedded actor byte')
        byte = inverse[payload[cursor]]
        cursor += 1
        if shift == 28 and byte > 15:
            raise ValueError('Embedded actor reference overflow')
        number |= (byte & 127) << shift
        if not byte & 128:
            if shift and byte == 0:
                raise ValueError('Noncanonical embedded actor reference')
            break
    else:
        raise ValueError('Unterminated embedded actor reference')
    if number >= 0x40000000 or number | 0x40000000 != actor:
        raise ValueError('Embedded actor does not match outer entity')
    inverse = _inverse(profile['amount_byte_pairs'])
    tail = payload[-4:]
    if any(byte not in inverse for byte in tail):
        raise ValueError('Unobserved health-loss scalar byte')
    decoded = bytes(inverse[byte] for byte in tail)
    value, = struct.unpack('<f', decoded)
    if (not math.isfinite(value) or value <= profile['minimum_component_exclusive']
            or value > profile['maximum_observed_component']):
        raise ValueError('Unobserved health-loss component range or scalar layout')
    return dict(kind='reported_health_loss_component', value=value, unit='health_points',
        reported_entity_id=entity_id, recipient_reference_payload_range=[start, cursor],
        recipient_reference_wire_hex=payload[start:cursor].hex(),
        amount_payload_offset=len(payload)-4, amount_wire_hex=tail.hex(),
        amount_decoded_hex=decoded.hex(),
        opaque_header_hex=payload[:start].hex(),
        opaque_middle_hex=payload[cursor:-4].hex(),
        attacker_entity_id=None, attack_count=None, hit_confirmed=None,
        exact_death_time=None, health_after=None,
        evidence_level='cross_checked_binary_inference',
        semantics='reported received health-loss component; overkill possible; not attributed attack count')
