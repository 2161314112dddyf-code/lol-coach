import json
from pathlib import Path

import pytest

from lol_coach.movement_1622 import RED_JUNGLE_REPLAY, VERSION
from lol_coach.player_state import load_own_observations, own_live_sample
from lol_coach.round_plan import review_round_plan
from test_lane_opportunity import ally_path, lane_case, seen
from test_round_chain import freeze


def test_nearest_to_player_can_replace_hidden_lane_opponent():
    b = lane_case()
    f = b['frame']
    ally_path(f, 'self', 100, 9.95)
    ally_path(f, 'ally', 550, 9.97)
    seen(f,'enemy',105,9.96,visible=False)
    seen(f,'jungler',300,9.91)
    p = review_round_plan(freeze(b))
    a = p['player_action_context']
    assert [e['entity_id'] for e in a['opponents_by_sampled_gap']] == ['jungler']
    assert a['allies_by_gap_to_nearest_opponent'][0]['sampled_gap_world_units'] == 250
    assert p['support_lane_opportunity']['engage']['target'] == 'jungler'


def test_stale_player_position_prohibits_ranking_visible_enemies():
    b = lane_case()
    ally_path(b['frame'],'self',100,4)
    seen(b['frame'],'enemy',110,9.99)
    p = review_round_plan(freeze(b))
    assert p['player_action_context']['position_status']=='stale'
    assert p['player_action_context']['opponents_by_sampled_gap']==[]
    assert p['support_lane_opportunity']['engage']['target'] is None


def test_nearest_visible_enemy_across_map_is_not_a_local_engagement():
    b = lane_case()
    ally_path(b['frame'],'self',100,9.9)
    seen(b['frame'],'enemy',12100,9.99)
    p = review_round_plan(freeze(b))
    assert p['player_action_context']['opponents_by_sampled_gap'][0]['sampled_gap_world_units']==12000
    assert p['player_action_context']['local_contact_to_check'] is None
    assert p['support_lane_opportunity']['engage']['target'] is None


def test_status_from_native_replay_is_bound_to_player_clock_and_team(tmp_path):
    eid = '0x400000b4'
    team = 200
    sha = RED_JUNGLE_REPLAY
    source = 'native_replay_liveclient_allplayers_self'
    hero = dict(rawChampionName='game_character_displayname_Pantheon',team='CHAOS',
                isDead=True,respawnTimer=4.1,level=4,scores={'creepScore':30},
                items=[dict(itemID=1036,count=1),dict(itemID=1036,count=1)],
                summonerSpells={k:{'displayName':v} for k,v in
                    [('summonerSpellOne','Smite'),('summonerSpellTwo','Flash')]},
                runes={k:{'id':1} for k in ('keystone','primaryRuneTree','secondaryRuneTree')})
    doc = dict(gameData=dict(gameTime=300.0,mapNumber=11),allPlayers=[hero,dict(hero,team='ORDER',level=18)])
    row = own_live_sample(doc,300,sha,team,eid)
    assert row['value']['inventory']==[dict(item_id=1036,count=2)] and row['value']['level']==4
    with pytest.raises(ValueError,match='clock_or_roster'):
        own_live_sample(doc,295,sha,team,eid)
    receipt = dict(schema='own-replay-state/v1',source_sha256=sha,entity_id=eid,team_id=team,build=VERSION,
                   samples=[row])
    path = Path(tmp_path)/sha/eid/(source+'.json')
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(receipt))
    index = dict(source_sha256=sha,version=VERSION)
    def load(at):
        return load_own_observations(index,team,eid,at,tmp_path)
    assert load(299.99)==[] and load(301.01)==[]
    assert load(300)[0]['value']['is_dead'] is True
    assert load_own_observations(index,100,'0x400000ae',300,tmp_path)==[]
    receipt['samples'][0]['value']['is_dead']=False
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError,match='invalid_native_player_state_evidence'):
        load(300)
