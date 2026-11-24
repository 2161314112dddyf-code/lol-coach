"""Provider-neutral decision contract and bounded checks, not a tactical judge.

The validator checks structure, exact cited values and machine-checkable limits.
It cannot establish that free-text explanations follow from those citations.
"""
from copy import deepcopy
import hashlib
import json
import math
import re

from .objective_credit import DRAGON_DISPLAY_NAMES, dragon_kill_events
from .review_pings import PING_TYPES


SCHEMA = 'round-decision/v1'
MACRO_REVIEW = 'macro-round/v1'
SUPPORT_LANE_REVIEW = 'support-lane/v1'
TEAM_COORDINATION_REVIEW = 'team-coordination/v1'
ROAM_DESTINATIONS = {'hold_bot': '照应下路', 'river_jungle': '接应打野', 'mid_lane': '支援中路', 'top_lane': '支援上路'}
MACRO_TRANSITIONS = {'start': '提出本轮计划', 'continue': '延续上一轮',
                     'close': '结束上一轮，重新部署', 'unknown': '回合交接待定'}
MACRO_INTENTS = {'pressure': '主动施压', 'defend': '防守掩护', 'trade': '交换资源',
                 'develop': '发育', 'reset': '回补整备', 'unknown': '方向待定'}
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


def quiet_personal_frame(task):
    trigger = task.get('team_coordination_trigger')
    return isinstance(trigger, dict) and trigger.get('active') is False


def output_schema(frame=None):
    """Return a fresh JSON Schema; semantic cross-field checks run separately."""
    from .brief_update import brief_schema, is_brief
    if is_brief(frame):
        return brief_schema(frame)
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
    task = frame.get('task') if isinstance(frame, dict) else None
    personal = isinstance(task, dict) and 'player_perspective' in task
    if isinstance(frame, dict):
        option['properties']['actor_id'] = deepcopy(_TEXT)
        if personal:
            option['required'].append('actor_id')
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
        'continuation': _object({
            'previous_frame_id': _TEXT,
            'disposition': {'enum': ['retain', 'revise', 'cancel']},
            'previous_action_execution': {'enum': ['unknown']},
            'reason': _TEXT,
            'current_fact_refs': nonempty_refs,
            'change_refs': refs,
        }),
    })
    # Old standalone answers remain valid. The frozen frame determines whether
    # this optional structural field is semantically required or forbidden.
    root['required'].remove('continuation')
    if personal:
        root['properties']['immediate_action'] = deepcopy(_TEXT)
        root['required'].append('immediate_action')
    if isinstance(task, dict) and task.get('knowledge_handbook', {}).get('schema') == 'coaching-handbook/v1':
        root['properties']['follow_through'] = _object({
            'option_id': {'type': ['string', 'null'], 'minLength': 1},
            'baseline_if_unchanged': _TEXT,
            'steps': {'type': 'array', 'maxItems': 3, 'items': _object({
                'after_step': {'type': 'integer', 'minimum': 0, 'maximum': 2},
                'action': _TEXT, 'expected_state': _TEXT,
                'state_basis': {'enum': ['conditional_projection']},
                'check_when': _TEXT, 'if_confirmed': _TEXT, 'if_not_confirmed': _TEXT,
                'fact_refs': nonempty_refs, 'knowledge_refs': {**refs, 'maxItems': 3},
            })},
            'limits': _TEXTS,
        })
        root['required'].append('follow_through')
    if isinstance(task, dict) and task.get('team_coordination_review') == TEAM_COORDINATION_REVIEW:
        coordination = _object({
            'mode': {'enum': ['communicate', 'already_signaled', 'no_signal']},
            'recipient_id': {'type': ['string', 'null'], 'minLength': 1},
            'trigger': _TEXT, 'known_information': _TEXT, 'intended_action': _TEXT,
            'message': {'type': 'string'}, 'response_cue': {'type': 'string'},
            'fallback': _TEXT, 'fact_ids': nonempty_refs,
        })
        coordination['properties']['ping_kind'] = {'enum': list(PING_TYPES)}
        root['properties']['team_coordination'] = coordination
        root['required'].append('team_coordination')
    if isinstance(task, dict) and task.get('bottom_lane_review') == SUPPORT_LANE_REVIEW:
        root['properties']['lane_plan'] = _object({
            'pressure': _TEXT, 'if_open': _TEXT, 'if_denied': _TEXT, 'fact_refs': nonempty_refs,
            'roam': _object({
                'option_id': _TEXT, 'wave_condition': _TEXT, 'return_by': _TEXT,
                'short_play': _TEXT, 'committed_play': _TEXT,
                # A spawn prefix and sampled minion positions do not identify the
                # numbered lane wave on which the carry can be left alone.
                'wave_number': {'type': 'null'},
            }),
        })
        root['required'].append('lane_plan')
        if task.get('roam_actors'):
            plan = root['properties']['lane_plan']
            destinations = [k for k in ROAM_DESTINATIONS if k != 'top_lane' or 'ally_top' in task['roam_actors']]
            plan['properties']['destination_choice'] = _object({
                'preferred': {'enum': destinations}, 'alternative': {'enum': destinations},
                'why': _TEXT, 'switch_if': _TEXT, 'fact_refs': nonempty_refs})
            plan['required'].append('destination_choice')
    if isinstance(task, dict) and task.get('macro_round_review') == MACRO_REVIEW:
        previous = task.get('previous_plan')
        card = previous.get('decision_card') if isinstance(previous, dict) else None
        prior = card.get('macro_round') if isinstance(card, dict) else None
        has_plan = isinstance(prior, dict) and isinstance(prior.get('intent'), str) and (
            prior['intent'] in MACRO_INTENTS and prior['intent'] != 'unknown')
        transitions = ['continue', 'close', 'unknown'] if has_plan else ['start', 'unknown']
        root['properties']['macro_round'] = _object({
            'transition': {'enum': transitions}, 'intent': {'enum': list(MACRO_INTENTS)},
            'map_goal': _TEXT, 'enabling_condition': _TEXT, 'opponent_reply': _TEXT,
            'fact_refs': nonempty_refs, 'change_refs': refs,
        })
        root['required'].append('macro_round')
    if isinstance(task, dict) and (task.get('require_objective_credit') is True
                                   or task.get('macro_round_review') == MACRO_REVIEW):
        root['properties']['objective_kill_claims'] = {
            'type': 'array', 'items': _object({
                'fact_id': _TEXT, 'killer_entity_id': {'type': ['string', 'null'], 'minLength': 1}})}
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


