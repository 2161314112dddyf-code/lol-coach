"""Frame-scoped JSON grammar and lossless evidence shorthand for a local model."""
from copy import deepcopy
import json

from .decision_contract import (MACRO_REVIEW, SCHEMA, SUPPORT_LANE_REVIEW, TEAM_COORDINATION_REVIEW,
                                TIME_FIELDS, own_ping_kinds, quiet_personal_frame)
from .objective_credit import dragon_kill_events
from .reasoning_frame import canonical


ACTIONS = ('leave_now', 'help_then_leave', 'clear_then_leave')


def _object(fields):
    return dict(type='object', properties=fields, required=list(fields), additionalProperties=False)


def _choice(values):
    return {'enum': list(values)}


def _list(item, low=0, high=2):
    return dict(type='array', items=item, minItems=low, maxItems=high)


def _refs(keys, low=0, high=2):
    ids = sorted(keys)
    if not ids and low:
        raise ValueError('required_reference_catalog_empty')
    return _list(_choice(ids) if ids else {'type':'string'}, low, min(high, len(ids)))


def _payload(request):
    payload = json.loads(request['messages'][1]['content'])
    if 'decision_frame' not in payload or request['response_schema']['properties']['schema'].get('const') != SCHEMA:
        raise ValueError('unsupported_round_format')
    frame = payload['decision_frame']
    if 'round_comparison' not in frame['task']:
        raise ValueError('unbound_round_model_format')
    return frame


def _bounded(schema):
    result = deepcopy(schema)
    if result.get('type') == 'string':
        result['maxLength'] = 48
    if result.get('type') == 'array':
        result['maxItems'] = min(result.get('maxItems', 2), 2)
        result['items'] = _bounded(result['items'])
    if 'properties' in result:
        result['properties'] = {k:_bounded(v) for k,v in result['properties'].items()}
    return result


