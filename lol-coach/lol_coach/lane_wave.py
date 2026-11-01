"""Observer-limited minion groups for decision frames, with explicit estimates.

Groups describe nearby units, not decoded spawn-wave IDs or lane priority.
Raw paths, hidden updates, full-file hashes and protocol payloads stay in audit.
"""
from collections import Counter
from copy import deepcopy
import json
import math
from pathlib import Path

from .lane_current_state import reconstruct_lane_current_state
from .lane_tracking import estimate_path
from .replay_state import VERSION

PROFILE = Path(__file__).with_name('profiles')/'lane_tracking_16_20.json'
GROUP_RADIUS = 600.0


def key(row):
    source = row['source']
    return (row['time_seconds'], source['chunk'], source.get('decompressed_offset', source.get('offset')),
            source.get('decoded_record_offset', -1), source.get('packet_index', -1))


def source_key(sample):
    return key(dict(time_seconds=sample['observed_at_seconds'], source=sample['source']))


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _anchors(towers, at, source_sha256):
    if towers is None:
        return [], None
    if (towers.get('schema') != 'turret-state/v1' or towers.get('version') != VERSION
            or towers.get('source', {}).get('sha256') != source_sha256):
        raise ValueError('Lane anchor source/build mismatch')
    anchors = {}
    for row in sorted(towers['identity_events'], key=key):
        if row['time_seconds'] > at:
            continue
        if row['source']['stream'] != 1 and not (row['source']['stream'] == 2 and row['time_seconds'] == 0):
            continue
        identity = row['identity']
        pos = identity.get('map_reference_position')
        if (not isinstance(pos, (list, tuple)) or len(pos) != 3
                or not all(finite(n) for n in pos) or identity.get('map_reference') not in ('Map11', 'Map12')):
            continue
        anchors.setdefault(row['entity_id'], dict(entity_id=row['entity_id'],
            team_id=identity['team'], name=identity['name'], role=identity['role'],
            position_xz=[pos[0], pos[2]], map_reference=identity['map_reference'],
            identity_available_at_seconds=row['time_seconds'], source=deepcopy(row['source'])))
    families = {a['map_reference'] for a in anchors.values()}
    if len(families) > 1:
        raise ValueError('Conflicting map-reference anchors')
    if not families or not PROFILE.exists():
        return list(anchors.values()), None
    profile = json.loads(PROFILE.read_text(encoding='utf-8'))
    if profile['version'] != VERSION:
        raise ValueError('Unsupported lane tracking profile')
    family = next(iter(families))
    binding = deepcopy(profile['maps'][family])
    binding['map_reference'] = family
    binding['runtime_map_id_decoded'] = False
    return list(anchors.values()), binding


def _position(event, at, binding):
    estimate = estimate_path(event, at, map_binding=binding)
    earlier = max(event['time_seconds'], at-0.1)
    elapsed = at-earlier
    velocity = None
    if elapsed > 0:
        previous = estimate_path(event, earlier)['relative_position_estimate']
        velocity = [round((estimate['relative_position_estimate'][i]-previous[i])/elapsed, 2) for i in range(2)]
    result = dict(relative_xz=[round(v, 2) for v in estimate['relative_position_estimate']],
        world_xz=None, motion=estimate['motion_state'], path_updated_at_seconds=event['time_seconds'],
        path_age_seconds=round(at-event['time_seconds'], 3), endpoint_clamped=estimate['endpoint_clamped'],
        velocity_xz_estimate=velocity, velocity_interval_seconds=round(elapsed, 3),
        semantics='forward_motion_estimate_not_direct_position_or_proven_arrival')
    if estimate.get('world_position_estimate') is not None:
        result['world_xz'] = [round(v, 2) for v in estimate['world_position_estimate']]
    return result


def _groups(units):
    """Deterministic radius components, explicitly a spatial grouping heuristic."""
    remaining = {u['entity_id']: u for u in units if u['position'] is not None}
    result = []
    while remaining:
        first = min(remaining)
        group = [remaining.pop(first)]
        frontier = [group[0]]
        while frontier:
            unit = frontier.pop()
            close = [i for i, other in remaining.items()
                     if math.dist(unit['position']['relative_xz'], other['position']['relative_xz']) <= GROUP_RADIUS]
            for actor in sorted(close):
                other = remaining.pop(actor)
                group.append(other)
                frontier.append(other)
        result.append(sorted(group, key=lambda u: u['entity_id']))
    return result


