"""Bind one validated previous decision to a new, observer-limited frame.

This compares observations, not simulated actions or automatic round boundaries.
Previous advice never becomes execution evidence. History stays outside facts.
"""
from copy import deepcopy
import math

from .decision_contract import validate_decision
from .reasoning_frame import canonical, digest


SCHEMA = 'round-plan-link/v1'


def _check_bundle(bundle):
    if not isinstance(bundle, dict) or bundle.get('schema') != 'reasoning-bundle/v1':
        raise ValueError('invalid_bundle')
    frame = bundle.get('frame', {})
    if (not isinstance(frame, dict) or frame.get('schema') != 'decision-frame/v1'
            or not isinstance(frame.get('decision'), dict)
            or not isinstance(frame.get('facts'), dict)
            or not isinstance(frame.get('task'), dict)
            or not isinstance(frame.get('input_policy'), list)
            or not isinstance(bundle.get('audit'), dict)):
        raise ValueError('invalid_bundle')
    body = {k: v for k, v in frame.items() if k != 'frame_id'}
    if frame.get('frame_id') != 'frame_' + digest(body)[:24]:
        raise ValueError('frame_identity_mismatch')
    decision = frame.get('decision', {})
    if (not isinstance(decision.get('build'), str) or not decision['build']
            or decision.get('observer_team_id') not in (100, 200)
            or not isinstance(decision.get('player_entity_id'), str)
            or not decision['player_entity_id']):
        raise ValueError('invalid_bundle')
    at = decision.get('at_seconds')
    if type(at) not in (int, float) or not math.isfinite(at) or at < 0:
        raise ValueError('invalid_frame_time')
    for fact in frame.get('facts', {}).values():
        if (not isinstance(fact, dict) or not isinstance(fact.get('entity_id'), str)
                or not isinstance(fact.get('field'), str) or 'value' not in fact
                or not isinstance(fact.get('temporal_scope'), str)
                or type(fact.get('observed_at_seconds')) not in (int, float)):
            raise ValueError('invalid_bundle')
        for key in ('observed_at_seconds', 'available_at_seconds'):
            value = fact.get(key)
            if value is not None and (type(value) not in (int, float)
                    or not math.isfinite(value) or value > at):
                raise ValueError('future_or_invalid_fact_time')
    return frame


def _source(bundle):
    value = bundle.get('audit', {}).get('source_replay_sha256')
    if (not isinstance(value, str) or len(value) != 64
            or any(c not in '0123456789abcdef' for c in value)):
        raise ValueError('missing_source_binding')
    return value


def _latest(facts):
    """Compare like entity/field observations, without calling absence death."""
    indexed = {}
    for fid, fact in facts.items():
        key = (fact['entity_id'], fact['field'])
        rank = (fact.get('observed_at_seconds', -1), fid)
        if key not in indexed or rank > indexed[key][0]:
            indexed[key] = (rank, fid, fact)
    return {k: (v[1], v[2]) for k, v in indexed.items()}


