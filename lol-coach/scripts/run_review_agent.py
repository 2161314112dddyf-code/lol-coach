"""Run a team-scoped round through MCP and save evidence or a checked model decision."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

from lol_coach.combat_inputs import attach_combat_inputs
from lol_coach.combat_catalog import preload_combat
from lol_coach.replay_runes import attach_player_runes, read_replay_rune_pages
from lol_coach.decision_contract import MACRO_INTENTS, MACRO_TRANSITIONS, ROAM_DESTINATIONS, render_decision, review_scope
from lol_coach.file_model_bridge import atomic_json, file_generate, file_sha256, new_directory
from lol_coach.reasoning_frame import canonical
from lol_coach.reasoning_runner import run_reasoning
from lol_coach.review_data_store import DEFAULT_ROOT
from lol_coach.review_external_context import bind_session_external_data
from lol_coach.review_subject import bottom_lane_actors, load_review_subject, roam_actors, validate_review_subject
from lol_coach.round_chain import _check_bundle, _source, attach_previous_plan
from lol_coach.round_lane_evidence import attach_round_lanes
from lol_coach.round_camps import attach_personal_camps
from lol_coach.round_options import RESOURCE_ORIGINS
from lol_coach.round_tools import bind_round, round_call
from lol_coach.review_abilities import session_damage_profiles
from scripts.reasoning import read_bundle, read_json


def ollama_generator(model, port, usage, directory, max_calls):
    from lol_coach.round_model_format import expand_round_response, prepare_round_request
    url = f'http://127.0.0.1:{port}/api/chat'
    def generate(request):
        messages, wire_schema = prepare_round_request(request, remaining_calls=max_calls-len(usage))
        body = dict(model=model, stream=False, format=wire_schema, messages=messages,
                    options=dict(temperature=0, seed=17, num_ctx=32768, num_predict=4096))
        req = urllib.request.Request(url, data=canonical(body).encode(),
                                     headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req, timeout=240) as res:
            reply = json.load(res)
        usage.append({key:reply.get(key) for key in
                      ('model','done_reason','prompt_eval_count','eval_count','total_duration')})
        atomic_json(directory/f'provider-{len(usage):02}.json', reply)
        return expand_round_response(request, json.loads(reply['message']['content']))
    return generate


def scoped_sequence(paths):
    scope = None
    for path in paths:
        bundle = read_bundle(path)
        frame = _check_bundle(bundle)
        d = frame['decision']
        binding = (_source(bundle), d['build'], d['observer_team_id'], d['player_entity_id'])
        if scope is not None and (binding != scope or d['at_seconds'] <= last_at):
            raise ValueError('sequence_requires_same_replay_team_player_and_increasing_time')
        scope, last_at = binding, d['at_seconds']
        yield bundle


def match_sequence_paths(path):
    sequence = read_json(path)
    paths = []
    for row in sequence['selections']:
        name = row['bundle']
        if not isinstance(name, str) or Path(name).name != name or not name.endswith('.json'):
            raise ValueError('invalid_match_sequence_filename')
        bundle_path = path.parent / name
        bundle = read_bundle(bundle_path)
        frame = bundle['frame']
        players = [hero['champion'] for hero in frame['lineup']
                   if hero['entity_id'] == frame['decision']['player_entity_id']]
        if (_source(bundle) != sequence['source_sha256'] or frame['frame_id'] != row['frame_id']
                or frame['decision']['at_seconds'] != row['at']
                or frame['decision']['observer_team_id'] != sequence['team']
                or players != [sequence['champion']]):
            raise ValueError('match_sequence_scope_mismatch')
        paths.append(bundle_path)
    if not paths:
        raise ValueError('empty_match_sequence')
    return paths


def bind_session_subject(args, inputs):
    """Resolve the requested match and reader before calling a model or opening an output directory."""
    replay_path = args.subject_replay or args.lane_replay
    if args.download_log and not args.game_log:
        raise ValueError('下载记录需要与同局的 --game-log 一起核对')
    if args.perspective == 'comparison' and not args.game_log:
        if replay_path and file_sha256(replay_path) != _source(inputs[0]):
            raise ValueError('对照回放与冻结帧的来源不一致')
        return None
    if not replay_path or not args.game_log:
        raise ValueError('本人复盘需要目标 ROFL 和同局开局日志（--subject-replay 与 --game-log）。队友或研究样例请显式使用 --perspective comparison。')
    subject = load_review_subject(replay_path, args.game_log, args.download_log)
    for bundle in inputs:
        if args.perspective == 'comparison':
            if _source(bundle) != subject['replay_sha256']:
                raise ValueError('对照帧与选定回放不符')
            continue
        validate_review_subject(subject, bundle)
        training = bundle['frame']['decision'].get('map_mode') == 'practice_tool'
        if args.perspective == 'personal' and (training or subject['roster_count'] == 1):
            raise ValueError('此帧来自训练或单人样本。复盘本人的训练请使用 --perspective practice。')
        if args.perspective == 'practice' and not training:
            raise ValueError('该冻结帧没有确认训练模式')
    return subject


def render_evidence(report, player):
    comp, plan = report['compare_round_options'], report['review_round_plan']
    d = comp['at_seconds']
    def window(pair):
        if pair is None:
            return '未知'
        return f'{pair[0]:g}' if pair[0] == pair[1] else f'{pair[0]:g}～{pair[1]:g}'
    jungle = comp['lane'] == 'jungle'
    return_label = '返回营地' if jungle else '返回兵线'
    return_key = 'return_to_camp_at' if jungle else 'return_to_lane_at'
    lines = [f"# {int(d)//60:02}:{int(d)%60:02} · 你的回合（{player['champion'] or player['entity_id']}）",'',
             f"观察方 {comp['observer_team_id']}，出发侧 {comp['lane']}。以下比较去 {comp['target']} 的三种走法，时间采用游戏秒数。",'',
             f'| 方案 | 出发 | 抵达目标 | 完成目标 | {return_label} |','| --- | --- | --- | --- | --- |']
    names_by_action = {'leave_now':'立即走','help_then_leave':f"协助 {comp['proposed_help_seconds']:g} 秒后走",
                       'clear_then_leave':'刷完当前营地再走' if jungle else '接完线再走'}
    for row in comp['options']:
        cells = [names_by_action[row['action']], *(window(row[key]) for key in ('depart_at','arrive_at','finish_target_at',return_key))]
        lines.append('| '+' | '.join(cells)+' |')
    if jungle:
        observation = comp['jungle_observation']
        lines.append('')
        for entry in observation['last_personal_observations']:
            label = {'blue':'蓝 buff', 'gromp':'魔沼蛙'}.get(entry['camp'],entry['camp'])
            if entry['state'] == 'cleared':
                lo, hi = entry['observed_clear_seconds']
                lines.append(f"你在 {entry['reward_time_seconds']:.2f} 秒收掉{label}，这次清理耗时 {lo:.2f}～{hi:.2f} 秒，获得 {entry['reward_gold']} 金币。")
            else:
                hp = f"，野怪剩 {entry['monster_hp']}/{entry['full_hp']} 血" if 'monster_hp' in entry else ''
                lines.append(f"在 {entry['sampled_at']:g} 秒的画面中你正在打{label}{hp}。")
        nearby = observation['camps_by_distance_from_sample']
        if nearby:
            closest = nearby[0]
            lines.extend(['',f"距你 {observation['sampled_at']:.1f} 秒的位置样本最近的营地标记是 "
                             f"{closest['locator']}，相距 {closest['distance_world']:g} 地图单位。"])
        if observation['current_camp']:
            pace = observation['constant_damage_rate_scenario']
            if pace:
                lines.append(f"按过去 {pace['elapsed_seconds']:g} 秒的平均掉血速度持续输出，再打约 "
                             f"{pace['seconds_if_rate_held']:g} 秒。下一轮技能、惩戒或拉脱会改变这个估计。")
            lines.append('现在转身会中断这组野。比较清完再走和立刻接应，还需要看下一轮伤害和队友能等多久。')
        else:
            lines.append('选择刷完再走，需要先确认有可刷营地、剩余清理时间，以及离开后的接应窗口。')
    wave = comp['lane_observation']
    if wave:
        names = {'melee':'近战','ranged':'远程','siege':'炮车','unknown':'兵种未明'}
        observed = '、'.join(f"{c['team_id']}方{names.get(c['kind'], c['kind'])}兵 {c['count']}" for c in wave['counts'])
        lines += ['', '这条线上登记的小兵为 '+(observed or '本查询无记录')+'。证据 '+wave['fact_id']+'。']
        enemy = wave['enemy_minions']
        if enemy['status'] == 'outside_source_coverage':
            lines.append('此来源只登记己方兵。玩家当时能否看见敌兵、能补几个仍未知。')
        elif enemy['observed_count'] is not None:
            lines.append(f"本次样本登记敌方兵 {enemy['observed_count']} 个。线上敌兵总数未知。")
        else:
            lines.append('此来源的敌兵覆盖范围未知。')
        samples = wave.get('position_samples')
        if samples is not None:
            lines.append(f"己方兵位置采样：最近一秒 {samples['recent_count']} 个，更早 {samples['older_count']} 个，"
                         f"尚无位置 {samples['unsampled_count']} 个。")
        cohorts = wave.get('allied_birth_cohorts')
        if cohorts and cohorts['cohorts']:
            lines.append('按己方出生批次拆开看：')
            for group in cohorts['cohorts']:
                sec = int(group['first_melee_born_at'])
                lines.append(f"- {sec//60:02}:{sec%60:02} 起出生，仍登记 {group['registered']} 只，"
                             f"其中炮车 {group['registered_siege']} 只。")
            if cohorts['unassigned_count']:
                lines.append(f"另有 {cohorts['unassigned_count']} 只无法归入已知批次。")
        clock = wave.get('wave_spawn_clock') or {}
        if clock.get('next_birth_window'):
            lines += ['', '按此前出兵节奏，下一波己方小兵预计从基地出生的游戏秒为 '+window(clock['next_birth_window'])+'。到塔时间仍须另算。']
    lines += ['', f"上一张卡中各走法的复查状态为 {plan['status']}。"]
    for trigger in plan['triggers']:
        affected = '、'.join(names_by_action.get(option, option) for option in trigger['option_ids']) if trigger['option_ids'] else '全局提醒'
        lines.append(f"- {trigger['entity_id']} · {trigger['kind']} · {affected} · {trigger['current_fact_id']}")
    lines += ['', '抵达、能输出和能安全撤出分别需要证据。' +
              ('营地观测与时间依据' if jungle else '兵损与队友意图') + '见 evidence.json 的对应字段。']
    external = plan.get('external_data')
    if external:
        lines += ['', f"本帧附有版本 {external['patch']} 的外部资料。快照编号为 {external['snapshot_id']}。",
                  '资料内容、来源和可用范围见 evidence.json 的 review_round_plan.external_data。']
    return '\n'.join(lines)+'\n'


def render_map_review(steps, *, end_seconds=None):
    """Keep sampled decision times and the model's boundary judgments distinct."""
    name = steps[0]['champion'] or steps[0]['player_entity_id']
    scope = steps[0].get('review_scope') or '回放 SHA-256 ' + steps[0]['source_sha256']
    lines = [f'# {name}的地图回合', '', scope, '',
             '时间为复盘暂停点。每项记录所选玩家当时可以怎样选。']
    for index, step in enumerate(steps, 1):
        seconds = int(step['at_seconds'])
        when = f'{seconds//60:02}:{seconds%60:02}'
        entry = step.get('macro_round')
        if entry is None:
            lines.extend(['', f'**{when}**　本帧未生成通过校验的判断。'])
            continue
        lines.extend(['', f"**{when}　{MACRO_TRANSITIONS[entry['transition']]} · {MACRO_INTENTS[entry['intent']]}**",
                      '', entry['map_goal'], '', entry['enabling_condition']])
        if choice := step.get('player_choice'):
            lines.extend(['', '**你现在做什么**　' + choice['first_step']])
            if choice['costs']:
                lines.extend(['', '**要付的代价**　' + '；'.join(choice['costs'])])
            lines.extend(['', '**何时改选**　' + '；'.join(choice['switch_conditions'])])
        lane = step.get('lane_plan')
        if lane:
            if choice := lane.get('destination_choice'):
                lines.extend(['', f"**首选{ROAM_DESTINATIONS[choice['preferred']]}**　{choice['why']}",
                              '', f"**改选{ROAM_DESTINATIONS[choice['alternative']]}的条件**　{choice['switch_if']}"])
            lines.extend(['', lane['pressure'], '', '对方给机会时，' + lane['if_open'],
                          '', '对方不给机会时，' + lane['if_denied'],
                          '', lane['roam']['wave_condition'],
                          '', '**短走河道**　' + lane['roam']['short_play'],
                          '', '**支援中野**　' + lane['roam']['committed_play']])
        lines.extend(['', '对方可能的回应　' + entry['opponent_reply'],
                      '', f'[查看本人第一步、代价和改选条件]({index:02}/answer.md)'])
    if end_seconds is not None and 0 <= end_seconds - steps[-1]['at_seconds'] < 1:
        remaining = end_seconds - steps[-1]['at_seconds']
        lines.extend(['', f'赛后核对：最后一次暂停距本局记录结束约 {remaining:.1f} 秒。'
                      '超过这段时间的操作只可作为当时的建议，执行结果无法再观察。'])
    return '\n'.join(lines)+'\n'


