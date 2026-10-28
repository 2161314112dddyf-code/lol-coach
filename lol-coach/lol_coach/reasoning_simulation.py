"""Synthetic paired decisions, never decoded or independently verified games."""
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path

from .decision_contract import output_schema, render_decision, validate_decision
from .reasoning_frame import digest, model_messages


ROOT = Path(__file__).resolve().parents[1]
PAIR_SPECS = {
    'C1': ('配合与兵线', 'facts.ally_action.value.action_key', 'move_to_entry', 'clear_wave'),
    'C2': ('现金与已买装备', 'facts.capital_state.value', 'key_item_purchased', 'equivalent_cash_unspent'),
    'C3': ('阵容中的输出职责', 'facts.damage_owner.value', 'self', 'ally'),
    'C4': ('隐藏位置不可知', 'audit.omniscient_enemy_position', 'far_from_entry', 'at_entry'),
    'C5': ('2v2与加入打野后的条件', 'facts.jungle_matchup.value', 'ally_control_enemy_no_interrupt', 'ally_no_control_enemy_interrupt'),
    'C6': ('经验地区标签迁移', 'references.principle:coordination.source_environment', 'CN_solo_queue', 'KR_premade'),
    'C7': ('独立有限行动与必要承接', 'facts.solo_capability.value', 'independent_limited_entry_and_exit_verified', 'requires_ally_not_yet_present'),
}


def _fact(entity, field, value, *, scope='observed_sample'):
    return dict(entity_id=entity, field=field, value=value, unit=None,
                observed_at_seconds=1200, available_at_seconds=1200,
                age_seconds=0, temporal_scope=scope, evidence_level='synthetic_stipulated')


def _base(pair):
    lineup = [dict(entity_id='self', champion='Synthetic_A', relation='ally'),
              dict(entity_id='ally', champion='Synthetic_B', relation='ally'),
              dict(entity_id='enemy', champion='Synthetic_C', relation='enemy')]
    reference = dict(kind='synthetic_conditional_principle',
        source_environment='CN_solo_queue',
        principle='同一回合需分别检查各人能否离开、到场、兑现能力及退出。',
        conditions=['有当时可知的局势支持', '队友具体行动需另外确认'],
        counterexample='具备独立完成行动的能力时，不能机械等待队友。',
        provenance='synthetic paraphrase for a controlled scenario; not an empirical regional claim')
    frame = dict(schema='decision-frame/v1',
        decision=dict(at_seconds=1200.0, observer_team_id=100, player_entity_id='self',
            build='SYNTHETIC-NOT-A-CLIENT-PATCH', map_mode='synthetic_summoners_rift_exercise',
            region='synthetic_CN_context', queue='synthetic_solo_queue', party_members=None),
        task=dict(unit='one_decision_point', question='', previous_plan=None, round_boundaries=None,
            evidence_notice='本题所有局势与能力均为合成给定；不得视为真实游戏机制或实测结果。'),
        lineup=lineup, facts={
            'self_state': _fact('self', 'condition', '可保持站位和输出；当前没有必须立即救援的基地威胁'),
            'ally_state': _fact('ally', 'condition', '能够配合但是否离线、到达和下一步动作分别核对'),
            'enemy_state': _fact('enemy', 'known_threat', '具备惩罚孤立前压的能力；没有给定伤害数值'),
            'environment': _fact('world', 'environment', '当前存在争取入口的机会，也存在原地保持可退出阵型的选项；不能默认另一侧有可换资源'),
        }, references={'principle:coordination': reference}, calculations={},
        unknowns=dict(action_durations='unknown', exact_damage='unknown', teammate_intent='unknown',
                      hidden_enemy_locations='unknown'),
        input_policy=['仅使用题设事实，不补充真实英雄机制', '所有题设均 synthetic_stipulated',
                      '未知不是0，动作开始不等于行动完成，隐蔽位置不能从审计数据获取'],
        reasoning_order=['目标', '双方职责', '窗口', '比较2—3个候选', '退出与代价', '依据'])
    return dict(schema='reasoning-bundle/v1', frame=frame,
                reference_library={'principle:coordination': deepcopy(reference)},
                audit=dict(evidence_level='synthetic_stipulated', generator='ROUND-004-SIM',
                           real_replay_used=False, pair=pair))


