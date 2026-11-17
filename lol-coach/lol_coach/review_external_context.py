"""Pin one eligible external-data reference to a sequence of frozen rounds."""
from copy import deepcopy

from .reasoning_frame import canonical, digest, lookup_reference
from .review_subject import _assigned_actors
from .round_chain import _check_bundle, _source, attach_previous_plan


def _assigned_lane_roles(frame, subject):
    sides = ((True, 'ally'), (False, 'enemy'))
    supported = {(allied, lane): (side, lane) for allied, side in sides
                 for lane in ('TOP', 'JUNGLE', 'MIDDLE', 'BOTTOM', 'UTILITY')}
    assigned = _assigned_actors(frame, subject, supported)
    return {side: {lane: actor for (relation, lane), actor in assigned.items() if relation == side}
            for _, side in sides} if assigned else None


def _scope(bundle, roles):
    frame = bundle['frame']
    return (_source(bundle), frame['decision']['build'], frame['decision']['observer_team_id'],
            frame['decision']['player_entity_id'], frame['task'].get('bottom_lane_actors'),
            frame['task'].get('roam_actors'), frame['task'].get('external_lane_roles', roles),
            sorted((h['entity_id'], h.get('champion'), h['relation']) for h in frame['lineup']))


def _index_profiles(context):
    tables = context.get('cn_lane_profiles') if context else None
    if not tables:
        return context, {}
    index = []
    details = {}
    for table in tables:
        ref = 'profile_' + digest(table)
        details[ref] = table
        entry = {key: table[key] for key in ('side', 'lane', 'champion_id', 'table', 'stat_date',
                 'source', 'source_url', 'retrieved_at_utc', 'sha256') if key in table}
        index.append(dict(entry, row_count=len(table['rows']), reference_id=ref))
    return {**context, 'cn_lane_profiles': index,
            'profile_lookup': '按英雄、分路和统计表选一项，用 get_reference(reference_id) 读该表。'}, details


def bind_session_external_data(bundles, root, *, cutoff=None, subject=None, previous=None, disabled=False):
    """Reuse a frozen reference on replay, including when its source is offline."""
    from .review_data_store import context_for_frame

    key = 'external_data_reference'
    time_key = 'match_information_cutoff_utc'
    frames = [_check_bundle(b) for b in bundles]
    if disabled and previous and _check_bundle(previous)['task'].get(key):
        raise ValueError('external_data_disabled_requires_previous_card_without_external_data')
    if disabled and all(key not in f['task'] for f in frames):
        return bundles
    scoped_bundles = ([previous] if previous else []) + list(bundles)
    roles = None
    for bundle in scoped_bundles:
        frame = _check_bundle(bundle)
        old_roles = frame['task'].get('external_lane_roles')
        assigned = _assigned_lane_roles(frame, subject) if subject and not disabled else None
        for group in (old_roles, assigned):
            if group is not None:
                if roles is not None and group != roles:
                    raise ValueError('external_data_sequence_lineup_or_role_mismatch')
                roles = group
    scope = _scope(bundles[0], roles)
    pinned = None
    profiles = {}
    for bundle in scoped_bundles:
        frame = _check_bundle(bundle)
        old_cutoff = frame['task'].get(time_key)
        if old_cutoff and cutoff and old_cutoff != cutoff:
            raise ValueError('external_data_match_information_cutoff_mismatch')
        if old_cutoff:
            cutoff = old_cutoff
        ref = frame['task'].get(key)
        if disabled or not ref:
            continue
        if _scope(bundle, roles) != scope:
            raise ValueError('external_data_sequence_lineup_or_role_mismatch')
        detail = lookup_reference(bundle, ref)
        if ref != 'external_' + digest(detail):
            raise ValueError('external_data_reference_id_mismatch')
        if pinned is not None and detail != pinned:
            raise ValueError('external_data_conflicting_frozen_snapshots')
        for table in detail.get('cn_lane_profiles', []):
            if profile_ref := table.get('reference_id'):
                profile = lookup_reference(bundle, profile_ref)
                if profile_ref != 'profile_' + digest(profile):
                    raise ValueError('external_profile_reference_id_mismatch')
                profiles[profile_ref] = profile
        pinned = detail
    if not disabled and pinned is None:
        view = frames[0]
        metadata = {}
        if cutoff:
            metadata[time_key] = cutoff
        if roles:
            metadata['external_lane_roles'] = roles
        if any(view['task'].get(k) != v for k, v in metadata.items()):
            view = {k: v for k, v in view.items() if k != 'frame_id'}
            view['task'] = {**view['task'], **metadata}
            view['frame_id'] = 'frame_' + digest(view)[:24]
        pinned, profiles = _index_profiles(context_for_frame(root, view))
    if pinned is not None and any(_scope(b, roles) != scope for b in bundles):
        raise ValueError('external_data_sequence_lineup_or_role_mismatch')
    ref = 'external_' + digest(pinned) if pinned is not None else None
    result = []
    for bundle, frame in zip(bundles, frames):
        old = frame['task'].get(key)
        if old == ref and (not ref or not roles or frame['task'].get('external_lane_roles') == roles):
            result.append(bundle)
            continue
        if disabled and frame['task'].get('previous_plan'):
            updated = attach_previous_plan(bundle, max_chars=300000)
        else:
            updated = deepcopy(bundle)
        f = updated['frame']
        if ref:
            for profile_ref, table in profiles.items():
                f['references'][profile_ref] = dict(kind='pregame_lane_profile', content_sha256=digest(table))
                updated['reference_library'][profile_ref] = deepcopy(table)
            f['references'][ref] = dict(kind='versioned_external_data', content_sha256=digest(pinned),
                                        patch=pinned['patch'], snapshot_id=pinned['snapshot_id'])
            updated['reference_library'][ref] = deepcopy(pinned)
            f['task'][key] = ref
            if roles:
                f['task']['external_lane_roles'] = deepcopy(roles)
            if cutoff:
                f['task'][time_key] = cutoff
        elif old and disabled:
            for entry in lookup_reference(bundle, old).get('cn_lane_profiles', []):
                if profile_ref := entry.get('reference_id'):
                    del f['references'][profile_ref], updated['reference_library'][profile_ref]
            del f['references'][old], updated['reference_library'][old], f['task'][key]
        f.pop('frame_id')
        f['frame_id'] = 'frame_' + digest(f)[:24]
        updated['audit']['frame_chars'] = len(canonical(f))
        result.append(updated)
    return result
