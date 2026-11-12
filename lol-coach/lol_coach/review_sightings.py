"""A small evidence view for the question 'which opponents can this team see?'."""
from math import isclose

from .reasoning_frame import digest, number


def enemy_sightings(frame):
    """Project one trusted, prefix-filtered decision frame. No index or replay access."""
    frame_id = frame['frame_id']
    if (frame.get('schema') != 'decision-frame/v1'
            or frame_id != 'frame_' + digest({k: v for k, v in frame.items() if k != 'frame_id'})[:24]):
        raise ValueError('invalid_frozen_frame')
    decision = frame['decision']
    team = decision['observer_team_id']
    at = decision['at_seconds']
    if team not in (100, 200) or not number(at) or at < 0:
        raise ValueError('invalid_decision_scope')

    facts = frame['facts']

    def checked(fid):
        fact = facts[fid]
        when = fact['observed_at_seconds']
        available = fact.get('available_at_seconds', when)
        if (fid != 'f_' + digest(fact)[:20] or not number(when) or not number(available)
                or not 0 <= when <= available <= at):
            raise ValueError('invalid_evidence')
        return fact

    scoped = {}
    for fid in frame.get('vision_fact_ids', []):
        fact = checked(fid)
        if fact['field'] == 'observer_visibility' and fact['entity_id'].startswith('entity:'):
            entity = fact['entity_id'].removeprefix('entity:')
            if entity in scoped or fact['value']['team_id'] != team:
                raise ValueError('ambiguous_observer')
            scoped[entity] = fid

    opponents = []
    for hero in frame['lineup']:
        if hero['relation'] != 'enemy':
            continue
        entity = hero['entity_id']
        fid = scoped.get(entity)
        sample = None
        visible = None
        if fid:
            fact = facts[fid]
            value = fact['value']
            visible = value['visible']
            pos = value.get('last_observed_position')
            if pos is not None:
                t = pos['sampled_at']
                if (not number(t) or not 0 <= t <= fact['observed_at_seconds']
                        or not number(pos['age_seconds']) or not isclose(pos['age_seconds'], at - t)
                        or len(pos['xz']) != 2 or not all(number(x) for x in pos['xz'])):
                    raise ValueError('invalid_position_sample')
                sample = dict(xz=pos['xz'], sampled_at=t, age_seconds=at - t)
        else:
            for key in hero['current_fact_ids']:
                fact = checked(key)
                if fact['entity_id'] == entity and fact['field'] == 'visibility':
                    fid, visible = key, fact['value']
                    break
        if visible is not None and type(visible) is not bool:
            raise ValueError('invalid_visibility_state')
        opponents.append(dict(champion=hero['champion'], entity_id=entity, visible=visible,
                              last_observed_path_start=sample, fact_id=fid))
    return dict(frame_id=frame_id, observer_team_id=team, at_seconds=at, opponents=opponents)


def check_sighting_answer(frame, entity_id, answer):
    """Grade this four-field reading task using only the host's scoped view."""
    view = enemy_sightings(frame)
    row = next((r for r in view['opponents'] if r['entity_id'] == entity_id), None)
    if row is None:
        raise ValueError('opponent_outside_frame')
    sample = row['last_observed_path_start']
    expected = dict(visible=row['visible'], last_xz=sample['xz'] if sample else None,
                    position_fact_id=row['fact_id'] if sample else None,
                    entrance_safety_proven=False)
    if not isinstance(answer, dict):
        raise ValueError('expected_structured_answer')
    # This tool has no route or ground observations, even when every enemy is visible.
    mismatches = []
    for key, value in expected.items():
        offered = answer.get(key)
        if (key not in answer or type(value) is not type(offered) or value != offered
                or (key == 'last_xz' and offered is not None and not all(number(n) for n in offered))):
            mismatches.append(key)
    extras = sorted(set(answer) - set(expected))
    return dict(frame_id=view['frame_id'], accepted=not (mismatches or extras),
                mismatched_fields=mismatches, unexpected_fields=extras, expected=expected)
