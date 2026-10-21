"""Exact-build, bounded spell-name observations, NOT a cast/cooldown counter."""
import json
import math
from pathlib import Path

VERSION = '16.20.824.8524'
PROFILE = Path(__file__).with_name('profiles')/'spell_activity_16_20.json'


def elf_hash(name):
    value = 0
    for byte in name.lower().encode('ascii'):
        value = (value << 4) + byte
        high = value & 0xf0000000
        value ^= high >> 24
        value &= ~high
    return value


def leb128(value):
    out = bytearray()
    while value >= 128:
        out.append((value & 127) | 128)
        value >>= 7
    out.append(value)
    return bytes(out)


def load_profile():
    profile = json.loads(PROFILE.read_text(encoding='utf8'))
    if profile['version'] != VERSION:
        raise ValueError('Unsupported spell profile')
    table = {int(k): v for k, v in profile['encoding_pairs'].items()}
    if any(not 0 <= x <= 255 for x in (*table, *table.values())) or len(set(table.values())) != len(table):
        raise ValueError('Non-bijective observed byte table')
    for name, row in profile['vocabulary'].items():
        plain = leb128(elf_hash(name))
        if any(b not in table for b in plain) or bytes(table[b] for b in plain).hex() != row['wire']:
            raise ValueError('Name/hash/table disagreement')
    return profile


def decode_activity(payload, *, version=VERSION, profile=None):
    if version != VERSION:
        raise ValueError('Unsupported replay version')
    profile = load_profile() if profile is None else profile
    if profile['version'] != VERSION:
        raise ValueError('Unsupported spell profile')
    # Observed packet forms only. The high bit/0x10 is NOT a new-cast flag.
    if not payload or payload[0] not in (0xa5, 0xb5):
        raise ValueError('Unobserved activity envelope')
    anchor = payload.rfind(b'\xed'*4)
    if anchor < 0:
        raise ValueError('Missing activity anchor')
    matches = []
    for name, row in profile['vocabulary'].items():
        word = bytes.fromhex(row['wire'])
        for relative in range(5, 12):
            offset = anchor + relative
            # All observed forms retain at least 14 opaque bytes after the name.
            if offset+len(word)+14 <= len(payload) and payload[offset:offset+len(word)] == word:
                matches.append(dict(spell_name=name, hash_payload_offset=offset, **row))
    if len(matches) != 1:
        raise ValueError('Unknown or ambiguous spell hash')
    return dict(**matches[0], new_cast=None, cooldown_ready_at=None,
                target_entity=None, ability_rank=None,
                semantic_status='cross_checked_hash_name; role_hint_is_not_execution_proof')


def prefix_events(events, cutoff):
    if not math.isfinite(cutoff) or cutoff < 0:
        raise ValueError('Invalid cutoff')
    return [e for e in events if e['time_seconds'] <= cutoff]
