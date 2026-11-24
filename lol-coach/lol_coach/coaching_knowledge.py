"""Freeze conditional coaching references, never new match observations.

The short catalog is visible to the model. Full cards use the existing scoped
get_reference tool. Applying a card still requires current, POV-scoped evidence.
"""
from copy import deepcopy
import json
from pathlib import Path

from .reasoning_frame import canonical, digest, lookup_reference, number
from .round_chain import _check_bundle


SCHEMA = 'coaching-handbook/v1'
KIND = 'conditional_coaching_knowledge'
PROFILE = Path(__file__).with_name('profiles') / 'coaching_handbook_v1.json'


def _guidance_events(frame):
    """Return evidence for optional prompts at this player's decision time."""
    at = frame['decision']['at_seconds']

    def known(fid):
        row = frame['facts'].get(fid, {})
        when = row.get('observed_at_seconds')
        available = row.get('available_at_seconds', when)
        return number(when) and number(available) and 0 <= when <= available <= at

    me = frame['decision']['player_entity_id']
    for fid, row in frame['facts'].items():
        if (row.get('entity_id') == me and row.get('field') == 'personal_client_state'
                and row.get('temporal_scope') in ('observed_sample', 'personal_native_observation')
                and known(fid) and at - row['observed_at_seconds'] <= 1
                and isinstance(row.get('value'), dict) and row['value'].get('is_dead') is True):
            return {}

    events = {}
    trigger = frame['task'].get('team_coordination_trigger') or {}
    if trigger.get('active'):
        ids = trigger.get('fact_ids', [])
        if ids and all(known(fid) for fid in ids):
            for reason in trigger.get('reasons', []):
                events[reason] = ids

    # A short editorial window, not a rule about when combat or the wave ends.
    kills = []
    for fid in frame.get('recent_public_combat_ids', []):
        if not known(fid):
            continue
        row = frame['facts'][fid]
        if row.get('field') != 'public_kill_feed' or at - row['observed_at_seconds'] > 8:
            continue
        value = row.get('value')
        if not isinstance(value, dict) or value.get('victim_entity_id') is None:
            continue
        if value['victim_entity_id'] == me:
            return {}
        if value.get('killer_entity_id') == me:
            kills.append(fid)
    if kills:
        events['recent_personal_kill'] = kills
    return events


def attach_handbook(bundle, *, max_chars=300000):
    """Pin this handbook once before a session is written or passed to MCP."""
    _check_bundle(bundle)
    result = deepcopy(bundle)
    frame = result['frame']
    if frame['task'].get('knowledge_handbook'):
        for rid in frame['task']['knowledge_handbook']['reference_ids']:
            lookup_reference(result, rid)
        return result
    profile = json.loads(PROFILE.read_text(encoding='utf-8'))
    if profile['schema'] != SCHEMA:
        raise ValueError('unsupported_handbook')
    catalog, guidance = [], []
    events = _guidance_events(frame)
    prompts = profile['decision_prompts']
    replay = result['audit'].get('source_replay_sha256')
    known_replay = isinstance(replay, str) and len(replay) == 64 and all(c in '0123456789abcdef' for c in replay)
    for card in profile['cards']:
        rid = 'knowledge:' + card['id']
        if rid in frame['references']:
            raise ValueError('duplicate_handbook_reference')
        sources = [deepcopy(profile['sources'][sid]) for sid in card['source_ids']]
        if not sources or any(s['reading_level'] not in ('primary_text', 'verified_video_excerpt') for s in sources):
            raise ValueError('unreviewed_handbook_source')
        prompt = prompts.get(card['id'])
        mode = prompt['mode'] if prompt else 'context'
        detail = dict(kind=KIND, handbook_version=profile['version'], **deepcopy(card), sources=sources, use_mode=mode,
            evidence_type='conditional_experience_not_match_observation',
            interpretation='project_synthesis_not_verbatim_source_or_current_patch_validation',
            training_permission='not_obtained_or_verified')
        pair = profile.get('worked_pairs', {}).get(card['id'])
        if (pair and known_replay and replay != pair['source_replay_sha256']
                and frame['decision'].get('build') == pair['build']):
            # Another match may illustrate the choice; this match's own examples could disclose its future.
            detail['worked_pair'] = deepcopy(pair)
        frame['references'][rid] = dict(kind=KIND, title=card['title'], topics=card['topics'],
            read_when=card['read_when'], use_mode=mode, content_sha256=digest(detail))
        if 'worked_pair' in detail:
            frame['references'][rid]['example_question'] = pair['question']
        if prompt:
            for event in prompt['events']:
                if event in events:
                    guidance.append(dict(reference_id=rid, question=prompt['question'], trigger=event,
                        fact_refs=events[event], fact_scope=('personal_kills' if event == 'recent_personal_kill'
                                                            else 'combined_team_trigger_evidence')))
                    break
        result['reference_library'][rid] = detail
        catalog.append(rid)
    frame['task']['knowledge_handbook'] = dict(schema=SCHEMA, version=profile['version'], reference_ids=catalog,
        use='choose_relevant_cards_via_get_reference_then_bind_current_facts', max_followup_steps=3,
        decision_guidance=guidance)
    frame['input_policy'].append('知识卡是有适用条件的经验。预测的兵线、补给或后续动作不是本局观测；执行与状态变化须在下一帧重新取证。')
    frame.pop('frame_id')
    frame['frame_id'] = 'frame_' + digest(frame)[:24]
    if len(canonical(frame)) > max_chars:
        raise ValueError('handbook_context_budget_exceeded')
    result['audit']['knowledge_handbook'] = dict(version=profile['version'], profile_sha256=digest(profile),
        full_bodies='reference_library_only', fact_changes=0)
    result['audit']['frame_chars'] = len(canonical(frame))
    return result


def cited_knowledge(answer, frame):
    """New handbook citations must have successful reads in the current run."""
    candidates = [rid for row in answer.get('options', []) for rid in row.get('reference_refs', [])]
    candidates += [rid for row in answer.get('follow_through', {}).get('steps', [])
                   for rid in row.get('knowledge_refs', [])]
    return {rid for rid in candidates if frame['references'].get(rid, {}).get('kind') == KIND}


def follow_through_lines(answer):
    """A short user-visible plan, including quiet personal checkpoints."""
    chain = answer.get('follow_through')
    if chain is None:
        return []
    lines = ['**照当前行动继续会怎样**　' + chain['baseline_if_unchanged'], '']
    if chain['steps']:
        lines += ['**做完以后怎么接**', '']
    for i, step in enumerate(chain['steps'], 1):
        lines += [f"{i}. {step['action']}",
                  f"   条件下预期：{step['expected_state']}",
                  f"   复查时机：{step['check_when']}",
                  f"   若确认：{step['if_confirmed']} 未确认或受阻：{step['if_not_confirmed']}", '']
    if chain['limits']:
        lines += ['**这段推演尚缺的依据**　' + ' '.join(chain['limits']), '']
    return lines
