"""Observer-bounded adapters for existing exact-build travel evidence.

This reads previously exported evidence; it does not decode a replay or certify
speed candidates as continuous movement. Original files are never rewritten.
"""
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from .travel_validity import VERSION, event_order


STEMS = frozenset(('HN1-11360086609', 'HN1-11363048522',
                   'HN1-11363093470', 'HN1-11372643015'))


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _source(row):
    if 'source' in row:
        result = deepcopy(row['source'])
    else:
        packet = row['packet']
        result = dict(stream=packet['stream'], chunk=packet['chunk'],
                      decompressed_offset=packet['offset'])
        if 'record_id' in row:
            result['record_id'] = row['record_id']
            result['packet_index'] = int(row['record_id'].split(':')[0])
    # Raw payloads are unnecessary for the adapter; preserve hashes/locations.
    result.pop('payload_hex', None)
    return result


def _wire_key(row):
    src = row['source']
    return (row['time_seconds'], src['chunk'], src['decompressed_offset'])


def _within_packet(row):
    """Byte locations order records; priority orders policy output, not wire facts."""
    src = row['source']
    offset = next((src[k] for k in ('decoded_payload_offset', 'record_payload_offset',
                  'decoded_record_offset') if k in src), -1)
    record_id = src.get('record_id', '')
    record_index = int(record_id.split(':')[1]) if ':' in record_id else src.get('record_index', -1)
    return (offset, src.get('decoded_group_offset', -1), record_index,
            src.get('group_index', -1), row.get('_priority', 1), row['entity_id'])


