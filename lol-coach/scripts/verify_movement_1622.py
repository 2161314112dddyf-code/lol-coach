"""Re-learn the 16.22 movement table and audit independent replay files."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
from itertools import permutations
import json
import math
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.movement_1622 import (OPCODE, ORIGIN, PANTHEON, TEN_PLAYER, WIRE_TO_PLAIN, _records, minion_birth, minion_class,
                                     decode_paths, reviewed_ward_sources)
from lol_coach.replay_container import container_info, packets


def varint(n):
    result = []
    while n >= 128:
        result.append((n & 127) | 128)
        n >>= 7
    return bytes(result + [n])


def learn(raw):
    if sha256(raw).hexdigest() != PANTHEON:
        raise ValueError('Use the controlled Pantheon replay as discovery input')
    known_entities, pairs, bodies = set(), {}, {}
    for p in packets(raw):
        known_entities.add(p['param'])
        b = p['payload']
        if p['opcode'] != OPCODE or p['stream'] != 1:
            continue
        # The low flags byte, two high zero bytes of a small network object ID,
        # and its class byte occupy stable interleaved positions.
        hs = [h for h in range(1, min(13, len(b)-10))
              if b[h+2] == b[h+8] == 0xc0 and b[h+10] == 0x71]
        if len(hs) != 1:
            continue
        h, = hs
        length = varint(len(b)-h)
        for plain, wire in zip(length, b[h-len(length):h], strict=True):
            if pairs.setdefault(wire, plain) != plain:
                raise ValueError('Inconsistent length pairs')
        body = b[h:]
        bodies[body[::2] + body[1::2][::-1]] = True
    learned = len(pairs)
    pairs[0xc0] = 0
    wires = sorted(set(range(256)) - pairs.keys())
    plains = sorted(set(range(256)) - set(pairs.values()))
    if len(wires) != 7 or len(plains) != 7:
        raise ValueError('Unexpected substitution ambiguity')
    # Select distinct short headers for a fast, deterministic bounded search.
    inputs = [b for b in bodies if len(b)<60 and set(wires).intersection(b)]
    tests, headers = [], set()
    for b in sorted(inputs, key=lambda b:(b[0] not in wires, len(b))):
        if b[:11] not in headers:
            headers.add(b[:11])
            tests.append(b)
        if len(tests) == 401:
            break
    tables = []
    for assignment in permutations(plains):
        m = pairs | dict(zip(wires, assignment))
        table = bytes(m[i] for i in range(256))
        try:
            if all(all(row['entity_id'] in known_entities for row in _records(b.translate(table)))
                   for b in tests):
                tables.append(table)
        except (ValueError, struct.error):
            continue
    if tables != [WIRE_TO_PLAIN]:
        raise ValueError('Wire substitution did not uniquely reproduce')
    return dict(length_mappings=learned, fixed_zero_wire='0xc0', remaining_assignments=5040,
                matching_tables=len(tables), short_header_checks=len(tests),
                table_sha256=sha256(tables[0]).hexdigest())


def audit(source):
    raw = source.read_bytes()
    digest = sha256(raw).hexdigest()
    info = container_info(raw)
    counts, path_entities, outer_entities = defaultdict(Counter), set(), set()
    births, first_position = {}, {}
    cohorts, model_counts = defaultdict(list), Counter()
    for p in packets(raw):
        if p['stream'] == 1 and p['opcode'] == 0x456:
            side = minion_birth(p['payload'])
            model = minion_class(p['payload'])
            births[p['param']] = side
            cohorts[p['time']].append((side,model))
            model_counts[model] += 1
        outer_entities.add(p['param'])
        if p['opcode'] != OPCODE:
            continue
        paths = decode_paths(p['payload'])
        if p['stream'] == 1:
            for path in paths:
                x,z = path['relative_waypoints_xz'][0]
                first_position.setdefault(path['entity_id'], (x+ORIGIN[0],z+ORIGIN[1]))
        counts[p['stream']]['packets'] += 1
        counts[p['stream']]['paths'] += len(paths)
        path_entities.update(path['entity_id'] for path in paths)
    missing = path_entities - outer_entities
    if missing:
        raise ValueError(f'{len(missing)} path IDs absent from packet headers')
    result = dict(source_sha256=digest, build=info['version'], streams=counts,
                  distinct_path_entities=len(path_entities), unbound_path_entities=0)
    # First cohort in the controlled replay, with its six clearly separated
    # base spawners. First-command positions of later minions can differ.
    spawners = {(100,'bottom'):(3322,1536),(100,'top'):(1390,3150),
        (100,'middle'):(2884,3356),(200,'middle'):(12080,11846),
        (200,'top'):(11810,13470),(200,'bottom'):(13314,11496)}
    lane_counts = Counter()
    nearest_matches, team_matches = 0, 0
    for entity, side in births.items():
        if side not in spawners or entity not in first_position:
            raise ValueError('Lane birth lacked a signed spawner or path witness')
        nearest = min(spawners, key=lambda k:math.dist(first_position[entity],spawners[k]))
        nearest_matches += nearest == side
        team_matches += nearest[0] == side[0]
        lane_counts[f'{side[0]}_{side[1]}'] += 1
    for group in cohorts.values():
        if len(group) != 6 or len({side for side,_ in group}) != 6 or len({model for _,model in group}) != 1:
            raise ValueError('Inconsistent six-lane cohort')
    result['minions'] = dict(model_counts=dict(model_counts),complete_six_lane_cohorts=len(cohorts),births=len(births), all_six_lanes=dict(lane_counts),
        first_position_nearest_lane_matches=nearest_matches,
        first_position_nearest_team_matches=team_matches)
    if digest not in (PANTHEON, TEN_PLAYER):
        return result
    wards = reviewed_ward_sources(raw)
    players = json.loads(info['metadata']['statsJson'])
    owner_checks = []
    for i, player in enumerate(players):
        entity = 0x400000ae + i
        own = [w for w in wards if w['owner_entity_id'] == entity]
        buckets = Counter(w['family'] for w in own)
        if (len(own) != int(player['WARD_PLACED'])
                or buckets['control_ward'] != int(player['WARD_PLACED_DETECTOR'])
                or any(w['team_id'] != int(player['TEAM']) for w in own)):
            raise ValueError(f'Ward counts or team mismatched for {player["SKIN"]}')
        if buckets['farsight_ward'] and int(player['ITEM6']) != 3363:
            raise ValueError('Farsight ward lacks item corroboration on this replay')
        owner_checks.append(dict(champion=player['SKIN'],network_id=hex(entity),
                                  team=int(player['TEAM']),placed=len(own),families=dict(buckets)))
    result['wards'] = dict(placements=len(wards), with_removal=sum(w['end_seconds'] is not None for w in wards),
                           with_stationary_position=sum(bool(w['positions']) for w in wards),
                           per_owner_terminal_crosscheck=owner_checks)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('training', type=Path)
    parser.add_argument('held_out', type=Path, nargs='+')
    args = parser.parse_args()
    print(json.dumps(dict(discovery=learn(args.training.read_bytes()),
                          audits=[audit(p) for p in [args.training,*args.held_out]]), indent=2))


if __name__ == '__main__':
    main()
