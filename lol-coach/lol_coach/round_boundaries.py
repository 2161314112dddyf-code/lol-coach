"""Causal candidates to reconsider a plan; never automatic tactical verdicts."""
from copy import deepcopy
from .round_chain import _check_bundle, _source, _latest
from .reasoning_frame import canonical, digest, number


class BoundaryTracker:
    def __init__(self):
        self.previous=None
        self.binding=None

    def feed(self,bundle):
        frame=_check_bundle(bundle);d=frame['decision'];at=d['at_seconds']
        binding=(_source(bundle),d['build'],d['observer_team_id'],d['player_entity_id'])
        if self.binding is not None and binding!=self.binding:raise ValueError('Boundary source/perspective changed')
        if self.previous is not None and at<=self.previous['decision']['at_seconds']:raise ValueError('Frames must increase strictly')
        current=_latest(frame['facts']);previous=_latest(self.previous['facts']) if self.previous else {}
        since=self.previous['decision']['at_seconds'] if self.previous else at
        reasons=[]
        for key,(fid,f) in sorted(current.items()):
            value=f['value'];field=f['field'];old=previous.get(key);changed=old is not None and canonical(old[1]['value'])!=canonical(value)
            reason=None
            if field=='visibility' and changed:
                reason='visibility_changed_reassess_information'
            elif field in ('health','tower_health') and number(value) and value==0 and f['temporal_scope']=='observed_sample' and f['observed_at_seconds']>since:
                if old is None or old[1]['value']!=0:
                    reason='observed_zero_tower_health' if field=='tower_health' else 'observed_zero_hero_health'
            elif field=='public_kill_feed' and f['observed_at_seconds']>since:
                reason='new_public_kill_event_not_current_death_state'
            elif field=='lifecycle_candidate' and f['observed_at_seconds']>since:
                reason='allied_lifecycle_candidate_changed_not_survival_proof'
            elif field=='lane_current_units_and_groups' and old:
                # Ignore continuously changing estimated coordinates. Count
                # changes concern known visible units, not a complete wave.
                a=old[1]['value'].get('counts',[]);b=value.get('counts',[])
                norm=lambda rows: sorted((r['team_id'],r['kind'],r['count']) for r in rows)
                if norm(a)!=norm(b):reason='known_visible_lane_composition_changed'
            if reason:
                reasons.append(dict(reason=reason,entity_id=f['entity_id'],current_fact_id=fid,
                    observed_at_seconds=f['observed_at_seconds'],previous_fact_id=old[0] if old else None))
        self.previous=deepcopy(frame);self.binding=binding
        if not reasons:return None
        result=dict(schema='round-boundary-candidate/v1',at_seconds=at,frame_id=frame['frame_id'],
            previous_scan_seconds=since,reasons=reasons,status='needs_review',
            actual_round_boundary=None,tactical_correctness=None,
            previous_action_execution='unknown',timing_calculations_used=False,
            semantics='Reconsideration candidate from newly available observations; scan time is not exact event/boundary time')
        result['candidate_id']='boundary_'+digest(dict(result,binding=binding))[:24]
        return result
