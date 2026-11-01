"""Conservative live-packet prefixes of exact-build lane-minion evidence.

This pure research query never interpolates a trajectory or counts survivors.
A visibility channel records its last message, not proof that an actor is alive.
Team views retain explicitly observed history; unknown/hidden updates cannot
refresh that history, and a new enter starts an empty observation interval.
"""
from copy import deepcopy
import json
import math


VERSION = '16.20.824.8524'
SCHEMA = 'lane-dynamics-evidence/v1'
HEALTH_FIELDS = ('health', 'max_health')
SOURCE_FIELDS = ('stream', 'chunk', 'decompressed_offset', 'packet_index',
                 'opcode', 'payload_sha256', 'decoded_record_offset',
                 'decoded_record_end', 'decoded_group_offset', 'record_index',
                 'group_index', 'encoded_array_offset')
VISIBILITY_KINDS = frozenset(('visibility_enter', 'visibility_leave',
                              'visibility_unknown_barrier', 'unknown_barrier'))


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _source(row):
    """Keep byte locations/hashes, never an unbounded raw packet or witness."""
    result = {key: deepcopy(row['source'][key]) for key in SOURCE_FIELDS
              if key in row['source']}
    for name in ('decoded_path_offset', 'decoded_position_offset'):
        if name in row:
            result[name] = deepcopy(row[name])
    return result


def _key(row, identity=False):
    src = row['source']
    # Packet locations precede decoded subrecord locations. The final canonical
    # tie-breaker makes ambiguous equal-location records input-order independent;
    # it does not claim a missing wire order has been recovered.
    return (row['time_seconds'], src['chunk'], src['decompressed_offset'],
            0 if identity else 1,
            src.get('decoded_record_offset', -1), src.get('decoded_group_offset', -1),
            src.get('record_index', -1), src.get('group_index', -1),
            src.get('packet_index', -1),
            json.dumps({'entity_id': row['entity_id']} if identity else row,
                       sort_keys=True, separators=(',', ':'), allow_nan=False))


def _live_prefix(rows, at):
    result = []
    for row in rows:
        # Checkpoint content must not participate in a live query, even if its
        # own timestamp is early. Future payloads also need not be decoded.
        if row.get('source', {}).get('stream') != 1:
            continue
        timestamp = row.get('time_seconds')
        if not _number(timestamp) or timestamp < 0:
            raise ValueError('Invalid live evidence timestamp')
        if timestamp > at:
            continue
        source = row['source']
        for name in ('chunk', 'decompressed_offset'):
            if type(source.get(name)) is not int or source[name] < 0:
                raise ValueError('Invalid live evidence packet location')
        for name in ('decoded_record_offset', 'decoded_group_offset', 'record_index',
                     'group_index', 'packet_index'):
            if name in source and (type(source[name]) is not int or source[name] < 0):
                raise ValueError('Invalid live evidence subrecord location')
        if not isinstance(row.get('entity_id'), str):
            raise ValueError('Invalid live evidence entity ID')
        result.append(row)
    return result


def _identity(row, at, observer):
    identity = row['identity']
    result = {key: deepcopy(identity[key]) for key in ('team_id', 'lane', 'kind')
              if key in identity}
    if result.get('kind') == 'super':
        available = identity.get('classification_available_at')
        # Retrospective attribute corroboration has no observer permission in
        # this bundle. Merely reaching its timestamp cannot make it team-known.
        if observer is not None or not _number(available) or available > at:
            result['kind'] = 'super_candidate'
        else:
            result['classification_available_at'] = available
    return result


def _sample(row, at, **values):
    return dict(**values, observed_at_seconds=row['time_seconds'],
                age_seconds=at-row['time_seconds'], source=_source(row),
                historical_sample=True)


def _empty_observed():
    return dict(health_samples={}, path_command=None,
                static_format_position_sample=None, zero_health_sample=None,
                removal_candidate=None)


def _entity(row, at, observer):
    return dict(entity_id=row['entity_id'], identity=_identity(row, at, observer),
        identity_evidence=dict(source_recorded_at_seconds=row['time_seconds'],
            age_seconds=at-row['time_seconds'], source=_source(row),
            semantics='live spawn identity record; timestamp is not observer knowledge time'),
        identity_available_to_observer_at_seconds=row['time_seconds'] if observer is None else None,
        last_health_samples={}, last_path_command=None,
        last_static_format_position_sample=None, zero_health_sample=None,
        removal_candidate=None, lifecycle_evidence=[],
        visibility=dict(observer_team_id=observer, visible=None, last_transition=None,
                        semantics='last explicit entity-channel state; not proof of survival'),
        current_observed=_empty_observed(),
        last_observed_is_current_state=False,
        current_position=None, alive=None, lane_priority=None,
        decision_input_eligible=False)


def _health(row, state, at):
    values = row.get('values', {})
    for name in HEALTH_FIELDS:
        if name not in values:
            continue
        value = values[name]
        if not _number(value) or value < 0:
            raise ValueError('Invalid lane-health sample')
        field = row.get('fields', {}).get(name, {})
        # A field anchor can retain its encoded scalar, but never the unknown
        # suffix, another actor's fields, or an arbitrary retrospective witness.
        field = {key: deepcopy(field[key]) for key in
                 ('value', 'decoded_offset', 'decoded_payload_offset', 'encoded_hex')
                 if key in field}
        sample = _sample(row, at, value=value, field_evidence=field,
                         unit='health_points')
        state['last_health_samples'][name] = sample
        state['current_observed']['health_samples'][name] = sample
        if name == 'health' and value == 0:
            zero = dict(sample, semantics='zero-health sample; exact death time unknown')
            state['zero_health_sample'] = zero
            state['current_observed']['zero_health_sample'] = zero
            state['lifecycle_evidence'].append(dict(kind='zero_health_sample', **zero))