def _counts(units):
    return [dict(team_id=team, kind=kind, count=count)
            for (team, kind), count in sorted(Counter((u['team_id'], u['kind']) for u in units).items())]


def _count_values(rows):
    return [{k: row[k] for k in ('team_id','kind','count')} for row in rows]


def _recent_damage(bundle, combat, *, at, team, window=3.0):
    result = dict(status='unavailable', window_seconds=window, components=[],
        unparsed_visible_records=None, attacker_attribution=None, attack_count=None,
        semantics='reported_health_loss_components_not_net_HP_loss_or_attack_count; overkill_possible')
    if combat is None:
        return result, []
    if (combat.get('schema') != 'lane-combat-evidence/v1' or combat.get('version') != VERSION
            or combat.get('source', {}).get('sha256') != bundle['source']['sha256']):
        raise ValueError('Lane combat source/build/schema mismatch')
    timeline = []
    for row in bundle['identities']:
        if row['source']['stream']==1 and row['time_seconds']<=at:
            timeline.append((key(row),0,row))
    for row in bundle['events']:
        if (row['source']['stream']==1 and row['time_seconds']<=at
                and (row['kind'].startswith('visibility_') or row['kind']=='unknown_barrier')):
            timeline.append((key(row),1,row))
    for typ, rows in ((2,combat['events']),(3,combat.get('rejected',[]))):
        for row in rows:
            if row['source']['stream']==1 and at-window <= row['time_seconds'] <= at:
                timeline.append((key(row),typ,row))
    identities, visible, sources = {}, {}, []
    result.update(status='available_observer_filtered', unparsed_visible_records=0)
    for _,typ,row in sorted(timeline,key=lambda x:(x[0],x[1])):
        actor=row['entity_id']
        if typ==0:
            identities.setdefault(actor,row['identity'])
        elif typ==1:
            if actor in identities and row.get('observer_team_id') in (None,team):
                visible[actor]=row.get('visible')
        elif actor in identities and visible.get(actor) is True:
            if typ==3:
                result['unparsed_visible_records']+=1
                sources.append(row)
                continue
            if (row.get('kind')!='reported_health_loss_component'
                    or row.get('reported_entity_id')!=actor
                    or not finite(row.get('value')) or row['value']<0):
                raise ValueError('Invalid named lane health-loss component')
            identity=identities[actor]
            result['components'].append(dict(entity_id=actor,team_id=identity['team_id'],
                kind='super_candidate' if identity['kind']=='super' else identity['kind'],
                at_seconds=row['time_seconds'],value=round(row['value'],3),unit='health_points'))
            sources.append(row)
    return result,sources


