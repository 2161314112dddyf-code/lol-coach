"""Same-build raw channel queries must not silently become player/HUD facts."""
from hashlib import sha256
import json
import struct

import pytest

from scripts.export_vision_channels import PANTHEON, channels_22, export, wire_query


def sample(packets, version=b'16.22.836.1077'):
    payload = b''.join(struct.pack('<BfIHI', 0, t, len(body), op, entity) + body
                       for t, entity, op, body in packets)
    header = b'RIOT\x02'+bytes(9)+bytes([len(version)])+version
    chunk = struct.pack('<IIBIIB', 2, 0, 1, len(payload), 0, 4)+payload
    footer = json.dumps({'gameLength':100000,'statsJson':'[]'}).encode()
    return header+chunk+bytes(256)+footer+struct.pack('<I',len(footer))


def test_wire_lookup_isolated_by_entity_team_and_cutoff():
    raw = sample([(1, 10, 0x4d5, b'\x56\xfd'), (2, 10, 0x35b, b'\x56\xfb'),
                  (2, 11, 0x35b, b'\x56\xfd'), (3, 10, 0x35b, b'\x56\xfd')])
    assert wire_query(raw, 10, 100, .5)['wire_state'] == 'unknown'
    result = wire_query(raw, 10, 100, 2.5)
    assert result['wire_state'] == 'wire_enter' and result['screen_visibility'] is None
    assert result['last_record']['outer_param'] == '0xa'
    assert result['source_sha256'] == sha256(raw).hexdigest()
    assert wire_query(raw, 10, 200, 2.5)['wire_state'] == 'wire_leave'
    assert wire_query(raw, 10, 100, 3)['wire_state'] == 'wire_leave'
    # This source is unbound; it cannot acquire a hero or a ground landmark.
    assert export(raw)['observations'] == []


def test_unknown_codes_and_lifecycle_barriers_end_last_wire_enter():
    raw = sample([(1, 10, 0x4d5, b'\x56\xfd'), (2, 10, 0x35b, b'\x56\xfe'),
                  (3, 10, 0x4d5, b'\x56\xfd'), (4, 10, 0x36c, b'x')])
    assert wire_query(raw, 10, 100, 2.1)['wire_state'] == 'unknown'
    assert wire_query(raw, 10, 100, 3.1)['wire_state'] == 'wire_enter'
    assert wire_query(raw, 10, 100, 4.1)['wire_state'] == 'unknown'


def test_wire_query_rejects_invalid_scope():
    raw = sample([])
    for entity, team, at in ((0, 100, 1), (-1, 100, 1), (1, 300, 1),
                             (1, 100, -1), (1, 100, 101), (1, 100, float('nan'))):
        with pytest.raises(ValueError):
            wire_query(raw, entity, team, at)
    with pytest.raises(ValueError):
        wire_query(sample([], version=b'16.21.829.9102'), 1, 100, 1)


def test_later_monster_movement_ends_ground_binding_without_erasing_earlier_light():
    e = 0x4000029b
    spawn = bytes(8)+bytes.fromhex('b3962571c4b0b079b8b7429fb14e0acf')+bytes(78)
    raw = sample([(1, e, 0x224, spawn), (2, e, 0x4d5, b'\x56\xfd'),
                  (3, e, 0xc, b'motion'), (4, e, 0x35b, b'\x56\xfd')])
    # Inject the reviewed binding for this synthetic regression only.
    rows, _, _ = channels_22(raw, PANTHEON)
    ground = [r for r in rows if r['subject'] == 'ground:blue-side-gromp-camp']
    assert [(r['time_seconds'], r['visible']) for r in ground] == [(2, True), (3, None)]
    assert next(r for r in rows if r['time_seconds'] == 4)['subject'] == 'entity:0x4000029b'
