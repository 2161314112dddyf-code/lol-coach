"""Read explicitly linked geometry landmarks without assuming runtime priority."""
import math


def extract_context(config, container_key):
    container = config[container_key]
    if container.get('__type') != 'MapContainer':
        raise ValueError('Expected MapContainer')
    navs = [x['NavGridPath'] for x in container.get('components', [])
            if isinstance(x, dict) and x.get('__type') == 'MapNavGrid']
    if len(navs) != 1:
        raise ValueError('Missing or ambiguous container navigation grid')
    landmarks = {}
    for chunk_key in set(container.get('chunks', {}).values()):
        chunk = config.get(chunk_key, {})
        if chunk.get('__type') != 'MapPlaceableContainer':
            continue
        for item_key, item in chunk.get('items', {}).items():
            if not isinstance(item, dict) or item.get('name') not in ('__Spawn_T1', '__Spawn_T2'):
                continue
            name = item['name']
            if name in landmarks or item.get('__type') != 'GdsMapObject' or item.get('type') != 1:
                raise ValueError('Duplicate or unexpected spawn object')
            transform = item.get('transform')
            if not isinstance(transform, list) or len(transform) != 4 or any(len(row) != 4 for row in transform):
                raise ValueError('Invalid spawn transform')
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for row in transform for v in row):
                raise ValueError('Invalid spawn transform values')
            # Refuse parent/transformed objects until composition is implemented.
            if transform[:3] != [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]] or transform[3][3] != 1 or 'transform' in chunk:
                raise ValueError('Only unparented translation spawn transforms supported')
            landmarks[name] = {'chunk_object': chunk_key, 'item_key': item_key,
                               'position_xyz': transform[3][:3], 'object_type': 'GdsMapObject',
                               'meaning': 'named_spawn_base_not_verified_first_slot'}
    if set(landmarks) != {'__Spawn_T1', '__Spawn_T2'}:
        raise ValueError('Both linked spawn objects are required')
    return {'container_object': container_key, 'navigation_path': navs[0], 'spawn_bases': landmarks}


def compare_navigation(skin_path, container_path):
    same = skin_path.lower() == container_path.lower()
    return {'status': 'references_agree_runtime_unverified' if same else 'conflicting_navigation_references',
            'skin_path': skin_path, 'container_path': container_path,
            'runtime_selected_path': None, 'priority_rule_verified': False}


def compare_spawn(position, base_xyz, offset_xyz):
    # A hypothesis test, not a claim that offsets are applied in world axes.
    predicted = [base_xyz[0] + offset_xyz[0], base_xyz[2] + offset_xyz[2]]
    residual = [position[i] - predicted[i] for i in range(2)]
    return {'base_plus_offset_hypothesis_xz': predicted, 'candidate_minus_hypothesis_xz': residual,
            'residual_distance_game_units': math.hypot(*residual),
            'application_rule_verified': False, 'exact_spawn_verified': False}