def build_lane_view(bundle, *, at, team, source_sha256, towers=None, combat=None):
    """Build only the observer-qualified subset; never authorize the raw bundle."""
    if bundle.get('source', {}).get('sha256') != source_sha256:
        raise ValueError('Lane replay source mismatch')
    state = reconstruct_lane_current_state(bundle, at, team)
    if state['mode'] != 'observer_current_replication':
        raise ValueError('Lane model adapter requires an observer')
    anchors, binding = _anchors(towers, at, source_sha256)
    damage,damage_sources = _recent_damage(bundle,combat,at=at,team=team)
    base_centers = {}
    for side in (100,200):
        points = [a['position_xz'] for a in anchors if a['team_id']==side and 'Nexus' in a['role']]
        if points:
            base_centers[str(side)] = [round(sum(p[axis] for p in points)/len(points), 2) for axis in range(2)]
    tracking_profile = json.loads(PROFILE.read_text(encoding='utf-8'))
    if tracking_profile['version'] != VERSION:
        raise ValueError('Unsupported lane tracking profile')
    errors = tracking_profile['evaluation']['checkpoint_comparison']['advance_along_path']
    quality = dict(checkpoint_samples=errors['count'], median_error_units=round(errors['median'], 2),
        p90_error_units=round(errors['p90'], 2), largest_checkpoint_error_units=round(errors['maximum'], 2),
        per_position_error_bound=None, independent_match_or_video_validation=False,
        sudden_motion_changes_not_predicted=True)
    live_paths = {}
    for row in bundle['events']:
        if row['source']['stream'] == 1 and row['time_seconds'] <= at and row['kind'] == 'path_command':
            live_paths.setdefault(row['entity_id'], []).append(row)
    by_lane, audit = {}, {}
    hidden_seen, dead_seen = 0, 0
    recent_zero=[]
    for entity in state['entities']:
        current = entity['current_state']
        if current['alive'] is None:
            hidden_seen += 1
            continue
        if current['alive'] is False:
            dead_seen += 1
            zero=entity['zero_health_sample']
            if zero is not None and at-3.0 <= zero['observed_at_seconds'] <= at:
                recent_zero.append(dict(entity_id=entity['entity_id'],team_id=entity['identity']['team_id'],
                    kind=entity['identity']['kind'],at_seconds=zero['observed_at_seconds']))
                audit[entity['entity_id']]=dict(zero_health=zero,identity=entity['identity_evidence'])
            continue
        # Current-state module has already enforced lifecycle and observer entry.
        transition = entity['visibility']['last_transition']
        candidates = [r for r in live_paths.get(entity['entity_id'], []) if key(r) >= source_key(transition)]
        path = max(candidates, key=key) if candidates else None
        health = current['health']
        hp, maximum = health.get('health'), health.get('max_health')
        unit = dict(entity_id=entity['entity_id'], team_id=entity['identity']['team_id'],
            kind=entity['identity']['kind'], health=None if hp is None else round(hp['value'], 3),
            max_health=None if maximum is None else round(maximum['value'], 3),
            health_updated_at_seconds=None if hp is None else hp['observed_at_seconds'],
            health_age_seconds=None if hp is None else round(at-hp['observed_at_seconds'], 3),
            health_semantics='retained_replication_value_with_unknown_delivery_delay',
            position=None if path is None else _position(path, at, binding))
        lane = entity['identity']['lane']
        by_lane.setdefault(lane, []).append(unit)
        audit[entity['entity_id']] = dict(identity=entity['identity_evidence'],
            visible=transition, health=hp, max_health=maximum, path=deepcopy(path),
            lifecycle=current)
    lanes = []
    for lane, units in sorted(by_lane.items()):
        groups = []
        for i, members in enumerate(_groups(units)):
            center = [round(sum(u['position']['relative_xz'][a] for u in members)/len(members), 2) for a in range(2)]
            world_center = None if binding is None else [round(center[a]+binding['origin_xz'][a], 2) for a in range(2)]
            nearest = None
            if anchors and world_center is not None:
                anchor = min(anchors, key=lambda a: math.dist(world_center, a['position_xz']))
                nearest = {k: anchor[k] for k in ('entity_id', 'team_id', 'name', 'role')}
                nearest.update(distance_units_estimate=round(math.dist(world_center, anchor['position_xz']), 1),
                    semantics='distance_to_static_map_anchor_not_tower_alive_or_in_range')
            teams = {u['team_id'] for u in members}
            groups.append(dict(group_id=f'{lane}:spatial:{i+1}', counts=_counts(members),
                center_relative_xz=center, center_world_xz_estimate=world_center,
                nearest_static_tower=nearest, both_teams_present=len(teams)>1,
                contact='opposing_units_nearby_not_proof_of_attacks' if len(teams)>1 else 'single_team_group',
                units=members))
        lanes.append(dict(lane=lane, known_visible_alive_count=len(units), counts=_counts(units),
            health_known_count=sum(u['health'] is not None for u in units),
            position_estimated_count=sum(u['position'] is not None for u in units),
            spatial_groups=groups,
            unlocated_units=[u for u in units if u['position'] is None],
            complete_lane_count=None, lane_priority=None))
    model = dict(at_seconds=at, observer_team_id=team,
        count_scope='explicitly_visible_named_lane_minions_with_live_lifecycle_evidence',
        known_visible_alive_count=sum(l['known_visible_alive_count'] for l in lanes),
        previously_seen_currently_unresolved_count=hidden_seen,
        observed_terminal_entities_count=dead_seen, lanes=lanes,
        recent_health_loss=damage, recent_zero_health_events=recent_zero,
        position_estimate_quality=quality,
        coordinate_basis=dict(relative_space='shared_decoded_path_xz_game_units',
            map_reference=None if binding is None else binding['map_reference'],
            world_transform_status='unavailable' if binding is None else binding['binding_status'],
            static_nexus_tower_centers_xz=base_centers,
            runtime_map_id_decoded=False),
        grouping_rule=dict(method='radius_connected_components', radius_units=GROUP_RADIUS,
            is_decoded_spawn_wave_id=False),
        limitations=['Counts exclude never-seen/hidden unknown minions; no whole-map total claimed',
            'Health is retained from delivered updates; exact server-time health and delivery delay unknown',
            'Positions are forward estimates; clamped endpoints do not prove arrival',
            'Spatial proximity does not prove combat, push direction, lane priority or safety',
            'Static tower anchors do not prove those towers still exist or are currently visible'])
    return dict(schema='lane-wave-view/v1', version=VERSION, model=model,
        model_input_eligible=True, audit=dict(source_sha256=source_sha256,
            units=audit, anchors=anchors, map_binding=binding, health_loss_components=damage_sources))


