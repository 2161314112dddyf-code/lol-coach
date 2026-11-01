"""Bounded compound position layouts observed for named 16.20 lane minions.

The caller must establish the minion identity and bind ``entity_id`` to the
outer packet param. The supplied movement reader must be the reviewed reader.
Decoded path starts remain candidates; endpoints never establish arrival.
"""
from .compound_inventory import VERSION, decode_inventory
from .neutral_identity import stationary_position


POSITION_PREFIX = bytes.fromhex(
    '00000000000000000000803f0000000000000000000000000000'
)[:25]


def compound_lane_position(payload, entity_id, movement, *, version):
    """Read one complete observed layout, without adopting a map origin.

This establishes binary samples only, not current-time semantics, visibility,
survival, or a continuous trajectory. The static format has no inner actor ID;
its actor binding depends on the caller's verified outer packet header.
"""
    if version != VERSION:
        raise ValueError('Unsupported exact build')
    try:
        actor = int(entity_id, 16) if isinstance(entity_id, str) else -1
    except ValueError:
        actor = -1
    if actor >> 30 != 1 or hex(actor) != entity_id:
        raise ValueError('Expected canonical class-1 entity ID')
    inventory = decode_inventory(payload, version=version)
    tail = bytes.fromhex(inventory['uninterpreted_state_hex'])
    if len(tail) < 26 or tail[:25] != POSITION_PREFIX:
        raise ValueError('Unobserved compound position prefix')
    if tail[25] == 2:
        # The minimum complete path record is 14 bytes; 26:30 stays opaque.
        if len(tail) < 44:
            raise ValueError('Truncated compound path')
        path = tail[30:]
        records = movement.parse_paths(path)
        if len(records) != 1 or records[0]['entity_id'] != entity_id:
            raise ValueError('Compound path actor mismatch or multiple records')
        record = records[0]
        if (record['decoded_offset'] != 0 or record['decoded_end'] != len(path)
                or not record['relative_waypoints']):
            raise ValueError('Incomplete compound path consumption')
        return dict(kind='embedded_path', relative_waypoints=record['relative_waypoints'],
            path_speed=record['speed'], flags=record['flags'], extra_byte=record['extra_byte'],
            first_relative_point_candidate=record['relative_waypoints'][0],
            decoded_path_offset=inventory['decoded_item_end']+30,
            opaque_path_metadata_hex=tail[26:30].hex(),
            position_semantics='path_start_candidate; not independent current position',
            actual_arrival=None, current_map_position=None)
    if tail[25] == 3:
        if len(tail) != 47 or tail[30] != 0:
            raise ValueError('Unobserved stationary compound layout')
        record = stationary_position(payload, version=version)
        return dict(kind='static_format_position_sample', position_xz=record['position_xz'],
            facing_xz=record['facing_xz'], decoded_position_offset=record['position_decoded_offset'],
            opaque_position_metadata_hex=tail[26:30].hex(),
            position_semantics='bounded compound float sample; current-time semantics need separate review',
            actual_arrival=None)
    raise ValueError('Unobserved compound position kind')
