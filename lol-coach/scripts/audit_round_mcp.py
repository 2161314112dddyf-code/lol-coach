"""Exercise all ten frozen player perspectives through real, independent stdio MCP sessions."""
import argparse
import asyncio
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from statistics import median
from time import perf_counter

from lol_coach.file_model_bridge import atomic_json
from lol_coach.round_chain import _check_bundle, _source
from lol_coach.round_tools import round_call
from scripts.round_review_mcp import query, round_client


def identity(bundle, path, raw, match_id):
    frame = _check_bundle(bundle)
    d = frame['decision']
    player = d['player_entity_id']
    champion, = [h['champion'] for h in frame['lineup'] if h['entity_id'] == player and h['relation'] == 'ally']
    origin = frame['task']['review_origin']
    replay_hash = _source(bundle)
    if (champion != path.parent.parent.name or d['at_seconds'] != int(path.parent.name)
            or str(origin['match_id']) != match_id or origin['replay_sha256'] != replay_hash):
        raise ValueError(f'{path}: unexpected source, player or time')
    role, = [r for r, actor in frame['task']['external_lane_roles']['ally'].items() if actor == player]
    return dict(match_id=match_id, source_replay_sha256=replay_hash, champion=champion, player_entity_id=player,
                observer_team_id=d['observer_team_id'], at_seconds=d['at_seconds'], frame_id=frame['frame_id'],
                bundle_sha256=sha256(raw).hexdigest(), lane=frame['task']['round_comparison']['lane'],
                assigned_role=role, perspective=origin['perspective'], build=d['build'])


def assert_response_scope(result, identity):
    for field in ('frame_id', 'observer_team_id', 'at_seconds'):
        if result[field] != identity[field]:
            raise ValueError(f'MCP returned another {field}')
    if result.get('actor_id', result.get('player_entity_id')) != identity['player_entity_id']:
        raise ValueError('MCP returned a different player')


def frame_evidence(frame):
    roles = {actor: lane for side in frame['task']['external_lane_roles'].values() for lane, actor in side.items()}
    roster = [dict(entity_id=h['entity_id'], champion=h['champion'], relation=h['relation'],
                   assigned_role=roles.get(h['entity_id'])) for h in frame['lineup']]
    actors = {h['entity_id']: {} for h in roster}
    lanes = {}
    observed_fields = {'identity', 'allied_path_start_sample', 'health', 'max_health', 'level', 'resource',
                       'max_resource', 'current_gold', 'total_gold', 'experience'}
    for fid, fact in frame['facts'].items():
        entity, field = fact['entity_id'], fact['field']
        if entity in actors and field in observed_fields:
            actors[entity][fid] = fact
        elif field == 'lane_current_units_and_groups':
            lanes[fid] = {**fact, 'value': {k: v for k, v in fact['value'].items()
                          if k in ('lane', 'observer_team_id', 'count_scope', 'counts', 'wave_spawn_clock')}}
    return dict(roster=roster, actor_facts=actors, lane_facts=lanes)


def coverage(frame, who, responses):
    options = responses['compare_round_options']
    plan = responses['review_round_plan']
    sightings = responses['enemy_sightings']
    external = plan.get('external_data') or {}
    roles = frame['task']['external_lane_roles']
    role = who['assigned_role']
    roster = {h['entity_id']: h['champion'] for h in frame['lineup']}
    relevant = {'self': who['champion'], 'lane_opponent': roster.get(roles['enemy'].get(role))}
    if role in ('UTILITY', 'BOTTOM'):
        partner = 'BOTTOM' if role == 'UTILITY' else 'UTILITY'
        relevant.update(lane_partner=roster.get(roles['ally'].get(partner)),
                        enemy_lane_partner=roster.get(roles['enemy'].get(partner)))
    static = {}
    for relation, champion in relevant.items():
        entry = external.get('champions', {}).get(champion, {})
        static[relation] = dict(champion=champion, slots=list(entry.get('abilities', {})),
                                version=entry.get('static_version'))
    own = {fid: fact['field'] for fid, fact in frame['facts'].items() if fact['entity_id'] == who['player_entity_id']}
    return dict(
        action_windows={r['action']: {k: r[k] for k in ('depart_at', 'arrive_at', 'finish_target_at', 'return_to_lane_at')}
                        for r in options['options']},
        exact_minions_forgone=options['exact_minions_forgone'],
        enemy_lane_coverage=(options['lane_observation'] or {}).get('enemy_minions'),
        additional_objective_contribution=options['additional_objective_contribution'],
        scope_of_vision=sightings['visibility_scope'], attention=sightings['player_attention'],
        visible_enemies=[h['champion'] for h in sightings['opponents'] if h['visible'] is True],
        unseen_enemies=[h['champion'] for h in sightings['opponents'] if h['visible'] is False],
        own_fact_ids=own, current_cooldowns=frame.get('unknowns', {}).get('current_cooldowns'),
        patch_references=static, population_statistics=external.get('availability'),
        support_lane_branches='support_lane_opportunity' in plan,
        engagement_status=plan['engagement'].get('missing_inputs'), snapshot_id=external.get('snapshot_id'))


