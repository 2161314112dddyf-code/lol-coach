"""Synthetic two-team footer tests. In-game rune counters must never enter the player's frame."""
from copy import deepcopy
import json

import pytest

from lol_coach.reasoning_frame import canonical, compile_frame, digest
from lol_coach.replay_runes import attach_player_runes, player_runes, read_replay_rune_pages


BUILD = '16.22.836.1077'
PERKS = [8010, 9111, 9104, 8014, 8304, 8347]


def player(team=200, champion='Pantheon', **changes):
    row = dict(TEAM=str(team), SKIN=champion, PERK_PRIMARY_STYLE='8000', PERK_SUB_STYLE='8300',
               STAT_PERK_0='5008', STAT_PERK_1='5008', STAT_PERK_2='5013', PERK0_VAR1='unreachable_counter')
    row.update({f'PERK{i}': str(p) for i, p in enumerate(PERKS)})
    row.update(changes)
    return row


def setup(rows, at=0):
    version = BUILD.encode()
    meta = json.dumps({'statsJson': json.dumps(rows)}).encode()
    raw = b'RIOT\x02' + b'\0' * 9 + bytes([len(version)]) + version + b'\0' * 256 + meta + len(meta).to_bytes(4, 'little')
    pages = read_replay_rune_pages(raw)
    bundle = compile_frame(dict(schema='macro-snapshot/v1', version=BUILD, source_sha256=pages['source_sha256'],
        context=dict(at_seconds=at, observer_team_id=200, player_entity_id='p'),
        heroes=[dict(entity_id='p', team_id=200, champion='Pantheon', visibility=dict(value=True), inventory={}),
                dict(entity_id='e', team_id=100, champion='Pantheon', visibility=dict(value=None), inventory={})],
        evidence={}, recent_public_combat=[]))
    return bundle, pages


@pytest.mark.parametrize('at', [0, 448])
def test_freezes_only_personally_known_ids_including_repeated_stat_shards(at):
    bundle, pages = setup([player(100, PERK0=8112), player()], at)
    frozen = attach_player_runes(bundle, pages)
    result = player_runes(frozen)
    assert result['perk_ids'] == PERKS and result['shard_ids'] == [5008, 5008, 5013]
    assert result['fact_id'] in frozen['frame']['facts']
    assert frozen['audit']['fact_sources'][result['fact_id']]['source'] == 'footer.statsJson[1]'
    assert '8112' not in canonical(frozen) and 'unreachable_counter' not in canonical(pages)
    assert attach_player_runes(frozen, pages) is frozen and player_runes(bundle) is None


@pytest.mark.parametrize('rows', [[player(STAT_PERK_2=None)], [player(), player()], [player(100)],
                                  [player(PERK2='not-an-id')], [player(PERK0='9104')]])
def test_incomplete_or_ambiguous_own_page_is_unknown(rows):
    base, pages = setup(rows)
    assert attach_player_runes(base, pages) is base and player_runes(base) is None


def test_index_integrity_source_and_build_bound_to_frame():
    base, pages = setup([player()])
    for key in ('source_sha256', 'build'):
        changed = deepcopy(pages)
        changed[key] += '1'
        changed['checksum'] = digest({k:v for k,v in changed.items() if k != 'checksum'})
        with pytest.raises(ValueError, match='scope_mismatch'):
            attach_player_runes(base, changed)
    pages['rows'][0]['page']['perk_ids'][1] += 1
    with pytest.raises(ValueError, match='scope_mismatch'):
        attach_player_runes(base, pages)


def test_native_keystone_contradiction_is_rejected():
    base, pages = setup([player()])
    fact = dict(entity_id='p', field='personal_client_state', value=dict(rune_ids={'keystone':8112}),
                observed_at_seconds=0, temporal_scope='observed_sample')
    frame = base['frame']
    fid = 'f_' + digest(fact)[:20]
    frame['facts'][fid] = fact
    next(h for h in frame['lineup'] if h['entity_id']=='p')['current_fact_ids'].append(fid)
    del frame['frame_id']
    frame['frame_id'] = 'frame_' + digest(frame)[:24]
    with pytest.raises(ValueError, match='disagree'):
        attach_player_runes(base, pages)


def test_ambiguous_same_team_champion_in_frame_is_not_resolved_by_partial_footer():
    base, pages = setup([player()])
    frame = base['frame']
    frame['lineup'].append(dict(frame['lineup'][0], entity_id='other', relation='ally', champion='Pantheon'))
    del frame['frame_id']
    frame['frame_id'] = 'frame_' + digest(frame)[:24]
    assert attach_player_runes(base, pages) is base
