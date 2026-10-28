"""Provider-neutral decision contract and bounded checks, not a tactical judge.

The validator checks structure, exact cited values and machine-checkable limits.
It cannot establish that free-text explanations follow from those citations.
"""
from copy import deepcopy
import hashlib
import json
import math


SCHEMA = 'round-decision/v1'
_TEXT = {'type': 'string', 'minLength': 1}
_TEXTS = {'type': 'array', 'items': _TEXT}
_RANGE = {'anyOf': [
    {'type': 'null'},
    {'type': 'array', 'minItems': 2, 'maxItems': 2,
     'items': {'type': 'number', 'minimum': 0}},
]}
TIME_FIELDS = ('travel_seconds', 'execution_seconds', 'exit_seconds', 'window_seconds')


def _object(properties):
    return {'type': 'object', 'properties': properties,
            'required': list(properties), 'additionalProperties': False}


def output_schema():
    """Return a fresh JSON Schema; semantic cross-field checks run separately."""
    refs = deepcopy(_TEXTS)
    nonempty_refs = {**deepcopy(_TEXTS), 'minItems': 1}
    role = _object({'actor_id': _TEXT, 'role': _TEXT, 'fact_refs': refs,
                    'assumptions': _TEXTS})
    ally = _object({'actor_id': _TEXT, 'required_action': _TEXT, 'action_key': _TEXT,
                    'status': {'enum': ['observed', 'conditional', 'unknown']},
                    'fact_refs': refs})
    # An additive optional field for old conditional/unknown answers. Observed
    # actions need the key so a state sample cannot masquerade as follow-up.
    ally['required'].remove('action_key')
    option = _object({
        'id': _TEXT, 'action': _TEXT,
        'status': {'enum': ['supported', 'conditional', 'ruled_out']},
        'fact_refs': nonempty_refs, 'reference_refs': refs,
        'preconditions': _TEXTS,
        'ally_requirements': {'type': 'array', 'items': ally},
        'enemy_responses': {**deepcopy(_TEXTS), 'minItems': 1},
        'time_budget': _object({**{k: _RANGE for k in TIME_FIELDS},
                                'calculation_refs': refs}),
        'gains': _TEXTS, 'costs': {**deepcopy(_TEXTS), 'minItems': 1},
        'end_state': _TEXT,
        'abort_signals': {**deepcopy(_TEXTS), 'minItems': 1},
        'assumptions': _TEXTS,
    })
    root = _object({
        'schema': {'const': SCHEMA}, 'frame_id': _TEXT, 'objective': _TEXT,
        'facts_used': {'type': 'array', 'minItems': 1,
                       'items': _object({'fact_id': _TEXT, 'value': {}})},
        'role_assignments': {'type': 'array', 'minItems': 1, 'items': role},
        'options': {'type': 'array', 'minItems': 2, 'maxItems': 3, 'items': option},
        'recommendation': _object({
            'preferred_option_id': {'type': ['string', 'null'], 'minLength': 1},
            'fallback_option_id': {'type': ['string', 'null'], 'minLength': 1},
            'confidence': {'enum': ['supported', 'conditional', 'insufficient_evidence']},
            'why': _TEXT,
            'switch_conditions': {**deepcopy(_TEXTS), 'minItems': 1},
        }),
        'open_questions': _TEXTS,
    })
    root['$schema'] = 'https://json-schema.org/draft/2020-12/schema'
    root['title'] = SCHEMA
    return deepcopy(root)


def _number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _fingerprint(value):
    try:
        encoded = json.dumps(value, sort_keys=True, ensure_ascii=False,
                             allow_nan=False, separators=(',', ':')).encode('utf8')
    except (TypeError, ValueError, OverflowError):
        return None
    return hashlib.sha256(encoded).hexdigest()


def _json_equal(a, b):
    """JSON numbers compare numerically; booleans never equal 0 or 1."""
    if _number(a) and _number(b):
        return a == b
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_json_equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_json_equal(x, y) for x, y in zip(a, b))
    return a == b


def _check_json(value, path, errors):
    if value is None or type(value) in (bool, str):
        return
    if _number(value):
        return
    if isinstance(value, list):
        for i, item in enumerate(value):
            _check_json(item, f'{path}[{i}]', errors)
        return
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        for key, item in value.items():
            _check_json(item, f'{path}.{key}', errors)
        return
    errors.append({'path': path, 'message': '必须为有限、合法的 JSON 值；NaN/Infinity 不允许。'})


