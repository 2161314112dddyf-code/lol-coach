"""16.22 native path starts and ordered waypoints (2 world units per coordinate).

The envelope and field order match the previously reviewed 16.20 grammar.
The wire substitution is build-specific. Endpoints are movement intentions.
"""
import hashlib
import math
import struct
from collections import defaultdict

from .replay_container import container_info, packets

VERSION = '16.22.836.1077'
OPCODE = 0x482
PANTHEON = '2febca32e5e32b182ded7dcccdcc0f2c41405d51e41115b058a5f2d7824e3692'
# All three contain the reviewed Map11 western and eastern Gromp spawn signatures.
MAP11_REPLAYS = {PANTHEON, 'de8bd7553e8847751f52e2877bc0b320825dc92cc8554f412d7769743cb68c7b',
                 'cf9bd72a98818d85f6ccf800c929142579831713d9e0c6e9c6194eac20f98e4f'}
# Integer part of the X/Z midpoint in both reviewed Map11 navgrid headers.
ORIGIN = (7358, 7412)
WIRE_TO_PLAIN = bytes.fromhex(
    '07b4f3271fa7f5bb8ec64d8d6b8284a57f2ea3dcf8caf02948cbd3b097d5691c'
    '64b6c194da31e4ffc242ce51ed01f20d8508109de0c9d7a6610579af2d6d9134'
    '11d4e2b91d6e154f5a22fb6c28cca00cc3ebefd8d949ab9a2b59685803bfdbe145'
    'adb309f683c5ba37362cc8675baa5e0a403df4e68733e575d618387bb84a5312'
    '735df1e36a0f62be54f990e85c4ec4d18c600e3cc788bddd1420650be93afab5'
    'b7ea741e2f99bcfc7d7a237c5772a8acee1ac004cf3f7766b186559e8a7192'
    '002147dea2cd39243e2a95569cfd17309b13448fec5f8b806f4c76a1dfae9f3b'
    '197893b28132633552e7701ba9435016a4967e02d0254b06fef78941d2462698')


def _records(data):
    pos = 0
    records = []
    while pos < len(data):
        flags, entity, speed = struct.unpack_from('<HIf', data, pos)
        pos += 10
        count = (flags & 255) >> 1
        if entity >> 30 != 1 or not math.isfinite(speed) or not 0 <= speed <= 5000 or count == 0:
            raise ValueError('Unexpected path header')
        pos += flags & 1
        mask_length = (2 * (count - 1) + 7) // 8
        mask = int.from_bytes(data[pos:pos + mask_length], 'little')
        pos += mask_length
        pair = [0, 0]
        points = []
        for index in range(count):
            for axis in range(2):
                if index and (mask >> (2 * (index - 1) + axis)) & 1:
                    value, = struct.unpack_from('<b', data, pos)
                    pair[axis] = (pair[axis] + value + 32768) % 65536 - 32768
                    pos += 1
                else:
                    pair[axis], = struct.unpack_from('<h', data, pos)
                    pos += 2
            points.append([2 * pair[0], 2 * pair[1]])
        records.append(dict(entity_id=entity, speed=speed, relative_waypoints_xz=points))
    return records


def decode_paths(payload):
    """Require a unique canonical length and complete, nonempty sequence of records."""
    decoded = payload.translate(WIRE_TO_PLAIN)
    choices = []
    for start in range(1, min(11, len(payload))):
        length = 0
        for i, byte in enumerate(decoded[start:start + 5]):
            length |= (byte & 127) << (7 * i)
            if byte & 128:
                continue
            end = start + i + 1
            if length > 0 and (i == 0 or byte != 0) and length == len(payload) - end:
                body = decoded[end:]
                try:
                    choices.append(_records(body[::2] + body[1::2][::-1]))
                except (ValueError, struct.error):
                    pass
            break
    if len(choices) != 1:
        raise ValueError('Missing or ambiguous 0x482 envelope')
    return choices[0]


def _ref(packet):
    return dict(stream=packet['stream'], chunk=packet['chunk'], offset=packet['offset'],
                opcode=hex(packet['opcode']), outer_param=hex(packet['param']),
                payload_sha256=hashlib.sha256(packet['payload']).hexdigest())


def iter_path_samples(raw, *, streams=(1,), map_id=None, at_seconds=None):
    """Yield raw-time packet observations. Unreviewed map origins remain unknown."""
    if container_info(raw)['version'] != VERSION:
        raise ValueError('Unsupported movement build')
    if at_seconds is not None and (type(at_seconds) not in (int, float)
            or not math.isfinite(at_seconds) or at_seconds < 0):
        raise ValueError('Invalid movement prefix')
    if map_id is None and hashlib.sha256(raw).hexdigest() in MAP11_REPLAYS:
        map_id = 11
    for packet in packets(raw):
        if (packet['stream'] not in streams or packet['opcode'] != OPCODE
                or (at_seconds is not None and packet['time'] > at_seconds)):
            continue
        ref = _ref(packet)
        for i, record in enumerate(decode_paths(packet['payload'])):
            points = record['relative_waypoints_xz']
            absolute = [[x + ORIGIN[0], z + ORIGIN[1]] for x, z in points] if map_id == 11 else None
            yield dict(**record, time_seconds=packet['time'], world_waypoints_xz=absolute,
                       source=dict(**ref, record_index=i))


