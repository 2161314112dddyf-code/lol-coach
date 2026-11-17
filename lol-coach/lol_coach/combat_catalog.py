"""Publish versioned Riot combat references and pin only a player's loadout for offline review."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import re

from .file_model_bridge import atomic_bytes, file_sha256
from .reasoning_frame import canonical, digest, lookup_reference, plain
from .round_chain import _check_bundle


KEY = 'combat_reference'


def validate_build(build, release):
    if (not isinstance(build, str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+', build)
            or build.split('.')[:2] != release.split('.')[:2]):
        raise ValueError('combat build must be an exact game build in the requested Data Dragon patch')


def _publication(client, release, filename):
    url = f'https://ddragon.leagueoflegends.com/cdn/{release}/data/zh_CN/{filename}.json'
    evidence, payload = client.fetch(f'riot-{filename}-{release}-zh_CN', url, expect_json=True, refresh=True)
    if (evidence.get('http_status') != 200 or evidence.get('requested_url') != url
            or evidence.get('final_url') != url or payload is None):
        raise ValueError(f'unconfirmed {filename} source for {release}')
    return payload, {k: evidence[k] for k in ('requested_url', 'final_url', 'http_status',
                                              'sha256', 'retrieved_at_utc', 'evidence_path')}


def roster_ability_profiles(build, champions):
    from .ability_damage_data import damage_profile
    profiles = {}
    for champion in champions:
        for slot in 'QWER':
            profile = damage_profile(build, champion, slot)
            if profile is not None:
                profiles.setdefault(champion, {})[slot] = profile
    return profiles


def fetch_combat_catalog(client, build, release, rules, ability_profiles):
    validate_build(build, release)
    trees, rune_source = _publication(client, release, 'runesReforged')
    items_file, item_source = _publication(client, release, 'item')
    if (not isinstance(trees, list) or not trees or not isinstance(items_file, dict)
            or items_file.get('version') != release or items_file.get('type') != 'item'
            or not isinstance(items_file.get('data'), dict) or not items_file['data']):
        raise ValueError('incomplete or mismatched combat sources')
    runes, items = {}, {}
    for tree in trees:
        if (not isinstance(tree, dict) or type(tree.get('id')) is not int
                or not isinstance(tree.get('slots'), list) or not tree['slots']):
            raise ValueError('invalid rune tree')
        for slot_index, slot in enumerate(tree['slots']):
            if not isinstance(slot, dict) or not isinstance(slot.get('runes'), list) or not slot['runes']:
                raise ValueError('empty rune slot')
            for rune in slot['runes']:
                if (not isinstance(rune, dict) or type(rune.get('id')) is not int or rune['id'] <= 0
                        or str(rune['id']) in runes or not all(isinstance(rune.get(k), str) and rune[k]
                                                              for k in ('name', 'key', 'longDesc'))):
                    raise ValueError('invalid or duplicate rune')
                rid = str(rune['id'])
                runes[rid] = dict(name=rune['name'], key=rune['key'], tree_id=tree['id'], slot_index=slot_index,
                                  description=plain(rune['longDesc']))
    for item_id, item in items_file['data'].items():
        if (not re.fullmatch('[1-9][0-9]*', item_id) or not isinstance(item, dict)
                or not isinstance(item.get('name'), str)
                or not isinstance(item.get('description', ''), str)):
            raise ValueError('invalid item in combat catalog')
        raw_description = item.get('description', '')
        items[item_id] = dict(name=item['name'], description=plain(raw_description.replace('<br>', ' ')),
                              raw_description=raw_description,
                              stats=item.get('stats', {}), maps=item.get('maps', {}))
    if rules is not None and rules.get('build') != build:
        raise ValueError('rune rules refer to another client build')
    return dict(schema='combat-source-catalog/v1', build=build, static_release=release,
                runes=runes, items=items, unnamed_item_ids=sorted(i for i, row in items.items() if not row['name']),
                rune_rules=rules, ability_profiles=ability_profiles,
                sources=dict(runes=rune_source, items=item_source))


def archive_game_sources(root, game_dir, catalog, champions):
    """Keep the verified WAD members while the matching installation is still available."""
    from .review_data_store import client_combat_bases
    from .wad import WadReader

    build = catalog['build']
    rows = list((catalog['rune_rules'] or {}).get('sources', []))
    bases = client_combat_bases(build)
    for name in champions:
        if name in bases:
            src = bases[name]['source']
            rows.append(dict(archive=f'DATA/FINAL/Champions/{name}.wad.client',
                             asset=src['asset'], sha256=src['sha256']))
        for profile in catalog['ability_profiles'].get(name, {}).values():
            src = profile['source']
            for kind in ('spell', 'tooltip'):
                rows.append(dict(archive=src[kind+'_archive'], asset=src[kind+'_asset'],
                                 sha256=src[kind+'_sha256']))
    archived = {}
    readers = {}
    for row in rows:
        if 'archive' not in row:
            continue
        expected = row['sha256']
        if expected in archived:
            continue
        archive = row['archive']
        if archive not in readers:
            readers[archive] = WadReader(Path(game_dir) / archive)
        reader = readers[archive]
        if 'asset' in row:
            body, _ = reader.extract_bytes(row['asset'], max_bytes=48_000_000)
        else:
            body, _ = reader.extract_hash(int(row['asset_hash'], 16), max_bytes=48_000_000)
        if sha256(body).hexdigest() != expected:
            raise ValueError(f'installed combat asset differs from reviewed build: {archive}')
        relative = Path('evidence', 'raw', expected + '.bin')
        path = Path(root) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            atomic_bytes(path, body)
        except FileExistsError:
            if file_sha256(path) != expected:
                raise ValueError(f'corrupt cached combat asset: {expected}')
        archived[expected] = {**row, 'local_file': relative.as_posix(), 'bytes': len(body)}
    return list(archived.values())


def _pinned(bundle):
    frame = _check_bundle(bundle)
    ref = frame['task'].get(KEY)
    if ref is None:
        return None
    pinned = lookup_reference(bundle, ref)
    if (ref != 'combat_' + digest(pinned) or pinned['build'] != frame['decision']['build']
            or pinned['player_entity_id'] != frame['decision']['player_entity_id']):
        raise ValueError('combat reference does not match frozen player and build')
    return pinned


def _load_catalog(root, build, snapshot_id, lineup):
    from .review_data_store import _records

    closest = None
    matched = -1
    for _, record in _records(root, '.'.join(build.split('.')[:2])):
        catalog = record.get('combat_catalog')
        if not catalog or catalog['build'] != build:
            continue
        if snapshot_id is not None:
            fingerprint = digest(catalog)
            if fingerprint == snapshot_id:
                return catalog, fingerprint
            continue
        covered = len(lineup.intersection(record['scope']['champions']))
        if covered == len(lineup):
            return catalog, digest(catalog)
        if covered > matched:
            closest, matched = catalog, covered
    if snapshot_id is not None:
        raise ValueError('pinned combat catalog unavailable for the next frame')
    return (closest, digest(closest)) if closest is not None else (None, None)


def _loadout(bundle):
    from .replay_runes import player_runes

    frame = bundle['frame']
    actor = frame['decision']['player_entity_id']
    at = frame['decision']['at_seconds']
    selected = player_runes(bundle)
    rune_ids = set(selected['perk_ids']) if selected else set()
    shards = list(selected['shard_ids']) if selected else []
    item_ids, inventory_seen = set(), False
    for fact in frame['facts'].values():
        if (fact['entity_id'] == actor and fact['field'] == 'personal_client_state'
                and fact['observed_at_seconds'] == at):
            state = fact['value']
            if not selected and (keystone := (state.get('rune_ids') or {}).get('keystone')):
                rune_ids.add(keystone)
            if isinstance(state.get('inventory'), list):
                inventory_seen = True
                item_ids.update(item['item_id'] for item in state['inventory'])
    return rune_ids, shards, item_ids, inventory_seen


def preload_combat(bundles, root, *, previous=None, disabled=False):
    """Resolve one immutable update for all decisions, then select the owner's visible equipment per frame."""
    pins = [_pinned(b) for b in bundles]
    old = _pinned(previous) if previous else None
    ids = {p['catalog_sha256'] for p in [old, *pins] if p}
    if len(ids) > 1:
        raise ValueError('conflicting frozen combat catalogs')
    if disabled:
        if old:
            raise ValueError('previous plan uses a combat catalog that is disabled for this session')
        result = []
        for bundle, pin in zip(bundles, pins):
            if not pin:
                result.append(bundle)
                continue
            updated = deepcopy(bundle)
            frame = updated['frame']
            ref = frame['task'].pop(KEY)
            del frame['references'][ref], updated['reference_library'][ref]
            _seal(updated)
            result.append(updated)
        return result
    if all(pins):
        return bundles
    build = bundles[0]['frame']['decision']['build']
    if not isinstance(build, str) or not re.fullmatch(r'\d+\.\d+\.\d+\.\d+', build):
        return bundles
    lineup = {hero['champion'] for hero in bundles[0]['frame']['lineup']}
    catalog, fingerprint = _load_catalog(root, build, next(iter(ids), None), lineup)
    if catalog is None:
        return bundles
    result = []
    for bundle, pin in zip(bundles, pins):
        if pin:
            result.append(bundle)
            continue
        frame = bundle['frame']
        if build != frame['decision']['build']:
            raise ValueError('mixed combat catalog builds')
        runes, shards, items, inventory_seen = _loadout(bundle)
        content = dict(build=build, static_release=catalog['static_release'], catalog_sha256=fingerprint,
                       player_entity_id=frame['decision']['player_entity_id'], sources=catalog['sources'],
                       rune_rules=catalog['rune_rules'], shard_ids=shards, inventory_observed=inventory_seen)
        if 'ability_profiles' in catalog:
            content['ability_profiles'] = {h['champion']: catalog['ability_profiles'][h['champion']]
                                           for h in frame['lineup'] if h['champion'] in catalog['ability_profiles']}
        for key, ids_in_frame in [('runes', runes), ('items', items)]:
            requested = sorted(str(i) for i in ids_in_frame)
            content[key] = {i: catalog[key][i] for i in requested if i in catalog[key] and catalog[key][i]['name']}
            content['missing_' + key] = [i for i in requested if i not in content[key]]
        updated = deepcopy(bundle)
        f = updated['frame']
        sha = digest(content)
        ref = 'combat_' + sha
        updated['reference_library'][ref] = deepcopy(content)
        f['references'][ref] = dict(kind='combat_catalog_for_player', content_sha256=sha)
        f['task'][KEY] = ref
        _seal(updated)
        result.append(updated)
    return result


def _seal(bundle):
    frame = bundle['frame']
    frame.pop('frame_id')
    frame['frame_id'] = 'frame_' + digest(frame)[:24]
    bundle['audit']['frame_chars'] = len(canonical(frame))
