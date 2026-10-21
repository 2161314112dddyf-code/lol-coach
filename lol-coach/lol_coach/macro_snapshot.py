"""Bounded, evidence-linked team knowledge at t; no tactical oracle."""
import math

from .replay_vision import VERSION, OBSERVABLE_FIELDS, validate_cutoff

SCHEMA = 'macro-snapshot/v1'
PRIVATE_FIELDS = {'current_gold', 'total_gold', 'experience'}


def unknown(reason):
    return {'status': 'unknown', 'value': None, 'reason': reason}


def source_of(row):
    source = row.get('source', row.get('packet', {}))
    return {k: v for k, v in source.items() if k != 'payload_hex'}


def order(row):
    src = source_of(row)
    return (row['time_seconds'], src['chunk'],
            src.get('decompressed_offset', src.get('offset')))


def validate_inputs(ten, state, inventory, vision, at, team, player):
    expected = ['replay-ten/v1', 'replay-state/v1',
                'replay-inventory-operations/v1', 'replay-hero-visibility/v1']
    bundles = [ten, state, inventory, vision]
    if [b.get('schema') for b in bundles] != expected:
        raise ValueError('Expected full exports of the four supported schemas')
    if any(b.get('version') != VERSION for b in bundles):
        raise ValueError('Unsupported or mismatched build')
    digest = ten['replay_sha256']
    if not digest or any(b.get('source_sha256') != digest for b in bundles[1:]):
        raise ValueError('Mismatched replay hashes')
    end = ten['game_length_metadata_ms'] / 1000
    if any(b['game_length_seconds'] != end for b in (state, vision)):
        raise ValueError('Mismatched replay durations')
    if isinstance(at, bool):
        raise ValueError('Boolean cutoff')
    validate_cutoff(at, end)
    if team not in (100, 200):
        raise ValueError('Observer team must be 100 or 200')
    cutoff = inventory.get('cutoff_seconds')
    if cutoff is not None and (not math.isfinite(cutoff) or cutoff < at):
        raise ValueError('Inventory prefix does not cover query')
    actors = vision['actors']
    ids = [a['entity_id'] for a in actors]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate actors')
    owners = {o['entity_id']: o for o in ten['identity_directory']['owners']}
    participants = ten['categories']['participants']
    for actor in actors:
        entity = actor['entity_id']
        if entity not in owners or actor['champion'] != owners[entity]['champion']:
            raise ValueError('Conflicting identity directories')
        index = ten['entity_to_participant'].get(entity)
        if actor['team_id'] is not None:
            if index is None or participants[index]['team_id'] != actor['team_id']:
                raise ValueError('Unverified actor team')
    if player is not None and not any(a['entity_id'] == player and a['team_id'] == team for a in actors):
        raise ValueError('Player must be a verified member of observer team')
    return actors