async def run(args):
    if not args.baseline:
        from scripts.round_review_mcp import query, round_client
    if (args.previous_bundle is None) != (args.previous_answer is None):
        raise ValueError('supply_both_previous_bundle_and_previous_answer')
    if not 1 <= args.max_calls <= 20 or not 1 <= args.port <= 65535:
        raise ValueError('invalid_model_budget_or_loopback_port')
    if args.baseline and (args.backend=='probe' or args.catalog_history):
        raise ValueError('baseline_requires_model_and_full_frame')
    previous = read_bundle(args.previous_bundle) if args.previous_bundle else None
    answer = read_json(args.previous_answer) if args.previous_answer else None
    inputs = list(scoped_sequence(args.bundle))
    subject = bind_session_subject(args, inputs + ([previous] if previous is not None else []))
    origin = dict(perspective=args.perspective, replay_sha256=_source(inputs[0]),
                  match_id=subject['match_id'] if subject else None)
    if previous is not None and args.perspective != 'comparison' and previous['frame']['task'].get('review_origin') != origin:
        raise ValueError('旧建议未绑定本次个人复盘。请从第一份原始冻结帧重新生成。')
    raw = args.lane_replay.read_bytes() if args.lane_replay else None
    if raw is not None and hashlib.sha256(raw).hexdigest() != _source(inputs[0]):
        raise ValueError('round_lane_source_or_build_mismatch')
    rune_pages = None
    if args.subject_replay or args.lane_replay:
        replay_bytes = raw if raw is not None else args.subject_replay.read_bytes()
        rune_pages = read_replay_rune_pages(replay_bytes)
    if rune_pages is not None:
        inputs = [attach_player_runes(base, rune_pages) for base in inputs]
    inputs = [attach_combat_inputs(base) for base in inputs]
    inputs = preload_combat(inputs, getattr(args, 'external_data_dir', DEFAULT_ROOT), previous=previous,
                            disabled=getattr(args, 'no_external_data', False))
    damage_profiles = session_damage_profiles(inputs, previous)
    frames = []
    for base in inputs:
        if raw is not None:
            base = attach_round_lanes(base, raw)
        lane = args.lane
        if subject and roam_actors(base['frame'], subject).get('ally_jungle') == base['frame']['decision']['player_entity_id']:
            lane = 'jungle'
        if lane == 'jungle':
            base = attach_personal_camps(base)
        duos = (bottom_lane_actors(base['frame'], subject)
                if subject and lane == 'bot' else None)
        frames.append(bind_round(base, lane, args.target, args.help_seconds,
                                 ally_id=args.ally, enemy_id=args.enemy, upgrade_legacy=True, macro_review=True,
                                 require_objective_credit=True, review_origin=origin, bottom_lane_actors=duos,
                                 damage_profiles=damage_profiles,
                                 roam_actors=(roam_actors(base['frame'], subject) or None) if duos else None))
    frames = bind_session_external_data(
        frames, getattr(args, 'external_data_dir', DEFAULT_ROOT),
        cutoff=subject.get('match_information_cutoff_utc') if subject else None,
        subject=subject, previous=previous, disabled=getattr(args, 'no_external_data', False))
    if previous is not None:
        frames[0] = attach_previous_plan(frames[0], previous, answer, max_chars=300000)
        if frames[0]['frame']['task']['continuity_status']['status'] != 'linked':
            raise ValueError('previous_decision_not_admissible: '+frames[0]['audit']['round_chain']['reason'])
    output = new_directory(args.output)
    manifest = dict(schema='round-agent-session/v1', backend=args.backend,
        variant='baseline' if args.baseline else 'round_tools', max_calls=args.max_calls,
        history='catalog' if args.catalog_history else 'full', steps=[], model=args.model if args.backend=='ollama' else None)
    manifest.update(perspective=args.perspective, verified_subject=subject)
    replay_path = args.subject_replay or args.lane_replay
    source_label = replay_path.name if replay_path else None
    if subject:
        source_label = subject['match_id']
    if args.perspective == 'comparison':
        purpose = '对照样例视角'
    elif args.perspective == 'practice':
        purpose = '本人训练复盘'
    else:
        purpose = '本人实战复盘'
    if subject is not None:
        side = {100: '蓝方', 200: '红方'}[subject['local_team_id']]
        purpose += f" · 本机玩家为{side} {subject['local_champion']}"
    for i, bundle in enumerate(frames):
        if i and previous is not None and answer is not None:
            bundle = attach_previous_plan(bundle, previous, answer, max_chars=300000)
            if bundle['frame']['task']['continuity_status']['status'] != 'linked':
                raise ValueError('previous_decision_not_admissible: '+str(bundle['audit']['round_chain']['reason']))
        directory = output / f'{i+1:02}'
        directory.mkdir()
        path = directory / 'bundle.json'
        atomic_json(path, bundle)
        frame = bundle['frame']
        player = next(hero for hero in frame['lineup'] if hero['entity_id']==frame['decision']['player_entity_id'])
        comparison_lane = frame['task']['round_comparison']['lane']
        clear_choice = ('确认当前营地可刷并清完再走' if comparison_lane == 'jungle'
                        else f'接完 {comparison_lane} 路兵线再走')
        question = (f"{purpose}。这张卡里的‘你’只指本帧选定的 {player['champion'] or player['entity_id']}。"
                    f"先选此人的地图计划。再把去 {args.target} 当作待比较的走法，计算现在离开、协助 {args.help_seconds:g} 秒再走、{clear_choice}的代价。"
                    '先说当前对你最要紧的选择。某一走法若从你的位置做不到，就说明原因。说清你会放掉什么，以及哪条新信息会让你改主意。'
                    '三个候选的 ID 依次为 leave_now、help_then_leave 和 clear_then_leave。')
        if frame['task'].get('bottom_lane_review'):
            question = (f"{purpose}。你是辅助 {player['champion']}。先给出这对下路的对线思路。"
                        '你要让谁难受，保留什么威胁？对手给机会时，何时动手、谁能跟、谁能反打？'
                        '对手不肯上前，你和射手从中拿到什么，接下来怎样处理兵线？'
                        '比较留下、短暂消失后回线和真正离线支援。说明哪种兵线能走、去帮谁、来得及换什么、'
                        '射手会放掉什么、你最迟何时该回，什么信号会让你当场取消。'
                        f'去 {args.target} 只是一个候选目的地。用工具比较 leave_now、help_then_leave、clear_then_leave，'
                        '第一步可以继续对线。没有兵线交接或到场证据时写可辨认的条件。')
        if frame.get('recent_public_combat_ids'):
            question += ('逐条核对公开击杀的击杀者和死者。两个队友各杀一人要分别写明。'
                         '提到个人双杀等连杀称号时需有对应的连杀证据。')
        detail = dict(frame_id=bundle['frame']['frame_id'], at_seconds=bundle['frame']['decision']['at_seconds'],
                      input_sha256=file_sha256(path), source_sha256=_source(bundle),
                      player_entity_id=player['entity_id'], champion=player['champion'])
        detail['review_scope'] = purpose + ' · ' + review_scope(bundle, source_label)
        ref = frame['task'].get('external_data_reference')
        detail['external_data_snapshot_id'] = frame['references'][ref]['snapshot_id'] if ref else None
        combat_ref = frame['task'].get('combat_reference')
        detail['combat_catalog_sha256'] = (bundle['reference_library'][combat_ref]['catalog_sha256']
                                           if combat_ref else None)
        usage = []
        def generator():
            if args.backend == 'ollama':
                return ollama_generator(args.model, args.port, usage, directory, args.max_calls)
            return file_generate(directory/'exchange', timeout_seconds=args.timeout,
                on_request=lambda e:print(json.dumps(e),flush=True))
        answer = None
        if args.baseline:
            result = await asyncio.to_thread(run_reasoning, bundle, generator(), max_calls=args.max_calls, question=question)
        else:
            async with round_client(path, detail['input_sha256']) as (client, protocol):
                detail['mcp_protocol'] = protocol
                if args.backend == 'probe':
                    reports = {}
                    for name in ('compare_round_options','review_round_plan','enemy_sightings'):
                        reports[name] = await query(client, name, {})
                        if reports[name] != round_call(bundle, name, {}):
                            raise ValueError('MCP_and_direct_results_differ')
                    for name, overrides in [('compare_round_options',{'at_seconds':0}),('enemy_sightings',{'observer_team_id':0})]:
                        if not (await client.call_tool(name, overrides)).isError:
                            raise ValueError('MCP_accepted_scope_override')
                    atomic_json(directory/'evidence.json',reports)
                    (directory/'evidence.md').write_text(detail['review_scope']+'\n\n'+render_evidence(reports, player),encoding='utf-8')
                    detail.update(status='evidence_only', direct_equals_mcp=True, rejected_overrides=2)
                    manifest['steps'].append(detail)
                    previous = None
                    continue
                loop = asyncio.get_running_loop()
                def call_tool(name, arguments):
                    return asyncio.run_coroutine_threadsafe(query(client, name, arguments),loop).result(timeout=45)
                result = await asyncio.to_thread(run_reasoning, bundle, generator(), max_calls=args.max_calls,
                    round_tool_call=call_tool, catalog_history=args.catalog_history, question=question)
        detail.update(status=result['status'],model_calls=result['model_calls'],usage=usage,error=result['error'])
        atomic_json(directory/'result.json',result)
        if result['status']=='completed':
            answer = result['answer']
            atomic_json(directory/'answer.json',answer)
            card = render_decision(answer, result['validation'], review_scope_label=detail['review_scope'])
            (directory/'answer.md').write_text(card, encoding='utf-8')
            detail['macro_round'] = answer['macro_round']
            rec = answer['recommendation']
            best = next((o for o in answer['options'] if o['id'] == rec['preferred_option_id']), None)
            detail['player_choice'] = dict(first_step=answer['immediate_action'],
                                           costs=best['costs'] if best else [],
                                           switch_conditions=rec['switch_conditions'])
            if 'lane_plan' in answer:
                detail['lane_plan'] = answer['lane_plan']
            detail['previous_frame_id'] = (frame['task'].get('previous_plan') or {}).get('previous_frame_id')
        previous = bundle if answer else None
        manifest['steps'].append(detail)
    if any(step['status'] == 'completed' for step in manifest['steps']):
        end = read_json(args.sequence)['end_seconds'] if getattr(args, 'sequence', None) else None
        (output/'review.md').write_text(render_map_review(manifest['steps'], end_seconds=end), encoding='utf-8')
        manifest['map_review'] = 'review.md'
    atomic_json(output/'manifest.json',manifest)
    print(json.dumps({'output':str(output),'statuses':[s['status'] for s in manifest['steps']]}))
    return 0 if all(s['status'] in ('evidence_only','completed') for s in manifest['steps']) else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--bundle', action='append', type=Path, help='Chronological same-player frozen bundles')
    inputs.add_argument('--sequence', type=Path, help='Sequence manifest from scripts.prepare_personal_match')
    parser.add_argument('--perspective', choices=['personal','practice','comparison'], default='personal',
                        help='Verified local player in a match (default), verified practice, or a comparison sample')
    parser.add_argument('--subject-replay', type=Path, help='Intended source ROFL for reader identity; defaults to --lane-replay')
    parser.add_argument('--game-log', type=Path, help='Game-start r3dlog for the same game and local player')
    parser.add_argument('--download-log', type=Path, help='Original LeagueClient download log if stored separately')
    parser.add_argument('--lane-replay', type=Path, help='Attach observer-team minions from this exact reviewed 16.22 ROFL')
    external = parser.add_mutually_exclusive_group()
    external.add_argument('--external-data-dir', type=Path, default=DEFAULT_ROOT,
                          help='Read previously refreshed reference data from this local store')
    external.add_argument('--no-external-data', action='store_true',
                          help='Prepare the review without external-data references')
    parser.add_argument('--lane', choices=RESOURCE_ORIGINS, required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--help-seconds', type=float, required=True)
    parser.add_argument('--ally', help='Own-team ally entity ID for a common target engagement')
    parser.add_argument('--enemy', help='Enemy entity ID for that engagement')
    parser.add_argument('--previous-bundle', type=Path)
    parser.add_argument('--previous-answer', type=Path)
    parser.add_argument('--backend', choices=['probe','file','ollama'], default='probe')
    parser.add_argument('--model', default='llama3.2:1b')
    parser.add_argument('--port', type=int, default=11434)
    parser.add_argument('--catalog-history', action='store_true')
    parser.add_argument('--baseline', action='store_true', help='Same frozen question with the legacy reference-only runner')
    parser.add_argument('--timeout', type=float, default=600, help='Seconds per file-backed model response')
    parser.add_argument('--max-calls', type=int, default=6)
    parser.add_argument('--output', type=Path, required=True, help='New directory under data/private/reasoning_sessions')
    args = parser.parse_args()
    try:
        if args.sequence is not None:
            args.bundle = match_sequence_paths(args.sequence)
        return asyncio.run(run(args))
    except (ValueError, FileNotFoundError) as exc:
        parser.exit(2, f'复盘未完成：{exc}\n')


if __name__=='__main__':
    raise SystemExit(main())
