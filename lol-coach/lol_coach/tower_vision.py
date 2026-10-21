"""Enemy tower observations filtered by the reviewed visibility event channel."""
from .replay_vision import VERSION, known_enemy_state


def enemy_tower_view(towers, vision, at, team):
    if towers.get('version')!=VERSION or vision.get('version')!=VERSION:
        raise ValueError('Unsupported tower view version')
    if towers['source']!=vision['source']:
        raise ValueError('Tower visibility source mismatch')
    identities={}
    for row in towers['identity_events']:
        if row['time_seconds']<=at and row['identity']['team']!=team:
            identities.setdefault(row['entity_id'],row)
    updates=[]
    for row in towers['health_samples']:
        if row['entity_id'] not in identities or row['time_seconds']<identities[row['entity_id']]['time_seconds']:
            continue
        if row['source']['stream']!=1:
            continue  # Do not assume every keyframe payload has current-state semantics.
        src=dict(row['source']);src['decompressed_offset']=src.pop('offset')
        updates.append(dict(row,source=src))
    observed=known_enemy_state(vision['events'],updates,at,team,list(identities))
    return dict(schema='enemy-tower-view/v1',source=towers['source'],version=VERSION,
        cutoff_seconds=at,observer_team_id=team,
        towers={entity:dict(identity=identities[entity],**state) for entity,state in observed.items()},
        visibility_evidence='exact-build cross-checked binary inference; no independent UI confirmation',
        enemy_tower_filter_supported=True,complete_world_vision=False,decision_input_eligible=False,
        limitations=['Current observations are sampled values with age, not continuous HP',
            'Only already-named enemy towers; no hidden HP, future identity or historical sample reuse after reentry',
            'World fog/wards/minions remain unresolved; deaths do not manufacture visibility transitions'])