def load_inputs(root: Path, stem: str, observer_team_id: int):
    """Return strictly ordered, source-bound events for one observer.

    Hero own-team information follows the existing ``team_shared_information``
    policy only for verified metadata mappings. Minions require both a live
    identity and an explicit matching enter. Unknown teams never receive route
    permission. Event-time facts come only from live packet timestamps.
    """
    root = Path(root).resolve()
    if stem not in STEMS:
        raise ValueError('Unsupported replay cohort')
    if type(observer_team_id) is not int or observer_team_id not in (100, 200):
        raise ValueError('Unsupported observer team')
    inputs = {}

    def read(relative):
        path = root / relative
        raw = path.read_bytes()
        inputs[relative] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)

    ten = read(f'data/private/replay_ten/{stem}.json')
    state = read(f'data/private/replay_state/{stem}.json')
    vision = read(f'data/private/replay_vision/{stem}.json')
    lane_name = f'data/private/lane_dynamics_run_20261028/{stem}/evidence.json'
    lane = read(lane_name)
    receipt = read(f'data/private/lane_dynamics_run_20261028/{stem}/receipt.json')
    world = read(f'data/private/world_objects/{stem}.json')
    raw_ref = lane['source']
    digest = raw_ref['sha256']
    if any(bundle.get('version') != VERSION for bundle in (ten, state, vision, lane, world)):
        raise ValueError('Build binding mismatch')
    if (ten['replay_sha256'] != digest or any(bundle['source_sha256'] != digest
            for bundle in (state, vision, world)) or receipt['source']['sha256'] != digest
            or ten['sources'][stem + '.rofl']['sha256'] != digest):
        raise ValueError('Replay SHA256 binding mismatch')
    if receipt['output']['sha256'] != inputs[lane_name]:
        raise ValueError('Lane receipt mismatch')
    raw_path = Path(raw_ref['path']).resolve()
    if hashlib.sha256(raw_path.read_bytes()).hexdigest() != digest:
        raise ValueError('Original replay SHA256 mismatch')
    inputs[str(raw_path)] = digest
    end = lane['recording_end_seconds']
    if not _finite(end) or end < 0:
        raise ValueError('Invalid recording end')

    actors = {}
    owners = {a['entity_id']: a for a in ten['identity_directory']['owners']}
    participants = ten['categories']['participants']
    for actor in vision['actors']:
        entity = actor['entity_id']
        if entity in actors or entity not in owners or actor['champion'] != owners[entity]['champion']:
            raise ValueError('Conflicting hero identity directories')
        team = actor.get('team_id')
        index = ten['entity_to_participant'].get(entity)
        if team is not None and (type(index) is not int or index < 0 or index >= len(participants)
                                 or participants[index]['team_id'] != team):
            raise ValueError('Unverified hero team')
        actors[entity] = team

    raw_events = []
    counts = Counter()

    def stage(row, kind, entity_kind, **values):
        src = _source(row)
        if src.get('stream') != 1:
            counts['checkpoint_rows_excluded'] += 1
            return
        t = row['time_seconds']
        if not _finite(t) or not 0 <= t <= end:
            raise ValueError('Invalid live evidence time')
        for key in ('chunk', 'decompressed_offset'):
            if type(src.get(key)) is not int or src[key] < 0:
                raise ValueError('Invalid source packet anchor')
        raw_events.append(dict(entity_id=row['entity_id'], entity_kind=entity_kind,
            time_seconds=t, kind=kind, source=src, **values))

    for row in vision['events']:
        stage(row, 'visibility', 'hero', observer_team_id=row['observer_team_id'], value=row['visible'])
    for row in state['updates']:
        if 'health' in row['values']:
            stage(row, 'health', 'hero', value=row['values']['health'])
    for row in ten['categories']['movement']['events']:
        stage(row, 'path', 'hero', points=deepcopy(row['relative_waypoints']), speed=row['speed_candidate'])
    for row in ten['categories']['lifecycle']['events']:
        if row['kind'] in ('death', 'respawn_candidate'):
            stage(row, row['kind'], 'hero')
    for row in world['hero_speed_stat_samples']:
        stage(row, 'speed', 'hero', value=row['movement_speed_stat_candidate'])
    for row in lane['identities']:
        # Do not propagate retrospective kind=super or its witnesses.
        stage(row, '_identity', 'minion', entity_team_id=row['identity'].get('team_id'), _priority=0)
    for row in lane['events']:
        kind = row['kind']
        if kind in ('visibility_enter', 'visibility_leave', 'visibility_unknown_barrier', 'unknown_barrier'):
            value = True if kind == 'visibility_enter' else False if kind == 'visibility_leave' else None
            stage(row, 'visibility', 'minion', observer_team_id=row.get('observer_team_id'), value=value)
        elif kind == 'health_sample' and 'health' in row.get('values', {}):
            stage(row, 'health', 'minion', value=row['values']['health'])
        elif kind == 'path_command':
            stage(row, 'path', 'minion', points=deepcopy(row.get('relative_waypoints', [])), speed=row.get('path_speed'))
        elif kind == 'terminal_removal_candidate':
            stage(row, 'removal_candidate', 'minion')
        elif kind == 'static_format_position_sample':
            stage(row, 'position', 'minion', point=deepcopy(row.get('position_xz')))
        else:
            counts['uninterpreted_lane_rows_excluded'] += 1

    visible = {}
    minion_teams = {}
    terminal_minions = set()
    output = []

    def emit(row):
        row.pop('_priority', None)
        row.update(source_sha256=digest, version=VERSION)
        output.append(row)

    for row in sorted(raw_events, key=lambda e: (_wire_key(e), _within_packet(e))):
        entity, kind = row['entity_id'], row['kind']
        hero = row['entity_kind'] == 'hero'
        if hero and entity not in actors:
            # replay_ten movement arrays can also contain an unnamed secondary
            # owner. A movement record alone does not establish hero identity.
            counts['movement_actor_without_hero_identity_excluded'] += 1
            continue
        if kind == '_identity':
            if entity in minion_teams and minion_teams[entity] != row['entity_team_id']:
                raise ValueError('Conflicting live minion identity')
            minion_teams.setdefault(entity, row['entity_team_id'])
            continue
        if not hero and entity not in minion_teams:
            counts['before_live_identity_excluded'] += 1
            continue
        team = actors[entity] if hero else minion_teams[entity]
        ally = team == observer_team_id
        if kind == 'visibility':
            if hero and ally:
                continue  # Ally observability is a separate policy, not this channel.
            observer = row['observer_team_id']
            if observer not in (None, observer_team_id):
                counts['other_observer_rows_excluded'] += 1
                continue
            row['observer_team_id'] = observer_team_id
            if observer is None:
                row['source']['observer_semantics'] = 'unknown_channel_barrier_applies_to_selected_observer'
                row['value'] = None
            visible[entity] = row['value']
            emit(row)
            continue
        if hero and ally and entity not in visible:
            init = dict(entity_id=entity, entity_kind='hero', time_seconds=row['time_seconds'],
                        kind='visibility', value=True, observer_team_id=observer_team_id,
                        source=deepcopy(row['source']))
            init['source']['policy'] = 'team_shared_information'
            init['source']['policy_semantics'] = 'First accepted live evidence for verified allied roster; not an explicit visibility-enter packet'
            visible[entity] = True
            emit(init)
        if hero and kind == 'death':
            row['public'] = True
            row['source']['policy'] = 'public_kill_feed_assumption'
            row['source']['field_semantics'] = 'transferred_same_build_death_grammar; public kill-feed policy, not exact simulation death time'
            emit(row)
            continue
        if visible.get(entity) is not True:
            counts['not_currently_observable_rows_excluded'] += 1
            continue
        if kind == 'speed':
            if not hero or not ally:
                counts['speed_permission_rows_excluded'] += 1
                continue
            row['source']['field_semantics'] = 'movement_speed_stat_candidate; conservative invalidation only, not verified continuous speed'
        elif kind == 'health' and not hero:
            if entity in terminal_minions and row['value'] > 0:
                counts['terminal_minion_positive_health_excluded'] += 1
                continue
            if row['value'] == 0:
                terminal_minions.add(entity)
        elif kind == 'removal_candidate' and not hero:
            terminal_minions.add(entity)
            row['source']['field_semantics'] = 'terminal_removal_candidate; exact death time unknown'
        elif kind == 'path':
            points = row['points']
            if not points:
                counts['empty_path_rows_excluded'] += 1
                continue
            if not ally:
                row['kind'] = 'position'
                row['point'] = points[0]
                row.pop('points'); row.pop('speed')
                row['source']['field_semantics'] = 'observed_path_start_candidate; enemy or unknown-team future route and speed withheld'
            else:
                row['entity_team_id'] = team
                row['source']['team_basis'] = 'verified_static_metadata_mapping' if hero else 'prior_live_spawn_identity'
                row['source']['field_semantics'] = 'received_path_command_candidate; not measured traversal'
        emit(row)

    # Assign explicit adapter order within each original packet. Policy visibility
    # is emitted immediately before its first supporting event. This ordinal is
    # not claimed to be an original byte offset.
    grouped = defaultdict(list)
    for row in output:
        grouped[_wire_key(row)].append(row)
    for rows in grouped.values():
        packet_indices = {r['source']['packet_index'] for r in rows
                          if r['source'].get('packet_index', -1) >= 0}
        if len(packet_indices) > 1:
            raise ValueError('Conflicting packet indices at one source anchor')
        packet_index = next(iter(packet_indices), -1)
        for ordinal, row in enumerate(rows):
            row['source']['packet_index'] = packet_index
            row['source']['ordinal'] = ordinal
            row['source']['ordinal_semantics'] = 'adapter_order_within_original_packet; initial team-sharing policy precedes its first supporting field'
    output.sort(key=event_order)
    counts.update({'events': len(output), 'unknown_team_heroes': sum(t is None for t in actors.values())})
    counts.update({'event_' + kind: n for kind, n in Counter(r['kind'] for r in output).items()})
    counts.update({'entity_kind_' + kind: n for kind, n in Counter(r['entity_kind'] for r in output).items()})
    return dict(events=output, source_sha256=digest, version=VERSION,
        recording_end_seconds=end, inputs=inputs, counts=dict(counts), limitations=[
            'Standalone research adapter; no model decision permission or arrival precision claim',
            'Verified allied hero roster is static metadata mapping, not a timed enter event',
            'Unknown-team short-replay heroes do not receive allied route permission',
            'Speed scalar is an independent binary candidate, used only for conservative invalidation',
            'Minions require live identity and explicit observer enter; terminal lifecycle persists',
            'Enemy and unknown-team future routes/speeds are withheld; re-entry never backfills hidden samples',
            'Packet ordering uses original anchors; ordinal is explicit adapter sequencing within a packet',
            'No calibrated observation-gap duration or continuous speed ground truth is provided'])
