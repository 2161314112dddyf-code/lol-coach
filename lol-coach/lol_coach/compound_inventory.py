"""16.20 item deltas in 0x37d compound unit state; never a full snapshot."""
import math
import struct

VERSION = '16.20.824.8524'
ENCODING_TABLE = bytes(((((x+40) & 255) ^ 41)+225) & 255 for x in range(256))
INVERSE_TABLE = bytes(ENCODING_TABLE.index(x) for x in range(256))


def unpack_array(payload, *, version=VERSION):
    if version != VERSION:
        raise ValueError('Unsupported exact build')
    if len(payload) < 3 or payload[0] not in (0x4c, 0x4e):
        raise ValueError('Unobserved compound envelope')
    size = 0
    cursor = 1
    for shift in range(0, 35, 7):
        if cursor >= len(payload):
            raise ValueError('Truncated compound length')
        b = INVERSE_TABLE[payload[cursor]]
        cursor += 1
        if shift == 28 and b > 15:
            raise ValueError('Compound length overflow')
        size |= (b & 127) << shift
        if not b & 128:
            if shift and b == 0:
                raise ValueError('Noncanonical compound length')
            break
    else:
        raise ValueError('Unterminated compound length')
    end = cursor+size
    expected_tail = 13 if payload[0] == 0x4e else 0
    if end > len(payload) or len(payload)-end != expected_tail:
        raise ValueError('Unobserved compound array boundary')
    raw = payload[cursor:end]
    body = (raw[::2]+raw[1::2][::-1]).translate(INVERSE_TABLE)
    return body, dict(data_start=cursor, data_length=size,
                      outer_tail_hex=payload[end:].hex())


def decode_inventory(payload, *, version=VERSION):
    body, envelope = unpack_array(payload, version=version)
    if not body:
        raise ValueError('Missing compound item count')
    count = body[0]
    if count > 10:
        raise ValueError('Unobserved compound item count')
    cursor = 1
    items = []
    seen = set()
    for _ in range(count):
        start = cursor
        if cursor+33 > len(body):
            raise ValueError('Truncated compound item')
        if body[cursor] != 0:
            raise ValueError('Unobserved compound item kind')
        slot, stacks = body[cursor+1:cursor+3]
        charges, item_id, price = struct.unpack_from('<HIf', body, cursor+3)
        stat_count = struct.unpack_from('<I', body, cursor+22)[0]
        if slot > 9 or slot in seen or stat_count > 64:
            raise ValueError('Invalid compound item slot/stat count')
        if not math.isfinite(price) or price < 0 or item_id > 100000:
            raise ValueError('Invalid compound item value')
        end = cursor+33+8*stat_count
        if end > len(body):
            raise ValueError('Truncated compound item stat map')
        stats = []
        for i in range(stat_count):
            key, value = struct.unpack_from('<If', body, cursor+26+8*i)
            if not math.isfinite(value):
                raise ValueError('Nonfinite compound item stat')
            stats.append(dict(key=key, value=value, semantic_name=None))
        items.append(dict(slot=slot, item_id=item_id, stack_count=stacks,
            charge_count=charges, price_value=price, stat_values=stats,
            empty=item_id == 0 and stacks == 0,
            decoded_offset=start, decoded_end=end,
            raw_record_hex=body[start:end].hex(),
            unknown_fields_hex=body[start+13:start+22].hex(),
            unknown_suffix_hex=body[end-7:end].hex()))
        seen.add(slot)
        cursor = end
    return dict(items=items, **envelope, decoded_item_end=cursor,
        uninterpreted_state_hex=body[cursor:].hex(),
        update_mode='observed_slot_delta; omitted_slots_are_not_empty',
        charge_semantics='item_specific_counter; not universally remaining_uses',
        effective_time_policy='unresolved_cached_state; known delayed inventory counterexample',
        complete_inventory_state=False)