def model_view(view, *, at, team):
    """Validate the generated namespace before admitting it to a model frame."""
    if (view.get('schema') != 'lane-wave-view/v1' or view.get('version') != VERSION
            or view.get('model_input_eligible') is not True):
        raise ValueError('Unqualified lane view')
    model = view['model']
    if model['at_seconds'] != at or model['observer_team_id'] != team:
        raise ValueError('Lane view decision context mismatch')
    all_ids = set()
    total = 0
    for lane in model['lanes']:
        units = [u for g in lane['spatial_groups'] for u in g['units']]+lane['unlocated_units']
        if len(units) != lane['known_visible_alive_count'] or len({u['entity_id'] for u in units}) != len(units):
            raise ValueError('Inconsistent known lane count')
        if all_ids.intersection(u['entity_id'] for u in units):
            raise ValueError('Entity repeated across lanes')
        all_ids.update(u['entity_id'] for u in units)
        total += len(units)
        if (_count_values(lane['counts']) != _counts(units)
                or lane['health_known_count'] != sum(u['health'] is not None for u in units)
                or lane['position_estimated_count'] != sum(u['position'] is not None for u in units)):
            raise ValueError('Inconsistent lane field coverage/counts')
        if lane['complete_lane_count'] is not None or lane['lane_priority'] is not None:
            raise ValueError('Unsupported complete count or lane priority')
        for group in lane['spatial_groups']:
            if _count_values(group['counts']) != _counts(group['units']):
                raise ValueError('Inconsistent group counts')
        for unit in units:
            t = unit['health_updated_at_seconds']
            if t is not None and (not finite(t) or not 0 <= t <= at):
                raise ValueError('Future or invalid lane health')
            if any(unit[k] is not None and (not finite(unit[k]) or unit[k] < 0) for k in ('health','max_health')):
                raise ValueError('Invalid lane health value')
            if unit['position'] is not None:
                t = unit['position']['path_updated_at_seconds']
                if not finite(t) or not 0 <= t <= at:
                    raise ValueError('Future or invalid lane position')
                for name in ('relative_xz', 'world_xz', 'velocity_xz_estimate'):
                    point = unit['position'][name]
                    if point is not None and (not isinstance(point, (tuple,list)) or len(point)!=2 or not all(finite(n) for n in point)):
                        raise ValueError('Invalid lane position coordinate')
    if model['known_visible_alive_count'] != total:
        raise ValueError('Inconsistent total known lane count')
    for event in model['recent_health_loss']['components']+model['recent_zero_health_events']:
        if not finite(event['at_seconds']) or not max(0,at-3.0)<=event['at_seconds']<=at:
            raise ValueError('Future or out-of-window lane combat evidence')
        if 'value' in event and (not finite(event['value']) or event['value']<0):
            raise ValueError('Invalid lane health-loss component')
    # This is deterministic generated content; do not propagate a caller's raw
    # packet/audit namespace or extra top-level keys into the prompt.
    allowed = ('at_seconds', 'observer_team_id', 'count_scope', 'known_visible_alive_count',
               'previously_seen_currently_unresolved_count', 'observed_terminal_entities_count',
               'lanes', 'recent_health_loss', 'recent_zero_health_events', 'position_estimate_quality',
               'coordinate_basis', 'grouping_rule', 'limitations')
    result = {k: deepcopy(model[k]) for k in allowed}
    def select(row, keys):
        return {k: deepcopy(row[k]) for k in keys}
    def counts(rows):
        return [select(row, ('team_id','kind','count')) for row in rows]
    def unit(row):
        value = select(row, ('entity_id','team_id','kind','health','max_health',
            'health_updated_at_seconds','health_age_seconds','health_semantics'))
        value['position'] = None if row['position'] is None else select(row['position'],
            ('relative_xz','world_xz','motion','path_updated_at_seconds','path_age_seconds',
             'endpoint_clamped','velocity_xz_estimate','velocity_interval_seconds','semantics'))
        return value
    result['lanes'] = []
    for lane in model['lanes']:
        value = select(lane, ('lane','known_visible_alive_count','health_known_count',
            'position_estimated_count','complete_lane_count','lane_priority'))
        value['counts'] = counts(lane['counts'])
        value['unlocated_units'] = [unit(u) for u in lane['unlocated_units']]
        value['spatial_groups'] = []
        for group in lane['spatial_groups']:
            clean = select(group, ('group_id','center_relative_xz','center_world_xz_estimate',
                'both_teams_present','contact'))
            clean['counts'] = counts(group['counts'])
            clean['units'] = [unit(u) for u in group['units']]
            anchor = group['nearest_static_tower']
            clean['nearest_static_tower'] = None if anchor is None else select(anchor,
                ('entity_id','team_id','name','role','distance_units_estimate','semantics'))
            value['spatial_groups'].append(clean)
        result['lanes'].append(value)
    result['coordinate_basis'] = select(model['coordinate_basis'],
        ('relative_space','map_reference','world_transform_status','runtime_map_id_decoded'))
    result['coordinate_basis']['static_nexus_tower_centers_xz'] = {
        side: list(model['coordinate_basis']['static_nexus_tower_centers_xz'][side])
        for side in ('100','200') if side in model['coordinate_basis']['static_nexus_tower_centers_xz']}
    result['grouping_rule'] = select(model['grouping_rule'],
        ('method','radius_units','is_decoded_spawn_wave_id'))
    result['position_estimate_quality'] = select(model['position_estimate_quality'],
        ('checkpoint_samples','median_error_units','p90_error_units','largest_checkpoint_error_units',
         'per_position_error_bound','independent_match_or_video_validation','sudden_motion_changes_not_predicted'))
    result['recent_health_loss']=select(model['recent_health_loss'],
        ('status','window_seconds','unparsed_visible_records','attacker_attribution','attack_count','semantics'))
    result['recent_health_loss']['components']=[select(e,('entity_id','team_id','kind','at_seconds','value','unit'))
        for e in model['recent_health_loss']['components']]
    result['recent_zero_health_events']=[select(e,('entity_id','team_id','kind','at_seconds'))
        for e in model['recent_zero_health_events']]
    return result