def observation_value(fact):
    """Compare the sighting itself; the age of an unchanged sample grows at every scan."""
    value = fact['value']
    if fact['field'] == 'observer_visibility' and isinstance(value, dict):
        sample = value.get('last_observed_position')
        if isinstance(sample, dict) and 'age_seconds' in sample:
            return dict(value, last_observed_position={k: v for k, v in sample.items() if k != 'age_seconds'})
    return value


def _live_dragon_in_pit(fact):
    value = fact.get('value')
    return fact.get('field') == 'dragon_pit_observation' and (
        (isinstance(value, dict) and value.get('alive') is True)
        or (isinstance(value, str) and value.startswith('龙坑内亚龙仍存活')))


def _dragon_completion_changes(previous, frame, changes):
    """Recognise the live-pit capture and its later public finish in scoped replay inputs.

    Team announcements can close the objective window regardless of whether
    anyone has independently identified the player who secured it.
    """
    card = previous.get('decision_card') or {}
    macro = card.get('macro_round') or {}
    cited = macro.get('fact_refs', [])
    if macro.get('intent') != 'pressure' or len(cited) != 1:
        return set()
    pit = previous.get('historical_facts', {}).get(cited[0], {})
    since = previous.get('previous_at_seconds')
    if not _live_dragon_in_pit(pit) or not _number(since):
        return set()
    facts, at = frame['facts'], frame['decision']['at_seconds']
    events = dragon_kill_events(frame)
    announced, hud = set(), set()
    for change_id, change in changes.items():
        if not isinstance(change, dict):
            continue
        fact = facts.get(change.get('current_fact_id'), {})
        when = fact.get('observed_at_seconds')
        available = fact.get('available_at_seconds', when)
        if not (_number(when) and _number(available) and since < when <= available <= at):
            continue
        value = fact.get('value')
        if change.get('current_fact_id') in events:
            announced.add(change_id)
        elif (fact.get('field') == 'dragon_pit_observation' and fact.get('entity_id') == pit.get('entity_id')
              and fact.get('temporal_scope') == 'player_view_at_video_frame'
              and isinstance(value, str) and value.startswith('玩家画面出现“我方队伍已经击杀了')
              and '亚龙' in value):
            hud.add(change_id)
    return announced | hud


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
             'integer': type(value) is int,
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
    if _number(value) and 'maximum' in schema and value > schema['maximum']:
        fail('数值不能大于 ' + str(schema['maximum']))
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


