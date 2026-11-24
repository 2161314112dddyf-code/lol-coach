"""Small personal interrupt contract and its player-scoped, frozen evidence."""
from copy import deepcopy
from math import dist
import re

from .reasoning_frame import digest


SCHEMA = 'personal-brief/v1'
BRIEF_REPLY_INSTRUCTIONS = (
    '请直接用中文回答眼前这一手。', '观察、怎么走、何时换手分别写一句实话。',
    '有上次建议才判断延续或改选。', '引用的 E 编号从当前 facts 选择。',
)


def is_brief(frame):
    task = (frame or {}).get('task', {})
    return task.get('personal_action_review') == 'personal-actions/v1' and task.get('brief_review') == SCHEMA


def bind_brief(bundle, selection=None):
    from .personal_episode import refresh_identity
    from .round_chain import _check_bundle
    frame = _check_bundle(bundle)
    if frame['task'].get('personal_action_review') != 'personal-actions/v1':
        raise ValueError('brief_requires_personal_checkpoint')
    out = deepcopy(bundle)
    out['frame']['task']['brief_review'] = SCHEMA
    at = frame['decision']['at_seconds']
    refs = set()
    for trigger in (selection or {}).get('triggers', []):
        if trigger.get('kind') != 'nearby_enemy_became_visible':
            continue
        sample = trigger['enemy_sample']
        if (trigger['at'] != at or sample['time_seconds'] != at or sample['subject'] != trigger['subject']
                or sample['team_id'] != frame['decision']['observer_team_id']):
            raise ValueError('brief_contact_scope_mismatch')
        for fid, row in frame['facts'].items():
            if row['field'] != 'observer_visibility' or row['entity_id'] != trigger['subject']:
                continue
            val = row['value']
            pos = val.get('last_observed_position') or {}
            evidence = bundle['audit']['fact_sources'].get(fid, {}).get('evidence', [])
            if (val.get('visible') is True and pos.get('xz') == sample['xz'] and pos.get('sampled_at') == at
                    and any(ev.get('mode') == 'visible_path_start' and ev.get('time_seconds') == at
                            and ev.get('source') == sample['source']
                            and ev.get('visibility_record') == sample['visibility_record'] for ev in evidence)):
                refs.add(fid)
                break
        else:
            raise ValueError('brief_contact_evidence_mismatch')
    out['frame']['task']['brief_contact_fact_ids'] = sorted(refs)
    return refresh_identity(out)


def brief_context(frame):
    """Keep last seen enemies distinct from current contacts; never project a path endpoint as arrival."""
    decision = frame['decision']
    player = decision['player_entity_id']
    at = decision['at_seconds']
    names = {h['entity_id']: h['champion'] for h in frame['lineup']}
    latest = {}
    wanted = {'observer_visibility', 'allied_path_start_sample', 'personal_movement_sample',
              'personal_lane_opportunity_change', 'personal_client_state', 'personal_hud_state',
              'public_kill_feed', 'map_ping_sent'}
    for fid, row in frame['facts'].items():
        field = row['field']
        when = row['observed_at_seconds']
        if field not in wanted or not 0 <= when <= row.get('available_at_seconds', when) <= at:
            continue
        if field in {'personal_client_state', 'personal_hud_state', 'personal_movement_sample', 'map_ping_sent'} and row['entity_id'] != player:
            continue
        if field in {'public_kill_feed', 'map_ping_sent', 'personal_lane_opportunity_change'} and at - when > 12:
            continue
        key = row['entity_id'], field
        if key not in latest or when > latest[key][1]['observed_at_seconds']:
            latest[key] = fid, row

    facts = {}
    trigger_ids = list(frame['task'].get('brief_contact_fact_ids', []))
    own = latest.get((player, 'allied_path_start_sample'))
    own_xz = own[1]['value']['xz'] if own and at - own[1]['observed_at_seconds'] <= 1 else None
    for (actor, field), (fid, row) in latest.items():
        when = row['observed_at_seconds']
        value = row['value']
        xz = None
        if field == 'observer_visibility':
            pos = value.get('last_observed_position') or {}
            if value.get('visible') is not True:
                continue
            sampled = pos.get('sampled_at')
            if sampled is not None and not 0 <= sampled <= at:
                raise ValueError('invalid_brief_position_time')
            value = {'visible': True, 'position_sample_at': sampled}
            xz = pos.get('xz') if sampled is not None and at-sampled <= 1 else None
        elif field == 'allied_path_start_sample':
            xz = value['xz'] if at-when <= 1 else None
            if xz is None:
                continue
        elif field == 'personal_movement_sample':
            value = {'start_xz': value['start_xz'], 'command_goal_xz': value['commanded_path_xz'][-1]}
        elif field == 'personal_lane_opportunity_change':
            trigger_ids.append(fid)
        entry = dict(champion=names.get(actor.removeprefix('entity:'), actor), field=field,
                     sampled_at=when, value=value)
        if xz is not None and own_xz is not None:
            entry['gap_from_player_sample'] = round(dist(own_xz, xz), 1)
        facts[fid] = entry

    previous = frame['task'].get('previous_plan') or {}
    card = previous.get('decision_card', {})
    prior = None
    if previous:
        rec = card.get('recommendation', {})
        prior = dict(at=previous['previous_at_seconds'], objective=card.get('objective'),
                     first_step=card.get('immediate_action'),
                     switch_if=card.get('switch_if') or rec.get('switch_conditions'),
                     status='earlier_recommendation_not_observed_execution')
    if not set(trigger_ids) <= facts.keys():
        raise ValueError('brief_trigger_outside_frozen_evidence')
    contacts = [facts[fid]['champion'] for fid in trigger_ids if facts[fid]['field'] == 'observer_visibility']
    observation = ('本队在你附近新采到 ' + '、'.join(contacts) + ' 的可见位置。') if contacts else None
    return dict(frame_id=frame['frame_id'], champion=names.get(player, player), at_seconds=at,
                observer_team_id=decision['observer_team_id'], previous_plan=prior, facts=facts,
                trigger_fact_ids=trigger_ids, verified_contact_observation=observation,
                limits='trigger_fact_ids 为实际触发本次暂停的观测，其他可见单位可能早已可见。间距比较一秒内采样起点；移动终点是指令。技能就绪、命中和接应需另证。')