def build_cases():
    cases = {}
    for pair, (_, _, a, b) in PAIR_SPECS.items():
        base = _base(pair); f = base['frame']; facts = f['facts']
        if pair == 'C1':
            f['task']['question'] = '本人是否应立即压向入口，还是先维持威胁等待队友可共同执行？'
            facts['lane_cost'] = _fact('ally', 'opportunity_cost', '入口行动会离开当前兵线；兵线损失未量化，不能省略此成本')
            facts['ally_action'] = _fact('ally', 'action_observation',
                {'action_key': a, 'status': 'in_progress'}, scope='observed_action')
            facts['action_glossary'] = _fact('world', 'synthetic_action_definition',
                {'move_to_entry': '已观察到开始向入口移动，尚未证明抵达、承诺或技能就绪',
                 'clear_wave': '已观察到仍在处理兵线，尚未开始向入口移动'})
        elif pair == 'C2':
            f['task']['question'] = '资源争夺窗口将出现；本人是先争入口，还是先补装并重新核对是否赶得上？'
            facts['capital_state'] = _fact('self', 'capital_state', a)
            facts['capital_definition'] = _fact('self', 'synthetic_capability_rule',
                '两个状态累计收入相同。key_item_purchased表示关键装备已经持有，题设规定它提供持续输出能力；equivalent_cash_unspent表示等值现金未花，尚不具备该装备能力。未给出购买/回场耗时。')
            facts['objective_window'] = _fact('world', 'objective_window', '争夺入口的窗口存在，但未给精确到期时间；不能保证补装后赶得上')
        elif pair == 'C3':
            f['task']['question'] = '本人可以先手但会暴露位置；现在应自己先手还是保留输出与退出位置？'
            facts['damage_owner'] = _fact('team', 'principal_damage_owner', a)
            facts['engage_tradeoff'] = _fact('self', 'synthetic_capability_rule',
                '本人可尝试先手，但先手期间不能同时保持原输出位置；主要输出者损失会显著降低本次收益。队友可承接但是否响应未确认。对手能反打孤立进场。')
        elif pair == 'C4':
            f['task']['question'] = '现在能否把入口当作安全位置并独自前压？只依据本人队伍当前可知信息。'
            facts['enemy_last_seen'] = _fact('enemy', 'last_seen_location', '河道外侧，观测已经过期', scope='last_seen_sample')
            facts['enemy_last_seen'].update(observed_at_seconds=1180, available_at_seconds=1180, age_seconds=20)
            facts['entry_visibility'] = _fact('world', 'entry_visibility', '入口当前不可见，敌人当前位置未知')
            base['audit']['omniscient_enemy_position'] = a
        elif pair == 'C5':
            f['task']['question'] = '原2v2不利。双方打野加入后的3v3能否争取，还是退回原站位？'
            f['lineup'] += [dict(entity_id='ally_jungle', champion='Synthetic_D', relation='ally'),
                            dict(entity_id='enemy_jungle', champion='Synthetic_E', relation='enemy')]
            facts['duo_matchup'] = _fact('world', 'duo_matchup', '不含打野时我方2v2不利；该事实不能直接替代加入打野后的比较')
            facts['jungle_matchup'] = _fact('world', 'jungle_matchup', a)
            facts['jungle_definitions'] = _fact('world', 'synthetic_capability_rule',
                {'ally_control_enemy_no_interrupt': '合成给定：我方打野能提供已就绪的控制；敌方打野本次不能中断承接，但仍有伤害',
                 'ally_no_control_enemy_interrupt': '合成给定：我方打野本次不能提供控制；敌方打野能中断承接',
                 'shared': '双方打野均已在可参与区域；我方具体同步行动未确认，伤害和操作结果未量化'})
        elif pair == 'C6':
            f['task']['question'] = '队友尚未开始向入口移动，本人是否单独前压？结合给定经验及其适用限制。'
            facts['ally_action'] = _fact('ally', 'action_observation',
                {'action_key': 'clear_wave', 'status': 'in_progress'}, scope='observed_action')
            facts['lane_cost'] = _fact('ally', 'opportunity_cost', '队友离开会放弃兵线收益；没有其已响应的证据')
        else:
            f['task']['question'] = '本人是否现在完成限定入口目标并退出，还是等待队友承接？区分行动的真实依赖与无关缺口。'
            facts['solo_capability'] = _fact('self', 'solo_capability', a)
            facts['ally_action'] = _fact('ally', 'action_observation',
                {'action_key': 'clear_wave', 'status': 'in_progress'}, scope='observed_action')
            facts['limited_scope'] = _fact('world', 'limited_action_scope',
                '限定目标：到入口外沿取得短暂观察位置，再沿已给定退路退出；不包括击杀、深入、长时间占位或夺取资源。当前环境已核对无额外中断，若环境或敌方状态变化立即重新判断。')
            facts['solo_definitions'] = _fact('self', 'synthetic_capability_rule',
                {'independent_limited_entry_and_exit_verified': '合成题设已确认：本人当前能独立完成上述有限目标并退出，不需要队友参与。队友仍清线不构成该动作的阻断条件。',
                 'requires_ally_not_yet_present': '合成题设已确认：完成同一个有限目标必须队友承接；队友当前仍清线且尚未到场，所需承接条件未满足。',
                 'scope': '以上是本题给定能力关系，不是现实英雄机制或实测导航保证；没有伤害数值、精确耗时或无限安全保证。'})
        for suffix, value in [('A', a), ('B', b)]:
            bundle = deepcopy(base); frame = bundle['frame']
            if pair == 'C1': frame['facts']['ally_action']['value']['action_key'] = value
            elif pair == 'C2': frame['facts']['capital_state']['value'] = value
            elif pair == 'C3': frame['facts']['damage_owner']['value'] = value
            elif pair == 'C4': bundle['audit']['omniscient_enemy_position'] = value
            elif pair == 'C5': frame['facts']['jungle_matchup']['value'] = value
            elif pair == 'C6':
                frame['references']['principle:coordination']['source_environment'] = value
                bundle['reference_library'] = deepcopy(frame['references'])
            else: frame['facts']['solo_capability']['value'] = value
            frame['frame_id'] = 'frame_' + digest(frame)[:24]
            cases[pair + suffix] = bundle
    return cases