def _validate_shape(value, schema, path, errors):
    """Small validator for exactly the JSON Schema subset emitted above."""
    def fail(message):
        errors.append({'path': path, 'message': message})

    if 'anyOf' in schema:
        alternatives = []
        for branch in schema['anyOf']:
            branch_errors = []
            _validate_shape(value, branch, path, branch_errors)
            alternatives.append(branch_errors)
        if all(alternatives):
            fail('应为 null 或两个非负有限数值组成的区间。')
        return
    kinds = schema.get('type', [])
    kinds = [kinds] if isinstance(kinds, str) else kinds
    types = {'object': isinstance(value, dict), 'array': isinstance(value, list),
             'string': isinstance(value, str), 'number': _number(value),
             'null': value is None}
    if kinds and not any(types.get(k, False) for k in kinds):
        fail('类型错误，要求 ' + '/'.join(kinds))
        return
    if 'const' in schema and not _json_equal(value, schema['const']):
        fail('固定值错误。')
    if 'enum' in schema and not any(_json_equal(value, x) for x in schema['enum']):
        fail('值不在允许的枚举范围内。')
    if isinstance(value, str) and 'minLength' in schema and not value.strip():
        fail('文本不得为空白。')
    if _number(value) and 'minimum' in schema and value < schema['minimum']:
        fail('数值不能小于 ' + str(schema['minimum']))
    if isinstance(value, list):
        if len(value) < schema.get('minItems', 0):
            fail('数组元素不足。')
        if len(value) > schema.get('maxItems', len(value)):
            fail('数组元素过多。')
        for i, item in enumerate(value):
            _validate_shape(item, schema.get('items', {}), f'{path}[{i}]', errors)
    if isinstance(value, dict):
        properties = schema.get('properties', {})
        for key in schema.get('required', []):
            if key not in value:
                errors.append({'path': f'{path}.{key}', 'message': '缺少必填字段。'})
        for key, item in value.items():
            if key not in properties:
                if schema.get('additionalProperties') is False:
                    errors.append({'path': f'{path}.{key}', 'message': '不允许未定义的字段。'})
            else:
                _validate_shape(item, properties[key], f'{path}.{key}', errors)


