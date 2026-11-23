from lol_coach.review_pings import assist_distances
from scripts.prepare_personal_match import add_signal_checkpoints, own_action_signals, review_times
from scripts.audit_native_match_events import public_event
from scripts.run_review_agent import match_sequence_paths
import json
import pytest


def test_assist_schedule_ignores_future_requests_and_other_senders():
    def ping(t, champion='Pantheon', team=200):
        return dict(time_seconds=t, sender_champion=champion, team_id=team, kind='assist_me')
    events = [ping(448.1), ping(80, 'Ahri'), ping(50, team=100), ping(599)]
    rows = review_times(600.4, 150, events, 'Pantheon', 200)
    assert [r['at'] for r in rows] == [0, 150, 300, 450, 451, 466, 600]
    assert all('own_assist' not in r['selected_by'] for r in rows if r['at'] <= 450)
    assert rows[-1]['selected_by'] == ['last_game_second', 'regular']


def test_event_mode_selects_only_novel_personal_action_pings_and_reuses_assist_checkpoints():
    def event(t, kind, actor='self', team=200, point=None):
        return dict(time_seconds=t, sender_entity_id=actor, sender_champion='Pantheon', team_id=team,
                    kind=kind, source={'packet_record': int(t)}, marker_xz=point)
    events = [event(10.2, 'assist_me'), event(10.7, 'assist_me'), event(25, 'enemy_missing'),
              event(27, 'need_vision'), event(28, 'command'), event(29, 'enemy_vision'),
              event(30, 'on_my_way', actor='ally'), event(31, 'on_my_way', team=100),
              event(40.2, 'on_my_way', point=[100, 100]), event(41, 'push'),
              event(41.3, 'on_my_way', point=[110, 100]), event(42, 'push'),
              event(55.2, 'retreat'), event(101, 'retreat')]
    selected = own_action_signals(reversed(events), 'self', 200, 100)
    assert [e['time_seconds'] for e in selected] == [10.2, 40.2, 41, 55.2]
    base = review_times(100, 50, selected, 'Pantheon', 200)
    base.append(dict(at=41.5, selected_by=['own_command_reversed']))
    schedule = add_signal_checkpoints(base, selected, 100)
    assert [r['at'] for r in schedule] == [0, 13, 28, 41.5, 50, 58, 100]
    rows = {r['at']: r for r in schedule}
    assert rows[13]['selected_by'] == ['own_action_signal', 'own_assist']
    assert rows[28]['selected_by'] == ['follow_up_own_assist']
    assert rows[41.5]['selected_by'] == ['own_action_signal', 'own_command_reversed']
    assert [x['kind'] for x in rows[41.5]['triggers']] == ['on_my_way', 'push']
    assert rows[58]['triggers'][0]['sender_entity_id'] == 'self'


def test_schedule_cannot_use_a_marker_observed_only_after_send_to_reopen_a_duplicate():
    event = dict(time_seconds=10, sender_entity_id='self', team_id=200, kind='on_my_way',
                 source={'packet_record': 10}, marker_xz=[0, 0])
    repeated = {**event, 'time_seconds': 11, 'marker_xz': None, 'marker_region': dict(
        xz_rounded_to_100=[5000, 0], observed_through_seconds=15)}
    assert own_action_signals([event, repeated], 'self', 200, 20) == [event]


def test_marker_distance_excludes_stale_invisible_and_missing_positions():
    def hero(actor, relation):
        return dict(entity_id=actor, champion=actor, relation=relation)
    def sample(x, age):
        return dict(xz=[x, 100], sampled_at=20-age, age_seconds=age, fact_id='path')
    event = dict(kind='assist_me', known_as='own_sent', fact_id='ping',
                 marker_region=dict(xz_rounded_to_100=[100,100]))
    lineup = [hero('self','ally'),hero('old','ally'),hero('hidden','enemy'),hero('enemy','enemy')]
    allies = {'self': sample(600,.1), 'old':sample(101,5)}
    opponents = [dict(entity_id='hidden', visible=False, last_observed_path_start=sample(100,0), fact_id='hid'),
                 dict(entity_id='enemy', visible=True, last_observed_path_start=sample(220,.3), fact_id='seen')]
    view = assist_distances(dict(events=[event],through_seconds=20), lineup, allies, opponents)
    assert [(r['champion'],r['distance_world_rounded_to_100']) for r in view['actors']] == [('enemy',100),('self',500)]
    assert assist_distances(dict(events=[{**event,'known_as':'delivered_to_team'}]), lineup, allies, opponents) is None


