"""Causal lifetime of received-route time estimates, independent of the LLM.

Freshness is an explicit operational policy, not a measured error guarantee.
No countdown or path endpoint establishes physical arrival.
"""
from copy import deepcopy
import hashlib
import json
import math

from .action_evidence import conditional_travel


VERSION = '16.20.824.8524'


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def point(value):
    return isinstance(value, (list, tuple)) and len(value)==2 and all(finite(v) for v in value)


def event_order(row):
    src = row['source']
    fields = [src.get(k, -1) for k in ('chunk','decompressed_offset','packet_index','ordinal')]
    if any(type(v) is not int or v < -1 for v in fields):
        raise ValueError('Invalid source order')
    return (row['time_seconds'], *fields)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
        separators=(',',':')).encode('utf8')).hexdigest()


class TravelValidityTracker:
    def __init__(self, *, source_sha256, version, observer_team_id, max_path_age_seconds=1.0):
        if (not isinstance(source_sha256,str) or len(source_sha256)!=64
                or any(c not in '0123456789abcdef' for c in source_sha256)):
            raise ValueError('Replay SHA256 required')
        if version != VERSION or type(observer_team_id) is not int or observer_team_id not in (100,200):
            raise ValueError('Unsupported build or observer')
        if not finite(max_path_age_seconds) or max_path_age_seconds<=0:
            raise ValueError('Positive finite freshness policy required')
        self.binding = dict(source_sha256=source_sha256,version=version,observer_team_id=observer_team_id)
        self.max_age = max_path_age_seconds
        self.entities = {}
        self.last_order = None
        self.same_order_events = {}

    def _invalidate(self, state, reason, event):
        old = state['plan']
        state['plan'] = None
        state['last_transition'] = dict(reason=reason,time_seconds=event['time_seconds'],
            source=deepcopy(event['source']), invalidated_plan_id=old['plan_id'] if old else None)

    def feed(self, event):
        if event.get('source',{}).get('stream') != 1:
            return
        t = event.get('time_seconds')
        if not finite(t) or t<0:
            raise ValueError('Invalid live timestamp')
        if event.get('source_sha256')!=self.binding['source_sha256'] or event.get('version')!=self.binding['version']:
            raise ValueError('Replay/build mismatch')
        if event.get('kind')=='visibility' and event.get('observer_team_id')!=self.binding['observer_team_id']:
            return
        key = event_order(event)
        if self.last_order is not None and key<self.last_order:
            raise ValueError('Feed must be ordered')
        if key != self.last_order:
            self.same_order_events = {}
        actor = event.get('entity_id')
        previous = self.same_order_events.get(actor)
        if previous is not None:
            if previous != event:
                raise ValueError('Ambiguous conflicting events at the same source order')
            return
        self.same_order_events[actor] = deepcopy(event)
        self.last_order = key
        entity = event.get('entity_id')
        if not isinstance(entity,str) or not entity:
            raise ValueError('Entity required')
        kind = event.get('kind')
        public_death = kind=='death' and event.get('public') is True
        if entity not in self.entities:
            if kind!='visibility' and not public_death:
                return  # Never-seen hidden samples cannot create model-visible identities.
            self.entities[entity] = dict(visible=None,alive=None,plan=None,speed_sample=None,
                last_transition=None,arrival_observation=None,visible_since=None,
                terminal_candidate=False)
        state = self.entities[entity]
        if kind=='visibility':
            value = event.get('value')
            if value is not None and type(value) is not bool:
                raise ValueError('Visibility must be bool or unknown')
            if value is not True:
                self._invalidate(state,'visibility_lost' if value is False else 'visibility_unknown',event)
                state['alive'] = False if state['alive'] is False else None
                state['speed_sample']=None;state['arrival_observation']=None;state['visible_since']=None
            elif state['visible'] is not True:
                self._invalidate(state,'new_visible_interval_requires_new_path',event)
                state['visible_since']=t
            state['visible']=value
            return
        if state['visible'] is not True and not public_death:
            return
        if kind=='death':
            state['alive']=False
            self._invalidate(state,'observed_death',event)
            state['arrival_observation']=None
            return
        if kind=='removal_candidate':
            state['alive']=None
            state['terminal_candidate']=True
            self._invalidate(state,'terminal_removal_candidate',event)
            state['arrival_observation']=None
            return
        if state['terminal_candidate'] or (event.get('entity_kind')=='minion' and state['alive'] is False):
            # Entity reuse is not decoded. A minion terminal state cannot be
            # undone by an unexplained late sample under the same identifier.
            return
        if kind=='respawn_candidate':
            state['alive']=None
            self._invalidate(state,'respawn_not_positive_health',event)
            state['arrival_observation']=None
            return
        if kind=='health':
            value=event.get('value')
            if not finite(value) or value<0:
                raise ValueError('Invalid health')
            if value==0:
                state['alive']=False
                self._invalidate(state,'observed_zero_health',event)
                state['arrival_observation']=None
            else:
                if state['alive'] is False:
                    self._invalidate(state,'positive_health_requires_new_path',event)
                state['alive']=True
            return
        if kind=='speed':
            value=event.get('value')
            if not finite(value) or value<0:
                raise ValueError('Invalid speed')
            state['speed_sample']=dict(value=value,time_seconds=t,source=deepcopy(event['source']))
            plan=state['plan']
            if plan and not math.isclose(value,plan['speed'],rel_tol=0,abs_tol=1e-5):
                self._invalidate(state,'speed_changed_requires_new_path',event)
            return
        if kind not in ('path','position'):
            raise ValueError('Unsupported validity event')
        if kind=='path' and (type(event.get('entity_team_id')) is not int
                or event['entity_team_id'] != self.binding['observer_team_id']):
            raise ValueError('Planned route requires verified observer-team ownership')
        points=event.get('points') if kind=='path' else [event.get('point')]
        if not isinstance(points,list) or not points or not all(point(p) for p in points):
            raise ValueError('Finite points required')
        old=state['plan']
        if old and state['alive'] is True and math.dist(points[0],old['points'][-1])<=5:
            age=t-old['issued_at_seconds']
            state['arrival_observation']=dict(plan_id=old['plan_id'],observed_at_seconds=t,
                elapsed_since_path_seconds=age,report_position=deepcopy(points[0]),
                source=deepcopy(event['source']),exact_arrival_seconds=None,
                continuous_fresh_observation=age<=self.max_age,
                semantics='Near-endpoint position report, not exact arrival or successful action')
        if kind=='position':
            # A position refresh does not refresh route age or establish intent.
            return
        speed=event.get('speed')
        if not finite(speed) or speed<0:
            raise ValueError('Invalid path speed')
        if state['alive'] is False:
            self._invalidate(state,'path_while_known_dead',event)
            return
        self._invalidate(state,'new_path_replaced' if old else 'new_path',event)
        if len(points)==1:
            state['last_transition']['reason']='single_point_observation'
            return
        if speed==0:
            state['last_transition']['reason']='zero_speed_no_eta'
            return
        calc=conditional_travel(points,speed)
        arrival=t+calc['duration_seconds']
        if not finite(arrival):
            raise ValueError('ETA overflow')
        if calc['route_length_game_units']==0:
            state['last_transition']['reason']='zero_length_no_arrival_claim'
            return
        plan=dict(entity_id=entity,issued_at_seconds=t,points=deepcopy(points),speed=speed,
            path_length=calc['route_length_game_units'],nominal_duration_seconds=calc['duration_seconds'],
            nominal_arrival_seconds=arrival,expires_at_seconds=min(arrival,t+self.max_age),
            source=deepcopy(event['source']),semantics='Conditional on received route and unchanged movement state')
        plan['plan_id']='plan_'+fingerprint(dict(plan,binding=self.binding))[:24]
        state['plan']=plan
        # The new path is the latest speed evidence at its new current start.
        state['speed_sample']=dict(value=speed,time_seconds=t,source=deepcopy(event['source']))

    def snapshot(self, at_seconds, *, entity_ids=None):
        if not finite(at_seconds) or at_seconds<0 or self.last_order and at_seconds<self.last_order[0]:
            raise ValueError('Cannot query before fed data or invalid time')
        entities={}
        for entity,state in self.entities.items():
            if entity_ids is not None and entity not in entity_ids:
                continue
            row=deepcopy(state); plan=row['plan']; remaining=None
            if row['visible'] is not True:
                status='not_visible' if row['visible'] is False else 'visibility_unknown'
            elif row['terminal_candidate']:
                status='terminal_candidate'
            elif row['alive'] is False:
                status='blocked_dead'
            elif row['alive'] is None:
                status='unknown_liveness'
            elif plan is None:
                status='awaiting_new_path'
            elif at_seconds>=plan['nominal_arrival_seconds']:
                status='due_unconfirmed'
            elif at_seconds>=plan['issued_at_seconds']+self.max_age:
                status='observation_stale'
            else:
                status='conditional_active'
                remaining=plan['nominal_arrival_seconds']-at_seconds
            # Expired plans remain explicitly historical for local audit; no
            # current remaining-time number is exposed when a gate is missing.
            row.update(status=status,conditional_remaining_seconds=remaining,
                actual_arrival_seconds=None,decision_input_eligible=False)
            entities[entity]=row
        return dict(schema='travel-validity/v1',binding=deepcopy(self.binding),at_seconds=at_seconds,
            max_path_age_seconds=self.max_age,entities=entities,decision_input_eligible=False,
            freshness_policy_semantics='Engineering expiry, not proven accuracy or observed arrival',
            validation_gate='Standalone only; timing qualification remains separate')


def query_validity(events, *, at_seconds, **kwargs):
    if not finite(at_seconds) or at_seconds<0:
        raise ValueError('Invalid cutoff')
    tracker=TravelValidityTracker(**kwargs)
    prefix=[]
    for event in events:
        if event.get('source',{}).get('stream')!=1:
            continue
        t=event.get('time_seconds')
        if not finite(t) or t<0:
            raise ValueError('Invalid live time')
        if t<=at_seconds:
            prefix.append(event)
    for event in sorted(prefix,key=event_order):
        tracker.feed(event)
    return tracker.snapshot(at_seconds)
