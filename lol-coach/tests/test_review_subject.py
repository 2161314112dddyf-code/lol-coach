import hashlib
import json
import os
from datetime import datetime

import pytest

from lol_coach import review_subject
from test_round_chain import bundle_at, freeze


def sources(tmp_path, match_id="123", *, local_uuid="local-private", team="Order"):
    version = b"16.22.836.1077"
    header = b"RIOT\x02" + bytes(9) + bytes([len(version)]) + version
    stats = [{"TEAM": "100", "SKIN": "Pantheon", "PUUID": "local-private"},
             {"TEAM": "200", "SKIN": "MasterYi", "PUUID": "opponent-private"}]
    metadata = {"statsJson": json.dumps(stats)}
    if match_id:
        metadata["gameId"] = match_id
    footer = json.dumps(metadata).encode()
    replay = tmp_path / "HN1-999.rofl"
    replay.write_bytes(header + bytes(256) + footer + len(footer).to_bytes(4, "little"))
    log = tmp_path / "session.txt"
    log.write_text(
        "GameStartData::GameID=123\n"
        f"ROST| CONNECTION READY | Team{team} 0) 'tester' **LOCAL** - Champion(Pantheon) "
        f"SkinID(0) TeamBuilderRole(UTILITY) PUUID({local_uuid})\n"
        "ROST| CONNECTION READY | TeamChaos 0) '**LOCAL**' - Champion(MasterYi) "
        "SkinID(0) TeamBuilderRole(JUNGLE) PUUID()\n",
        encoding="utf-8",
    )
    return replay, log


