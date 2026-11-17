"""A personally observed camp can be projected only after its own HUD frame."""
import json

import pytest

from lol_coach.reasoning_frame import compile_frame, digest
from lol_coach.round_camps import attach_personal_camps
from test_macro_snapshot import bundles, query


def test_private_hud_observations_bound_to_source_actor_and_time(bundles, tmp_path):
    bundle = compile_frame(query(bundles,player='self',at=8))
    frame = bundle['frame']
    frame['decision']['player_entity_id'] = '0x400000b4'
    frame['frame_id'] = 'frame_' + digest({k:v for k,v in frame.items() if k!='frame_id'})[:24]
    replay_sha = 'a'*64
    bundle['audit']['source_replay_sha256'] = replay_sha
    source_dir = tmp_path/replay_sha
    source_dir.mkdir()
    path = source_dir/'0x400000b4.json'
    record = dict(schema='personal-camp-hud/v1',source_sha256=replay_sha,actor='0x400000b4',
                  team_id=100,build=frame['decision']['build'],observations=[
                      dict(camp='blue',locator='A',state='engaged',available_at_seconds=2,evidence={}),
                      dict(camp='blue',locator='A',state='engaged',available_at_seconds=8,evidence={'frame':'p'},
                           unrelated_observer_data='hidden'),
                      dict(camp='blue',locator='A',state='cleared',available_at_seconds=9,evidence={},
                           reward_gold=90,reward_time_seconds=8.89,observed_clear_seconds=[5,5.5])])
    def save():
        path.write_text(json.dumps(dict(record,record_sha256=digest(record))),encoding='utf8')
    save()
    result = attach_personal_camps(bundle, tmp_path)
    fid, = result['frame']['personal_camp_fact_ids']
    fact = result['frame']['facts'][fid]
    assert fact['age_seconds']==0 and fact['value']==dict(camp='blue',locator='A',state='engaged',observer_team_id=100)
    assert result['audit']['fact_sources'][fid]['evidence']=={'frame':'p'}
    assert not any(f['value'].get('reward_gold') for f in (fact,))
    assert 'personal_camp_fact_ids' not in frame
    assert attach_personal_camps(result,tmp_path)==result
    bundle['audit']['source_replay_sha256'] = 'b'*64
    assert attach_personal_camps(bundle,tmp_path) is bundle
    bundle['audit']['source_replay_sha256'] = replay_sha
    record['team_id'] = 200
    save()
    with pytest.raises(ValueError, match='source_mismatch'):
        attach_personal_camps(bundle,tmp_path)