def render_lane_view(view):
    model = model_view(view, at=view['model']['at_seconds'], team=view['model']['observer_team_id'])
    lines = ['## 当时可知兵线', '',
        f"截止 {model['at_seconds']:g} 秒，观察队伍 {model['observer_team_id']}。已知可见活兵 {model['known_visible_alive_count']} 个；不是全图总量。",
        '生命按收到的增量保持；位置按当前可见区间内路径前推，可能有同步延迟和突变。', '',
        '| 路线 / 空间兵团 | 已知兵种数量 | 位置参照 |', '| --- | --- | --- |']
    for lane in model['lanes']:
        for group in lane['spatial_groups']:
            count = '；'.join(f"{c['team_id']}队 {c['kind']}×{c['count']}" for c in group['counts'])
            anchor = group['nearest_static_tower']
            place = (f"距{anchor['team_id']}队 {anchor['role']} 静态塔位约{anchor['distance_units_estimate']:g}单位"
                     if anchor else '相对坐标'+str(group['center_relative_xz']))
            lines.append(f"| {lane['lane']} / {group['group_id']} | {count} | {place} |")
        if lane['unlocated_units']:
            lines.append(f"| {lane['lane']} / 位置缺失 | {len(lane['unlocated_units'])}个 | 没有本可见区间路径 |")
    lines += ['', '空间分组采用600单位连通规则，不是解出的出生波次；接近不等于攻击，静态塔位不证明塔还活着。', '']
    damage=model['recent_health_loss']
    if damage['status']=='unavailable':
        lines += ['未载入受伤分量；不能把缺失当作近3秒没有受伤。','']
    else:
        lines += [f"近3秒已知受伤分量 {len(damage['components'])} 条、零血事件 {len(model['recent_zero_health_events'])} 条；受伤分量可含过量伤害，来源与攻击次数未知。",'']
    return '\n'.join(lines)
