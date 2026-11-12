"""Frame-scoped JSON grammar and lossless evidence shorthand for a local model."""
from copy import deepcopy
import json

from .decision_contract import SCHEMA, TIME_FIELDS
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
    fields = _bounded(schema)['properties']
    facts, refs = frame['facts'], frame['references']
    fields['schema'] = _choice([SCHEMA])
    fields['frame_id'] = _choice([frame['frame_id']])
    fields['facts_used'] = _refs(facts, 1, 8)
    player = frame['decision']['player_entity_id']
    groups = {'player':[player]}
    for relation in ('ally','enemy'):
        ids = [r['entity_id'] for r in frame['lineup'] if r['relation']==relation and r['entity_id']!=player]
        if ids:
            groups[relation] = ids
    role_template = fields['role_assignments']['items']
    rows = {}
    for group, ids in groups.items():
        role = deepcopy(role_template)
        role['properties'].update(actor_id=_choice(ids), fact_refs=_refs(facts))
        rows[group] = role
    fields['role_assignments'] = _object(rows)
    if len(frame['lineup']) > len(rows):
        other = deepcopy(role_template)
        other['properties'].update(actor_id=_choice([r['entity_id'] for r in frame['lineup']]),
                                   fact_refs=_refs(facts))
        fields['role_assignments']['properties']['others'] = _list(other, 0, len(frame['lineup']) - len(rows))

    option_template = fields['options']['items']
    choices = {}
    for action in ACTIONS:
        props = deepcopy(option_template['properties'])
        del props['id'], props['time_budget']
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
    if len(complete_budgets.intersection(ACTIONS)) < 2:
        rec['confidence']['enum'].remove('supported')
    recommendations = []
    for preferred in (*ACTIONS, None):
        branch = deepcopy(rec)
        branch['preferred_option_id'] = _choice([preferred])
        if preferred is None:
            branch['confidence'] = _choice(['insufficient_evidence'])
            branch['fallback_option_id'] = _choice([None, *ACTIONS])
        else:
            branch['fallback_option_id'] = _choice(a for a in ACTIONS if a != preferred)
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
        elif name in done and name != 'compare_help_duration':
            continue
        choices.append(_object(dict(id=_choice(['q'+str(n)]), name=_choice([name]), arguments=args)))
    exposed = {tool['function']['name'] for tool in request['tools']}
    mandatory = {'compare_round_options'} & exposed
    if 'review_round_plan' in exposed and frame['task'].get('previous_plan'):
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
            batch = dict(type='array', prefixItems=required, items=False,
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
                   'facts_used 只选当前事实 ID。role_assignments 分 player、ally、enemy 三个位置，'
                   '每组自己选有影响的一人并描述职责。可选 others 补充更多相关英雄。options 是以三个走法 ID 为键的对象。'
                   '每种走法自己写行动、得失、条件和理由，calculation_id 选该走法已登记的计算或 null。'
                   '程序只展开你选的事实及时间值。推荐和承接由你自己判断。每段只写一句具体中文。')
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
    if not isinstance(roles,dict):
        raise ValueError('invalid_selected_roles')
    others = roles.pop('others', [])
    if set(roles)!=wanted or not isinstance(others,list):
        raise ValueError('invalid_selected_roles')
    for group,role in roles.items():
        actor = role['actor_id']
        if (group=='player' and actor!=player) or (group!='player' and (actor==player or roster.get(actor)!=group)):
            raise ValueError('invalid_selected_actor')
    answer['role_assignments'] = [*roles.values(), *others]
    options = answer['options']
    if not isinstance(options,dict) or set(options)!=set(ACTIONS):
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