def _answer_grammar(frame, schema):
    actions = ('continue_action', 'change_action') if frame['task'].get('personal_action_review') else ACTIONS
    fields = _bounded(schema)['properties']
    facts, refs = frame['facts'], frame['references']
    fields['schema'] = _choice([SCHEMA])
    fields['frame_id'] = _choice([frame['frame_id']])
    fields['facts_used'] = _refs(facts, 1, 8)
    if 'follow_through' in fields:
        chain = fields['follow_through']['properties']
        chain['option_id'] = _choice([None, *actions])
        chain['baseline_if_unchanged']['maxLength'] = 240
        chain['steps']['maxItems'] = 3
        step = chain['steps']['items']['properties']
        step['fact_refs'] = _refs(facts, 1, 8)
        step['knowledge_refs'] = _refs([rid for rid, row in refs.items()
            if row.get('kind') == 'conditional_coaching_knowledge'], 0, 3)
        for key in ('action', 'expected_state', 'check_when', 'if_confirmed', 'if_not_confirmed'):
            step[key]['maxLength'] = 240
    if 'lane_plan' in fields:
        plan = fields['lane_plan']['properties']
        plan['fact_refs'] = _refs(facts, 1, 16)
        if 'destination_choice' in plan:
            choice = plan['destination_choice']['properties']
            choice['fact_refs'] = _refs(facts, 1, 8)
            for key in ('why', 'switch_if'):
                choice[key]['maxLength'] = 160
        plan['roam']['properties']['option_id'] = _choice(actions)
        for key in ('pressure', 'if_open', 'if_denied'):
            plan[key]['maxLength'] = 120
        for key in ('wave_condition', 'return_by', 'short_play', 'committed_play'):
            plan['roam']['properties'][key]['maxLength'] = 120
        fields['facts_used'] = _refs(facts, 1, 16)
    if 'macro_round' in fields:
        macro_fields = fields['macro_round']['properties']
        changes = frame['task'].get('round_transition', {}).get('changes', {})
        macro_fields['fact_refs'] = _refs(facts, 1)
        variants = []
        for transition in macro_fields['transition']['enum']:
            if transition == 'close' and not changes:
                continue
            branch = deepcopy(macro_fields)
            branch['transition'] = _choice([transition])
            if transition in ('start', 'continue'):
                branch['intent']['enum'].remove('unknown')
            branch['change_refs'] = _refs(changes, int(transition == 'close'))
            variants.append(_object(branch))
        fields['macro_round'] = {'anyOf': variants}
    if 'objective_kill_claims' in fields:
        claims = []
        for fid, event in dragon_kill_events(frame).items():
            killer = event['killer_entity_id']
            claims.append(_object({'fact_id': _choice([fid]), 'killer_entity_id': _choice([killer])}))
        if claims:
            fields['objective_kill_claims'] = _list({'anyOf': claims}, high=len(claims))
        else:
            del fields['objective_kill_claims']
    player = frame['decision']['player_entity_id']
    groups = {'player':[player]}
    for relation in ('ally','enemy'):
        ids = [r['entity_id'] for r in frame['lineup'] if r['relation']==relation and r['entity_id']!=player]
        if ids:
            groups[relation] = ids
    quiet = quiet_personal_frame(frame['task'])
    role_groups = {'player': [player]} if quiet else dict(groups)
    if 'lane_plan' in fields and not quiet:
        duo = frame['task']['bottom_lane_actors']
        role_groups.update(ally=[duo['carry']], enemy=[duo['enemy_carry']], enemy_support=[duo['enemy_support']])
    role_template = fields['role_assignments']['items']
    rows = {}
    for group, ids in role_groups.items():
        role = deepcopy(role_template)
        role['properties'].update(actor_id=_choice(ids), fact_refs=_refs(facts))
        rows[group] = role
    fields['role_assignments'] = _object(rows)
    if 'team_coordination' in fields:
        template = fields['team_coordination']['properties']
        variants = []
        own_sends = own_ping_kinds(frame)
        for mode in template['mode']['enum']:
            if mode != 'no_signal' and 'ally' not in groups:
                continue
            if mode == 'already_signaled' and not own_sends:
                continue
            props = deepcopy(template)
            props.update(mode=_choice([mode]), recipient_id=_choice(
                [None] if mode == 'no_signal' else groups['ally']), fact_ids=_refs(facts, 1, 8))
            if mode == 'already_signaled':
                props['ping_kind'] = _choice(sorted(set(own_sends.values())))
            elif mode == 'no_signal':
                del props['ping_kind']
            if mode == 'communicate':
                props['message']['minLength'] = 1
            else:
                props['message'] = _choice([''])
            if mode != 'no_signal':
                props['response_cue']['minLength'] = 1
            variant = _object(props)
            if mode == 'communicate':
                variant['required'].remove('ping_kind')
            variants.append(variant)
        fields['team_coordination'] = {'anyOf': variants}
    if len(frame['lineup']) > len(rows):
        other = deepcopy(role_template)
        other['properties'].update(actor_id=_choice([r['entity_id'] for r in frame['lineup']]),
                                   fact_refs=_refs(facts))
        fields['role_assignments']['properties']['others'] = _list(other, 0, len(frame['lineup']) - len(rows))

    option_template = fields['options']['items']
    choices = {}
    for action in actions:
        props = deepcopy(option_template['properties'])
        del props['id'], props['time_budget']
        if 'player_perspective' in frame['task']:
            props['actor_id'] = _choice([player])
        cids = [cid for cid,row in frame['calculations'].items()
                if row.get('option_id') == action and 'time_budget' in row]
        props.update(calculation_id=_choice([None, *sorted(cids)]), fact_refs=_refs(facts, 1),
                     reference_refs=_refs(refs))
        ally = props['ally_requirements']['items']['properties']
        ally['fact_refs'] = _refs(facts)
        if 'ally' in groups:
            ally['actor_id'] = _choice(groups['ally'])
        else:
            props['ally_requirements']['maxItems'] = 0
        # Keep the existing decision validator's logical alternatives in the
        # grammar. A model may still choose any supported tactical conclusion.
        variants = []
        for status in props['status']['enum']:
            branch = deepcopy(props)
            branch['status'] = _choice([status])
            if status == 'conditional':
                branch['preconditions']['minItems'] = 1
            if status == 'supported':
                for key in ('preconditions','assumptions'):
                    branch[key]['maxItems'] = 0
                # Only an action explicitly observed in this frame can satisfy
                # a required ally response on a supported option.
                valid_actions = [f for f in facts.values() if f['field']=='action_observation'
                                 and f['temporal_scope']=='observed_action'
                                 and isinstance(f['value'],dict)
                                 and f['value'].get('status') in ('in_progress','completed')]
                if valid_actions:
                    need = branch['ally_requirements']['items']
                    need['properties']['status'] = _choice(['observed'])
                    need['required'] = list(need['properties'])
                else:
                    branch['ally_requirements']['maxItems'] = 0
            variants.append(_object(branch))
        choices[action] = {'anyOf':variants}
    fields['options'] = _object(choices)
    rec = fields['recommendation']['properties']
    complete_budgets = {c.get('option_id') for c in frame['calculations'].values()
                        if all(c.get('time_budget',{}).get(k) is not None for k in TIME_FIELDS)}
    if len(complete_budgets.intersection(actions)) < 2:
        rec['confidence']['enum'].remove('supported')
    recommendations = []
    for preferred in (*actions, None):
        branch = deepcopy(rec)
        branch['preferred_option_id'] = _choice([preferred])
        if preferred is None:
            branch['confidence'] = _choice(['insufficient_evidence'])
            branch['fallback_option_id'] = _choice([None, *actions])
        else:
            branch['fallback_option_id'] = _choice(a for a in actions if a != preferred)
        recommendations.append(_object(branch))
    fields['recommendation'] = {'anyOf':recommendations}
    prior = frame['task'].get('previous_plan')
    if prior:
        cont = fields['continuation']['properties']
        cont.update(previous_frame_id=_choice([prior['previous_frame_id']]), current_fact_refs=_refs(facts,1),
                    change_refs=_refs(frame['task'].get('round_transition',{}).get('changes',{})))
    else:
        del fields['continuation']
    return _object(fields)


