"""Freeze only the selected player's rune choices. Footer counters are never imported."""
from copy import deepcopy
import hashlib
import json

from .reasoning_frame import canonical, digest
from .round_chain import _check_bundle, _source


PAGE_FIELDS = (tuple(f'PERK{i}' for i in range(6))
               + tuple(f'STAT_PERK_{i}' for i in range(3))
               + ('PERK_PRIMARY_STYLE', 'PERK_SUB_STYLE'))
SCHEMA = 'replay-rune-pages/v1'
FIELD = 'selected_personal_runes'


def _positive_id(value):
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        value = int(value)
    return value if type(value) is int and value > 0 else None


def _valid_page(page):
    if not isinstance(page, dict) or set(page) != {'perk_ids', 'shard_ids', 'primary_style_id', 'secondary_style_id'}:
        return False
    perks, shards = page['perk_ids'], page['shard_ids']
    return (isinstance(perks, list) and len(perks) == 6 and isinstance(shards, list) and len(shards) == 3
            and all(type(i) is int and i > 0 for i in
                    [*perks, *shards, page['primary_style_id'], page['secondary_style_id']])
            and len(set(perks)) == 6 and page['primary_style_id'] != page['secondary_style_id'])


def read_replay_rune_pages(raw):
    """Read one immutable loadout index, limited to identifiers known before the match."""
    from .replay_container import container_info
    info = container_info(raw)
    players = json.loads(info['metadata'].get('statsJson', '[]'))
    if not isinstance(players, list) or any(not isinstance(p, dict) for p in players):
        raise ValueError('invalid_replay_rune_roster')
    rows = []
    for index, player in enumerate(players):
        ids = [_positive_id(player.get(key)) for key in PAGE_FIELDS]
        page = dict(perk_ids=ids[:6], shard_ids=ids[6:9], primary_style_id=ids[9], secondary_style_id=ids[10])
        rows.append(dict(champion=player.get('SKIN'), team=_positive_id(player.get('TEAM')), index=index,
                         page=page if _valid_page(page) else None))
    content = dict(schema=SCHEMA, build=info['version'], source_sha256=hashlib.sha256(raw).hexdigest(), rows=rows)
    return dict(content, checksum=digest(content))


def _owner(frame):
    decision = frame['decision']
    rows = [h for h in frame['lineup'] if h['entity_id'] == decision['player_entity_id'] and h['relation'] == 'ally']
    if len(rows) != 1:
        raise ValueError('invalid_rune_page_owner')
    return rows[0]


def player_runes(bundle):
    """Return a complete personal page and its fact ID, or None for older/partial frames."""
    frame = _check_bundle(bundle)
    fact_id = frame.get('personal_rune_page_fact_id')
    if fact_id is None:
        return None
    fact = frame['facts'][fact_id]
    owner = _owner(frame)
    if (fact_id not in owner['current_fact_ids'] or fact_id != 'f_' + digest(fact)[:20]
            or fact['entity_id'] != owner['entity_id'] or fact['field'] != FIELD
            or fact['temporal_scope'] != 'fixed_pregame_selection' or fact['observed_at_seconds'] != 0
            or not _valid_page(fact['value'])):
        raise ValueError('invalid_frozen_personal_runes')
    return dict(deepcopy(fact['value']), fact_id=fact_id)


def attach_player_runes(bundle, pages):
    """Match by replay, build, side and unique champion; leave unavailable pages unfilled."""
    frame = _check_bundle(bundle)
    if pages is None:
        return bundle
    content = {k: v for k, v in pages.items() if k != 'checksum'}
    decision = frame['decision']
    if (pages.get('schema') != SCHEMA or pages.get('source_sha256') != _source(bundle)
            or pages.get('build') != decision['build'] or digest(content) != pages.get('checksum')):
        raise ValueError('replay_rune_page_scope_mismatch')
    owner = _owner(frame)
    same_hero = [h for h in frame['lineup'] if h['relation'] == 'ally' and h['champion'] == owner['champion']]
    candidates = [r for r in pages['rows']
                  if (r['champion'], r['team']) == (owner['champion'], decision['observer_team_id'])]
    if len(same_hero) != 1 or len(candidates) != 1 or not candidates[0]['page']:
        return bundle
    candidate, = candidates
    page = candidate['page']
    if not _valid_page(page):
        raise ValueError('invalid_personal_runes')
    sample_ids = dict(keystone=page['perk_ids'][0], primaryRuneTree=page['primary_style_id'],
                      secondaryRuneTree=page['secondary_style_id'])
    for fid in owner['current_fact_ids']:
        row = frame['facts'][fid]
        if row['field'] == 'personal_client_state' and row['entity_id'] == owner['entity_id']:
            observed = row['value'].get('rune_ids')
            if observed and any(observed.get(k, v) != v for k, v in sample_ids.items()):
                raise ValueError('selected_runes_disagree_with_personal_client')
    prior = player_runes(bundle)
    if prior:
        if any(prior[k] != v for k, v in page.items()):
            raise ValueError('inconsistent_frozen_personal_runes')
        return bundle
    result = deepcopy(bundle)
    frame = result['frame']
    fact = dict(field=FIELD, entity_id=owner['entity_id'], value=deepcopy(page),
                temporal_scope='fixed_pregame_selection', observed_at_seconds=0,
                available_at_seconds=0)
    fid = 'f_' + digest(fact)[:20]
    frame['facts'][fid] = fact
    _owner(frame)['current_fact_ids'].append(fid)
    frame['personal_rune_page_fact_id'] = fid
    result['audit']['fact_sources'][fid] = dict(source_sha256=pages['source_sha256'], build=pages['build'],
            source=f"footer.statsJson[{candidate['index']}]", fields=list(PAGE_FIELDS),
            scope='preselected_ids_only_without_performance_counters')
    frame.pop('frame_id')
    frame['frame_id'] = 'frame_' + digest(frame)[:24]
    result['audit']['frame_chars'] = len(canonical(frame))
    return result