def _controlled_ward_sources(raw):
    """Four HUD-identified placements in the controlled blue Pantheon replay.

    Packet timestamps remain unrounded. Position rows represent samples. A move
    between two distinct keyframes has unknown time unless a live packet records it.
    """
    if hashlib.sha256(raw).hexdigest() != PANTHEON:
        raise ValueError('Ward identity and ownership have not been reviewed for this replay')
    labels = {0x40000392:(3340,0x36c), 0x400004d2:(2055,0x2e7),
              0x40000632:(2055,None), 0x4000080c:(3340,0x36c)}
    relevant = [p for p in packets(raw) if p['stream'] == 1 and (
        p['param'] in labels or (p['param'] == 0x400000ae and p['opcode'] == 0x268))]
    wards = {}
    for entity, (item, removal) in labels.items():
        create, = [p for p in relevant if p['param'] == entity and p['opcode'] == 0x41c]
        anchor_op = 0x294 if item == 3340 else 0x268
        anchor_id = entity if item == 3340 else 0x400000ae
        anchor, = [p for p in relevant if p['opcode'] == anchor_op and p['param'] == anchor_id
                   and p['time'] == create['time']]
        end = None
        if removal is not None:
            end, = [p for p in relevant if p['param'] == entity and p['opcode'] == removal]
        wards[entity] = dict(entity_id=entity, team_id=100, item_id=item,
            family='sight_ward' if item == 3340 else 'control_ward', owner_entity_id=0x400000ae,
            start_seconds=anchor['time'], end_seconds=end['time'] if end else None,
            start_source=_ref(anchor), placement_source=_ref(create),
            end_source=_ref(end) if end else None, positions=[])
    return _sample_ward_positions(raw, wards)


def _sample_ward_positions(raw, wards):
    for row in iter_path_samples(raw, streams=(1,2)):
        ward = wards.get(row['entity_id'])
        if not ward or row['time_seconds'] < ward['start_seconds']:
            continue
        if ward['end_seconds'] is not None and row['time_seconds'] >= ward['end_seconds']:
            continue
        if len(row['world_waypoints_xz']) != 1 or row['speed'] != 0:
            raise ValueError('Unreviewed nonstationary ward sample')
        ward['positions'].append(dict(time_seconds=row['time_seconds'], world_xz=row['world_waypoints_xz'][0],
                                      speed=row['speed'], source=row['source']))
    for ward in wards.values():
        ward['positions'].sort(key=lambda p:p['time_seconds'])
    return list(wards.values())


TEN_PLAYER = 'cf9bd72a98818d85f6ccf800c929142579831713d9e0c6e9c6194eac20f98e4f'

# Verified by single-caster 0x2f6 anchors. The tenth player had no such cast.
SIGHT_OWNERS = {
    0x06:0x400000ae, 0x46:0x400000b0, 0x66:0x400000b1,
    0x85:0x400000b2, 0xa5:0x400000b3, 0xc5:0x400000b4,
    0xe5:0x400000b5, 0x05:0x400000b6, 0x25:0x400000b7,
}
# 0x41c contains three wire variants per family. Each of the detector counts
# and all ward counts reconcile per player, not just at team or match level.
CREATION_FAMILY = {
    bytes.fromhex(signature): family
    for family, signatures in (
        ('control_ward', ('d5cf1160f2cf7bf3cf4c4c77d8','e475a28379ac15ac69a2a2a6ea',
                          '8cb771aaaa6135476125b1c161')),
        ('farsight_ward', ('e2f7cf7eb360f33ccf','a84168e1a230f4a2ae','4a778e21610735b1ae')),
    ) for signature in signatures
}


def _cast_owner(create, tick):
    body = create['payload']
    family = next((f for signature, f in CREATION_FAMILY.items()
                   if body.startswith(signature, 7)), None)
    casts = {p['param']:p for p in tick if p['opcode'] == 0x2f6}
    if family == 'farsight_ward':
        heroes = [p for actor, p in casts.items() if 0x400000ae <= actor <= 0x400000b7]
        if len(heroes) == 1:
            return family, heroes[0], heroes[0]
    if family == 'control_ward':
        uses = [p for p in tick if p['opcode'] == 0x268 and p['payload'][1:] == b'\x3a']
        if len({p['param'] for p in uses}) == 1 and uses[0]['param'] in casts:
            return family, uses[0], casts[uses[0]['param']]
    for anchor in tick:
        b = anchor['payload']
        if (anchor['opcode'] == 0x294 and anchor['param'] == create['param'] and len(b) == 8
                and b[2:6] == bytes.fromhex('a40f4550') and SIGHT_OWNERS.get(b[6]) in casts):
            return 'sight_ward', anchor, casts[SIGHT_OWNERS[b[6]]]
    return None


