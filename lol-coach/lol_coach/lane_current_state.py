"""Bounded current lane state from ordered live replication, never checkpoints.

The retained-attribute contract is cross-checked on the four existing exact-build
replays. It describes the latest replicated state, with unknown transmission
delay, rather than exact simulation state. Observer views preserve the stricter
identity/time/visibility filters in lane_dynamics.query_at.
"""
from collections import defaultdict
from copy import deepcopy

from .lane_dynamics import query_at


def reconstruct_lane_current_state(bundle, at_seconds, observer_team_id=None):
    """Add current lifecycle/attributes to the existing evidence query.

    An explicit visible interval permits sparse attributes to retain their last
    value until another update. Leaving visibility or an unknown barrier makes
    current attributes unavailable; re-entering never imports old/hidden HP.
    An already observed zero is terminal for these named non-respawning lane
    entities. Movement, visibility and generic opcodes cannot revive them.

    Research mode may count all live-prefix identities but is never model-ready.
    Team counts cover explicitly visible named units only, not the whole map.
    """
    result = query_at(bundle, at_seconds, observer_team_id)
    research = observer_team_id is None
    grouped = defaultdict(list)
    active = 0
    for entity in result['entities']:
        visible = entity['visibility']['visible'] is True
        zero = entity['zero_health_sample']
        removal = entity['removal_candidate']
        if zero is not None:
            alive, status, lifecycle = False, 'observed_zero_health', zero
        elif removal is not None:
            alive, status, lifecycle = False, 'observed_terminal_removal', removal
        elif research or visible:
            alive, status, lifecycle = True, 'replicated_alive', None
        else:
            alive, status, lifecycle = None, 'hidden_unknown', None

        observed = entity['current_observed'] or {}
        samples = observed.get('health_samples', {}) if research or visible else {}
        current_health = {'health': None, 'max_health': None}
        conflicts = []
        for name in current_health:
            sample = samples.get(name)
            if sample is None:
                continue
            if name == 'health' and alive is False and sample['value'] > 0:
                # A missing zero or contradictory later sample must not publish
                # positive current HP for a terminal entity or revive it.
                conflicts.append('positive_health_with_terminal_lifecycle')
                continue
            current_health[name] = dict(deepcopy(sample),
                freshness='retained_live_replication' if research else 'retained_within_visible_interval',
                value_semantics='latest_replicated_value', replication_delay_unknown=True,
                exact_simulation_value=False)
        transition = entity['visibility']['last_transition']
        start = transition['observed_at_seconds'] if visible and transition else None
        eligible = not research and (visible or alive is False)
        entity['current_state'] = dict(alive=alive, lifecycle_status=status,
            lifecycle_evidence=deepcopy(lifecycle), health=current_health,
            basis='live_replication_event_state', evidence_level='bounded_binary_crosschecked',
            replication_delay_unknown=True, exact_simulation_death_time=None,
            continuous_visible_interval_start_seconds=start,
            conflicts=conflicts, decision_input_eligible=eligible,
            decision_input_scope='current lifecycle and available replicated health only')
        if alive is True:
            active += 1
            if not research and visible:
                identity = entity['identity']
                group = (identity.get('team_id'), identity.get('lane'), identity.get('kind'))
                grouped[group].append(entity['entity_id'])

    result.update(schema='lane-current-state/v1',
        mode='research_omniscient' if research else 'observer_current_replication',
        known_visible_alive_counts=[dict(team_id=t, lane=l, kind=k, count=len(ids), entity_ids=sorted(ids))
            for (t, l, k), ids in sorted(grouped.items(), key=lambda item: str(item[0]))],
        counts_scope='explicitly_visible_named_lane_units_only',
        replay_active_count=active if research else None,
        decision_input_eligible=not research,
        decision_input_scope='observer current_state fields and known_visible_alive_counts only',
        replication_delay_unknown=True,
        validation_scope='16.20.824.8524; four existing replays; 15 withheld checkpoint identity sets',
        limitations=[
            'Latest replicated HP can lag simulation changes; update age is not an error bound',
            'Team counts cover explicitly visible named units, not all hidden units or the full map',
            'No checkpoint fields or future records are used to fill a current observation',
            'Visible re-entry requires fresh health fields; older observations remain history only',
            'Zero-health lifecycle is terminal within this accepted lane-entity scope; generic movement cannot revive it',
            'Positions, lane pressure, collision, attack state and arrival ETA are not reconstructed here',
            'Research omniscient mode is not authorized model decision input'])
    return result
