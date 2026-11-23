"""Select personal coaching stops from chronological POV candidates."""
from math import dist


# Editorial thresholds in seconds and world units; none represents a skill range.
CONTACT_BURST = 8
REACTION_WINDOW = 3
CONTACT_GAP = 30
RETURNING_OPPONENT = 75
CLOSE_SAMPLE = 450
FAR_SAMPLE = 800


def _contacts(candidate, seen_at, far_samples, after_gap):
    observations = []
    for trigger in candidate.get('triggers', []):
        if trigger.get('kind') != 'nearby_enemy_became_visible':
            continue
        subject = trigger['subject']
        own, enemy = trigger['own_sample'], trigger['enemy_sample']
        at = candidate['at']
        if not (enemy['subject'] == subject and enemy['time_seconds'] == trigger['at'] == at
                and 0 <= at - own['time_seconds'] <= 2):
            raise ValueError('contact requires a current visible position and recent personal sample')
        distance = dist(enemy['xz'], own['world_waypoints_xz'][0])
        prior_far = far_samples.get(subject)
        if after_gap:
            change = 'contact_after_gap'
        elif at - seen_at.get(subject, float('-inf')) >= RETURNING_OPPONENT:
            change = 'new_local_opponent'
        elif prior_far and at - prior_far['at'] < CONTACT_GAP and distance <= CLOSE_SAMPLE:
            change = 'closer_local_opponent'
        else:
            change = 'repeated_local_opponent'
        observations.append(dict(subject=subject, distance_world_units=round(distance, 1),
                                 enemy_at=at, own_at=own['time_seconds'], change=change))
        if change == 'closer_local_opponent':
            observations[-1]['previous_far_sample'] = prior_far
        if distance >= FAR_SAMPLE:
            far_samples[subject] = dict(at=at, distance_world_units=round(distance, 1))
        elif distance <= CLOSE_SAMPLE:
            far_samples.pop(subject, None)
        seen_at[subject] = at
    return observations


def select_coaching_checkpoints(candidates):
    """One pass. Later observations can extend an episode only at their own clocks."""
    rows = []
    selected = []
    seen_at = {}
    far_samples = {}
    additions_in_burst = set()
    burst_already_updated = False
    last_stop = last_noncontact_stop = last_contact = last_contact_anchor = last_signal_at = float('-inf')
    last_signal = None
    previous_at = float('-inf')
    for candidate in candidates:
        at = candidate['at']
        if at <= previous_at:
            raise ValueError('coaching candidates must have strictly increasing clocks')
        previous_at = at
        reasons = candidate['selected_by']
        signals = [t['kind'] for t in candidate.get('triggers', []) if 'sent_at_seconds' in t]
        after_gap = at - last_contact >= CONTACT_GAP
        if after_gap:
            seen_at.clear()
            far_samples.clear()
        observations = _contacts(candidate, seen_at, far_samples, after_gap)
        changes = {o['change'] for o in observations}
        contact_reason = next((s for s in ('closer_local_opponent', 'contact_after_gap', 'new_local_opponent')
                               if s in changes), None)
        additions = {o['subject'] for o in observations if o['change'] == 'new_local_opponent'}
        additions_in_burst.update(additions)
        elapsed = at - last_stop
        since_contact_stop = at - last_contact_anchor
        material_update = (REACTION_WINDOW <= since_contact_stop < CONTACT_BURST and not burst_already_updated
                           and (contact_reason == 'closer_local_opponent'
                                or (additions and len(additions_in_burst) >= 2)))
        reason = None
        if at == 0:
            reason = 'opening_plan'
        elif 'last_game_second' in reasons:
            reason = 'final_visible_state'
        elif contact_reason and elapsed >= 1 and (since_contact_stop >= CONTACT_BURST or material_update):
            reason = contact_reason
        elif 'public_kill_became_available' in reasons and elapsed >= 12:
            reason = 'public_combat_change'
        elif signals and elapsed >= 1 and at - last_noncontact_stop >= (35 if signals[-1] == 'on_my_way' else 12):
            if signals[-1] != last_signal or at - last_signal_at >= 80:
                reason = 'changed_personal_signal'
        if reason is None:
            if 'own_command_reversed' in reasons and elapsed >= 100:
                reason = 'recheck_personal_movement'
            elif 'regular' in reasons and elapsed >= 115:
                reason = 'quiet_coverage'
        is_selected = reason is not None
        review_mode = None
        if is_selected:
            review_mode = 'brief_update' if reason == contact_reason and elapsed <= 15 else 'decision'
            selected.append(at)
            last_stop = at
            if reason != contact_reason:
                last_noncontact_stop = at
            if observations:
                last_contact_anchor = at
                additions_in_burst.clear()
                burst_already_updated = bool(material_update)
        elif contact_reason and elapsed < 1 and at - last_contact_anchor >= CONTACT_BURST:
            # A later receipt belongs to the audit; the already frozen stop still has its old prefix.
            last_contact_anchor = at
            additions_in_burst.clear()
            burst_already_updated = False
        if signals:
            last_signal, last_signal_at = signals[-1], at
        if observations:
            last_contact = at
        if reason is None:
            if contact_reason:
                reason = 'same_contact_burst'
            elif observations:
                reason = 'repeated_contact'
            else:
                reason = 'recent_checkpoint_covers_candidate'
        rows.append(dict(at=at, selected=is_selected, selection_reason=reason, review_mode=review_mode,
                         covered_by_at=selected[-1] if selected else None, selected_by=reasons,
                         observable_signals=signals, nearby_observations=observations))
    return dict(candidate_count=len(rows), selected_count=len(selected), selected_times=selected, rows=rows)