def _check_lane_plan(answer, frame, facts, actors, player, fail):
    """Check the four players, cited lane evidence and the linked counterfactual."""
    lane = answer['lane_plan']
    roam = lane['roam']
    quartet = frame['task'].get('bottom_lane_actors')
    relations = {'support': 'ally', 'carry': 'ally', 'enemy_support': 'enemy', 'enemy_carry': 'enemy'}
    if (not isinstance(quartet, dict) or quartet.keys() != relations.keys()
            or any(not isinstance(v, str) for v in quartet.values())
            or len(set(quartet.values())) != 4 or quartet['support'] != player
            or any(actors.get(quartet[k], {}).get('relation') != rel for k, rel in relations.items())):
        fail('frame.task.bottom_lane_actors', '下路计划需要已核实的本人、己方射手和敌方双人组。')
        return
    role_actors = {row['actor_id'] for row in answer['role_assignments']}
    if not quiet_personal_frame(frame['task']) and not set(quartet.values()).issubset(role_actors):
        fail('$.role_assignments', '请说明双方下路四人的职责或仍待确认的配合与反制。')
    if len({lane[k].strip().casefold() for k in ('pressure', 'if_open', 'if_denied')}) != 3:
        fail('$.lane_plan', '施压思路、对手给机会时的行动和不给机会时的行动需分别说明。')
    if roam['short_play'].strip().casefold() == roam['committed_play'].strip().casefold():
        fail('$.lane_plan.roam', '短离线与实际支援中野需分别写出目的地、收益和折返条件。')
    # This producer can distinguish relative wave conditions and allied births,
    # but cannot label the safe outing "wave N" from either observation.
    ordinal_go = (r'第\s*[0-9一二两三四五六七八九十百]+\s*波[，, ]*'
                  r'(?:直接|马上|就能|可以|就|可|能)?(?:离线|游走|出发|走人|走中|走)'
                  r'|\b(?:roam|leave)\s+(?:on\s+)?wave\s*#?\s*\d+\b')
    if re.search(ordinal_go, roam['wave_condition'] + ' ' + roam['return_by'], re.IGNORECASE):
        fail('$.lane_plan.roam.wave_condition', '请用兵线落点或下一批交汇等可复查条件描述窗口，本帧无法给出可离线的绝对波序。')
    fact_ids = set(lane['fact_refs'])
    bottom_facts = {fid for fid, f in facts.items() if f.get('field') == 'lane_current_units_and_groups'
                    and f.get('entity_id') == 'lane:bot' and isinstance(f['value'], dict)
                    and f['value'].get('lane') == 'bot'
                    and f.get('observed_at_seconds') == frame['decision']['at_seconds']}
    if bottom_facts and fact_ids.isdisjoint(bottom_facts):
        fail('$.lane_plan.fact_refs', '此帧已有下路兵线观测，需引用它评估离线条件。')
    if not any(isinstance(facts.get(fid, {}).get('entity_id'), str)
               and facts[fid]['entity_id'].removeprefix('entity:') in quartet.values() for fid in fact_ids):
        fail('$.lane_plan.fact_refs', '对线判断需要至少一条属于本场下路四人之一的本人或对手、队友依据。')
    option = next((o for o in answer['options'] if o['id'] == roam['option_id']), None)
    if option is None:
        fail('$.lane_plan.roam.option_id', '游走得失须引用本卡实际比较的一条出发路线。')
    elif not option['gains']:
        fail('$.lane_plan.roam.option_id', '所引用的路线需写出离开下路可能换来的具体收益。')
    elif option['status'] == 'supported' and not any(
            facts[fid]['value'].get('count_scope') == 'observer_filtered_visible_units'
            for fid in bottom_facts & fact_ids):
        fail('$.lane_plan.roam.option_id', '下路兵线缺失或只有己方兵时，可离线的窗口只能给条件判断。')
    if not answer['open_questions']:
        fail('$.open_questions', '请指出影响离线或交手的未确认信息，以及玩家如何复查。')