def _next_tools(request, frame):
    history = (frame['task'].get('previous_plan') or {}).get('historical_facts', {})
    done, seen_refs, seen_history, request_ids = set(), set(), set(), set()
    for msg in request['messages'][2:]:
        if msg['role'] != 'assistant':
            continue
        for call in json.loads(msg['content']).get('tool_requests', []):
            done.add(call['name'])
            request_ids.add(call['id'])
            args = call['arguments']
            seen_refs.add(args.get('reference_id'))
            seen_history.add(args.get('history_id'))
    # These read-only tools have immutable outputs in a given frame.
    choices = []
    n = 1
    while 'q'+str(n) in request_ids:
        n += 1
    for definition in request['tools']:
        name = definition['function']['name']
        args = deepcopy(definition['function']['parameters'])
        if name in ('get_reference','read_history'):
            key, available = (('reference_id',set(frame['references'])-seen_refs) if name=='get_reference'
                              else ('history_id',set(history)-seen_history))
            if not available:
                continue
            args['properties'][key] = _choice(sorted(available))
        elif name == 'get_ability_parameters':
            args['properties']['champion'] = _choice(sorted({h['champion'] for h in frame['lineup']}))
        elif name == 'calculate_ability_damage':
            ref = frame['task'].get('ability_damage_reference')
            player = frame['task']['player_perspective']['champion']
            slots = frame['references'][ref]['champions'].get(player, []) if ref else []
            targets = [h['entity_id'] for h in frame['lineup'] if h['relation'] == 'enemy']
            if not slots or not targets:
                continue
            args['properties']['target_id'] = _choice(targets)
            args['properties']['hits']['items']['properties']['slot'] = _choice(slots)
        elif name in done and name != 'compare_help_duration':
            continue
        choices.append(_object(dict(id=_choice(['q'+str(n)]), name=_choice([name]), arguments=args)))
    exposed = {tool['function']['name'] for tool in request['tools']}
    mandatory = ({'review_personal_action'} if frame['task'].get('personal_action_review')
                 else {'compare_round_options'}) & exposed
    if 'review_round_plan' in exposed and not quiet_personal_frame(frame['task']) and (
        frame['task'].get('previous_plan') or frame['task'].get('macro_round_review') == MACRO_REVIEW
        or frame['task'].get('bottom_lane_review') == SUPPORT_LANE_REVIEW
        or frame['task'].get('team_coordination_review') == TEAM_COORDINATION_REVIEW
    ):
        mandatory.add('review_round_plan')
    return choices, mandatory - done


