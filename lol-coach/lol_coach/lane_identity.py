"""Bounded 0x005 lane-spawn identity tokens observed in four 16.20 replays.

Labels are cross-field inferences, not decoded character-name strings. The
remaining header and trailing instance token are deliberately uninterpreted.
"""
from .replay_inventory import VERSION

SPAWNS = {
    '23': (100, 'single_lane', 'single_lane_reference'),
    '1e': (200, 'single_lane', 'single_lane_reference'),
    '2d3b': (100, 'bottom', 'three_lane_reference'),
    '883b': (100, 'top', 'three_lane_reference'),
    '983b': (100, 'middle', 'three_lane_reference'),
    '7a3b': (200, 'middle', 'three_lane_reference'),
    '483b': (200, 'top', 'three_lane_reference'),
    'a33b': (200, 'bottom', 'three_lane_reference'),
}
KINDS = {0xec:'melee', 0xd0:'ranged', 0x27:'siege', 0xb4:'super_candidate'}


def decode_spawn(payload, *, version=VERSION):
    if version != VERSION:
        raise ValueError('Unsupported exact build')
    if not 10 <= len(payload) <= 19:
        raise ValueError('Unobserved lane-spawn length')
    choices=[]
    for token, (team,lane,family) in SPAWNS.items():
        wire=bytes.fromhex(token)
        for start in range(4,len(payload)-3):
            pos=start+len(wire)
            if payload[start:pos] != wire or pos>=len(payload):continue
            if payload[pos] not in KINDS or not 3<=len(payload)-pos-1<=5:continue
            choices.append(dict(team_id=team,lane=lane,reference_map_family=family,
                spawn_token=token,kind=KINDS[payload[pos]],kind_wire=hex(payload[pos]),
                spawn_token_offset=start,kind_offset=pos,
                opaque_header_hex=payload[:start].hex(),
                opaque_instance_token_hex=payload[pos+1:].hex(),
                evidence_level='cross_checked_binary_inference',
                character_name=None,runtime_map_id=None))
    if len(choices)!=1:
        raise ValueError('Unknown or ambiguous lane-spawn identity')
    return choices[0]