def _path(row, state, at, observer):
    points = row.get('relative_waypoints', [])
    start = points[0] if points else row.get('first_relative_point_candidate')
    values = dict(first_relative_point_candidate=deepcopy(start),
                  position_semantics='historical path-start candidate; not current position',
                  actual_arrival=None)
    if observer is None or state['identity'].get('team_id') == observer:
        values.update(relative_waypoints=deepcopy(points),
                      path_speed=deepcopy(row.get('path_speed')),
                      plan_semantics='recorded command; not continuous position or arrival')
    else:
        values['plan_semantics'] = 'enemy future route and speed withheld'
    sample = _sample(row, at, **values)
    state['last_path_command'] = sample
    state['current_observed']['path_command'] = sample


def _position(row, state, at):
    sample = _sample(row, at, position_xz=deepcopy(row.get('position_xz')),
        position_semantics='historical compound-format sample; current-time position unverified',
        current_position=None)
    state['last_static_format_position_sample'] = sample
    state['current_observed']['static_format_position_sample'] = sample


def query_at(bundle, at, observer_team_id=None):
    """Return an immutable-input research prefix; this is not a model frame.

    ``observer_team_id=None`` exposes live omniscient research observations.
    ``100``/``200`` require a live identity then an explicit enter before an
    entity can appear. In either team, unknown initial visibility remains
    unknown, including allied entities. ``current_observed`` contains only
    samples received in the latest visible interval, never assumed current HP.

    Full-file source/dependency references are placed only in ``audit``; they
    are provenance, not time-t gameplay facts. No summaries, rejected records,
    checkpoint payloads, or retrospective identity witnesses are propagated.
    """
    if bundle.get('schema') != SCHEMA:
        raise ValueError('Unsupported lane-dynamics schema')
    if bundle.get('version') != VERSION:
        raise ValueError('Unsupported exact build')
    end = bundle.get('recording_end_seconds')
    if not _number(end) or end < 0:
        raise ValueError('Invalid recording end')
    if not _number(at) or at < 0 or at > end:
        raise ValueError('Invalid lane-dynamics cutoff')
    if observer_team_id is not None and (type(observer_team_id) is not int
                                        or observer_team_id not in (100, 200)):
        raise ValueError('Unsupported observer team')

    identities = _live_prefix(bundle.get('identities', []), at)
    events = _live_prefix(bundle.get('events', []), at)
    timeline = [(_key(row, True), True, row) for row in identities]
    timeline.extend((_key(row), False, row) for row in events)
    state, ever_seen = {}, set()
    for _, is_identity, row in sorted(timeline, key=lambda item: item[0]):
        actor = row['entity_id']
        if is_identity:
            # Repeated/checkpoint-like identities cannot reset a live actor or
            # retroactively import another observation into its first identity.
            if actor not in state:
                state[actor] = _entity(row, at, observer_team_id)
            continue
        if actor not in state:
            continue
        entity = state[actor]
        kind = row.get('kind')
        if kind in VISIBILITY_KINDS:
            if observer_team_id is None:
                # Omniscient has no single observer channel. Do not invent one.
                continue
            if row.get('observer_team_id') not in (None, observer_team_id):
                continue
            if kind == 'visibility_enter' and row.get('observer_team_id') == observer_team_id:
                visible = True
                if actor not in ever_seen:
                    entity['identity_available_to_observer_at_seconds'] = row['time_seconds']
                ever_seen.add(actor)
            elif kind == 'visibility_leave' and row.get('observer_team_id') == observer_team_id:
                visible = False
            else:
                visible = None
            entity['visibility'].update(visible=visible, last_transition=
                _sample(row, at, kind=kind, visible=visible))
            entity['current_observed'] = _empty_observed()
            continue
        if observer_team_id is not None and entity['visibility']['visible'] is not True:
            continue
        if kind == 'health_sample':
            _health(row, entity, at)
        elif kind == 'path_command':
            _path(row, entity, at, observer_team_id)
        elif kind == 'static_format_position_sample':
            _position(row, entity, at)
        elif kind == 'terminal_removal_candidate':
            sample = _sample(row, at, payload_hex=row.get('payload_hex'),
                semantics='terminal-removal candidate; not exact death time', exact_death_time=None)
            entity['removal_candidate'] = sample
            entity['current_observed']['removal_candidate'] = sample
            entity['lifecycle_evidence'].append(dict(kind=kind, **sample))
        elif kind == 'uninterpreted_167':
            # Preserve a visibly received raw event as an observation. It never
            # changes death, removal, visibility, or any current-state value.
            entity['lifecycle_evidence'].append(_sample(row, at,
                kind=kind, payload_hex=row.get('payload_hex'),
                semantics='uninterpreted opcode; no lifecycle transition inferred'))

    entities = []
    for actor, entity in sorted(state.items()):
        if observer_team_id is not None:
            if actor not in ever_seen:
                continue
            if entity['visibility']['visible'] is not True:
                entity['current_observed'] = None
        entities.append(entity)
    return dict(schema='lane-dynamics-query/v1', version=VERSION,
        at_seconds=at, observer_team_id=observer_team_id,
        mode='research_omniscient' if observer_team_id is None else 'research_observer_limited',
        entities=entities, current_position=None, alive_count=None, lane_priority=None,
        decision_input_eligible=False,
        audit=dict(source=deepcopy(bundle.get('source')),
                   dependencies=deepcopy(bundle.get('dependencies', {}))),
        limitations=['Historical live-packet observations only; no checkpoint backfill',
            'Last visible channel state does not prove current visibility coverage or survival',
            'No continuous current position, alive count, lane priority, or arrival ETA',
            'Not connected to model decision input; independent gameplay validation absent'])