def build_rubric():
    entries = {
        'C1': dict(required_fact_refs=['ally_action', 'lane_cost'],
            expected='解释开始移动与仍在清线的配合差异；到达和未来响应仍需条件，考虑离线成本；不强制首选一定翻转。',
            forbidden=['把已移动写成已抵达或承诺', '用生命值/身份证明队友已跟进']),
        'C2': dict(required_fact_refs=['capital_state', 'capital_definition'],
            expected='区别装备能力已兑现与现金未花；讨论补装及回场机会成本，不能保证补装后赶得上。',
            forbidden=['等累计收入当成等当前战力', '虚构补装或到达精确秒数']),
        'C3': dict(required_fact_refs=['damage_owner', 'engage_tradeoff'],
            expected='根据主要输出职责调整自身先手成本和队友承接；保持敌方反制约束。',
            forbidden=['只因本人能先手就必须先手', '把队友能力写成承诺执行']),
        'C4': dict(required_fact_refs=['enemy_last_seen', 'entry_visibility'],
            expected='两个相同可知输入都不应使用全知敌人位置；历史位置不保证当前入口安全。允许随机措辞差异。',
            forbidden=['使用审计中的全知位置', '历史位置升级为当前坐标或保证安全']),
        'C5': dict(required_fact_refs=['duo_matchup', 'jungle_matchup', 'jungle_definitions'],
            expected='从不变2v2局势重新比较3v3控制和中断关系；有利控制只支持候选，不证明必赢。',
            forbidden=['2v2不利直接判3v3必败', '能力优势直接判稳赢']),
        'C6': dict(required_fact_refs=['ally_action', 'lane_cost'],
            expected='资料地区标签变化不改变当前事实；说明经验适用限制，不能用国服/韩服刻板印象反转建议。',
            forbidden=['由地区标签推断队友真实配合', '把组排经验当本局已沟通证据']),
        'C7': dict(required_fact_refs=['solo_capability', 'solo_definitions', 'limited_scope', 'ally_action'],
            expected='A清楚比较并允许当前可独立完成的有限入口行动，不因队友仍清线而机械等待；B识别必要承接未满足并等待或后撤。两者都保持有限目标与环境变更中止条件。',
            forbidden=['把无关队友缺口升级为A的必需条件', '忽略B的必要承接', '把有限安全条件扩成无限前压或稳赢']),
    }
    return dict(schema='simulation-rubric/v1', evidence_level='synthetic_stipulated',
                tactical_review='requires_developer_reading_not_automated_keyword_score',
                cases={pid+side: deepcopy(row) for pid,row in entries.items() for side in 'AB'})


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def _new_output(path):
    path = Path(path).resolve(); allowed = (ROOT/'data/private/reasoning_simulation').resolve()
    if not path.is_relative_to(allowed) or path == allowed:
        raise ValueError('Output must be a new child of data/private/reasoning_simulation')
    path.mkdir(parents=True, exist_ok=False)
    return path