def validate_decision(answer, frame):
    """Check an answer against its frozen frame, without a model call.

    A scoped calculator may register a record under ``frame.calculations`` with
    a ``time_budget`` mapping. A numerical answer must exactly match such a
    host-provided range. An arbitrary reference ID alone never licenses numbers.
    Round-specific records are bound to the corresponding action as well.
    """
    from .brief_update import is_brief, validate_brief
    if is_brief(frame):
        return validate_brief(answer, frame)
    errors = []
    reader = None

    def fail(path, message):
        errors.append({'path': path, 'message': message})

    def result():
        return {**({'player_perspective': reader} if reader is not None and not errors else {}),
                'status': 'FAIL' if errors else 'PASS', 'errors': errors,
                'tactical_quality': 'not_evaluated',
                'answer_sha256': _fingerprint(answer),
                'limitations': ['仅检查结构、引用、数值一致性与显式条件；不证明文字由引用推出。',
                                '行动观测只支持对应动作发生，不证明会继续、全部前提就绪或行动文字逻辑。',
                                '不证明战术最优、队友会执行或实际到场；需要场景评阅。']}

    _check_json(answer, '$', errors)
    if errors:
        return result()
    if not isinstance(frame, dict) or frame.get('schema') != 'decision-frame/v1':
        fail('frame', '需要 decision-frame/v1 输入。')
        return result()
    if not isinstance(frame.get('task', {}), dict):
        fail('frame.task', '帧的复盘任务无效。')
        return result()
    _validate_shape(answer, output_schema(frame), '$', errors)
    decision = frame.get('decision')
    facts = frame.get('facts')
    lineup = frame.get('lineup')
    references = frame.get('references')
    calculations = frame.get('calculations')
    if (not isinstance(decision, dict) or not _number(decision.get('at_seconds'))
            or not isinstance(facts, dict) or not isinstance(lineup, list) or not isinstance(frame.get('task', {}), dict)
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
    player = decision.get('player_entity_id')
    if not isinstance(player, str) or not player.strip():
        fail('frame.decision.player_entity_id', '需指定一名被复盘的玩家。')
        return result()
    task = frame.get('task', {})
    if 'player_perspective' in task:
        pov = task['player_perspective']
        hero = actors.get(player, {})
        team = decision.get('observer_team_id')
        if (not isinstance(pov, dict) or pov.get('player_entity_id') != player
                or type(team) is not int or team not in (100, 200) or not _json_equal(pov.get('observer_team_id'), team)
                or hero.get('relation') != 'ally' or 'champion' not in pov
                or pov['champion'] != hero.get('champion')
                or (pov['champion'] is not None and not isinstance(pov['champion'], str))):
            fail('frame.task.player_perspective', '复盘对象须是当前观察方阵容中的指定玩家。')
        else:
            reader = dict(player_entity_id=player, champion=hero.get('champion'), observer_team_id=team, at_seconds=at)
            if quiet_personal_frame(task):
                reader['quiet_personal_frame'] = True
            comparison = task.get('round_comparison')
            if 'macro_round' in answer and isinstance(comparison, dict) and isinstance(comparison.get('target'), str):
                reader['route_target'] = comparison['target']
    if 'round_comparison' in frame.get('task', {}):
        expected_options = ({'continue_action', 'change_action'} if task.get('personal_action_review')
                            else {'leave_now','help_then_leave','clear_then_leave'})
        if {o['id'] for o in answer['options']} != expected_options:
            fail('$.options', '本次回合的选项 ID 与当前行动比较模式不符。')
        actions = [o['action'].strip() for o in answer['options']]
        if len(set(actions)) != len(actions):
            fail('$.options', '每个选项需分别说明玩家可以执行的第一步。')
        prose = [('objective', answer['objective']), ('recommendation.why', answer['recommendation']['why'])]
        if 'macro_round' in answer:
            prose.extend(('macro_round.' + key, answer['macro_round'][key])
                         for key in ('map_goal', 'enabling_condition', 'opponent_reply'))
        if 'lane_plan' in answer:
            lane = answer['lane_plan']
            prose.extend(('lane_plan.' + key, lane[key]) for key in ('pressure', 'if_open', 'if_denied'))
            prose.extend(('lane_plan.roam.' + key, lane['roam'][key])
                         for key in ('wave_condition', 'return_by', 'short_play', 'committed_play'))
        if reader:
            prose.append(('immediate_action', answer['immediate_action']))
        prose.extend(('recommendation.switch_conditions', s) for s in answer['recommendation']['switch_conditions'])
        for i, option in enumerate(answer['options']):
            if re.fullmatch(r'(?:走法|选项|方案|option|action|plan)\s*[-#._]?\s*(?:[a-z]|[0-9]+|[一二三甲乙丙])',
                            option['action'].strip(), flags=re.IGNORECASE):
                fail(f'$.options[{i}].action', '选项编号没有说明玩家的第一步动作。')
            if any(re.fullmatch(r'[+-]?\d+(?:\.\d+)?', s.strip()) for s in option['costs']):
                fail(f'$.options[{i}].costs', '需要说明会付出什么代价，单独的数字没有对象或单位。')
            prose.extend((f'options[{i}].{key}', option[key]) for key in ('action','end_state'))
            for key in ('costs','gains','abort_signals','preconditions','enemy_responses'):
                prose.extend((f'options[{i}].{key}', s) for s in option[key])
        for path, value in prose:
            if (not any(c.isalnum() for c in value) or '%_' in value
                    or re.fullmatch(r'[a-zA-Z]+(?:_[a-zA-Z0-9]+)+', value.strip())):
                fail('$.'+path, '需要可读的具体说明。当前字段含内部标识、占位符或标点残片。')

    def fact_refs(ids, path):
        for i, fid in enumerate(ids):
            if fid.startswith('h_'):
                fail(f'{path}[{i}]', '历史引用不能作为当前事实；请引用本帧 facts。')
                continue
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

    previous = task.get('previous_plan') if isinstance(task, dict) else None
    require_credit = task.get('require_objective_credit') is True
    if require_credit or answer.get('objective_kill_claims'):
        events = dragon_kill_events(frame)
        claimed = set()
        credit_lines = []
        for i, claim in enumerate(answer.get('objective_kill_claims', [])):
            fid = claim['fact_id']
            path = f'$.objective_kill_claims[{i}]'
            event = events.get(fid)
            if fid in claimed:
                fail(path + '.fact_id', '同一击杀依据重复提交。')
            claimed.add(fid)
            if fid not in seen_facts or event is None:
                fail(path + '.fact_id', '目标击杀须引用当时可知的击杀事件并列入 facts_used。')
            elif claim['killer_entity_id'] != event['killer_entity_id']:
                fail(path + '.killer_entity_id', '个人击杀须有明确署名并与本局阵容一致的击杀记录。')
            else:
                side = '蓝方' if event['credited_team_id'] == 100 else '红方'
                name = DRAGON_DISPLAY_NAMES.get(event['objective_name'], event['objective_name'])
                killer = event['killer_entity_id']
                if killer is None:
                    credit_lines.append(f'{name}由{side}击杀。这条公告能确认队伍，个人击杀者未知。')
                else:
                    champion = actors[killer].get('champion') or killer
                    credit_lines.append(f'{name}的击杀记在{side} {champion} 名下。')
        if require_credit and seen_facts.intersection(events) - claimed:
            fail('$.objective_kill_claims', '引用目标击杀事件时，须逐条核对队伍及可证实的个人归属。')
        if reader is not None and credit_lines:
            reader['objective_credit_lines'] = list(dict.fromkeys(credit_lines))
    transitions = task.get('round_transition')
    changes = transitions.get('changes', {}) if isinstance(transitions, dict) else {}

    def cited_transition(current_refs, change_refs, path, evidence_key):
        fact_refs(current_refs, path + '.' + evidence_key)
        for i, fid in enumerate(current_refs):
            if fid not in seen_facts:
                fail(f'{path}.{evidence_key}[{i}]', '判断依据必须同时列入 facts_used 并核对当前值。')
        for i, change_id in enumerate(change_refs):
            change = changes.get(change_id) if isinstance(changes, dict) else None
            if not isinstance(change, dict):
                fail(f'{path}.change_refs[{i}]', '变化引用不在本帧 round_transition.changes 中。')
                continue
            if change.get('current_fact_id') not in current_refs:
                fail(f'{path}.change_refs[{i}]', f'引用变化对应的 current_fact_id 必须列入 {evidence_key}。')

    if 'team_coordination' in answer:
        plan = answer['team_coordination']
        path = '$.team_coordination'
        cited_transition(plan['fact_ids'], [], path, 'fact_ids')
        mode, recipient = plan['mode'], plan['recipient_id']
        if mode == 'no_signal':
            if recipient is not None or 'ping_kind' in plan:
                fail(path, '不发信号时请将收件人留空，并省略信号类型。')
        else:
            if recipient == player or actors.get(recipient, {}).get('relation') != 'ally':
                fail(path + '.recipient_id', '沟通对象须是本局同队的另一位玩家。')
            elif reader is not None:
                reader['coordination_recipient'] = actors[recipient].get('champion') or recipient
            if not plan['response_cue'].strip():
                fail(path + '.response_cue', '请说明等到哪一步、看队友做什么才继续。')
        if bool(plan['message'].strip()) != (mode == 'communicate'):
            fail(path + '.message', '仅建议现在沟通时填写一句可发给队友的短话。')
        if mode == 'already_signaled' and not any(
            kind == plan.get('ping_kind') for fid, kind in own_ping_kinds(frame).items()
            if fid in plan['fact_ids']
        ):
            fail(path + '.ping_kind', '请指定信号类型并引用本帧窗口内本人实际发过的同类信号。')
        for key in ('trigger', 'known_information', 'intended_action', 'fallback'):
            if not any(c.isalnum() for c in plan[key]):
                fail(path + '.' + key, '需要可读的具体说明。')

    if 'lane_plan' in answer:
        lane_refs = answer['lane_plan']['fact_refs']
        cited_transition(lane_refs, [], '$.lane_plan', 'fact_refs')
        _check_lane_plan(answer, frame, facts, actors, player, fail)
        choice = answer['lane_plan'].get('destination_choice')
        if choice:
            path = '$.lane_plan.destination_choice'
            cited_transition(choice['fact_refs'], [], path, 'fact_refs')
            if choice['preferred'] == choice['alternative']:
                fail(path, '请比较两个不同去处，并给出会改选的信号。')
            roles = ['ally_mid', 'ally_jungle']
            if 'top_lane' in (choice['preferred'], choice['alternative']):
                roles.append('ally_top')
            for role in roles:
                actor = task['roam_actors'].get(role)
                samples = {fid for fid in frame.get('allied_path_fact_ids', [])
                           if facts.get(fid, {}).get('entity_id') == actor and actor is not None}
                if samples and samples.isdisjoint(choice['fact_refs']):
                    fail(path + '.fact_refs', '比较去处时须核对相应队友的位置采样与信息年龄。')
    if 'macro_round' in answer:
        macro = answer['macro_round']
        cited_transition(macro['fact_refs'], macro['change_refs'], '$.macro_round', 'fact_refs')
        # A calculator destination is just a hypothetical trip. Only label the
        # card with the pit when this plan cites the player's current live view.
        if (reader and reader.get('route_target') == 'dragon'
                and macro['transition'] in ('start', 'continue') and macro['intent'] == 'pressure'
                and any(_live_dragon_in_pit(facts.get(fid, {}))
                        and facts[fid].get('observed_at_seconds') == at
                        and facts[fid].get('temporal_scope') == 'player_view_at_video_frame'
                        for fid in macro['fact_refs'])):
            reader['live_dragon_context'] = True
        if macro['transition'] == 'close' and not macro['change_refs']:
            fail('$.macro_round.change_refs', '结束上一轮须引用使地图计划改变的当时观测变化。')
        # A frozen linked frame can predate the age filter in the linker.
        if macro['transition'] == 'close' and isinstance(previous, dict) and isinstance(changes, dict):
            finishes = _dragon_completion_changes(previous, frame, changes)
            if finishes and finishes.isdisjoint(macro['change_refs']):
                fail('$.macro_round.change_refs', '上一轮施压依据为仍存活的亚龙，收尾须引用本帧已公开的击杀公告对应的变化。')
            history = previous.get('historical_facts', {})
            for change_id in macro['change_refs']:
                change = changes.get(change_id)
                if not isinstance(change, dict):
                    continue  # the missing change has already been reported
                old = history.get(change.get('historical_fact_id')) if isinstance(history, dict) else None
                new = facts.get(change.get('current_fact_id'))
                if isinstance(old, dict) and isinstance(new, dict) and old.get('field') == new.get('field') == 'observer_visibility':
                    if 'value' in old and _json_equal(observation_value(old), observation_value(new)):
                        fail('$.macro_round.change_refs', '上次出现的位置仅信息年龄增加，不能当作新地图观测。')
        if macro['transition'] in ('start', 'continue') and macro['intent'] == 'unknown':
            fail('$.macro_round.intent', '提出或延续地图计划时要说明本人当前目的。')
    continuation = answer.get('continuation')
    if previous is None:
        if continuation is not None:
            fail('$.continuation', '本帧没有上一计划，不能提交承接处置。')
    elif (not isinstance(previous, dict)
          or not isinstance(previous.get('previous_frame_id'), str)
          or not previous['previous_frame_id'].strip()):
        fail('frame.task.previous_plan', '上一计划缺少有效的 previous_frame_id。')
    elif continuation is None:
        fail('$.continuation', '本帧含上一计划，必须说明保留、改选或取消及当前依据。')
    else:
        path = '$.continuation'
        if continuation['previous_frame_id'] != previous['previous_frame_id']:
            fail(path + '.previous_frame_id', '承接引用的上一决策帧不匹配。')
        cited_transition(continuation['current_fact_refs'], continuation['change_refs'], path, 'current_fact_refs')
        if continuation['disposition'] in ('revise', 'cancel') and not continuation['change_refs']:
            fail(path + '.change_refs', '改选或取消上一计划必须引用至少一条当前变化。')

    role_actors = []
    for i, role in enumerate(answer['role_assignments']):
        actor = role['actor_id']
        role_actors.append(actor)
        if actor not in actors:
            fail(f'$.role_assignments[{i}].actor_id', '英雄 ID 不在本局阵容中。')
        fact_refs(role['fact_refs'], f'$.role_assignments[{i}].fact_refs')
    if len(role_actors) != len(set(role_actors)):
        fail('$.role_assignments', '英雄职责记录重复。')
    if player not in role_actors:
        fail('$.role_assignments', '必须说明被复盘玩家的职责，包括职责未知的情况。')
    for relation, label in [('ally', '队友'), ('enemy', '对手')]:
        ids = {key for key, actor in actors.items()
               if actor.get('relation') == relation and key != player}
        if not quiet_personal_frame(task) and ids and not ids.intersection(role_actors):
            fail('$.role_assignments', f'至少需要结合一名{label}的职责/威胁。')

    options = {}
    for i, option in enumerate(answer['options']):
        path = f'$.options[{i}]'
        if option['id'] in options:
            fail(path + '.id', '候选行动 ID 重复。')
        options[option['id']] = option
        if 'actor_id' in option and option['actor_id'] != player:
            fail(path + '.actor_id', '每种候选动作都须由本次被复盘的玩家执行。')
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
            elif isinstance(calculations[cid], dict) and calculations[cid].get('option_id', option['id']) != option['id']:
                fail(f'{path}.time_budget.calculation_refs[{j}]', '时间计算属于另一种走法。')
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
    if 'follow_through' in answer:
        chain = answer['follow_through']
        if chain['option_id'] != preferred:
            fail('$.follow_through.option_id', '后续方案必须承接本次首选。')
        if preferred is None and chain['steps']:
            fail('$.follow_through.steps', '没有首选时不能安排执行链。')
        if preferred is not None and not chain['steps']:
            if 'decision_guidance' not in task.get('knowledge_handbook', {}):
                fail('$.follow_through.steps', '此历史帧的首选须给出至少一步条件后续。')
            elif not chain['limits']:
                fail('$.follow_through.limits', '请说明为什么推演在当前行动收束，并在改选条件中指出下次观察信号。')
        for i, step in enumerate(chain['steps']):
            path = f'$.follow_through.steps[{i}]'
            if step['after_step'] != i:
                fail(path + '.after_step', '后续步骤依次承接当前首选及上一条件步骤。')
            fact_refs(step['fact_refs'], path + '.fact_refs')
            if any(fid not in seen_facts for fid in step['fact_refs']):
                fail(path + '.fact_refs', '后续步骤的当前依据也须列入 facts_used。')
            for j, rid in enumerate(step['knowledge_refs']):
                if references.get(rid, {}).get('kind') != 'conditional_coaching_knowledge':
                    fail(f'{path}.knowledge_refs[{j}]', '后续经验须引用本帧冻结的知识卡。')
    if reader and 'round_comparison' in task and preferred in options:
        # This index contains sampled start positions, including each ally's.
        # A teammate's sample does not locate the player choosing a route.
        indexes = frame.get('allied_path_fact_ids', [])
        if not isinstance(indexes, list) or not all(isinstance(fid, str) for fid in indexes):
            fail('frame.allied_path_fact_ids', '己方英雄位置样本索引无效。')
        else:
            own_paths = {fid for fid in indexes if fid in facts and facts[fid].get('entity_id') == player
                         and facts[fid].get('field') == 'allied_path_start_sample'}
            if own_paths and not own_paths.intersection(options[preferred]['fact_refs']):
                fail('$.recommendation.preferred_option_id', '移动首选需引用本人最近的位置样本，才能从你的出发点比较走法。')
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


def own_ping_kinds(frame):
    """Only verified own sends inside this POV's recorded signal window qualify."""
    scope = frame.get('recent_team_pings', {})
    decision = frame['decision']
    start, at = scope.get('window_start_seconds'), decision['at_seconds']
    if scope.get('coverage') != 'verified_events_only' or not _number(start):
        return {}
    result = {}
    for fid in scope.get('fact_ids', []):
        fact = frame['facts'].get(fid, {})
        v = fact.get('value')
        sent = fact.get('observed_at_seconds')
        if (fact.get('field') == 'map_ping_sent' and fact.get('temporal_scope') == 'communication_event'
                and fact.get('entity_id') == decision['player_entity_id'] and isinstance(v, dict)
                and v.get('known_as') == 'own_sent' and v.get('observer_team_id') == decision['observer_team_id']
                and v.get('kind') in PING_TYPES and _number(sent) and _number(v.get('available_at_seconds'))
                and start <= sent <= v['available_at_seconds'] <= at):
            result[fid] = v['kind']
    return result


def _coordination_lines(answer, reader):
    plan = answer.get('team_coordination')
    if plan is None:
        return []
    if plan['mode'] == 'no_signal':
        return ['**这时可以不发信号**　' + plan['trigger'], '',
                '**你的走法**　' + plan['intended_action'], '', '**局势变化时**　' + plan['fallback'], '']
    recipient = reader.get('coordination_recipient') or plan['recipient_id']
    lines = [f'## 和 {recipient} 怎么配合', '', '**何时沟通**　' + plan['trigger'], '',
             '**当时的依据**　' + plan['known_information'], '',
             '**你准备怎么做**　' + plan['intended_action'], '']
    if plan['mode'] == 'communicate':
        lines += ['**可以这样提醒**　' + plan['message'], '']
    else:
        lines += ['**已发过的信号**　' + PING_TYPES[plan['ping_kind']] + '，此时可以先观察。', '']
    return lines + ['**看队友如何接应**　' + plan['response_cue'], '',
                    '**等不到接应时**　' + plan['fallback'], '']


def _macro_lines(answer):
    macro = answer.get('macro_round')
    if macro is None:
        return []
    return [f"## 地图计划 · {MACRO_TRANSITIONS[macro['transition']]}", '',
            f"**{MACRO_INTENTS[macro['intent']]}**　{macro['map_goal']}", '',
            f"**这一手的条件**　{macro['enabling_condition']}", '',
            f"**对方可能怎么走**　{macro['opponent_reply']}", '']


def _lane_lines(answer, options):
    plan = answer.get('lane_plan')
    if plan is None:
        return []
    roam = plan['roam']
    option = options[roam['option_id']]
    status = {'conditional': '等条件满足再走', 'ruled_out': '当前排除', 'supported': '当前可考虑'}
    choice = plan.get('destination_choice')
    comparison = ([f"**这一拍先选{ROAM_DESTINATIONS[choice['preferred']]}**　{choice['why']}", '',
                   f"**何时改选{ROAM_DESTINATIONS[choice['alternative']]}**　{choice['switch_if']}", '']
                  if choice else [])
    return ['## 下路怎么打', '', plan['pressure'], '',
            '**对手给机会**　' + plan['if_open'], '',
            '**对手不给机会**　' + plan['if_denied'], '',
            '## 哪一波能离线', '', roam['wave_condition'], '', *comparison,
            '**短离线**　' + roam['short_play'], '',
            '**支援中野**　' + roam['committed_play'], '',
            f"**{status[option['status']]}**　{option['action']}", '',
            '**游走能换来什么**　' + '；'.join(option['gains']), '',
            '**搭档独自留线的代价**　' + '；'.join(option['costs']), '',
            '**取消条件**　' + '；'.join(option['abort_signals']), '',
            '**什么时候回下路**　' + roam['return_by'], '']


def review_scope(bundle, source_name=None):
    """Label a reviewed perspective. The host supplies a source name only after binding the input."""
    frame = bundle['frame']
    decision = frame['decision']
    player = decision['player_entity_id']
    hero = next(h for h in frame['lineup'] if h['entity_id'] == player)
    team = {100: '蓝方', 200: '红方'}[decision['observer_team_id']]
    if not source_name:
        digest = bundle['audit'].get('source_replay_sha256')
        source_name = 'SHA-256 ' + digest if digest else '来源未标记'
    parts = ['回放 ' + source_name]
    if (decision.get('map_mode') == 'practice_tool'
            and decision.get('environment_status') == 'practice_tool_controls_on_player_screen'):
        parts.append('训练模式')
    elif len(frame['lineup']) == 10:
        parts.append('十人阵容')
    parts.append(f"选定视角为{team} {hero['champion'] or player}")
    return ' · '.join(parts)


def _render_player_card(answer, reader, review_scope_label=None):
    from .coaching_knowledge import follow_through_lines
    options = {option['id']: option for option in answer['options']}
    rec = answer['recommendation']
    best = options.get(rec['preferred_option_id'])
    fallback = options.get(rec['fallback_option_id'])
    clock = int(reader['at_seconds'])
    route_heading = '小龙在场时怎么选' if reader.get('live_dragon_context') else '接下来怎么选'
    exact = reader['at_seconds']
    stamp = f'{clock//60:02}:{clock%60:02}' if exact == clock else f'{int(exact//60):02}:{exact%60:06.3f}'
    lines = [f"# {stamp} · 你的 {reader['champion'] or reader['player_entity_id']} 复盘", '',
             *([review_scope_label, ''] if review_scope_label else []),
             *reader.get('objective_credit_lines', []), *([''] if reader.get('objective_credit_lines') else []),
             answer['objective'], '', '## 你现在的第一步', '', answer['immediate_action'], '']
    if reader.get('quiet_personal_frame'):
        lines += [rec['why'], '']
        if best and best['preconditions']:
            lines += ['**动手前先确认**　' + ' '.join(best['preconditions']), '']
        signals = [*(best['abort_signals'] if best else []), *rec['switch_conditions']]
        lines += ['**何时改选**　' + ' '.join(dict.fromkeys(signals)), '']
        if fallback:
            lines += ['**你的备选**　' + fallback['action'], '']
        lines += follow_through_lines(answer)
        return '\n'.join(lines)
    lines += [*_coordination_lines(answer, reader), *_lane_lines(answer, options), *_macro_lines(answer),
              '## ' + route_heading, '']
    if best:
        lines += [best['action'], '', rec['why'], '']
        if best['preconditions']:
            lines += ['动手前先确认', '', *['- ' + s for s in best['preconditions']], '']
        lines += ['你要承担的代价', '', *['- ' + s for s in best['costs']], '']
        if best['ally_requirements']:
            lines += ['这一步需要的队友配合', '']
            for need in best['ally_requirements']:
                state = '已观测到动作' if need['status'] == 'observed' else '待确认'
                lines.append(f"- {need['required_action']}（{state}）")
            lines.append('')
        lines += ['对手可能怎么应对', '', *['- ' + s for s in best['enemy_responses']], '',
                  '**如果这一步做成**　' + best['end_state'], '']
    else:
        lines += ['现有信息不足以为你选定首选。', '', rec['why'], '']
    lines += follow_through_lines(answer)
    if fallback:
        lines += ['## 你的备选', '', fallback['action'], '']
        if fallback['preconditions']:
            lines += ['这条路的前提', '', *['- ' + s for s in fallback['preconditions']], '']
    for option in answer['options']:
        if option is not best and option is not fallback:
            label = '已排除' if option['status'] == 'ruled_out' else '其他走法'
            lines += [f"**{label}**　{option['action']}", '']
    signals = [*(best['abort_signals'] if best else []), *rec['switch_conditions']]
    lines += ['## 你看到什么时该改', '', *['- ' + s for s in dict.fromkeys(signals)], '']
    if 'continuation' in answer:
        continuation = answer['continuation']
        action = {'retain': '保留', 'revise': '调整', 'cancel': '取消'}[continuation['disposition']]
        lines += [f"**{action}上次建议的依据**　{continuation['reason']}", '',
                  '你当时是否执行了上次建议，尚无操作证据。', '']
    if answer['open_questions']:
        lines += ['仍需确认', '', *['- ' + s for s in answer['open_questions']], '']
    if any(isinstance(f['value'], dict) and f['value'].get('count_scope') == 'own_team_observed_live_only'
           for f in answer['facts_used']):
        lines += ['这份兵线记录只覆盖己方小兵。你当时能否看到敌兵、能补几只仍未知。', '']
    return '\n'.join(lines)


def render_decision(answer, validation, *, review_scope_label=None):
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
    from .brief_update import SCHEMA as BRIEF_SCHEMA
    if answer.get('schema') == BRIEF_SCHEMA:
        return '\n\n'.join([review_scope_label or '个人短更新', answer['change'],
                             answer['immediate_action'], answer['switch_if']]) + '\n'
    if 'player_perspective' in validation:
        return _render_player_card(answer, validation['player_perspective'], review_scope_label)
    rec = answer['recommendation']
    options = {o['id']: o for o in answer['options']}
    best = options.get(rec['preferred_option_id'])
    fallback = options.get(rec['fallback_option_id'])
    levels = {'supported': '有依据推荐', 'conditional': '条件推荐',
              'insufficient_evidence': '暂不能排序'}
    lines = ['# 本回合决策卡', '', f"目标：{answer['objective']}", '',
             f"结论：{levels[rec['confidence']]}",
             f"首选：{best['action'] if best else '现有信息不足以确定首选'}", '',
             rec['why'], '', *_lane_lines(answer, options), *_macro_lines(answer)]
    if any(isinstance(fact['value'], dict) and fact['value'].get('count_scope') == 'own_team_observed_live_only'
           for fact in answer['facts_used']):
        lines += ['兵线依据只覆盖己方小兵。该记录无法确定当时玩家能否看见敌兵、能补几个或多久清完。', '']
    if fallback:
        lines += [f"退路：{fallback['action']}", '']
    continuation = answer.get('continuation')
    if continuation is not None:
        dispositions = {'retain': '保留', 'revise': '改选', 'cancel': '取消'}
        lines += [f"上一计划承接：{dispositions[continuation['disposition']]}",
                  f"上一决策帧：{continuation['previous_frame_id']}",
                  '上一行动执行：未知；先前建议不等于已经执行。',
                  '承接原因：' + continuation['reason'],
                  '当前事实引用：' + '、'.join(continuation['current_fact_refs']),
                  '变化引用：' + ('、'.join(continuation['change_refs']) or '无新增变化引用'), '']
    option_levels = {'supported': '已具备条件', 'conditional': '待条件满足',
                     'ruled_out': '已排除，不执行'}
    for option in answer['options']:
        lines += [f"## 候选（{option_levels[option['status']]}）：{option['action']}", '',
                  '成立条件：' + ('；'.join(option['preconditions']) or '未列待满足前提'),
                  '代价：' + '；'.join(option['costs']),
                  '完成后状态：' + option['end_state'],
                  '停止信号：' + '；'.join(option['abort_signals']),
                  '事实引用：' + '、'.join(option['fact_refs']), '']
    from .coaching_knowledge import follow_through_lines
    lines += follow_through_lines(answer)
    lines += ['## 何时改计划', ''] + ['- ' + s for s in rec['switch_conditions']]
    if answer['open_questions']:
        lines += ['', '## 尚需判断的条件', ''] + ['- ' + s for s in answer['open_questions']]
    lines += ['', '结构与引用检查通过；战术质量尚未评阅。', '']
    return '\n'.join(lines)