def brief_schema(frame):
    context = brief_context(frame)
    text = dict(type='string', minLength=2, maxLength=200)
    fields = dict(schema={'const': SCHEMA}, frame_id={'const': frame['frame_id']},
                  change={'const': context['verified_contact_observation']} if context['verified_contact_observation'] else text,
                  disposition={'enum': ['retain', 'revise'] if context['previous_plan'] else ['unanchored']},
                  immediate_action=text, switch_if=text, fact_refs=dict(type='array', minItems=1, maxItems=5,
                      items={'enum': list(context['facts'])}))
    return dict(type='object', required=list(fields), properties=fields, additionalProperties=False)


def validate_brief(answer, frame):
    from .decision_contract import _check_json, _validate_shape
    errors = []
    _check_json(answer, '$', errors)
    if not errors:
        _validate_shape(answer, brief_schema(frame), '$', errors)
    if not errors:
        refs = answer['fact_refs']
        context = brief_context(frame)
        triggers = context['trigger_fact_ids']
        if len(set(refs)) != len(refs) or not set(triggers).issubset(refs):
            errors.append(dict(path='$.fact_refs', message='逐项引用不同的冻结证据，并指出触发本次重看的观测。'))
        for key in ('change', 'immediate_action', 'switch_if'):
            text = answer[key].strip()
            if len(text) < 2 or len(text) > 200 or not any(c.isalnum() for c in text) or re.fullmatch(r'[A-Za-z\d_:-]+', text):
                errors.append(dict(path='$.'+key, message='用简短具体的中文告诉玩家，不可只填 ID 或占位符。'))
            if re.search(r'(?<![A-Za-z0-9])(?:E\d+|f_[0-9a-f]+|fact_refs|immediate_action|switch_if)(?![A-Za-z0-9])', text):
                errors.append(dict(path='$.'+key, message='给玩家听的句子要说场上的人和能做的事，证据编号只放引用栏。'))
        prose = [re.sub(r'[\W_]+', '', answer[key]) for key in ('change', 'immediate_action', 'switch_if')]
        if any(re.sub(r'[\W_]+', '', instruction) in sentence
               for instruction in BRIEF_REPLY_INSTRUCTIONS for sentence in prose):
            errors.append(dict(path='$', message='回答里出现了提示词原句，请直接告诉玩家眼前该怎么做。'))
        if len(set(prose)) < 3:
            errors.append(dict(path='$', message='眼前已见的变化、本人下一手与将来的改选条件各回答不同的问题。'))
        prior = context['previous_plan'] or {}
        conditions = prior.get('switch_if') or []
        if isinstance(conditions, str):
            conditions = [conditions]
        if answer['change'] in [prior.get('objective'), prior.get('first_step'), *conditions]:
            errors.append(dict(path='$.change', message='上次建议或旧改选条件不能充当这一刻新见的观测。'))
    return dict(status='FAIL' if errors else 'PASS', errors=errors, answer_sha256=digest(answer),
                tactical_quality='not_evaluated')
