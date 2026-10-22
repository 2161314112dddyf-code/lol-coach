"""Bounded inventory/attribute observations for the reviewed build only."""
import re
import json
from pathlib import Path

from .inventory_sync import decode_item_tail, COUNTS
from .replay_state import VERSION, floating, varuint
from .spell_activity import leb128

WRAPPERS = frozenset(bytes.fromhex(x) for x in (
    'c4ffd5e8', 'c5ffd5e8', 'c4efd5e8', 'c5efd5e8',
    'c4ff25e8', 'c4ff8de9', 'c4ffade9', 'c4ff6de8', 'c4ffa5e8',
    'c4ff85e8', 'c4ff85e9', 'c4ffade8', 'c4ff65e8', 'c4ff8de8',
    'c4ff25e9', 'c4ff45e8', 'c4ff4de8'))
BOUNDARY = re.compile(rb'[\xc4\xc5][\xef\xff].[\xe8\xe9]', re.S)
# No claim that the other fields in these layouts have been named.
ATTRIBUTE_NAMES = {3: 'base_attack_damage_candidate', 7: 'armor_candidate',
    8: 'magic_resistance_candidate', 11: 'attack_range_candidate',
    12: 'bonus_attack_damage_candidate', 14: 'ability_power_candidate'}


def checkpoint_profile():
    profile = json.loads((Path(__file__).with_name('profiles')/'inventory_checkpoint_items_16_20.json').read_text(encoding='utf8'))
    table = {int(k):v for k,v in profile['encoding_pairs'].items()}
    if profile['version'] != VERSION or len(set(table.values())) != len(table):
        raise ValueError('Invalid checkpoint profile')
    for wire, item in profile['items'].items():
        if bytes(table[x] for x in leb128(item['item_id'])).hex() != wire:
            raise ValueError('Item/byte profile disagreement')
    return profile


def inventory_checkpoint(payload, *, version=VERSION, profile=None):
    if version != VERSION:
        raise ValueError('Unsupported build')
    count_at = 2
    if payload.startswith(bytes.fromhex('4d3021edbfa130')):
        count_at = 7  # Observed extended envelope only; the extra field is opaque.
    elif payload[:2] != b'\x4d\x38':
        raise ValueError('Unknown inventory envelope')
    if len(payload) < count_at+5 or payload[count_at] not in COUNTS:
        raise ValueError('Unknown inventory count')
    matches = list(BOUNDARY.finditer(payload, count_at+1))
    if len(matches) != COUNTS[payload[count_at]] or matches[0].start() != count_at+1:
        raise ValueError('Inventory boundary/count mismatch')
    profile = checkpoint_profile() if profile is None else profile
    if profile['version'] != VERSION:
        raise ValueError('Unsupported item profile')
    items = []; omitted = []
    for i, match in enumerate(matches):
        wrapper = match.group()
        if wrapper not in WRAPPERS:
            raise ValueError('Unobserved inventory wrapper')
        start = match.end(); end = matches[i+1].start() if i+1 < len(matches) else len(payload)
        raw = payload[start:end]
        if wrapper[1] == 0xef:
            if raw:
                raise ValueError('Nonempty omitted record')
            omitted.append(dict(record_index=i, slot=None, value=None,
                wrapper_range=[match.start(), start], reason='omitted nested object; default semantics unresolved'))
            continue
        prefix = suffix = b''
        if wrapper[2] != 0xd5:
            if len(raw) < 7:
                raise ValueError('Truncated extended item')
            if raw.startswith(b'\x69\x69'):
                prefix = raw[:4]; start += 4
            elif wrapper != bytes.fromhex('c4ff25e9'):
                raise ValueError('Unobserved extended prefix')
            suffix = raw[-4:]; end -= 4
        item = decode_item_tail(payload[start:end], profile=profile)
        item.update(payload_range=[start, end], wrapper_hex=wrapper.hex(),
            opaque_extension_prefix_hex=prefix.hex(), opaque_extension_suffix_hex=suffix.hex())
        if item['identity_payload_offset'] is not None:
            item['identity_payload_offset'] += start
        items.append(item)
    slots = [x['slot'] for x in items]
    if slots != sorted(set(slots)):
        raise ValueError('Ambiguous or unordered slots')
    return dict(items=items, omitted_records=omitted, complete_inventory_state=False,
        opaque_envelope_hex=payload[:count_at].hex(), missing_slots='unknown', decision_input_eligible=False,
        effective_inventory_time=None,
        semantic_status='serialized_slot_records; cache_or_rollback_semantics_unresolved; not_current_inventory')


def attribute_group(group, *, version=VERSION):
    if version != VERSION:
        raise ValueError('Unsupported build')
    kind = group['group']
    if kind not in (4, 8):
        raise ValueError('Unsupported hero attribute group')
    data = bytes.fromhex(group['decoded_data_hex']); cursor = 0; fields = []
    for bit in range(32):
        if not group['field_mask'] & (1 << bit):
            continue
        integer = kind == 4 and bit < 3 or kind == 8 and bit >= 29
        start = cursor
        value, cursor = varuint(data, cursor, defaultable=True) if integer else floating(data, cursor)
        fields.append(dict(group=kind, bit=bit, value=value,
            candidate_name=ATTRIBUTE_NAMES.get(bit) if kind == 4 else None,
            encoding='varuint' if integer else 'float',
            decoded_payload_offset=group['payload_offset']+start,
            decoded_hex=data[start:cursor].hex()))
    if cursor != len(data):
        raise ValueError('Unconsumed hero attribute data')
    return fields
