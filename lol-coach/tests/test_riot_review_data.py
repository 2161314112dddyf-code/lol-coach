import hashlib
import io
import json
from unittest.mock import Mock

import pytest

from lol_coach.http import EvidenceClient
from lol_coach.riot_review_data import current_riot_version, fetch_item_names, fetch_riot_review_data


ARGS = dict(version="16.22.1", locale="zh_CN", champions=["Pantheon"])


def payload():
    spells = [dict(name=s, description="合成测试", id=f"Pantheon{s}", range=[600], cooldown=[9])
              for s in "QWER"]
    return dict(version="16.22.1", data={"Pantheon":dict(id="Pantheon", key="80", name="潘森", spells=spells,
                                                        passive=dict(name="测试", description="合成测试"))})


def client(tmp_path, data):
    def open_sample(request, timeout):
        reply = io.BytesIO(json.dumps(data).encode())
        reply.headers = {"Content-Type":"application/json"}
        reply.geturl = lambda: request.full_url
        reply.status = 200
        return reply
    opener = Mock(side_effect=open_sample)
    return EvidenceClient(tmp_path, opener=opener, interval=0, retries=0), opener


def test_refresh_and_offline_preserve_evidence_and_version(tmp_path):
    riot, opener = client(tmp_path, payload())
    report = fetch_riot_review_data(riot, **ARGS, refresh=True)
    champ = report["champions"]["Pantheon"]
    assert champ["champion_id"] == 80 and set(champ["abilities"]) == {"passive", *"QWER"}
    assert champ["abilities"]["W"]["range_by_rank"] == [600]
    assert champ["abilities"]["W"]["cooldown_by_rank"] == [9]
    source = champ["source"]
    assert source["sha256"] == hashlib.sha256((tmp_path / source["evidence_path"]).read_bytes()).hexdigest()
    assert source["cache_hit"] is False and source["http_status"] == 200
    assert source["requested_url"].endswith("/16.22.1/data/zh_CN/champion/Pantheon.json")
    again = fetch_riot_review_data(riot, **ARGS, offline=True)["champions"]["Pantheon"]
    assert again["source"] == {**source, "cache_hit": True}
    assert opener.call_count == 1


@pytest.mark.parametrize("bad", ["version", "missing_version", "key", "id", "range", "spells", "text"])
def test_invalid_sources_do_not_produce_a_review_bundle(tmp_path, bad):
    value = payload()
    hero = value["data"]["Pantheon"]
    if bad == "version":
        value["version"] = "16.21.1"
    elif bad == "missing_version":
        del value["version"]
    elif bad == "range":
        hero["spells"][0]["range"] = [True]
    elif bad == "spells":
        hero["spells"].pop()
    elif bad == "text":
        del hero["spells"][2]["description"]
    else:
        hero[bad] = "wrong"
    riot, _ = client(tmp_path, value)
    with pytest.raises(ValueError):
        fetch_riot_review_data(riot, **ARGS)


@pytest.mark.parametrize("args", [dict(version="latest"), dict(locale="../hi"), dict(champions=["../bad"]),
                                  dict(champions=[]), dict(refresh=True, offline=True)])
def test_identifiers_are_validated_before_fetch(tmp_path, args):
    riot, opener = client(tmp_path, payload())
    with pytest.raises(ValueError):
        fetch_riot_review_data(riot, **{**ARGS, **args})
    opener.assert_not_called()


def test_missing_offline_input_cannot_silently_use_another_champion(tmp_path):
    riot, opener = client(tmp_path, payload())
    fetch_riot_review_data(riot, **ARGS)
    with pytest.raises(ValueError, match="Caitlyn.*cache_miss"):
        fetch_riot_review_data(riot, **{**ARGS, "champions":["Pantheon", "Caitlyn"]}, offline=True)
    assert opener.call_count == 1