def prepare_cases(output, *, schema=None, schema_provenance=None):
    output = _new_output(output)
    schema = output_schema() if schema is None else schema
    cases = build_cases()
    _write(output/'schema.json', schema); _write(output/'rubric.json', build_rubric())
    for case_id, bundle in cases.items():
        case_dir=output/case_id; case_dir.mkdir()
        _write(case_dir/'bundle.json', bundle)
        _write(case_dir/'messages.json', model_messages(bundle, schema))
    manifest = dict(schema='simulation-cases/v1', evidence_level='synthetic_stipulated',
        case_ids=list(cases), pairs={pid:dict(case_ids=[pid+'A',pid+'B'], title=title,
            unique_semantic_difference=path, derived_frame_id_may_change=True)
            for pid,(title,path,_,_) in PAIR_SPECS.items()},
        schema_provenance=schema_provenance or 'current decision_contract.output_schema',
        files={str(p.relative_to(output)):hashlib.sha256(p.read_bytes()).hexdigest()
               for p in output.rglob('*') if p.is_file()},
        real_game_test=False, model_called=False)
    _write(output/'manifest.json', manifest)
    return manifest


def check_answers(cases_dir, answers_dir, output):
    cases_dir=Path(cases_dir); answers_dir=Path(answers_dir)
    manifest=json.loads((cases_dir/'manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        if hashlib.sha256((cases_dir/name).read_bytes()).hexdigest()!=expected:
            raise ValueError('Frozen case artifact changed: '+name)
    rubric=json.loads((cases_dir/'rubric.json').read_text(encoding='utf-8'))
    output=_new_output(output); rows=[]
    for cid in manifest['case_ids']:
        bundle=json.loads((cases_dir/cid/'bundle.json').read_text(encoding='utf-8'))
        dest=output/cid; dest.mkdir(); path=answers_dir/(cid+'.json')
        answer=None
        try:
            answer=json.loads(path.read_text(encoding='utf-8'))
            validation=validate_decision(answer,bundle['frame'])
        except (OSError,ValueError) as exc:
            validation=dict(status='FAIL',errors=[{'path':'answer','message':str(exc)}],
                            tactical_quality='not_evaluated',answer_sha256=None)
        cited=set()
        if isinstance(answer,dict):
            for row in answer.get('facts_used',[]) if isinstance(answer.get('facts_used'),list) else []:
                if isinstance(row,dict) and isinstance(row.get('fact_id'),str):cited.add(row['fact_id'])
            linked=set()
            for key in ('options','role_assignments'):
                for row in answer.get(key,[]) if isinstance(answer.get(key),list) else []:
                    if isinstance(row,dict) and isinstance(row.get('fact_refs'),list):
                        linked.update(v for v in row['fact_refs'] if isinstance(v,str))
            cited &= linked
        required=rubric['cases'][cid]['required_fact_refs']; missing=[fid for fid in required if fid not in cited]
        row=dict(case_id=cid,contract_status=validation['status'],
            critical_fact_coverage_status='FAIL' if missing else 'PASS',
            missing_critical_fact_refs=missing,tactical_quality='not_evaluated',
            answer_sha256=hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None)
        rows.append(row)
        _write(dest/'validation.json',validation);_write(dest/'coverage.json',row)
        (dest/'answer.md').write_text(render_decision(answer,validation),encoding='utf-8')
    result=dict(schema='simulation-check/v1', evidence_level='synthetic_stipulated',
        status='PASS' if all(r['contract_status']=='PASS' and r['critical_fact_coverage_status']=='PASS' for r in rows) else 'FAIL',
        cases=rows, tactical_quality='not_evaluated',
        cases_manifest_sha256=hashlib.sha256((cases_dir/'manifest.json').read_bytes()).hexdigest(),
        checker_sources={name:dict(path=str(Path(inspect.getsourcefile(fn)).resolve()),
            sha256=hashlib.sha256(Path(inspect.getsourcefile(fn)).read_bytes()).hexdigest())
            for name,fn in [('validator',validate_decision),('renderer',render_decision),('harness',check_answers)]},
        limitation='PASS covers output contract and explicit critical-fact references only; no semantic or tactical judgement.')
    _write(output/'summary.json',result)
    return result