def test_game_local_roster_and_anonymous_subject_survive_renamed_files(tmp_path):
    subject = review_subject.load_review_subject(*sources(tmp_path))
    assert subject["match_id"] == "123" and subject["local_team_id"] == 100
    assert subject["local_champion"] == "Pantheon" and subject["roster_count"] == 2
    assert [h['assigned_role'] for h in subject['roster']] == ['UTILITY', 'JUNGLE']
    assert subject["match_id_source"] == "replay_footer_and_game_log"
    assert "private" not in json.dumps(subject)
    bundle = bundle_at(10)
    bundle["audit"]["source_replay_sha256"] = subject["replay_sha256"]
    frame = bundle["frame"]
    current = next(r for r in frame["lineup"] if r["entity_id"] == frame["decision"]["player_entity_id"])
    current.update(champion="Pantheon", relation="ally")
    review_subject.validate_review_subject(subject, freeze(bundle))
    current["champion"] = "TwistedFate"
    with pytest.raises(ValueError, match="local_player_mismatch"):
        review_subject.validate_review_subject(subject, freeze(bundle))
    frame["decision"]["observer_team_id"] = 200
    with pytest.raises(ValueError, match="observer_team_mismatch"):
        review_subject.validate_review_subject(subject, freeze(bundle))
    bundle["audit"]["source_replay_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="replay_mismatch"):
        review_subject.validate_review_subject(subject, freeze(bundle))


def test_personal_support_requires_four_verified_lane_assignments():
    from lol_coach.round_tools import bind_round
    bundle = bundle_at(10)
    frame = bundle['frame']
    frame['lineup'].append(dict(entity_id='enemy2', champion='D', relation='enemy'))
    roster = [dict(team_id=100 if h['relation'] == 'ally' else 200, champion=h['champion'], assigned_role=role)
              for h, role in zip(frame['lineup'], ['UTILITY', 'BOTTOM', 'UTILITY', 'BOTTOM'])]
    duos = review_subject.bottom_lane_actors(frame, dict(roster=roster))
    assert duos == {'support':'self', 'carry':'ally', 'enemy_support':'enemy', 'enemy_carry':'enemy2'}
    old = bind_round(freeze(bundle), 'bot', 'dragon', 5)
    bound = bind_round(old, 'bot', 'dragon', 5, bottom_lane_actors=duos)
    assert bound['frame']['task']['bottom_lane_actors'] == duos
    assert bound['frame']['task']['engagement_question'] == {'ally_id':'ally', 'target_id':'enemy2'}
    assert 'bottom_lane_actors' not in old['frame']['task']
    assert bind_round(bound, 'bot', 'dragon', 5, bottom_lane_actors=duos) == bound
    with pytest.raises(ValueError, match='invalid_bottom_lane_actors'):
        bind_round(bound, 'bot', 'dragon', 5, bottom_lane_actors={**duos, 'carry':'enemy2'})
    assert review_subject.bottom_lane_actors(frame, dict(roster=roster[:-1])) is None
    assert review_subject.bottom_lane_actors(frame, dict(roster=[*roster, roster[1]])) is None
    frame['decision']['player_entity_id'] = 'ally'
    assert review_subject.bottom_lane_actors(frame, dict(roster=roster)) is None


def test_partial_mid_jungle_roles_only_from_unique_same_side_assignments():
    frame = {'decision': {'observer_team_id': 200}, 'lineup': [
        dict(entity_id='a', relation='ally', champion='Mirror'),
        dict(entity_id='b', relation='enemy', champion='Mirror'),
        dict(entity_id='c', relation='ally', champion='Other')]}
    roster = [dict(team_id=200, champion='Mirror', assigned_role='JUNGLE'),
              dict(team_id=100, champion='Mirror', assigned_role='MIDDLE'),
              dict(team_id=200, champion='Other', assigned_role='MIDDLE')]
    assert review_subject.roam_actors(frame, dict(roster=roster)) == {
        'ally_jungle':'a', 'enemy_mid':'b', 'ally_mid':'c'}
    assert review_subject.roam_actors(frame, dict(roster=[*roster, roster[-1]])) == {
        'ally_jungle':'a', 'enemy_mid':'b'}


@pytest.mark.parametrize(("kwargs", "error"), [
    (dict(match_id="987"), "match_id_mismatch"),
    (dict(local_uuid="other-player"), "local_player_mismatch"),
    (dict(team="Chaos"), "roster_mismatch"),
])
def test_contradictions_are_rejected(tmp_path, kwargs, error):
    with pytest.raises(ValueError, match=error):
        review_subject.load_review_subject(*sources(tmp_path, **kwargs))


def test_same_players_and_filename_cannot_authenticate_another_training_game(tmp_path, monkeypatch):
    replay, log = sources(tmp_path, match_id=None)
    replay = replay.rename(tmp_path / "HN1-123.rofl")
    with pytest.raises(ValueError, match="pair_unverified"):
        review_subject.load_review_subject(replay, log)
    monkeypatch.setitem(review_subject._REVIEWED_PAIRS, hashlib.sha256(replay.read_bytes()).hexdigest(),
                        ("123", hashlib.sha256(log.read_bytes()).hexdigest()))
    assert review_subject.load_review_subject(replay, log)["match_id_source"] == "reviewed_file_pair_and_game_log"
    log.write_bytes(log.read_bytes() + b"another session\n")
    with pytest.raises(ValueError, match="pair_unverified"):
        review_subject.load_review_subject(replay, log)


def test_original_client_download_can_bind_an_unregistered_replay(tmp_path):
    replay, log = sources(tmp_path, match_id=None)
    timestamp = datetime(2026, 11, 13, 14, 30, 0).timestamp() + 21.25
    os.utime(replay, (timestamp, timestamp))
    log_dir = tmp_path / "GameLogs" / "session"
    log_dir.mkdir(parents=True)
    log = log.rename(log_dir / "session_r3dlog.txt")
    directory = tmp_path / "LeagueClient Logs"
    directory.mkdir()
    client = directory / "2026-11-13T14-30-00_77_LeagueClient.log"
    messages = [
        "DownloaderSubmodule: server request, download from GAMHS for game '123'",
        f"FileManager: caching metadata for Replay gameId '123', roflPath '{replay.resolve()}'",
        "DownloaderSubmodule: Rofl download job ending",
    ]
    def write(messages):
        client.write_text("\n".join(f"0000{19+i}.000| OKAY| rcp-be-lol-replays| {m}"
                                     for i, m in enumerate(messages)), encoding="utf-8")
    write(messages)
    subject = review_subject.load_review_subject(replay, log)
    assert subject["match_id_source"] == "authenticated_client_download"
    assert subject["download_evidence"]["mtime_delta_seconds"] == 0.25
    assert review_subject.load_review_subject(replay, log, client) == subject
    for bad in ([messages[1], messages[2]], [messages[0], messages[1]],
                [messages[0], messages[1].replace("123", "456"), messages[2]],
                [messages[0], messages[1].replace(replay.name, "different.rofl"), messages[2]]):
        write(bad)
        with pytest.raises(ValueError, match="client_download_unverified"):
            review_subject.load_review_subject(replay, log, client)
    write(messages)
    os.utime(replay, (timestamp+1000, timestamp+1000))
    with pytest.raises(ValueError, match="client_download_unverified"):
        review_subject.load_review_subject(replay, log, client)