def test_combat_bases_and_growth_keep_static_source_and_missing_values(tmp_path):
    data = payload()
    stats = dict(attackdamage=55, attackdamageperlevel=3.2, armor=22, armorperlevel=4.2,
                 spellblock=30, spellblockperlevel=1.3, hp=640)
    data["data"]["Pantheon"]["stats"] = stats
    riot, _ = client(tmp_path, data)
    hero = fetch_riot_review_data(riot, **ARGS)["champions"]["Pantheon"]
    combat = hero["combat_base_stats"]
    assert set(combat) == {"armor", "magic_resist", "health", "attack_damage"}
    assert combat["magic_resist"] == dict(level_1=30, growth=1.3, source_fields=["spellblock", "spellblockperlevel"])
    assert combat["health"]["growth"] is None
    stats["armorperlevel"] = True
    riot, _ = client(tmp_path, data)
    with pytest.raises(ValueError, match="Invalid Data Dragon combat stat"):
        fetch_riot_review_data(riot, **ARGS, refresh=True)


def test_numeric_keys_must_uniquely_identify_members_of_the_requested_roster(tmp_path):
    data = payload()
    data["data"]["Caitlyn"] = {**data["data"]["Pantheon"], "id":"Caitlyn"}
    riot, _ = client(tmp_path, data)
    with pytest.raises(ValueError, match="Ambiguous.*Caitlyn"):
        fetch_riot_review_data(riot, **{**ARGS, "champions":["Pantheon", "Caitlyn"]})


def test_current_version_rechecks_official_list_and_keeps_evidence(tmp_path):
    versions = ["16.22.1", "16.21.1"]
    riot, opener = client(tmp_path, versions)
    first = current_riot_version(riot)
    versions.insert(0, "16.23.1")
    second = current_riot_version(riot)
    assert [first["version"], second["version"]] == ["16.22.1", "16.23.1"]
    assert opener.call_count == 2
    for resolution in (first, second):
        source = resolution["source"]
        body = (tmp_path / source["evidence_path"]).read_bytes()
        assert hashlib.sha256(body).hexdigest() == source["sha256"]
        assert json.loads(body)[0] == resolution["version"]


def test_historical_resolution_tracks_only_releases_in_the_replay_patch(tmp_path):
    riot, _ = client(tmp_path, ["17.1.1", "16.220.1", "16.22.2", "16.22.1", "16.21.1"])
    resolved = current_riot_version(riot, patch="16.22")
    assert resolved["version"] == "16.22.2"
    assert resolved["published_releases"] == ["16.22.2", "16.22.1"]
    with pytest.raises(ValueError, match="no Data Dragon release"):
        current_riot_version(riot, patch="16.23")


@pytest.mark.parametrize("versions", [[], {"version":"16.22.1"}, ["current", "16.22.1"], ["16.22.1", None]])
def test_unusable_live_version_list_stops_resolution(tmp_path, versions):
    riot, _ = client(tmp_path, versions)
    with pytest.raises(ValueError, match="version list"):
        current_riot_version(riot)


def test_refresh_cli_resolves_each_poll_even_when_previous_scope_is_cached(tmp_path, monkeypatch, capsys):
    import sys
    from scripts import refresh_review_sources as cli

    versions = ["16.22.1"]
    riot, opener = client(tmp_path / "evidence", versions)
    monkeypatch.setattr(cli, "EvidenceClient", lambda root: riot)
    monkeypatch.setattr(sys, "argv", ["refresh", "--root", str(tmp_path), "--version", "current",
                                     "--champions", "Pantheon", "--interval-minutes", "1"])
    calls = []
    def pull(root, version, champions, matchups, **kwargs):
        calls.append(version)
        return dict(status="fresh_cache", snapshot="fixture")
    def advance(seconds):
        assert seconds == 60
        if len(calls) == 2:
            raise KeyboardInterrupt
        versions.insert(0, "16.23.1")
    monkeypatch.setattr(cli, "refresh_sources", pull)
    # Replacing cli.time.sleep would also affect EvidenceClient's request interval.
    monkeypatch.setattr(cli, "time", Mock(sleep=advance))
    with pytest.raises(KeyboardInterrupt):
        cli.main()
    assert calls == ["16.22.1", "16.23.1"] and opener.call_count == 2
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [line["version_resolution"]["version"] for line in lines] == calls


