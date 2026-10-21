"""Hero visibility channels for the four supplied 16.20 replays.

Directions/observer teams are cross-checked binary inferences, not a universal
protocol decoder. Unknown initial state is never converted to hidden.
"""
import json
import math
from pathlib import Path

VERSION='16.20.824.8524'
PROFILE=Path(__file__).with_name('profiles')/'vision_16_20.json'
OBSERVABLE_FIELDS=frozenset(('health','max_health','resource','max_resource','level'))


def load_profile():
    profile=json.loads(PROFILE.read_text(encoding='utf8'))
    if profile['version']!=VERSION:raise ValueError('Invalid visibility profile')
    return profile


def decode_payload(opcode,payload,*,version=VERSION,profile=None):
    if version!=VERSION:raise ValueError('Unsupported visibility version')
    profile=load_profile() if profile is None else profile
    if profile['version']!=version:raise ValueError('Visibility profile mismatch')
    operation=profile['opcodes'].get(hex(opcode))
    if operation is None:raise ValueError('Unsupported visibility opcode')
    if len(payload)!=2 or payload.hex() not in profile['observer_codes']:
        raise ValueError('Unsupported visibility payload')
    return dict(observer_team_id=profile['observer_codes'][payload.hex()],
                visible=operation=='enter',kind='visibility_'+operation,
                evidence_level='cross_checked_binary_inference')


def event_key(row):
    """Use original packet order within a timestamp; no look-ahead in a frame."""
    source=row['source']
    return (row['time_seconds'],source['chunk'],source['decompressed_offset'])


def validate_cutoff(at,end):
    if not math.isfinite(at) or at<0 or at>end:raise ValueError('Invalid visibility cutoff')


def visibility_at(events,at,observer_team_id,entities):
    if not math.isfinite(at) or at<0:raise ValueError('Invalid visibility cutoff')
    if observer_team_id not in (100,200):raise ValueError('Unsupported observer team')
    result={entity:dict(visible=None,last_transition=None) for entity in entities}
    for event in sorted(events,key=event_key):
        if event['time_seconds']>at:break
        if event['entity_id'] not in result:continue
        # A malformed visibility message cannot safely retain a prior state.
        if event['observer_team_id'] not in (None,observer_team_id):continue
        result[event['entity_id']]=dict(visible=event['visible'],last_transition=event)
    return result


def intervals(events,entities,end):
    """Half-open intervals, including unknown prefixes for both observer teams."""
    output=[]
    for entity in entities:
        for team in (100,200):
            active=None;start=0.0;origin=None
            relevant=[e for e in sorted(events,key=event_key) if e['entity_id']==entity and e['observer_team_id'] in (None,team)]
            for event in relevant:
                t=event['time_seconds']
                if t<0 or t>end:raise ValueError('Visibility event outside duration')
                if t>start:
                    output.append(dict(entity_id=entity,observer_team_id=team,start_seconds=start,end_seconds=t,
                        visible=active,start_event=origin,end_event=event,right_censored=False))
                active=event['visible'];start=t;origin=event
            if end>start:
                output.append(dict(entity_id=entity,observer_team_id=team,start_seconds=start,end_seconds=end,
                    visible=active,start_event=origin,end_event=None,right_censored=True))
    return output


def known_enemy_state(events,updates,at,observer_team_id,entities):
    """Whitelist visible state samples; never fill from hidden or future data.

    Caller supplies only enemies (or explicit unknown-team research actors).
    Last observed values are historical, not a prediction of hidden state.
    """
    if not math.isfinite(at) or at<0:raise ValueError('Invalid knowledge cutoff')
    if observer_team_id not in (100,200):raise ValueError('Unsupported observer team')
    state={entity:dict(visible=None,current_observed={},last_observed={},last_transition=None) for entity in entities}
    stream=[(event_key(e),0,e) for e in events if e['time_seconds']<=at]
    stream.extend((event_key(u),1,u) for u in updates if u['time_seconds']<=at)
    for _,kind,row in sorted(stream,key=lambda x:(x[0],x[1])):
        entity=row['entity_id']
        if entity not in state:continue
        current=state[entity]
        if kind==0:
            if row['observer_team_id'] not in (None,observer_team_id):continue
            if row['visible'] is not current['visible']:
                current['current_observed']={}
            current['visible']=row['visible'];current['last_transition']=row
        elif current['visible'] is True:
            for name,value in row['values'].items():
                if name not in OBSERVABLE_FIELDS:continue
                sample=dict(value=value,observed_at_seconds=row['time_seconds'],source=row['source'])
                current['current_observed'][name]=sample
                current['last_observed'][name]=sample
    for current in state.values():
        if current['visible'] is not True:current['current_observed']=None
        current['last_observed_is_current_hidden_state']=False
    return state