async def probe(path, out, match_id):
    raw = path.read_bytes()
    bundle = json.loads(raw)
    frame = bundle['frame']
    who = identity(bundle, path, raw, match_id)
    calls, responses = [], {}
    started = perf_counter()
    async with round_client(path, who['bundle_sha256']) as (client, protocol):
        setup_ms = round((perf_counter() - started) * 1000, 2)
        async def read(name, args, reason):
            begin = perf_counter()
            result = await query(client, name, args)
            latency = round((perf_counter() - begin) * 1000, 2)
            if round_call(bundle, name, args) != result:
                raise ValueError(f'{path}: MCP and direct {name} differ')
            if name != 'get_reference':
                assert_response_scope(result, who)
            calls.append(dict(name=name, arguments=args, purpose=reason, mcp_ms=latency, direct_equal=True, result=result))
            responses[name] = result
            return result

        default = frame['task']['round_comparison']['help_seconds']
        await read('compare_round_options', {}, 'compare_wave_departure_and_objective_cost')
        await read('compare_help_duration', {'help_seconds': 0 if default else 5}, 'change_only_help_duration')
        plan = await read('review_round_plan', {}, 'inspect_engagement_opportunity_and_options_for_this_player')
        vision = await read('enemy_sightings', {}, 'separate_visible_opponents_from_last_evidence')
        opponents = {h['entity_id'] for h in frame['lineup'] if h['relation'] == 'enemy'}
        if ({h['entity_id'] for h in vision['opponents']} != opponents or len(vision['opponents']) != len(opponents)
                or vision['visibility_scope'] != 'shared_team_vision' or vision['player_attention'] != 'unknown'):
            raise ValueError(f'{path}: unexpected sighting or individual-attention scope')
        if ref := frame['task'].get('external_data_reference'):
            external = await read('get_reference', {'reference_id': ref}, 'verify_patch_mechanics_for_actor_and_lane_opponents')
            if external != plan['external_data']:
                raise ValueError(f'{path}: plan and frozen patch reference differ')
            hero_id = external['champions'].get(who['champion'], {}).get('champion_id')
            for table in external.get('cn_lane_profiles', []):
                if table.get('side') == 'ally' and table.get('champion_id') == hero_id and table.get('reference_id'):
                    await read('get_reference', {'reference_id': table['reference_id']}, 'read_current_actor_pregame_' + table['table'])
        rejected = []
        for name, args in [('enemy_sightings', {'observer_team_id': 300 - who['observer_team_id']}),
                           ('compare_round_options', {'at_seconds': who['at_seconds'] + 1}),
                           ('review_round_plan', {'player_entity_id': next(iter(sorted(opponents)))})]:
            reply = await client.call_tool(name, args)
            if not reply.isError:
                raise ValueError(f'{path}: accepted scope override {args}')
            rejected.append(dict(name=name, arguments=args, rejected=True))
    result = dict(schema='ten-pov-mcp-audit/v1', identity=who, protocol=protocol,
                  setup_ms=setup_ms, session_ms=round((perf_counter()-started)*1000, 2), calls=calls,
                  scope_rejections=rejected, coverage=coverage(frame, who, responses), frame_evidence=frame_evidence(frame))
    location = out / who['champion'] / (path.parent.name + '.json')
    location.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(location, result)
    return result


