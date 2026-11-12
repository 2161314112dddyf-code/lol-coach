"""Source-bound enemy position samples. Never expose a path's destination."""
from collections import defaultdict

from .movement_1622 import PANTHEON, TEN_PLAYER, iter_path_samples


def reviewed_heroes(digest):
    if digest == PANTHEON:
        return {0x400000ae: dict(name='Pantheon', team_id=100, basis='single-player roster, cast and recall anchors')}
    if digest != TEN_PLAYER:
        return {}
    # Both fountain groups and the ten individual ward-placement totals
    # independently identify these actors in this match.
    names = ('Aatrox', 'Jayce', 'TwistedFate', 'Caitlyn', 'Pantheon',
             'Yone', 'MasterYi', 'Katarina', 'KogMaw', 'TahmKench')
    return {0x400000ae + i: dict(name=name, team_id=100 if i < 5 else 200,
            basis='reviewed match roster, native fountain side and per-actor ward counts') for i, name in enumerate(names)}


def visible_path_starts(samples, heroes, observations):
    """Join only current path starts, inside known opposing-team enter/leave intervals."""
    channels = defaultdict(list)
    for row in observations:
        key = row['subject'], row['team_id']
        if row['mode'] == 'transition':
            channels[key].append(row)
    windows = {}
    for entity, hero in heroes.items():
        observer = 300 - hero['team_id']
        key = 'entity:'+hex(entity), observer
        events = sorted(channels[key], key=lambda e:(e['time_seconds'], e['source']['chunk'], e['source']['offset']))
        windows[entity] = (observer, events, {e['time_seconds'] for e in events if e['visible'] is not True})
    eligible = defaultdict(list)
    for s in samples:
        if s['entity_id'] in windows:
            eligible[s['entity_id']].append(s)
    output = []
    for entity, rows in eligible.items():
        observer, events, ambiguous_ticks = windows[entity]
        event_index = 0
        state = None
        for sample in sorted(rows, key=lambda s:(s['time_seconds'], s['source']['chunk'], s['source']['offset'])):
            t = sample['time_seconds']
            bound = (t, sample['source']['chunk'], sample['source']['offset'])
            while event_index < len(events):
                event = events[event_index]
                if (event['time_seconds'], event['source']['chunk'], event['source']['offset']) > bound:
                    break
                state = event
                event_index += 1
            if not state or state['visible'] is not True or t in ambiguous_ticks or not sample['world_waypoints_xz']:
                continue
            output.append(dict(subject='entity:'+hex(entity), team_id=observer, time_seconds=t,
                               xz=sample['world_waypoints_xz'][0], source=sample['source'],
                               visibility_record=state['source']))
    return sorted(output, key=lambda s:(s['time_seconds'], s['source']['chunk'], s['source']['offset']))


def positions_in_view(raw, digest, observations):
    heroes = reviewed_heroes(digest)
    return visible_path_starts(iter_path_samples(raw), heroes, observations) if heroes else []


def native_vision_snapshot(index, team, player, at):
    """Build the existing decision snapshot from a reviewed 16.22 vision index."""
    from .region_vision import visibility_query
    roster = reviewed_heroes(index['source_sha256'])
    heroes = []
    evidence = {}
    owner = None
    for entity, hero in roster.items():
        eid = hex(entity)
        if player in (eid, hero['name']) and hero['team_id'] == team:
            owner = eid
        visibility = dict(value=True if team == hero['team_id'] else None)
        if team != hero['team_id']:
            answer = visibility_query([index], team, 'entity:'+eid, at)
            if answer['visible'] is not None and answer['evidence']:
                last = answer['evidence'][-1]
                key = 'vision-'+eid
                evidence[key] = dict(entity_id=eid, time_seconds=last['time_seconds'], source=last['source'])
                visibility = dict(value=answer['visible'], transition_seconds=last['time_seconds'], evidence_id=key)
        heroes.append(dict(entity_id=eid, team_id=hero['team_id'], champion=hero['name'],
                           visibility=visibility, inventory={}))
    if owner is None:
        raise ValueError("Choose a verified own-team champion name or network ID on a reviewed replay")
    return dict(schema='macro-snapshot/v1', version=index['version'], source_sha256=index['source_sha256'],
                context=dict(at_seconds=at, observer_team_id=team, player_entity_id=owner),
                heroes=heroes, recent_public_combat=[], evidence=evidence)