def build_snapshot(ten, state, inventory, vision, *, at, team, player=None, window=30):
    """Merge only prefix events. Inputs are decoded evidence, never mutated.

    Team public observations are shared. Private economy/inventory operations
    require a selected self actor. Visibility is inferred, not UI certified.
    """
    actors = validate_inputs(ten, state, inventory, vision, at, team, player)
    if not math.isfinite(window) or window <= 0:
        raise ValueError('Recent event window must be positive and finite')
    evidence = {}
    evidence_ids = {}

    def ref(row, kind, field=None):
        key = (kind, row.get('entity_id'), order(row), field, row.get('record_id'))
        if key not in evidence_ids:
            name = f'e{len(evidence) + 1}'
            evidence_ids[key] = name
            value = dict(kind=kind, time_seconds=row['time_seconds'], source=source_of(row))
            if row.get('entity_id') is not None:
                value['entity_id'] = row['entity_id']
            if field is not None:
                value['field'] = field
                value['field_location'] = row.get('field_sources', {}).get(field)
            if row.get('record_id') is not None:
                value['record_id'] = row['record_id']
            evidence[name] = value
        return evidence_ids[key]

    def sample(value, row, kind, field=None, unit=None):
        return dict(value=value, observed_at_seconds=row['time_seconds'],
                    age_seconds=at-row['time_seconds'], unit=unit,
                    evidence_id=ref(row, kind, field))

    knowledge = {}
    for actor in actors:
        relation = 'unknown' if actor['team_id'] is None else ('ally' if actor['team_id'] == team else 'enemy')
        knowledge[actor['entity_id']] = dict(relation=relation, visible=None, transition=None,
            current={}, history={}, position=None, last_position=None, private={}, life=None)

    streams = [('vision', vision['events']), ('state', state['updates']),
               ('position', ten['categories']['movement']['events']),
               ('life', ten['categories']['lifecycle']['events'])]
    merged = [(order(row), i, kind, row) for i, (kind, rows) in enumerate(streams)
              for row in rows if row['time_seconds'] <= at]
    for _, _, kind, row in sorted(merged, key=lambda x: (x[0], x[1])):
        k = knowledge.get(row['entity_id'])
        if k is None:
            continue
        ally = k['relation'] == 'ally'
        if kind == 'vision':
            if ally or row['observer_team_id'] not in (None, team):
                continue
            if k['visible'] is not row['visible']:
                k['current'] = {}
                k['position'] = None
            k['visible'] = row['visible']
            k['transition'] = row
            continue
        # Unknown identity/team never silently becomes own-team knowledge.
        observable = ally or (k['relation'] == 'enemy' and k['visible'] is True)
        if kind == 'state':
            for field, value in row['values'].items():
                if observable and field in OBSERVABLE_FIELDS:
                    k['current'][field] = (value, row)
                    k['history'][field] = (value, row)
                if row['entity_id'] == player and field in PRIVATE_FIELDS:
                    k['private'][field] = (value, row)
        elif kind == 'position' and observable:
            points = row['relative_waypoints']
            if points:
                # Only the starting point is a position candidate, never endpoint.
                k['position'] = k['last_position'] = (points[0], row)
        elif kind == 'life' and ally:
            k['life'] = row

    def fields(raw):
        return {field: sample(value, row, 'state', field, state['units'].get(field))
                for field, (value, row) in sorted(raw.items())}

    def position(raw):
        if raw is None:
            return None
        value, row = raw
        return {**sample(value, row, 'movement'), 'interpretation': 'path_start_position_candidate',
                'coordinate_frame': 'decoded_relative_xy', 'current_exact_position': False}

    heroes = []
    for actor in actors:
        entity = actor['entity_id']
        k = knowledge[entity]
        available = k['relation'] == 'ally' or (k['relation'] == 'enemy' and k['visible'] is True)
        ops = []
        barriers = []
        if entity == player:
            for row in sorted(inventory['events'], key=order):
                if row['entity_id'] == entity and at-window <= row['time_seconds'] <= at:
                    allowed = {key: row[key] for key in ('kind', 'slot', 'other_slot', 'item_id', 'item_name') if key in row}
                    ops.append({**allowed, 'time_seconds': row['time_seconds'], 'evidence_id': ref(row, 'inventory_operation')})
            barriers = [row for row in inventory['state_barriers'] + inventory['unresolved']
                        if row['entity_id'] == entity and row['time_seconds'] <= at]
        barrier = max(barriers, key=order) if barriers else None
        inventory_view = dict(status='incomplete' if entity == player else 'unknown', current_slots=None,
            recent_self_operations=ops, latest_self_barrier=None if barrier is None else
            dict(time_seconds=barrier['time_seconds'], evidence_id=ref(barrier, 'inventory_barrier')),
            reason='Operation stream misses undo/consumption; others inventory observations not established')
        transition = k['transition']
        life = k['life']
        heroes.append(dict(**actor, relation=k['relation'],
            visibility=dict(value=True if k['relation'] == 'ally' else k['visible'],
                basis='team_shared_information' if k['relation'] == 'ally' else 'cross_checked_binary_inference',
                transition_seconds=None if transition is None else transition['time_seconds'],
                evidence_id=None if transition is None else ref(transition, 'visibility')),
            observed_now=fields(k['current']) if available else None,
            last_observed=fields(k['history']),
            position_candidate=position(k['position']) if available else None,
            last_observed_position=position(k['last_position']),
            private_economy=fields(k['private']) if entity == player else unknown('Only selected self can expose private economy'),
            inventory=inventory_view,
            last_allied_lifecycle_event=None if life is None else
                dict(kind=life['kind'], time_seconds=life['time_seconds'], evidence_id=ref(life, 'lifecycle')),
            spell_readiness=unknown('Cast, rank and cooldown timeline unresolved'),
            resource_type=unknown('Resource numeric fields decoded; type not established')))

    # Death/kill feed is assumed team-public. Do not expose assists or hidden respawns.
    recent_combat = []
    for row in sorted(ten['categories']['kills'], key=order):
        if at-window <= row['time_seconds'] <= at:
            recent_combat.append(dict(time_seconds=row['time_seconds'], victim_entity_id=row['victim_entity_id'],
                killer_entity_id=row['killer_entity_id'], evidence_id=ref(row, 'public_kill_feed')))
    allies = [a['entity_id'] for a in actors if a['team_id'] == team]
    enemies = [a['entity_id'] for a in actors if a['team_id'] is not None and a['team_id'] != team]
    return dict(schema=SCHEMA, version=VERSION, source_sha256=ten['replay_sha256'],
        context=dict(at_seconds=at, observer_team_id=team, player_entity_id=player,
            recent_window_seconds=window, perspective='team_shared_public_information_with_optional_self_private',
            map=unknown('Replay map/mode not independently established'),
            observation_policy='Samples retain age; current visibility is not exact continuous state or player attention'),
        summary=dict(ally_ids=allies, enemy_ids=enemies,
            visible_enemy_ids=[e for e in enemies if knowledge[e]['visible'] is True],
            hidden_enemy_ids=[e for e in enemies if knowledge[e]['visible'] is False],
            unknown_visibility_enemy_ids=[e for e in enemies if knowledge[e]['visible'] is None],
            unknown_team_ids=[a['entity_id'] for a in actors if a['team_id'] is None]),
        heroes=heroes, recent_public_combat=recent_combat,
        composition=dict(ally_ids=allies, enemy_ids=enemies,
            interactions=[dict(actor_id=a['entity_id'],
                allied_ids=[b['entity_id'] for b in actors if b['entity_id'] != a['entity_id'] and
                            a['team_id'] is not None and b['team_id'] == a['team_id']],
                opponent_ids=[b['entity_id'] for b in actors if a['team_id'] is not None and
                              b['team_id'] is not None and b['team_id'] != a['team_id']],
                grounded_capabilities=unknown('No reviewed mechanics/matchup evidence joined for this actor')) for a in actors],
            required_axes=['engage', 'disengage', 'follow_up', 'peel', 'wave_clear', 'sustain', 'range', 'objective_damage']),
        world={key: unknown(reason) for key, reason in {
            'navigation': 'Map identity must match navigation asset before routes/ETA',
            'objectives': 'Structure/camp state and respawn timers not decoded',
            'waves': 'Minion positions, counts and lane pressure not decoded',
            'area_vision': 'Hero visibility is not ward/terrain vision coverage',
            'action_durations': 'No condition-matched measured duration joined',
            'human_experience': 'No version/context-matched human guide evidence joined'}.items()},
        analysis_contract=dict(status='partial_input', complete_macro_analysis_ready=False,
            usable=['both_lineups', 'visibility_and_last_observations', 'sample_ages', 'recent_public_combat', 'optional_self_economy'],
            output_requirements=['facts_with_evidence_ids', 'hypotheses_separate_from_facts', 'compare_actions', 'conditions_to_change_plan'],
            action_comparison_fields=['action', 'objective', 'allied_follow_up', 'enemy_response', 'required_facts',
                'travel_and_execution_time', 'expected_end_state', 'benefit', 'risk', 'opportunity_cost',
                'uncertainties', 'evidence_ids', 'abort_or_replan_conditions'],
            prohibitions=['no_hidden_state_as_current', 'no_plan_endpoint_as_arrival', 'no_unknown_as_zero',
                'no_final_scoreboard_backfill', 'no_model_memory_as_verified_mechanics', 'no_visibility_as_proof_of_attention']),
        evidence=evidence,
        provenance=dict(identity='Hash-bound existing actor mapping; only champion/team whitelisted from metadata',
            profiles={kind: bundle.get('profile_sha256') for kind, bundle in
                      [('state', state), ('inventory', inventory), ('vision', vision)]},
            packet_evidence='Existing bounded exact-build decoders; no new UI semantic validation',
            public_combat_assumption='Kill/death feed shared across both teams; assists omitted'))


