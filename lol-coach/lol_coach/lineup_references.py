"""Expose already source-checked interaction rules as optional references."""
from copy import deepcopy
from .round_chain import _check_bundle
from .reasoning_frame import digest


def attach_lineup_references(bundle,mechanisms):
    frame=_check_bundle(bundle)
    if mechanisms.get('schema')!='champion-mechanisms/v1' or mechanisms.get('patch')!='16.20.1' or frame['decision']['build']!='16.20.824.8524':raise ValueError('Unsupported source/build')
    result=deepcopy(bundle);f=result['frame'];added=[]
    for rule in mechanisms['interactions']:
        for actor in f['lineup']:
            if actor['champion']!=rule['participants'][0]:continue
            allowed=actor['allied_ids'] if rule['relationship']=='ally' else actor['opponent_ids']
            for other in f['lineup']:
                if other['champion']!=rule['participants'][1] or other['entity_id'] not in allowed:continue
                rid='interaction:'+rule['id']+':'+actor['entity_id']+':'+other['entity_id']
                source_names={r['source'] for r in rule['evidence']}
                detail=dict(kind='conditional_static_interaction_not_current_state',rule=deepcopy(rule),actor_id=actor['entity_id'],other_id=other['entity_id'],
                    sources={n:deepcopy(mechanisms['sources'][n]) for n in source_names},
                    current_conditions=None,current_applicability=None,exact_client_compatibility='not_independently_verified')
                f['references'][rid]=dict(kind=detail['kind'],title=rule['summary_zh'],actor_id=actor['entity_id'],other_id=other['entity_id'],
                    relationship=rule['relationship'],patch='16.20.1',current_applicability=None,content_sha256=digest(detail),detail_in_prompt=False)
                result['reference_library'][rid]=detail;added.append(rid)
    f['frame_id']='frame_'+digest({k:v for k,v in f.items() if k!='frame_id'})[:24]
    result['audit']['lineup_reference_ids']=added
    return result
