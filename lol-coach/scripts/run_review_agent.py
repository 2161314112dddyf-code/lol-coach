"""Run a team-scoped round through MCP and save evidence or a checked model decision."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

from lol_coach.decision_contract import render_decision
from lol_coach.file_model_bridge import atomic_json, file_generate, file_sha256, new_directory
from lol_coach.reasoning_frame import canonical
from lol_coach.reasoning_runner import run_reasoning
from lol_coach.round_chain import _check_bundle, _source, attach_previous_plan
from lol_coach.round_lane_evidence import attach_round_lanes
from lol_coach.round_options import LANES
from lol_coach.round_tools import bind_round, round_call
from scripts.reasoning import read_bundle, read_json
from scripts.round_review_mcp import query, round_client


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


def render_evidence(report):
    comp, plan = report['compare_round_options'], report['review_round_plan']
    d = comp['at_seconds']
    def window(pair):
        if pair is None:
            return '未知'
        return f'{pair[0]:g}' if pair[0] == pair[1] else f'{pair[0]:g}～{pair[1]:g}'
    lines = [f'# {int(d)//60:02}:{int(d)%60:02} 回合证据','',
             f"观察方 {comp['observer_team_id']}，分路 {comp['lane']}，目标 {comp['target']}。表内为假设成立时的游戏秒数。",'',
             '| 方案 | 出发 | 抵达目标 | 完成目标 | 返回兵线 |','| --- | --- | --- | --- | --- |']
    names_by_action = {'leave_now':'立即走','help_then_leave':f"协助 {comp['proposed_help_seconds']:g} 秒后走",'clear_then_leave':'接完线再走'}
    for row in comp['options']:
        cells = [names_by_action[row['action']], *(window(row[key]) for key in ('depart_at','arrive_at','finish_target_at','return_to_lane_at'))]
        lines.append('| '+' | '.join(cells)+' |')
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
        clock = wave.get('wave_spawn_clock') or {}
        if clock.get('next_birth_window'):
            lines += ['', '按此前出兵节奏，下一波己方小兵预计从基地出生的游戏秒为 '+window(clock['next_birth_window'])+'。到塔时间仍须另算。']
    lines += ['', f"上回合状态 {plan['status']}。"]
    for trigger in plan['triggers']:
        affected = '、'.join(names_by_action.get(option, option) for option in trigger['option_ids']) if trigger['option_ids'] else '全局提醒'
        lines.append(f"- {trigger['entity_id']} · {trigger['kind']} · {affected} · {trigger['current_fact_id']}")
    lines += ['', '抵达、能输出和能安全撤出分别需要证据。此次兵损与队友意图见 evidence.json 的对应字段。']
    return '\n'.join(lines)+'\n'


async def run(args):
    if (args.previous_bundle is None) != (args.previous_answer is None):
        raise ValueError('supply_both_previous_bundle_and_previous_answer')
    if not 1 <= args.max_calls <= 20 or not 1 <= args.port <= 65535:
        raise ValueError('invalid_model_budget_or_loopback_port')
    if args.baseline and (args.backend=='probe' or args.catalog_history):
        raise ValueError('baseline_requires_model_and_full_frame')
    previous = read_bundle(args.previous_bundle) if args.previous_bundle else None
    answer = read_json(args.previous_answer) if args.previous_answer else None
    inputs = list(scoped_sequence(args.bundle))
    raw = args.lane_replay.read_bytes() if args.lane_replay else None
    if raw is not None and hashlib.sha256(raw).hexdigest() != _source(inputs[0]):
        raise ValueError('round_lane_source_or_build_mismatch')
    frames = []
    for base in inputs:
        if raw is not None:
            base = attach_round_lanes(base, raw)
        frames.append(bind_round(base, args.lane, args.target, args.help_seconds, ally_id=args.ally, enemy_id=args.enemy))
    if previous is not None:
        frames[0] = attach_previous_plan(frames[0], previous, answer, max_chars=300000)
        if frames[0]['frame']['task']['continuity_status']['status'] != 'linked':
            raise ValueError('previous_decision_not_admissible: '+frames[0]['audit']['round_chain']['reason'])
    output = new_directory(args.output)
    manifest = dict(schema='round-agent-session/v1', backend=args.backend,
        variant='baseline' if args.baseline else 'round_tools', max_calls=args.max_calls,
        history='catalog' if args.catalog_history else 'full', steps=[], model=args.model if args.backend=='ollama' else None)
    forms = ('立即走、在当前位置协助指定秒数再走、接完当前线再走。请比较到达目标、返回兵线和退路。'
             '分别写出哪条可知信息会改变计划。')
    question = (f'本人，{args.lane} 路，目标 {args.target}，假设协助 {args.help_seconds:g} 秒。'+forms+
                ' 三个候选的 ID 依次为 leave_now、help_then_leave 和 clear_then_leave。')
    for i, bundle in enumerate(frames):
        if i and previous is not None and answer is not None:
            bundle = attach_previous_plan(bundle, previous, answer, max_chars=300000)
            if bundle['frame']['task']['continuity_status']['status'] != 'linked':
                raise ValueError('previous_decision_not_admissible: '+str(bundle['audit']['round_chain']['reason']))
        directory = output / f'{i+1:02}'
        directory.mkdir()
        path = directory / 'bundle.json'
        atomic_json(path, bundle)
        detail = dict(frame_id=bundle['frame']['frame_id'], at_seconds=bundle['frame']['decision']['at_seconds'],
                      input_sha256=file_sha256(path), source_sha256=_source(bundle))
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
                    (directory/'evidence.md').write_text(render_evidence(reports),encoding='utf-8')
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
            (directory/'answer.md').write_text(render_decision(answer,result['validation']),encoding='utf-8')
        previous = bundle if answer else None
        manifest['steps'].append(detail)
    atomic_json(output/'manifest.json',manifest)
    print(json.dumps({'output':str(output),'statuses':[s['status'] for s in manifest['steps']]}))
    return 0 if all(s['status'] in ('evidence_only','completed') for s in manifest['steps']) else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', action='append', type=Path, required=True, help='Chronological same-player frozen bundles')
    parser.add_argument('--lane-replay', type=Path, help='Attach observer-team minions from this exact reviewed 16.22 ROFL')
    parser.add_argument('--lane', choices=LANES, required=True)
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
    return asyncio.run(run(parser.parse_args()))


if __name__=='__main__':
    raise SystemExit(main())
