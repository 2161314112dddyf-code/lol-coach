"""Recorded real packet regression plus synthetic safety cases; not game UI proof."""
import copy
import math
import pytest
from lol_coach.inventory_sync import decode_sync, decode_item_tail
from lol_coach.spell_activity import decode_activity, load_profile, prefix_events

SYNC = bytes.fromhex('4d3832c4ffd5e88bcd25d07f1636b0b5019a44f26741d6434ac4ffd5e8bbc5267b163287b53a824444d9e956b544442241d69d4444a0ee6246fec4ffd5e88b7534163679356f7cc4ffd5e83b5034cc590a')
SPELL = bytes.fromhex('b50f84867c72e1333420921eb0155b6e0c2adcdcdaa8ede6dbe16248b800eda5410656bb7f28838bfa8b8b6767318ffe2020fd80974e07fefc3f764a8804aedc706dfdf220c7085c58952cdd554ddaeabc9a6d96816d7f6781f9a006edededed93bb71dfccad3ed1ddddcf89b9c8a7e91ec70c89c2dc9a28')


def test_recorded_resync_partial_slots_and_special_unknown():
    result=decode_sync(SYNC)
    assert [(r['slot'],r['item_id']) for r in result['items']]==[(0,3003),(1,6657),(2,3111),(7,None)]
    assert result['missing_slots']=='unknown' and result['complete_inventory_state'] is False
    assert all(r['count_verified'] is False for r in result['items'])


@pytest.mark.parametrize('wire',[b'',SYNC[:3],SYNC.replace(b'\xc4\xff\xd5\xe8',b'\xc4\xef\xd5\xe8',1),SYNC[:-1]+b'\x00'])
def test_bad_sync_structure_refused(wire):
    with pytest.raises(ValueError):decode_sync(wire)


def test_tail_does_not_invent_unknown_identity():
    result=decode_item_tail(bytes.fromhex('3b5034cc590a'))
    assert result['item_id'] is None and not result['empty'] and result['slot']==7


def test_recorded_spell_name_is_not_cooldown_or_cast_count():
    row=decode_activity(SPELL)
    assert row['spell_name']=='ZyraQ'
    assert row['hash_payload_offset']==98
    assert row['new_cast'] is None and row['cooldown_ready_at'] is None
    assert row['target_entity'] is None and row['ability_rank'] is None


@pytest.mark.parametrize('payload',[b'',b'\xb5'+b'\x00'*40,SPELL[:100],b'\x00'+SPELL[1:]])
def test_missing_or_truncated_spell_evidence_refused(payload):
    with pytest.raises(ValueError):decode_activity(payload)


def test_ambiguous_spell_name_refused():
    profile=load_profile();profile=copy.deepcopy(profile)
    profile['vocabulary']['synthetic_collision']=profile['vocabulary']['ZyraQ']
    with pytest.raises(ValueError,match='ambiguous'):decode_activity(SPELL,profile=profile)


def test_wrong_versions_refused():
    with pytest.raises(ValueError):decode_sync(SYNC,version='16.21')
    with pytest.raises(ValueError):decode_activity(SPELL,version='16.21')


def test_helpers_and_phases_remain_separate():
    p=load_profile()['vocabulary']
    assert p['VeigarDarkMatterCastLockout']['role_hint']=='helper_or_effect'
    assert p['JhinRShot']['role_hint']=='followup_or_alternate_stage'
    assert p['LeblancWReturn']['role_hint']=='return_stage'
    assert p['RyzeQ']['role_hint']!=p['RyzeQWrapper']['role_hint']


@pytest.mark.parametrize('cutoff',[-1,math.nan,math.inf])
def test_invalid_activity_cutoff_refused(cutoff):
    with pytest.raises(ValueError):prefix_events([],cutoff)


def test_activity_prefix_excludes_future_without_mutation():
    events=[dict(time_seconds=5,spell_name='past'),dict(time_seconds=6,spell_name='future')]
    assert prefix_events(events,5)==events[:1]
    assert len(events)==2
