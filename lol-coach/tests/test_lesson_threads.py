from copy import deepcopy

import pytest

from lol_coach.lesson_threads import continues_question, register_question, resolve_question
from lol_coach.reasoning_frame import digest


def wave_frame(at, starts, *, previous=None, ally_distance=400):
    actor, ally = 'me', 'carry'
    f = dict(schema='decision-frame/v1', facts={}, task={'bottom_lane_actors': {'carry': ally}},
             decision=dict(player_entity_id=actor, observer_team_id=100, build='test', at_seconds=at),
             lineup=[dict(entity_id=ally, relation='ally', champion='Test')], input_policy=[])
    if previous:
        f['task']['previous_plan'] = dict(previous_frame_id=previous['frame_id'],
                                          previous_answer_sha256=previous['answer_sha256'])
    def add(field, value, actor):
        row = dict(entity_id=actor, field=field, value=value, temporal_scope='test', observed_at_seconds=at)
        fid = 'f_' + digest(row)[:20]
        f['facts'][fid] = row
        return fid
    f['allied_path_fact_ids'] = [add('allied_path_start_sample', dict(observer_team_id=100, xz=[x, 0]), who)
                                for x, who in [(0, actor), (ally_distance, ally)]]
    lane = dict(lane='bot', observer_team_id=100, count_scope='own_team_observed_live_only',
                wave_spawn_clock=dict(observed_starts=starts), units=[
                    dict(entity_id='minion', born_at=32, sampled_at=at, last_xz=[400, 0])] if at >= 32 else [])
    f['lane_fact_ids'] = [add('lane_current_units_and_groups', lane, 'lane:bot')]
    f['frame_id'] = 'frame_' + digest(f)[:24]
    return dict(schema='reasoning-bundle/v1', frame=f, audit=dict(source_replay_sha256='a'*64))


def decision(bundle, *, destination='hold_bot'):
    return dict(frame_id=bundle['frame']['frame_id'], immediate_action='留下陪射手接线。',
                macro_round=dict(intent='defend', transition='continue'), continuation=dict(disposition='retain'),
                lane_plan=dict(destination_choice=dict(preferred=destination)),
                recommendation=dict(switch_conditions=['看到下一波再走。']))


def test_question_registered_before_next_wave_survives_intermediate_stop_and_limit():
    origin = wave_frame(10, [1])
    answer = decision(origin)
    q = register_question(origin, answer)
    unchanged = deepcopy(q)
    middle = wave_frame(15, [1], previous=q)
    end = wave_frame(60, [1, 31], ally_distance=500)
    out = resolve_question(q, [middle, end])
    assert out['at'] == 60 and out['birth_receipt']['born_at'] == 31
    assert out['own_to_ally'] == 500 and out['ally_to_minion'] == 100
    assert out['frame_id'] == end['frame']['frame_id'] and len(out['position_refs']) == 2
    assert q == unchanged == register_question(origin, answer)
    assert resolve_question(q, [middle])['status'] == 'unresolved'
    assert resolve_question(q, [wave_frame(60, [1, 31], ally_distance=4000)])['status'] == 'birth_only'
    # Losing the anchor means we cannot tell whether a later cohort was actually the next one.
    assert resolve_question(q, [wave_frame(90, [31, 61])])['status'] == 'unresolved'


def test_only_a_sealed_link_and_unchanged_objective_continue_the_same_lesson():
    first = wave_frame(10, [1])
    q = register_question(first, decision(first))
    later = wave_frame(15, [1], previous=q)
    q2 = register_question(later, decision(later))
    assert continues_question(q, q2)
    assert not continues_question(q, dict(q2, previous_answer_sha256='wrong'))
    assert not continues_question(q, register_question(later, decision(later, destination='mid_lane')))


def test_watch_follows_chosen_action_and_explicit_teammate_over_lane_worksheet():
    first = wave_frame(10, [1])
    unrelated = dict(decision(first), immediate_action='和中单接控制。',
                     recommendation={'switch_conditions': ['队友没控住就退。']})
    assert register_question(first, unrelated)['observation'] is None
    coordination = dict(decision(first), team_coordination={'recipient_id': 'carry'})
    assert register_question(first, coordination)['observation']['kind'] == 'next_joint_position'


def test_full_lesson_survives_two_linked_briefs_and_then_rechecks_the_full_topic():
    first = wave_frame(10, [1])
    anchor = previous = register_question(first, decision(first))
    for at in (11, 14):
        bundle = wave_frame(at, [1], previous=previous)
        brief = dict(frame_id=bundle['frame']['frame_id'], schema='personal-brief/v1',
                     disposition='revise', immediate_action='先往后一步。', switch_if='队友靠近再进。')
        current = register_question(bundle, brief)
        assert continues_question(previous, current)
        previous = current
    next_frame = wave_frame(60, [1, 31], previous=previous)
    question = register_question(next_frame, decision(next_frame))
    assert continues_question(previous, question, last_full=anchor)
    assert not continues_question(previous, dict(question, intent='pressure'), last_full=anchor)


@pytest.mark.parametrize('mismatch', ['team','actor','replay','build','clock'])
def test_no_delayed_observation_from_another_perspective_or_earlier_clock(mismatch):
    first = wave_frame(10, [1])
    q = register_question(first, decision(first))
    later = wave_frame(60, [1, 31])
    bound = later['frame']['decision']
    if mismatch == 'team':
        bound['observer_team_id'] = 200
    elif mismatch == 'actor':
        bound['player_entity_id'] = 'other'
    elif mismatch == 'replay':
        later['audit']['source_replay_sha256'] = 'b' * 64
    elif mismatch == 'build':
        bound['build'] = 'other'
    else:
        bound['at_seconds'] = 10
    with pytest.raises(ValueError):
        resolve_question(q, [later])
