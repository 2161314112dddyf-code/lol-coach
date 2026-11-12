"""Export dated, team-specific entity channels and corroborated fixed-point probes.

In 16.22 both sides' wire codes are collected on every input. Only reviewed
objects may enter the evidence index. A team seeing a projectile, a minimap
icon or a moving monster does not establish ground vision at its spawn.
"""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.replay_container import container_info, packets
from lol_coach.replay_fields import DISCOVERY_SHA256
from lol_coach.replay_vision import decode_payload, load_profile
from lol_coach import turret_identity
from lol_coach.map11_tower_anchors import tower_landmarks
from lol_coach.hero_sight import positions_in_view, reviewed_heroes
from lol_coach.movement_1622 import TEN_PLAYER, reviewed_ward_sources
from lol_coach.vision_regions_1622 import ward_region_observations


PANTHEON = '2febca32e5e32b182ded7dcccdcc0f2c41405d51e41115b058a5f2d7824e3692'
LUX = 'de8bd7553e8847751f52e2877bc0b320825dc92cc8554f412d7769743cb68c7b'
VERSION_22 = '16.22.836.1077'
VERSION_20 = '16.20.824.8524'
TEAM_CODES = {bytes.fromhex('56fd'): 100, bytes.fromhex('56fb'): 200}
ENTER, LEAVE = 0x4D5, 0x35B

# Families from this build's creation records, observed twice for the east
# camp and twice for the dragon pit. These are signatures, not decoded X/Z.
CREATIONS = {
    (102, 'b3962571c4b0b079b8b7429fb14e0acf'): 'blue-side-gromp',
    (106, '79474e71cb9f777a348f729fb14e0acf'): 'red-side-gromp',
    (119, '4616dd312800f87af6d380ce0d0d94cf'): 'cloud-drake',
    (122, '4616dd312800f87af6d380ce0d0d94cf'): 'infernal-drake',
}


def packet_ref(p):
    return {'kind': 'rofl_packet', 'stream': p['stream'], 'chunk': p['chunk'],
            'offset': p['offset'], 'opcode': hex(p['opcode']), 'outer_param': hex(p['param']),
            'payload_hex': p['payload'].hex()}


def observation(subject, team, when, visible, source):
    return dict(subject=subject, team_id=team, time_seconds=when, mode='transition',
                visible=visible, source=source)


def wire_query(raw, entity_id, team, at):
    """Read an entity's latest same-team signal without implying screen visibility."""
    header = container_info(raw)
    if header['version'] != VERSION_22:
        raise ValueError('This wire query supports build '+VERSION_22)
    if type(entity_id) is not int or not 0 < entity_id <= 0xffffffff or team not in (100, 200):
        raise ValueError('Invalid entity network ID or observer team')
    if not math.isfinite(at) or not 0 <= at <= header['metadata']['gameLength']/1000:
        raise ValueError('Query is outside this replay')
    latest = None
    events = 0
    anchors = []
    for p in packets(raw):
        if p['stream'] != 1 or p['param'] != entity_id or p['time'] > at:
            continue
        op = p['opcode']
        if op == 0x2f6 and len(p['payload']) == 121 and entity_id == 0x400000ae:
            anchors.append(round(p['time'], 3))
        if op in (ENTER, LEAVE):
            observer = TEAM_CODES.get(p['payload'])
            if observer is not None and observer != team:
                continue
            state = ('wire_enter' if op == ENTER else 'wire_leave') if observer else 'unknown'
        elif op in (0x36c, 0x2e7):
            # Lifecycle-like records can invalidate the unit even if a leave
            # was never sent. These opcodes alone do not identify a death.
            state = 'unknown'
        else:
            continue
        events += 1
        key = (p['time'], p['chunk'], p['offset'])
        if latest is None or latest[0] < key:
            latest = key, state, packet_ref(p)
    digest = sha256(raw).hexdigest()
    tower = tower_landmarks(raw, VERSION_22).get(entity_id)
    binding = tower if tower and tower['available_at_seconds'] <= at else None
    if digest == LUX and anchors == [57.775, 67.598]:
        binding = dict(candidate='Lux', basis='local blue Lux in startup roster and two same-actor records '
                       'at the HUD cast clocks', cast_window_seconds=anchors,
                       scope='correlation; empty ROFL footer roster; not a decoded name')
    return dict(schema='vision-wire-query/v1', version=header['version'], source_sha256=digest,
                network_id=hex(entity_id), observer_team=team, at_seconds=at,
                wire_state=latest[1] if latest else 'unknown', screen_visibility=None,
                last_event_seconds=latest[0][0] if latest else None,
                last_record=latest[2] if latest else None, events_examined=events,
                actor_binding=binding,
                basis='Latest native channel indication, scoped to this ID, team and cutoff. '
                      'World position, unit presence and client presentation are not inferred.')