def validate_decision(answer, frame):
    """Check an answer against its frozen frame, without a model call.

    A future calculator may register a record under ``frame.calculations`` with
    a ``time_budget`` mapping. A numerical answer must exactly match such a
    host-provided range. An arbitrary reference ID alone never licenses numbers.
    The current frame compiler emits no duration calculations.
    """
    errors = []

    def fail(path, message):
        errors.append({'path': path, 'message': message})

    def result():
        return {'status': 'FAIL' if errors else 'PASS', 'errors': errors,
                'tactical_quality': 'not_evaluated',
                'answer_sha256': _fingerprint(answer),
                'limitations': ['仅检查结构、引用、数值一致性与显式条件；不证明文字由引用推出。',
                                '行动观测只支持对应动作发生，不证明会继续、全部前提就绪或行动文字逻辑。',
                                '不证明战术最优、队友会执行或实际到场；需要场景评阅。']}

    _check_json(answer, '$', errors)
    if errors:
        return result()
    _validate_shape(answer, output_schema(), '$', errors)
    if not isinstance(frame, dict) or frame.get('schema') != 'decision-frame/v1':
        fail('frame', '需要 decision-frame/v1 输入。')
        return result()
    decision = frame.get('decision')
    facts = frame.get('facts')
    lineup = frame.get('lineup')
    references = frame.get('references')
    calculations = frame.get('calculations')
    if (not isinstance(decision, dict) or not _number(decision.get('at_seconds'))
            or not isinstance(facts, dict) or not isinstance(lineup, list)
            or not isinstance(references, dict) or not isinstance(calculations, dict)
            or any(not isinstance(x, dict) or not isinstance(x.get('entity_id'), str)
                   for x in lineup)
            or any(not isinstance(x, dict) or 'value' not in x for x in facts.values())):
        fail('frame', '输入帧结构不完整。')
        return result()
    if errors:
        return result()
    at = decision['at_seconds']
    actors = {x['entity_id']: x for x in lineup}
    if len(actors) != len(lineup):
        fail('frame.lineup', '输入帧的英雄 ID 重复。')
    if answer['frame_id'] != frame.get('frame_id'):
        fail('$.frame_id', '答案不属于此冻结时刻；禁止复用其他帧的答案。')

    def fact_refs(ids, path):
        for i, fid in enumerate(ids):
            if fid not in facts:
                fail(f'{path}[{i}]', '引用不存在的事实 ID。')
                continue
            fact = facts[fid]
            for key in ('observed_at_seconds', 'available_at_seconds'):
                value = fact.get(key)
                if value is not None and (not _number(value) or value > at):
                    fail(f'{path}[{i}]', '引用的事实尚未在决策时刻可用。')

    seen_facts = set()
    for i, used in enumerate(answer['facts_used']):
        fid = used['fact_id']
        fact_refs([fid], f'$.facts_used[{i}].fact_id')
        if fid in seen_facts:
            fail(f'$.facts_used[{i}].fact_id', '事实 ID 重复。')
        seen_facts.add(fid)
        if fid in facts and not _json_equal(used['value'], facts[fid]['value']):
            fail(f'$.facts_used[{i}].value', '事实值与输入不一致，不能修改数值或类型。')

    role_actors = []
    for i, role in enumerate(answer['role_assignments']):
        actor = role['actor_id']
        role_actors.append(actor)
        if actor not in actors:
            fail(f'$.role_assignments[{i}].actor_id', '英雄 ID 不在本局阵容中。')
        fact_refs(role['fact_refs'], f'$.role_assignments[{i}].fact_refs')
    if len(role_actors) != len(set(role_actors)):
        fail('$.role_assignments', '英雄职责记录重复。')
    player = decision.get('player_entity_id')
    if player not in role_actors:
        fail('$.role_assignments', '必须说明被复盘玩家的职责，包括职责未知的情况。')
    for relation, label in [('ally', '队友'), ('enemy', '对手')]:
        ids = {key for key, actor in actors.items()
               if actor.get('relation') == relation and key != player}
        if ids and not ids.intersection(role_actors):
            fail('$.role_assignments', f'至少需要结合一名{label}的职责/威胁。')

    options = {}
    for i, option in enumerate(answer['options']):
        path = f'$.options[{i}]'
        if option['id'] in options:
            fail(path + '.id', '候选行动 ID 重复。')
        options[option['id']] = option
        fact_refs(option['fact_refs'], path + '.fact_refs')
        for j, rid in enumerate(option['reference_refs']):
            if rid not in references:
                fail(f'{path}.reference_refs[{j}]', '经验/机制引用不在输入资料中。')
        if option['status'] == 'conditional' and not option['preconditions']:
            fail(path + '.preconditions', '条件行动必须写出成立前提。')
        if option['status'] == 'supported' and (option['assumptions'] or option['preconditions']):
            fail(path + '.status', '仍有待满足前提或假设，不能标为 supported。')
        for j, need in enumerate(option['ally_requirements']):
            npath = f'{path}.ally_requirements[{j}]'
            actor = actors.get(need['actor_id'])
            if actor is None or actor.get('relation') != 'ally' or need['actor_id'] == player:
                fail(npath + '.actor_id', '跟进依赖必须指向本局另一名队友。')
            fact_refs(need['fact_refs'], npath + '.fact_refs')
            if need['status'] == 'observed':
                cited = [facts[fid] for fid in need['fact_refs'] if fid in facts]
                action_key = need.get('action_key')
                if not isinstance(action_key, str) or not action_key.strip():
                    fail(npath + '.action_key', '已观测行动必须提供与事实匹配的 action_key。')
                relevant = [f for f in cited if f.get('entity_id') == need['actor_id']
                            and f.get('field') == 'action_observation'
                            and f.get('temporal_scope') == 'observed_action'
                            and isinstance(f.get('value'), dict)
                            and isinstance(action_key, str) and bool(action_key.strip())
                            and f['value'].get('action_key') == action_key
                            and f['value'].get('status') in ('in_progress', 'completed')]
                if not relevant:
                    fail(npath + '.fact_refs',
                         '已观测行动必须引用同一队友、同一 action_key 的当前行动观测；生命、位置候选或阵容不能替代。')
                scopes = [f.get('temporal_scope', '') for f in cited]
                if any(isinstance(scope, str) and
                       (scope.startswith(('last_seen', 'historical')) or scope == 'last_observed')
                       for scope in scopes):
                    fail(npath + '.status', '历史观测不能直接证明队友此刻已满足跟进条件。')
            elif option['status'] == 'supported':
                fail(path + '.status', '队友跟进仍为条件或未知，不能标为 supported。')
        budget = option['time_budget']
        for j, cid in enumerate(budget['calculation_refs']):
            if cid not in calculations:
                fail(f'{path}.time_budget.calculation_refs[{j}]', '时间计算引用不存在。')
        for field in TIME_FIELDS:
            value = budget[field]
            if value is None:
                continue
            if value[0] > value[1]:
                fail(path + '.time_budget.' + field, '区间下界不能大于上界。')
            supported = any(
                isinstance(calculations.get(cid), dict)
                and isinstance(calculations[cid].get('time_budget'), dict)
                and _json_equal(calculations[cid]['time_budget'].get(field), value)
                for cid in budget['calculation_refs'])
            if not supported:
                fail(path + '.time_budget.' + field,
                     '缺少对应的已登记时间计算；当前未知耗时须填 null，不能编造秒数。')

    rec = answer['recommendation']
    preferred, fallback = rec['preferred_option_id'], rec['fallback_option_id']
    if preferred is not None and fallback is None:
        fail('$.recommendation.fallback_option_id', '给出首选时必须提供退路。')
    if preferred is not None and preferred == fallback:
        fail('$.recommendation.fallback_option_id', '退路不能与首选相同。')
    if preferred is None and rec['confidence'] != 'insufficient_evidence':
        fail('$.recommendation.confidence', '没有首选时应明确为证据不足。')
    if preferred is None and not answer['open_questions']:
        fail('$.open_questions', '不能排序时应指出决定性缺失条件。')
    for field in ('preferred_option_id', 'fallback_option_id'):
        oid = rec[field]
        if oid is None:
            continue
        option = options.get(oid)
        if option is None or option['status'] == 'ruled_out':
            fail('$.recommendation.' + field, '推荐必须指向未被排除的候选行动。')
            continue
        if rec['confidence'] == 'supported' and (
                option['status'] != 'supported' or option['assumptions']
                or option['preconditions']
                or any(option['time_budget'][key] is None for key in TIME_FIELDS)
                or any(n['status'] != 'observed' for n in option['ally_requirements'])):
            fail('$.recommendation.confidence', '存在未知时间或条件依赖，只能给条件推荐。')
    return result()


