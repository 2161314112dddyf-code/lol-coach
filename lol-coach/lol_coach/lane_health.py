"""Read only group-8 health prefixes for independently identified lane units.

The caller must obtain identity from the accepted lane-identity path. This
function does not identify entities from their health layout or grant observer
visibility. Offsets are relative to decoded_data_hex; encoded_hex preserves the
field serialization after the outer replication byte table has been decoded,
not the original packet's wire bytes.
"""
from .replay_state import VERSION, floating


LANE_KINDS = frozenset(('melee', 'ranged', 'siege', 'super_candidate', 'super'))


def decode_health_prefix(group: dict, *, version: str, identity: dict) -> dict:
    """Return independently present health fields and leave the suffix opaque.

Missing fields remain absent, including when no health bits are present.
Malformed selected fields reject the entire result instead of returning a
partial health observation. No hero-group layout is applied to the suffix.
"""
    if version != VERSION:
        raise ValueError('Unsupported exact build')
    if (not isinstance(identity, dict)
            or type(identity.get('team_id')) is not int
            or identity['team_id'] not in (100, 200)
            or not isinstance(identity.get('kind'), str)
            or identity.get('kind') not in LANE_KINDS):
        raise ValueError('Accepted lane identity required')
    if not isinstance(group, dict) or type(group.get('group')) is not int or group['group'] != 8:
        raise ValueError('Only nonhero group 8 is supported')
    mask = group.get('field_mask')
    if type(mask) is not int or mask < 0:
        raise ValueError('Nonnegative integer field mask required')
    raw_hex = group.get('decoded_data_hex')
    if not isinstance(raw_hex, str):
        raise ValueError('Decoded group data must be a hexadecimal string')
    try:
        data = bytes.fromhex(raw_hex)
    except ValueError as exc:
        raise ValueError('Invalid decoded group hexadecimal data') from exc
    cursor = 0
    values, fields = {}, {}
    for bit, name in ((0, 'health'), (1, 'max_health')):
        if not mask & (1 << bit):
            continue
        start = cursor
        value, cursor = floating(data, cursor)
        if value < 0:
            raise ValueError('Negative lane health value')
        values[name] = value
        fields[name] = dict(value=value, decoded_offset=start,
                            encoded_hex=data[start:cursor].hex())
    return dict(values=values, fields=fields, unparsed_suffix_hex=data[cursor:].hex())