def channels_22(raw, digest):
    reviewed = digest == PANTHEON
    heroes = reviewed_heroes(digest)
    bindings = dict(heroes)
    rows = []
    counts = Counter()
    shapes = []
    actor_records = defaultdict(list)
    creation_packets = {}
    observed_channels = defaultdict(set)
    channel_packets = defaultdict(list)
    dead = set()
    for p in packets(raw):
        if p['stream'] != 1:
            continue
        e, op, body = p['param'], p['opcode'], p['payload']
        if op == 0x224:
            label = CREATIONS.get((len(body), body[8:24].hex()))
            if label:
                shapes.append(dict(entity_id=hex(e), time_seconds=p['time'], candidate=label,
                                   source=packet_ref(p)))
                if reviewed:
                    bindings[e] = dict(name=label, basis='creation signature and matched camp/kill on this replay')
                    creation_packets[e] = packet_ref(p)
        if op in (ENTER, LEAVE):
            counts[(hex(op), body.hex())] += 1
        if e not in bindings:
            continue
        actor_records[e].append(p)
        if e in dead:
            continue
        if op in (ENTER, LEAVE):
            # A malformed payload invalidates the retained states instead of
            # applying it to a guessed observer.
            team = TEAM_CODES.get(body)
            teams = [team] if team else [100, 200]
            for observer in teams:
                visible = op == ENTER if team else None
                ref = packet_ref(p)
                ref['basis'] = 'team-specific binary visibility channel, cross-checked on this replay'
                if reviewed and e == 0x400000ae:
                    ref['basis'] = ('opposite-team channel on known blue Pantheon; player camera shows '
                                    'crossing the mid wave into south river brush, no red player camera')
                if e == 0x4000029d and op == LEAVE:
                    # The returning monster still has a visible silhouette and
                    # health bar in player frames during this short channel gap.
                    visible = None
                    ref.update(wire_channel_visible=False, basis='03:11 HUD preserves the leashing model')
                row = observation('entity:'+hex(e), observer, p['time'], visible, ref)
                rows.append(row)
                observed_channels[e].add(observer)
                channel_packets[e].append(row)
        elif e in heroes and op in (0x2e7, 0x36c):
            for team in observed_channels[e]:
                rows.append(observation('entity:'+hex(e), team, p['time'], None, packet_ref(p)))
        elif op == 0x2e7 and e in creation_packets:
            # This family is used here only on source-bound Gromp and drakes
            # with an independently matched kill. The empty camp stays unknown.
            if e in (0x4000029d, 0x400003e1, 0x40000ce2):
                dead.add(e)
                for team in observed_channels[e]:
                    rows.append(observation('entity:'+hex(e), team, p['time'], None, packet_ref(p)))

    if reviewed:
        # These two generations stand at their own camp, receive no attack or
        # path records, and are independently visible under a yellow ward.
        # The negative ground observation ends at the last reviewed HUD window.
        probes = [(0x4000029b, 'blue-side-gromp-camp', 265.0),
                  (0x40000835, 'red-side-gromp-camp', 445.0)]
        for e, name, last_dark_clock in probes:
            if e not in creation_packets:
                continue
            subject = 'ground:'+name
            scope_end = last_dark_clock + 1
            created = next(p['time'] for p in actor_records[e] if p['opcode'] == 0x224)
            invalidating = next((p for p in actor_records[e] if p['opcode'] not in (ENTER, LEAVE)
                and not (p['time']-created < 0.1 and p['opcode'] in (0x224, 0xc7, 0x19c, 0x1c8, 0x9f))), None)
            if invalidating is not None and invalidating['time'] < scope_end:
                scope_end = invalidating['time']
                stop = dict(packet_ref(invalidating), basis='movement, damage or unreviewed update ends fixed-point binding')
            else:
                stop = {'kind':'scope_end','basis':'end of the reviewed dark HUD interval',
                        'last_reviewed_hud_clock':last_dark_clock}
            for change in channel_packets[e]:
                if change['team_id'] != 100 or change['time_seconds'] >= scope_end:
                    continue
                source = dict(change['source'], basis='stationary neutral footprint; matched minimap light/dark',
                              spawn_record=creation_packets[e], footprint='sampled camp ground near resting Gromp only')
                rows.append(observation(subject, 100, change['time_seconds'], change['visible'], source))
            rows.append(observation(subject, 100, scope_end, None, stop))
    return rows, {hex(e):v for e,v in bindings.items()}, {
        'wire_counts': {f'{op}/{payload}': n for (op,payload), n in counts.items()},
        'unbound_creation_candidates': [] if reviewed else shapes,
        'scope':'On unreviewed files, wire counts and creation signatures are diagnostics only. '
                'Blue neutral channel independently checked against HUD; opposite team on the blue champion is inferred.'}