def prepare_round_request(request, *, remaining_calls=None):
    """Return a copy of the model-facing messages and the Ollama format object."""
    frame = _payload(request)
    tools, missing = _next_tools(request, frame)
    if remaining_calls is not None and (type(remaining_calls) is not int or remaining_calls < 1):
        raise ValueError('invalid_remaining_model_calls')
    if remaining_calls == 1 and missing:
        raise ValueError('required_round_tools_missing_at_final_call')
    branches = []
    if not missing:
        branches.append(_object({'answer':_answer_grammar(frame,request['response_schema'])}))
    if remaining_calls == 2 and missing:
        required = [t for t in tools if t['properties']['name']['enum'][0] in missing]
        if len(required) != len(missing):
            raise ValueError('required_round_tools_unavailable')
        if len(required) == 1:
            batch = _list(required[0], 1, 1)
        else:
            seen_ids = {call['id'] for msg in request['messages'][2:] if msg['role']=='assistant'
                        for call in json.loads(msg['content']).get('tool_requests', [])}
            i = 1
            for tool in required:
                while 'q'+str(i) in seen_ids:
                    i += 1
                tool['properties']['id'] = _choice(['q'+str(i)])
                i += 1
            # The fixed length already forbids extra items. Ollama rejects a
            # boolean schema for items when converting this tuple to a grammar.
            batch = dict(type='array', prefixItems=required,
                         minItems=len(required), maxItems=len(required))
        branches.append(_object({'tool_requests':batch}))
    elif tools and remaining_calls != 1:
        branches.append(_object({'tool_requests':_list({'anyOf':tools}, 1, 1)}))
    if not branches:
        raise ValueError('required_round_tools_unavailable')
    grammar = branches[0] if len(branches)==1 else {'anyOf':branches}
    messages = deepcopy(request['messages'])
    # The standard (expanded) contract stays in the runner. The model sees the
    # complete public frame, plus instructions for the on-wire representation.
    messages[1]['content'] = canonical({'decision_frame':frame})
    instruction = ('这是此轮本地输出格式。一次只发一个工具请求，或发最终 answer。'
                   'facts_used 只选当前事实 ID。role_assignments 按给定角色位置填写，'
                   '先写你自己能做什么。队友和对手只写会改变你选择的动作或条件。可选 others 补充相关英雄。options 的键必须符合当前契约中的行动 ID。'
                   '每种走法自己写行动、得失、条件和理由，calculation_id 选该走法已登记的计算或 null。'
                   '程序只展开你选的事实及时间值。推荐和承接由你自己判断。每段只写一句具体中文。')
    if quiet_personal_frame(frame['task']):
        instruction += '此刻优先处理本人的兵线或手上这组野，role_assignments 只需 player。必要时可在 others 补直接相关对象。'
    elif frame['task'].get('bottom_lane_review') == SUPPORT_LANE_REVIEW:
        instruction += ('下路角色按 player（你）、ally（搭档）、enemy（敌方射手）、enemy_support（敌辅）填写。'
                        '对线施压和给、不给机会分开写。游走候选的收益和搭档代价放到所引走法，写清出发和回线条件。')
    if frame['task'].get('team_coordination_review') == TEAM_COORDINATION_REVIEW:
        instruction += ('读取 review_round_plan 后，给受本次行动影响的队友一句当时可发的短话，分开写你已知什么、'
                        '准备做什么。response_cue 写到哪个动作前观察队友怎样接应，fallback 写届时未跟进你的退路。'
                        '已发同类信号时用 already_signaled，引用本人的近期发送事实与 ping_kind。'
                        '这一步自己就能做且没有新消息时用 no_signal，trigger 说明理由。队友是否看见或答应仍需证据。')
    if missing:
        instruction += '答复前仍须取得 ' + '、'.join(sorted(missing)) + '。'
    if remaining_calls == 2 and missing:
        instruction += '这是最后一次工具机会，本批一次列齐所有尚缺的必需工具。'
    elif remaining_calls == 1:
        instruction += ('这是最终一次响应，只提交 answer。action 写玩家现在要做的第一步，why 写本帧影响选择的一条观测。'
                        '走法 ID 只用于标识选项。拿不准时写要等什么、什么情况要退。')
    if remaining_calls != 1:
        instruction += ' 可调用工具 '+canonical(request['tools'])
    messages.append(dict(role='user',content=instruction))
    return messages, grammar