async def run(args):
    if len(set(args.seconds)) != len(args.seconds) or not 1 <= args.jobs <= 10 or args.wait_seconds < 0:
        raise ValueError('distinct timestamps and 1..10 concurrent sessions required')
    root = args.root.resolve()
    out = args.output.resolve() if args.output else root / 'tools'
    source = root / 'frames'
    if out.exists():
        raise ValueError(f'choose a new output folder using --output if {out} already exists')
    gate = asyncio.Semaphore(args.jobs)
    async def worker(path):
        async with gate:
            return await probe(path, out, args.match_id)
    scopes, rows = [], []
    for t in sorted(args.seconds):
        deadline = perf_counter() + args.wait_seconds
        paths = sorted(source.glob(f'*/{t}/bundle.json'))
        while len(paths) < 10 and perf_counter() < deadline:
            await asyncio.sleep(2)
            paths = sorted(source.glob(f'*/{t}/bundle.json'))
        if len(paths) != 10:
            raise ValueError(f'{t}: found {len(paths)} frozen bundles, need ten')
        at = []
        for path in paths:
            raw = path.read_bytes()
            at.append(identity(json.loads(raw), path, raw, args.match_id))
        role_scope = {(s['observer_team_id'], s['assigned_role']) for s in at}
        if (len({s['player_entity_id'] for s in at}) != 10 or len(role_scope) != 10
                or Counter(s['observer_team_id'] for s in at) != {100: 5, 200: 5}):
            raise ValueError(f'{t}: incomplete or repeated perspectives')
        scopes.extend(at)
        players = {(s['observer_team_id'], s['player_entity_id'], s['champion'], s['assigned_role']) for s in scopes}
        if len(players) != 10 or len({s['source_replay_sha256'] for s in scopes}) != 1:
            raise ValueError('all timestamps must share one roster and source')
        rows.extend(await asyncio.gather(*(worker(p) for p in paths)))
        print(f'{t}s: all ten player evidence files published', flush=True)
    timings = {}
    for row in rows:
        for call in row['calls']:
            timings.setdefault(call['name'], []).append(call['mcp_ms'])
    summary = dict(schema='ten-pov-mcp-audit-summary/v1', match_id=args.match_id,
                   source_replay_sha256=scopes[0]['source_replay_sha256'], timestamps=args.seconds,
                   players=len(players), concurrency=args.jobs, sessions=len(rows),
                   direct_equal_calls=sum(len(v) for v in timings.values()),
                   rejected_scope_overrides=sum(len(r['scope_rejections']) for r in rows),
                   calls={k: dict(count=len(v), median_ms=round(median(v), 2), max_ms=max(v)) for k, v in timings.items()},
                   sessions_with_any_arrival=sum(any(o['arrive_at'] is not None for o in r['coverage']['action_windows'].values()) for r in rows),
                   sessions_with_exact_minion_cost=sum(r['coverage']['exact_minions_forgone'] is not None for r in rows),
                   sessions_with_frozen_own_skill_reference=sum(bool(r['coverage']['patch_references']['self']['slots']) for r in rows))
    atomic_json(out / 'summary.json', summary)
    print(json.dumps(summary, ensure_ascii=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True, help='Directory containing frames/Champion/seconds/bundle.json')
    parser.add_argument('--match-id', required=True, help='Verified numeric match ID in review_origin')
    parser.add_argument('--seconds', type=int, nargs='+', default=[300, 730, 740, 755, 1200, 1560])
    parser.add_argument('--output', type=Path, help='New evidence directory (default: ROOT/tools)')
    parser.add_argument('--jobs', type=int, default=3)
    parser.add_argument('--wait-seconds', type=int, default=0, help='Wait this long for each set of ten input frames')
    args = parser.parse_args()
    asyncio.run(run(args))