def channels_20(raw, digest, stats):
    # Participant row order has only been validated on this raw file.
    bindings = {}
    if digest == DISCOVERY_SHA256:
        for i, player in enumerate(stats):
            bindings[0x40000034+i] = dict(name=player['SKIN'], team_id=int(player['TEAM']),
                                           basis='reviewed ten-player actor mapping')
    profile, towers = load_profile(), turret_identity.load_profile()
    rows = []
    destroyed = set()
    # Process only records that can affect these channels. Keyframes must be
    # ordered on the game clock before identity can be used.
    needed = {0xd8, 0x269, 0x484, 0x3cd}
    relevant = sorted((p for p in packets(raw) if p['opcode'] in needed),
                      key=lambda p:(p['time'], 0 if p['stream'] == 2 else 1, p['chunk'], p['offset']))
    for p in relevant:
        e, op = p['param'], p['opcode']
        if op == 0xd8:
            try:
                tower = turret_identity.decode_name(p['payload'], version=VERSION_20, profile=towers)
            except ValueError:
                continue
            bindings.setdefault(e, dict(name=tower['name'], team_id=tower['team'], role=tower['role'],
                map_reference_position=tower['map_reference_position'], map_reference=tower['map_reference'],
                basis='decoded tower name and static tower position', identified_at=p['time']))
            continue
        if e not in bindings or p['stream'] != 1 or e in destroyed:
            continue
        identity = bindings[e]
        team = 300-identity['team_id']
        if op == 0x269:
            if 'role' in identity:
                destroyed.add(e)
                rows.append(observation('entity:'+hex(e), team, p['time'], None, packet_ref(p)))
            continue
        try:
            state = decode_payload(op, p['payload'], version=VERSION_20, profile=profile)
        except ValueError:
            rows.append(observation('entity:'+hex(e), team, p['time'], None, packet_ref(p)))
            continue
        if state['observer_team_id'] != team:
            raise ValueError('Entity identity conflicts with observer team')
        ref = dict(packet_ref(p), basis=state['evidence_level'])
        rows.append(observation('entity:'+hex(e), team, p['time'], state['visible'], ref))
    return rows, {hex(e):v for e,v in bindings.items()}, {
        'scope':'Entity channel; turret positions are named map-reference landmarks, not a ground fog polygon.'}


def export(raw, game_dir=None):
    info = container_info(raw)
    digest = sha256(raw).hexdigest()
    position_samples = []
    wards = []
    bonuses = None
    if info['version'] == VERSION_22:
        rows, actors, diagnostics = channels_22(raw, digest)
        position_samples = positions_in_view(raw, digest, rows)
        diagnostics['fixed_map_landmarks'] = {hex(e): t for e, t in tower_landmarks(raw, VERSION_22).items()}
        if digest in (PANTHEON, TEN_PLAYER):
            wards = reviewed_ward_sources(raw)
            native = {r['entity_id']:r for r in ward_region_observations(raw, wards)}
            for ward in wards:
                ward['spatial_record'] = native.get(ward['entity_id'])
            if game_dir is not None:
                from lol_coach.faelights_1622 import faelight_intervals, load_faelights
                bonuses = faelight_intervals(raw, wards, load_faelights(game_dir))
    elif info['version'] == VERSION_20:
        rows, actors, diagnostics = channels_20(raw, digest, json.loads(info['metadata']['statsJson']))
    else:
        raise ValueError('No reviewed visibility profile for this build')
    # A tick can carry enter followed by leave in the same object channel.
    # Keep only the final wire state available to a game-clock cutoff.
    by_tick = {(r['subject'], r['team_id'], r['time_seconds']):r for r in rows}
    return dict(schema='vision-evidence/v1', version=info['version'], source_sha256=digest,
                end_seconds=info['metadata']['gameLength']/1000, entities=actors, diagnostics=diagnostics,
                enemy_positions_in_view=position_samples, ward_placements=wards, faelight_intervals=bonuses,
                observations=sorted(by_tick.values(),key=lambda r:(r['time_seconds'],r['subject'],r['team_id'])))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', required=True, type=Path)
    parser.add_argument('--game-dir', type=Path, help='Matching Game directory for native Faelight region geometry')
    parser.add_argument('--output', type=Path, help='Evidence index path, or optional wire-query result path')
    parser.add_argument('--entity-id', type=lambda value:int(value, 0), help='Network ID for a raw 16.22 channel query')
    parser.add_argument('--team', type=int, choices=(100, 200))
    parser.add_argument('--at', type=float, help='Inclusive game clock in seconds')
    args = parser.parse_args()
    if args.output and args.output.resolve() == args.replay.resolve():
        parser.error('Output would overwrite the input')
    if args.entity_id is not None:
        if args.team is None or args.at is None:
            parser.error('--entity-id requires --team and --at')
        result = wire_query(args.replay.read_bytes(), args.entity_id, args.team, args.at)
        print(json.dumps(result, ensure_ascii=True))
        if not args.output:
            return
    else:
        if not args.output or args.at is not None or args.team is not None:
            parser.error('Export needs an output file; use --entity-id for timed channel queries')
        result = export(args.replay.read_bytes(), game_dir=args.game_dir)
        print(json.dumps({'version':result['version'], 'observations':len(result['observations']),
                          'entities':len(result['entities'])}))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