def render_markdown(snapshot):
    c, s = snapshot['context'], snapshot['summary']
    lines = [f"# {c['at_seconds']:g} 秒 / 队伍 {c['observer_team_id']} 局势快照", '',
        '这是带证据的部分分析输入；采样不等于连续实时状态，隐藏后的值只在历史栏保留。', '',
        f"敌方：可见 {len(s['visible_enemy_ids'])}，隐藏 {len(s['hidden_enemy_ids'])}，未知 {len(s['unknown_visibility_enemy_ids'])}。", '',
        '| 英雄 / 阵营 | 可见 | 生命采样（秒前） | 位置候选（秒前） |', '| --- | --- | --- | --- |']
    for h in snapshot['heroes']:
        health = (h['observed_now'] or {}).get('health')
        hp = '未知' if health is None else f"{health['value']:.1f}（{health['age_seconds']:.2f}）"
        p = h['position_candidate']
        pos = '未知' if p is None else f"{p['value']}（{p['age_seconds']:.2f}）"
        visible = {True: '可见/队伍共享', False: '隐藏', None: '未知'}[h['visibility']['value']]
        lines.append(f"| {h['champion'] or h['entity_id']} / {h['team_id']} | {visible} | {hp} | {pos} |")
    lines += ['', '## 分析时必须结合的内容', '',
        'JSON 的 composition 为每个英雄列出队友与对手；分析契约要求比较行动收益、风险、机会成本、完成后状态和改变计划的条件。', '',
        '## 当前缺口', '',
        '地图身份、路线与抵达耗时、兵线/目标状态、区域视野、当前技能冷却、完整背包、匹配双方阵容的机制和真人经验仍未知。不会自动把模型记忆填进这些字段。', '',
        '每个动态采样含 observed_at_seconds / age_seconds / evidence_id；evidence 可回到源包位置。金币只开放可选本人，装备只保留本人的近期操作，不声称完整背包。', '']
    return '\n'.join(lines)
