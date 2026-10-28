"""Prepare a model-ready decision, look up references, or check a model answer.

All commands are offline. The example command emits an explicitly authored
conditional example for the existing 283-second sample, never a model result.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.decision_contract import output_schema, render_decision, validate_decision
from lol_coach.reasoning_frame import (TOOLS, canonical, compile_frame, digest,
    lookup_reference, model_messages, render_frame)
from scripts.analysis import context


def read_json(path):
    def reject(value):
        raise ValueError('Nonfinite JSON value: ' + value)
    return json.loads(Path(path).read_text(encoding='utf-8'), parse_constant=reject)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def new_directory(path):
    path = Path(path).resolve(); allowed = (ROOT/'data/private/reasoning').resolve()
    if not path.is_relative_to(allowed) or path == allowed:
        raise ValueError('Output must be a new child directory of data/private/reasoning')
    path.mkdir(parents=True, exist_ok=False)
    return path


def read_bundle(path):
    bundle = read_json(path)
    if bundle.get('schema') != 'reasoning-bundle/v1':
        raise ValueError('Expected reasoning-bundle/v1')
    frame = bundle['frame']; body = {k: v for k, v in frame.items() if k != 'frame_id'}
    if frame['frame_id'] != 'frame_'+digest(body)[:24]:
        raise ValueError('Frame content differs from its identity')
    return bundle


def manifest(target, inputs, *, authorship):
    paths = ['lol_coach/reasoning_frame.py', 'lol_coach/decision_contract.py',
             'lol_coach/reasoning_runner.py', 'lol_coach/profiles/round_reasoning_cards_v1.json',
             'scripts/reasoning.py', 'scripts/analysis.py', 'lol_coach/analysis_context.py',
             'lol_coach/macro_snapshot.py', 'lol_coach/tower_vision.py']
    write_json(target/'manifest.json', dict(schema='reasoning-artifacts/v1', inputs=inputs,
        authorship=authorship, network_used=False, model_called=False,
        implementation={p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},
        outputs={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in target.iterdir() if p.is_file()}))


def authored_example(frame):
    """An authored fixture bound to a known real input, not a tactical oracle."""
    d = frame['decision']; heroes = {h['champion']: h for h in frame['lineup']}
    if d['at_seconds'] != 283 or d['player_entity_id'] != '0x40000034' or d['observer_team_id'] != 100 or not {'Aphelios', 'Veigar', 'MasterYi'}.issubset(heroes):
        raise ValueError('Authored example only applies to the existing 283s Aphelios input')
    facts = frame['facts']
    def find(entity, field):
        return next(fid for fid, f in facts.items() if f['entity_id'] == entity and f['field'] == field)
    self_id=d['player_entity_id']; ally=heroes['Veigar']['entity_id']; enemy=heroes['MasterYi']['entity_id']
    self_hp=find(self_id, 'health'); ally_identity=find(ally, 'identity'); enemy_identity=find(enemy, 'identity')
    combat=frame['recent_public_combat_ids']
    used=list(dict.fromkeys([self_hp, ally_identity, enemy_identity]+combat))
    budget={k: None for k in ('travel_seconds', 'execution_seconds', 'exit_seconds', 'window_seconds')}
    budget['calculation_refs']=[]
    def option(oid, action, conditions, costs, end, abort):
        return dict(id=oid, action=action, status='conditional', fact_refs=used,
            reference_refs=['principle:J01', 'principle:L02'], preconditions=conditions,
            ally_requirements=[dict(actor_id=ally, required_action='在可到达且具备当前能力时承接或保护',
                                   status='unknown', fact_refs=[ally_identity])],
            enemy_responses=['对手可能利用我方前压反打；最近死亡记录不能排除其已复活或重新到场'],
            time_budget=copy.deepcopy(budget), gains=['保留局部压力转化收益的可能，同时避免分散追击'],
            costs=costs, end_state=end, abort_signals=abort,
            assumptions=['兵线、路径、关键技能和实际跟进均需确认，静态能力不能替代这些条件'])
    a=option('A', '先确认来线与队友位置；条件满足时处理兵线并有组织地施压防御塔',
        ['兵线确实能够进入推进区域', '有可撤出路径且队友能够承接', '敌方可见威胁与未知威胁容许本次前压'],
        ['前压会消耗状态并暴露位置；若不能及时退出可能丢失下一轮发育窗口'],
        '若窗口成立，取得兵线或塔的压力后保持可退出位置；不预设一定推掉塔',
        ['队友无法跟进', '敌方关键威胁进入', '兵线消失或状态不足'])
    b=option('B', '暂缓前压，维持可输出且可退出的站位，等待兵线或敌方新信息',
        ['当前能够找到可守住的位置', '暂缓不会立即丢失必须处理的基地防守目标'],
        ['可能放过短暂的推进机会，需要随新信息立即重评'],
        '保留状态与阵型，等待下一次可共同执行的窗口',
        ['出现已经确认的推进条件', '敌方强开使原位置不可守'])
    return dict(schema='round-decision/v1', frame_id=frame['frame_id'],
        objective='判断近期战斗变化能否转成推进收益，同时保留退出与下一回合空间',
        facts_used=[dict(fact_id=fid, value=copy.deepcopy(facts[fid]['value'])) for fid in used],
        role_assignments=[
            dict(actor_id=self_id, role='保持可持续输出位置；具备条件时参与推进', fact_refs=[self_hp],
                 assumptions=['当前武器、技能和完整装备未知，不推算具体输出能力']),
            dict(actor_id=ally, role='承接或保护的候选参与者，具体能力需资料与局内状态支持',
                 fact_refs=[ally_identity], assumptions=['队友愿意跟进且能够及时到场尚未确认']),
            dict(actor_id=enemy, role='需要考虑的敌方反制参与者，不能忽略其对前压的回应',
                 fact_refs=[enemy_identity], assumptions=['对手下一步行动未知'])],
        options=[a,b], recommendation=dict(preferred_option_id='A', fallback_option_id='B',
            confidence='conditional', why='最近公开战斗事件值得检查转化窗口，但不足以保证当前人数优势或安全推进。',
            switch_conditions=['确认兵线与承接后才执行A，否则先执行B', '获得敌方新位置或技能信息后重新比较']),
        open_questions=['当前兵线能否承载推进？', '队友何时能形成有效跟进？', '当前关键技能与可退出路线是什么？'])


def main():
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest='command',required=True)
    prep=sub.add_parser('prepare'); src=prep.add_mutually_exclusive_group(required=True)
    src.add_argument('--replay-id'); src.add_argument('--snapshot',type=Path)
    prep.add_argument('--at',type=float); prep.add_argument('--team',type=int,choices=[100,200],default=100)
    prep.add_argument('--player'); prep.add_argument('--window',type=float,default=30)
    prep.add_argument('--max-chars',type=int,default=60000); prep.add_argument('--output',type=Path,required=True)
    ref=sub.add_parser('reference'); ref.add_argument('--bundle',type=Path,required=True);ref.add_argument('--id',required=True)
    check=sub.add_parser('check');check.add_argument('--bundle',type=Path,required=True)
    check.add_argument('--answer',type=Path,required=True);check.add_argument('--output',type=Path,required=True)
    ex=sub.add_parser('example');ex.add_argument('--bundle',type=Path,required=True);ex.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.command=='prepare':
        if a.snapshot:
            s=read_json(a.snapshot);inputs=[dict(path=str(a.snapshot.resolve()),sha256=hashlib.sha256(a.snapshot.read_bytes()).hexdigest())]
        else:
            if a.at is None or a.player is None:p.error('Replay prepare requires --at and --player')
            s,_,inputs=context(a.replay_id,a.at,a.team,a.player,a.window)
        bundle=compile_frame(s,max_chars=a.max_chars);schema=output_schema()
        target=new_directory(a.output)
        for name,value in [('bundle.json',bundle),('frame.json',bundle['frame']),
                           ('messages.json',model_messages(bundle,schema)),('tools.json',TOOLS),('response.schema.json',schema)]:
            write_json(target/name,value)
        (target/'frame.md').write_text(render_frame(bundle),encoding='utf-8')
        manifest(target,inputs,authorship='deterministic_compilation_of_existing_decoded_evidence')
        print(json.dumps(dict(output=str(target),frame_id=bundle['frame']['frame_id'],facts=len(bundle['frame']['facts']),
            frame_chars=bundle['audit']['frame_chars'],model_called=False),ensure_ascii=True))
        return 0
    bundle=read_bundle(a.bundle)
    if a.command=='reference':
        print(json.dumps(lookup_reference(bundle,a.id),ensure_ascii=False,indent=2));return 0
    answer=authored_example(bundle['frame']) if a.command=='example' else read_json(a.answer)
    result=validate_decision(answer,bundle['frame']);target=new_directory(a.output)
    write_json(target/'answer.json',answer);write_json(target/'validation.json',result)
    label='# 人工编写的条件示例\n\n基于真实283秒输入；不是通用模型运行结果，不是已验证最优战术。\n\n' if a.command=='example' else ''
    (target/'answer.md').write_text(label+render_decision(answer,result),encoding='utf-8')
    inputs=[dict(path=str(a.bundle.resolve()),sha256=hashlib.sha256(a.bundle.read_bytes()).hexdigest())]
    if a.command=='check':
        inputs.append(dict(path=str(a.answer.resolve()),sha256=hashlib.sha256(a.answer.read_bytes()).hexdigest()))
    manifest(target,inputs,
        authorship='Codex_authored_example_not_model_eval' if a.command=='example' else 'caller_supplied_answer_not_verified_as_model_output')
    print(json.dumps(dict(output=str(target),status=result['status'],tactical_quality=result['tactical_quality']),ensure_ascii=True))
    return 0 if result['status']=='PASS' else 2


if __name__=='__main__':
    try: raise SystemExit(main())
    except (ValueError, OSError, KeyError, StopIteration) as exc:
        print('reasoning: '+str(exc),file=sys.stderr);raise SystemExit(2)