def game_log(entries):
    rows = []
    for i, (side, champion, role, local) in enumerate(entries):
        marker = '**LOCAL** ' if local else ''
        rows.append(f"ROST| CONNECTION READY | Team{side} {i}) 'player' {marker}- Champion({champion}) "
                    f"SkinID(0) TeamBuilderRole({role}) PUUID(private-id-{i})")
    return "\n".join(rows).encode()


def test_cli_infers_directed_pairs_and_forwards_profile_flag(tmp_path, monkeypatch, capsys):
    import sys
    from scripts import refresh_review_sources as cli
    log = tmp_path / "r3dlog.txt"
    entries = [(team, name+suffix, position, position == 'MIDDLE' and team == 'Chaos')
               for team, suffix in [('Order','Blue'),('Chaos','Red')]
               for position, name in [('TOP','Top'), ('JUNGLE','Jg'), ('MIDDLE','Mid'),
                                      ('BOTTOM','Bot'), ('UTILITY','Sup')]]
    log.write_bytes(game_log(entries))
    fetch = Mock(return_value=dict(status="updated"))
    monkeypatch.setattr(cli, "refresh_sources", fetch)
    monkeypatch.setattr(cli, "current_riot_version", Mock(side_effect=AssertionError("fixed version must stay pinned")))
    monkeypatch.setattr(sys, "argv", ["refresh", "--root", str(tmp_path), "--version", "16.22.1",
                                     "--game-log", str(log), "--lane-profiles"])
    assert cli.main() == 0
    _, version, champions, pairs = fetch.call_args.args
    assert version == "16.22.1" and len(champions) == 10 and len(pairs) == 5
    assert all(ally.endswith('Red') and enemy.endswith('Blue') for _, ally, enemy in pairs)
    assert fetch.call_args.kwargs["include_profiles"] is True
    output = capsys.readouterr().out
    assert "private-id" not in output and not json.loads(output)["roster_scope"]["unpaired_roles"]


def test_missing_or_ambiguous_log_roles_keep_only_confirmed_pairs():
    from scripts.refresh_review_sources import roster_scope
    raw = game_log([('Order','A','UTILITY',True), ('Chaos','B','UTILITY',False),
                    ('Order','C','MIDDLE',False), ('Order','D','MIDDLE',False),
                    ('Chaos','E','MIDDLE',False), ('Chaos','F','UNKNOWN',False)])
    champions, pairs, missing = roster_scope(raw)
    assert len(champions) == 6
    assert pairs == [('UTILITY','A','B')]
    assert missing == ['TOP','JUNGLE','MIDDLE','BOTTOM']


def test_item_names_require_versioned_source_and_preserve_officially_unnamed_ids(tmp_path):
    data = dict(type="item", version="16.22.1", data={"1001":{"name":"鞋子"}, "2008":{"name":""}})
    riot, opener = client(tmp_path, data)
    result = fetch_item_names(riot, version="16.22.1", locale="zh_CN", refresh=True)
    assert result["items"] == {"1001":"鞋子"} and result["unnamed_item_ids"] == ["2008"]
    source = result["source"]
    assert source["requested_url"] == source["final_url"] == "https://ddragon.leagueoflegends.com/cdn/16.22.1/data/zh_CN/item.json"
    assert source["content_version"] == data["version"]
    assert source["sha256"] == hashlib.sha256((tmp_path / source["evidence_path"]).read_bytes()).hexdigest()
    assert fetch_item_names(riot, version="16.22.1", locale="zh_CN")["source"]["cache_hit"] is True
    assert opener.call_count == 1


@pytest.mark.parametrize("bad", [dict(version=None), dict(version="16.21.1"), dict(type="champion"),
                                 dict(data={"1001":{}}), dict(data={"not_an_id":{"name":"鞋子"}})])
def test_inconsistent_item_catalog_is_rejected(tmp_path, bad):
    data = dict(type="item", version="16.22.1", data={"1001":{"name":"鞋子"}})
    riot, _ = client(tmp_path, {**data, **bad})
    with pytest.raises(ValueError, match="Data Dragon item"):
        fetch_item_names(riot, version="16.22.1", locale="zh_CN")