def _match_ward_sources(raw):
    ticks, deaths, initial = defaultdict(list), {}, {}
    for p in packets(raw):
        if p['stream'] != 1:
            continue
        op = p['opcode']
        if op == OPCODE and p['time'] <= .2:
            for i, path in enumerate(decode_paths(p['payload'])):
                actor = path['entity_id']
                if 0x400000ae <= actor <= 0x400000b7 and actor not in initial:
                    x, z = path['relative_waypoints_xz'][0]
                    team = 100 if x < -5500 and z < -5500 else 200 if x > 5500 and z > 5500 else None
                    if team:
                        initial[actor] = (team, dict(**_ref(p), record_index=i,
                            time_seconds=p['time'], world_xz=[x + ORIGIN[0], z + ORIGIN[1]]))
        if op in (0x294,0x268,0x41c,0x2f6):
            ticks[p['time']].append(p)
        if op == 0x2e7:
            deaths[p['param']] = p
    wards = {}
    for time, tick in ticks.items():
        for create in (p for p in tick if p['opcode'] == 0x41c):
            binding = _cast_owner(create, tick)
            if not binding:
                continue
            family, anchor, cast = binding
            actor = cast['param']
            if actor not in initial:
                continue
            team, fountain = initial[actor]
            entity = create['param']
            end = deaths.get(entity)
            wards[entity] = dict(entity_id=entity, owner_entity_id=actor,
                family=family, team_id=team, team_source=fountain, item_id=None,
                start_seconds=time, end_seconds=end['time'] if end else None,
                placement_source=_ref(create), start_source=_ref(anchor), cast_source=_ref(cast),
                end_source=_ref(end) if end else None, positions=[])
    return _sample_ward_positions(raw, wards)


def reviewed_ward_sources(raw):
    """Return raw lifecycles and sampled locations on the two reviewed matches."""
    digest = hashlib.sha256(raw).hexdigest()
    if digest == PANTHEON:
        return _controlled_ward_sources(raw)
    if digest == TEN_PLAYER:
        return _match_ward_sources(raw)
    raise ValueError('Ward identity and ownership have not been reviewed for this replay')

LANE_SPAWNS = {0x1e:(100,'bottom'), 0x23:(100,'top'), 0x0e:(100,'middle'),
               0x0a:(200,'middle'), 0xdf:(200,'top'), 0xea:(200,'bottom')}


def minion_birth(payload):
    """Six Map11 lane spawners, each seen once per six-entity birth cohort."""
    if not 15 <= len(payload) <= 20:
        return None
    marker = payload.rfind(b'\x3d', max(0, len(payload) - 3))
    if marker <= 0 or len(payload)-marker not in (2,3):
        return None
    return LANE_SPAWNS.get(payload[marker-1])


MINION_CLASSES = {0x9b:'melee',0xdb:'ranged',0x7b:'siege'}


def minion_class(payload):
    """Observed model tag before the variable network-ID bytes in 0x456."""
    if minion_birth(payload) is None:
        return None
    for i in range(8,13):
        if payload[i-1] in (0x11,0x51,0x13,0x53) and payload[i] in MINION_CLASSES:
            return MINION_CLASSES[payload[i]]
    return None


def lane_minion_positions_at(raw, at_seconds):
    """Return surviving, source-bound lane-minion births at a replay timestamp.

    Only stream-1 evidence up to the query time is consumed. The first waypoint
    is an observation at its packet timestamp. Its age can exceed several seconds.
    Coordinates of enemy entities require the caller's viewpoint filter.
    """
    info = container_info(raw)
    if info['version'] != VERSION or hashlib.sha256(raw).hexdigest() not in MAP11_REPLAYS:
        raise ValueError('Lane birth mapping requires a reviewed Map11 replay')
    if (type(at_seconds) not in (int, float) or not math.isfinite(at_seconds)
            or not 0 <= at_seconds <= info['metadata']['gameLength']/1000):
        raise ValueError('Query outside replay')
    live = {}
    for p in packets(raw):
        if p['stream'] != 1 or p['time'] > at_seconds:
            continue
        op, entity = p['opcode'], p['param']
        if op == 0x456:
            side = minion_birth(p['payload'])
            if side:
                kind = minion_class(p['payload'])
                live[entity] = dict(entity_id=entity, team_id=side[0], lane=side[1],
                    minion_class=kind, vision_radius_units=1200.0 if kind else None,
                    birth_seconds=p['time'], birth_source=_ref(p), position=None)
        elif op == 0x2e7:
            live.pop(entity, None)
        elif op == OPCODE:
            for i, path in enumerate(decode_paths(p['payload'])):
                minion = live.get(path['entity_id'])
                if minion is None:
                    continue
                x,z = path['relative_waypoints_xz'][0]
                minion['position'] = dict(time_seconds=p['time'], age_seconds=at_seconds-p['time'],
                    world_xz=[x+ORIGIN[0],z+ORIGIN[1]], speed=path['speed'],
                    source=dict(**_ref(p), record_index=i))
    return list(live.values())