def render_decision(answer, validation):
    """Render only a contract-checked answer; never polish invalid output."""
    valid_result = (isinstance(validation, dict) and validation.get('status') == 'PASS'
                    and validation.get('answer_sha256') is not None
                    and validation.get('answer_sha256') == _fingerprint(answer))
    if not valid_result:
        lines = ['# 分析输出未通过检查', '', '这份输出暂不作为行动建议。', '']
        if isinstance(validation, dict) and validation.get('status') == 'PASS':
            lines.append('- 检查记录与当前答案不一致，需要重新检查。')
        for error in (validation.get('errors', []) if isinstance(validation, dict) else []):
            if isinstance(error, dict):
                lines.append(f"- {error.get('path', '?')}：{error.get('message', '检查失败')}")
        return '\n'.join(lines) + '\n'
    rec = answer['recommendation']
    options = {o['id']: o for o in answer['options']}
    best = options.get(rec['preferred_option_id'])
    fallback = options.get(rec['fallback_option_id'])
    levels = {'supported': '有依据推荐', 'conditional': '条件推荐',
              'insufficient_evidence': '暂不能排序'}
    lines = ['# 本回合决策卡', '', f"目标：{answer['objective']}", '',
             f"结论：{levels[rec['confidence']]}",
             f"首选：{best['action'] if best else '现有信息不足以确定首选'}", '',
             rec['why'], '']
    if fallback:
        lines += [f"退路：{fallback['action']}", '']
    option_levels = {'supported': '已具备条件', 'conditional': '待条件满足',
                     'ruled_out': '已排除，不执行'}
    for option in answer['options']:
        lines += [f"## 候选（{option_levels[option['status']]}）：{option['action']}", '',
                  '成立条件：' + ('；'.join(option['preconditions']) or '未列待满足前提'),
                  '代价：' + '；'.join(option['costs']),
                  '完成后状态：' + option['end_state'],
                  '停止信号：' + '；'.join(option['abort_signals']),
                  '事实引用：' + '、'.join(option['fact_refs']), '']
    lines += ['## 何时改计划', ''] + ['- ' + s for s in rec['switch_conditions']]
    if answer['open_questions']:
        lines += ['', '## 尚需判断的条件', ''] + ['- ' + s for s in answer['open_questions']]
    lines += ['', '结构与引用检查通过；战术质量尚未评阅。', '']
    return '\n'.join(lines)