def attach_previous_plan(current_bundle, previous_bundle=None, previous_answer=None,
                         *, max_chars=120000):
    """Return a copy with a bounded one-step history, or an explicit fallback.

    Bad current input is an error. Missing/invalid previous input is a normal
    standalone result. No recursive chain, raw packets, audit or reference
    library are copied into the model-facing plan.
    """
    if type(max_chars) is not int or max_chars < 1:
        raise ValueError('max_chars must be positive')
    _check_bundle(current_bundle)
    result = deepcopy(current_bundle)
    frame = result['frame']
    task = frame['task']
    task['previous_plan'] = None
    task.pop('round_transition', None)
    # A previously linked current bundle must not retain stale chain metadata.
    result['audit'].pop('round_chain', None)
    prior = None
    rejection = None
    if previous_bundle is None or previous_answer is None:
        rejection = 'previous_input_missing'
    else:
        try:
            prior = _check_bundle(previous_bundle)
            if _source(current_bundle) != _source(previous_bundle):
                raise ValueError('source_replay_mismatch')
            for key in ('build', 'observer_team_id', 'player_entity_id'):
                if prior['decision'].get(key) != frame['decision'].get(key):
                    raise ValueError(key + '_mismatch')
            if prior['decision']['at_seconds'] >= frame['decision']['at_seconds']:
                raise ValueError('previous_time_not_earlier')
            checked = validate_decision(previous_answer, prior)
            if checked['status'] != 'PASS':
                raise ValueError('previous_answer_invalid')
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            # Enumerate stable reason codes only; arbitrary malformed source
            # strings must not leak into the model's instruction surface.
            allowed = {'invalid_bundle', 'frame_identity_mismatch', 'invalid_frame_time',
                'future_or_invalid_fact_time', 'missing_source_binding', 'source_replay_mismatch',
                'build_mismatch', 'observer_team_id_mismatch', 'player_entity_id_mismatch',
                'previous_time_not_earlier', 'previous_answer_invalid'}
            rejection = str(exc) if str(exc) in allowed else 'malformed_previous_input'

    if rejection:
        task['continuity_status'] = {'status': 'standalone', 'reason': rejection}
        result['audit']['round_chain'] = {'schema': SCHEMA, 'status': 'rejected_or_missing',
                                         'reason': rejection}
    else:
        at = frame['decision']['at_seconds']
        historical = {}

        def bind(fid):
            hid = 'h_' + fid
            if hid not in historical:
                old = deepcopy(prior['facts'][fid])
                old['original_temporal_scope'] = old['temporal_scope']
                old['temporal_scope'] = 'historical_previous_frame'
                old['original_fact_id'] = fid
                old['previous_frame_id'] = prior['frame_id']
                old['age_seconds'] = at - old['observed_at_seconds']
                historical[hid] = old
            return hid

        card = {key: deepcopy(previous_answer[key]) for key in (
            'objective', 'role_assignments', 'options', 'recommendation', 'open_questions')}

        def remap(node):
            if isinstance(node, list):
                return [remap(v) for v in node]
            if isinstance(node, dict):
                return {k: [bind(fid) for fid in v] if k == 'fact_refs' else remap(v)
                        for k, v in node.items()}
            return node

        card = remap(card)
        for used in previous_answer['facts_used']:
            bind(used['fact_id'])
        old_by_key, new_by_key = _latest(prior['facts']), _latest(frame['facts'])
        changes = {}
        for key in sorted(old_by_key.keys() & new_by_key.keys()):
            old_id, old_fact = old_by_key[key]
            new_id, new_fact = new_by_key[key]
            # A timestamp refresh with the same value is not a value change.
            if canonical(old_fact['value']) == canonical(new_fact['value']):
                continue
            item = {'entity_id': key[0], 'field': key[1],
                    'kind': 'observed_value_changed_not_action_proof',
                    'historical_fact_id': bind(old_id), 'current_fact_id': new_id}
            changes['change_' + digest(item)[:20]] = item
        for key in sorted(new_by_key.keys() - old_by_key.keys()):
            new_id, _ = new_by_key[key]
            item = {'entity_id': key[0], 'field': key[1],
                    'kind': 'newly_available_observation_not_action_proof',
                    'historical_fact_id': None, 'current_fact_id': new_id}
            changes['change_' + digest(item)[:20]] = item
        task['previous_plan'] = {
            'schema': 'previous-plan/v1', 'previous_frame_id': prior['frame_id'],
            'previous_at_seconds': prior['decision']['at_seconds'],
            'previous_answer_sha256': digest(previous_answer),
            'decision_card': card, 'historical_facts': historical,
            'execution_status': 'unknown',
            'semantics': '先前模型建议与历史观测；不是玩家执行、成功或承诺的证据。',
        }
        task['round_transition'] = {
            'previous_frame_id': prior['frame_id'],
            'elapsed_seconds': at - prior['decision']['at_seconds'], 'changes': changes,
            'semantics': '相邻观测值变化；不是动作归因、完整事件列表或自动回合边界。消失不等于死亡，兵团编号不跨帧稳定。',
        }
        task['continuity_status'] = {'status': 'linked', 'reason': None}
        result['audit']['round_chain'] = {'schema': SCHEMA, 'status': 'linked',
            'previous_bundle_sha256': digest(previous_bundle),
            'previous_answer_sha256': digest(previous_answer),
            'current_base_frame_id': current_bundle['frame']['frame_id'],
            'previous_frame_id': prior['frame_id'], 'history_steps': 1}
    policy = ('上一计划与historical_facts只代表历史，不能作为当前facts引用，建议不证明执行。'
              '有previous_plan时必须输出continuation：保留/改选/取消及当前证据，改选/取消引用变化。'
              '当前复制HP可用且同步延迟未知，不能仅因更新年龄降为unknown；前后空间兵团分开判断。')
    if policy not in frame['input_policy']:
        frame['input_policy'].append(policy)
    frame.pop('frame_id', None)
    frame['frame_id'] = 'frame_' + digest(frame)[:24]
    size = len(canonical(frame))
    if size > max_chars:
        raise ValueError('Context budget too small for plan history; increase max_chars, never truncate')
    result['audit']['frame_chars'] = size
    return result