def test_manifest_binds_unbound_player_identity(tmp_path, monkeypatch):
    import scripts.run_review_agent as runner
    frame = dict(frame_id='f1', task={}, lineup=[dict(entity_id='red:1',champion='Pantheon')],
                 decision=dict(at_seconds=7,observer_team_id=200,player_entity_id='red:1'))
    monkeypatch.setattr(runner, 'read_bundle', lambda path: dict(frame=frame))
    monkeypatch.setattr(runner, '_source', lambda bundle: 'rofl')
    path = tmp_path / 'sequence.json'
    seq = dict(source_sha256='rofl',team=200,champion='Pantheon',
               selections=[dict(bundle='007.json',frame_id='f1',at=7)])
    path.write_text(json.dumps(seq))
    assert match_sequence_paths(path) == [tmp_path / '007.json']
    path.write_text(json.dumps(dict(seq, champion='Amumu')))
    with pytest.raises(ValueError, match='scope_mismatch'):
        match_sequence_paths(path)
    path.write_text(json.dumps(dict(seq, selections=[dict(bundle='../007.json')])))
    with pytest.raises(ValueError, match='filename'):
        match_sequence_paths(path)


def test_event_audit_credits_only_unique_local_roster_aliases():
    players = [dict(championName='A',summonerName='one',riotIdGameName='ambiguous'),
               dict(championName='B',summonerName='two',riotIdGameName='ambiguous')]
    event = public_event(dict(EventName='ChampionKill',KillerName='one',VictimName='two',
                        Assisters=['ambiguous','missing'], RiotId='private'), players)
    assert event == dict(EventName='ChampionKill',KillerName='A',VictimName='B',Assisters=[None,None])


def test_kill_feed_appears_only_after_observation_without_assists_or_hidden_respawns():
    from lol_coach.native_kill_feed import project_feed
    from lol_coach.reasoning_frame import digest
    rec = dict(schema='native-public-kills/v1',source_sha256='match',build='16',
               events=[dict(time_seconds=10.1, available_at_seconds=10.5, event_id=5, victim='B', killer='A')])
    rec['checksum'] = digest(rec)
    roster = {1:dict(name='A'),2:dict(name='B')}
    assert project_feed(rec,'match','16',roster,10.45) == ([],{})
    feed,evidence = project_feed(rec,'match','16',roster,10.5)
    event, = feed
    assert event['killer_entity_id']=='0x1' and event['victim_entity_id']=='0x2'
    assert evidence[event['evidence_id']]['available_at_seconds']==10.5
    assert 'assists' not in event and 'respawn' not in event
    assert project_feed(rec,'match','16',roster,41)==([], {})
    with pytest.raises(ValueError,match='source mismatch'):
        project_feed(rec,'other','16',roster,10.5)


def test_absent_native_feed_is_distinct_from_zero_published_kills(tmp_path):
    from lol_coach.native_kill_feed import load_feed
    from lol_coach.reasoning_frame import compile_frame
    assert load_feed({'source_sha256':'abc','version':'16'},{1:{'name':'A'}},20,tmp_path) == (None,{})
    snapshot = dict(schema='macro-snapshot/v1',version='16',source_sha256='abc',
                    context=dict(at_seconds=20,observer_team_id=100,player_entity_id='self'),
                    heroes=[dict(entity_id='self',team_id=100,champion='A',visibility=dict(value=True),inventory={})],
                    evidence={}, recent_public_combat=[], public_kill_feed_missing=True)
    frame = compile_frame(snapshot)['frame']
    assert frame['unknowns']['recent_champion_kills'] == 'native_public_feed_not_available_for_this_replay'