def expand_round_response(request, envelope):
    """Only copy facts/time budgets the model selected. Invalid IDs are errors."""
    if not isinstance(envelope,dict) or set(envelope) not in ({'tool_requests'},{'answer'}):
        raise ValueError('invalid_round_envelope')
    if 'tool_requests' in envelope:
        return deepcopy(envelope)
    frame = _payload(request)
    answer = deepcopy(envelope['answer'])
    if not isinstance(answer,dict) or answer.get('frame_id') != frame['frame_id']:
        raise ValueError('round_wire_frame_mismatch')
    chosen = answer['facts_used']
    if not isinstance(chosen,list) or not chosen or not all(isinstance(fid,str) and fid in frame['facts'] for fid in chosen):
        raise ValueError('invalid_selected_fact_ids')
    answer['facts_used'] = [dict(fact_id=fid,value=deepcopy(frame['facts'][fid]['value'])) for fid in dict.fromkeys(chosen)]
    roles = answer['role_assignments']
    roster = {r['entity_id']:r['relation'] for r in frame['lineup']}
    player = frame['decision']['player_entity_id']
    wanted = {rel for eid,rel in roster.items() if eid!=player and rel in ('ally','enemy')} | {'player'}
    lane_roles = None
    if quiet_personal_frame(frame['task']):
        wanted = {'player'}
    elif frame['task'].get('bottom_lane_review') == SUPPORT_LANE_REVIEW:
        duo = frame['task']['bottom_lane_actors']
        lane_roles = dict(player=duo['support'], ally=duo['carry'], enemy=duo['enemy_carry'],
                          enemy_support=duo['enemy_support'])
        wanted = set(lane_roles)
    if not isinstance(roles,dict):
        raise ValueError('invalid_selected_roles')
    others = roles.pop('others', [])
    if set(roles)!=wanted or not isinstance(others,list):
        raise ValueError('invalid_selected_roles')
    for group,role in roles.items():
        actor = role['actor_id']
        if lane_roles:
            if actor != lane_roles[group]:
                raise ValueError('invalid_selected_actor')
        elif (group=='player' and actor!=player) or (group!='player' and (actor==player or roster.get(actor)!=group)):
            raise ValueError('invalid_selected_actor')
    answer['role_assignments'] = [*roles.values(), *others]
    options = answer['options']
    actions = ('continue_action', 'change_action') if frame['task'].get('personal_action_review') else ACTIONS
    if not isinstance(options,dict) or set(options)!=set(actions):
        raise ValueError('invalid_selected_options')
    for action, option in options.items():
        if 'id' in option or 'time_budget' in option or 'calculation_id' not in option:
            raise ValueError('ambiguous_option_encoding')
        cid = option.pop('calculation_id')
        if cid is None:
            budget = dict.fromkeys(TIME_FIELDS)
            budget['calculation_refs'] = []
        else:
            calc = frame['calculations'].get(cid)
            if not calc or calc.get('option_id') != action or not isinstance(calc.get('time_budget'),dict):
                raise ValueError('invalid_selected_calculation')
            budget = {key:deepcopy(calc['time_budget'].get(key)) for key in TIME_FIELDS}
            budget['calculation_refs'] = [cid]
        option.update(id=action,time_budget=budget)
    answer['options'] = list(options.values())
    return {'answer':answer}
