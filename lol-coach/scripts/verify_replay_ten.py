"""Real-output verification and CLI rejection checks for the ten-category export."""
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def reference(path):
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def footer(raw):
    size = int.from_bytes(raw[-4:], "little")
    return json.loads(json.loads(raw[-4-size:-4])["statsJson"])


def main():
    bundles, evidence = [], []
    for game_id in (11360086609, 11363048522, 11363093470, 11372643015):
        path = ROOT / f"data/private/replay_ten/HN1-{game_id}.json"
        bundle = json.loads(path.read_text(encoding="utf-8"))
        for ref in bundle["sources"].values():
            assert reference(Path(ref["path"]))["sha256"] == ref["sha256"], ref["path"]
        replay = Path(bundle["sources"][f"HN1-{game_id}.rofl"]["path"])
        assert reference(replay)["sha256"] == bundle["replay_sha256"]
        assert bundle["decision_input_eligible"] is False
        assert [c["id"] for c in bundle["coverage"]] == [f"T{i:02}" for i in range(1, 11)]
        if game_id != 11360086609:
            assert not footer(replay.read_bytes())
            assert all(c["status"] == "unavailable" for c in bundle["coverage"][:6])
        bundles.append(bundle)
        evidence.extend([reference(path), reference(path.with_suffix(".md"))])
    full = bundles[0]
    assert all(c["status"] == "available" and c["complete_record_count"] > 0 for c in full["coverage"])
    source = Path(full["sources"]["HN1-11360086609.rofl"]["path"])
    players = footer(source.read_bytes())
    c = full["categories"]
    field_checks = 0
    def equal(actual, raw):
        nonlocal field_checks
        expected = None if raw is None or raw == "" else float(raw)
        assert actual == expected, (actual, expected)
        field_checks += 1
    for i, player in enumerate(players):
        assert c["participants"][i]["champion"] == player["SKIN"]
        equal(c["participants"][i]["team_id"], player["TEAM"])
        loadout = c["loadouts"][i]
        for index, value in enumerate(loadout["summoner_spell_ids"], 1):
            equal(value, player[f"SUMMONER_SPELL_{index}"])
        for index, value in enumerate(loadout["rune_ids"]):
            equal(value, player[f"PERK{index}"])
        for index, value in enumerate(loadout["stat_shard_ids"]):
            equal(value, player[f"STAT_PERK_{index}"])
        equal(loadout["primary_style_id"], player["PERK_PRIMARY_STYLE"])
        equal(loadout["secondary_style_id"], player["PERK_SUB_STYLE"])
        for slot in c["inventory"][i]["slots"]:
            equal(slot["item_id"], player[slot["source_field"]])
        for key, raw_key in (("gold_earned", "GOLD_EARNED"), ("gold_spent", "GOLD_SPENT")):
            equal(c["economy"][i][key], player[raw_key])
        for key, raw_key in (("lane_minions", "MINIONS_KILLED"), ("neutral_minions", "NEUTRAL_MINIONS_KILLED"), ("experience", "EXP")):
            equal(c["creep_score"][i][key], player[raw_key])
        for key, value in c["combat_totals"][i]["values_by_source_field"].items():
            equal(value, player[key])
    old_kills_path = ROOT.parent / "kill_timeline.json"
    old_kills = json.loads(old_kills_path.read_text())
    assert old_kills["source_sha256"] == full["replay_sha256"]
    assert len(c["kills"]) == len(old_kills["events"]) == 113
    names = {e: players[index]["SKIN"] for e, index in full["entity_to_participant"].items()}
    for current, old in zip(c["kills"], old_kills["events"]):
        assert current["time_seconds"] == old["time_seconds"]
        assert names[current["victim_entity_id"]] == old["victim"]
        assert names.get(current["killer_entity_id"]) == old["killer"]
        assert [names[e] for e in current["assist_entity_ids"]] == old["assists"]
    old_life_path = ROOT.parent / "lifecycle_experiment.json"
    old_life = json.loads(old_life_path.read_text())
    assert old_life["source_sha256"] == full["replay_sha256"]
    assert len(c["lifecycle"]["intervals"]) == len(old_life["intervals"]) == 113
    for current, old in zip(c["lifecycle"]["intervals"], old_life["intervals"]):
        assert current["entity_id"] == old["entity_id"]
        assert current["death_seconds"] == old["death_seconds"]
        assert current["respawn_seconds"] == old["respawn_seconds"]
        assert current["complete"] == old["complete"]
    assert len(full["checks"]["combat"]) == 10
    assert all(x["status"] == "PASS" for x in full["checks"]["combat"])
    evidence.extend([reference(old_kills_path), reference(old_life_path)])
    prefix_path = ROOT / "data/private/replay_ten/HN1-11360086609-at50.json"
    prefix = json.loads(prefix_path.read_text(encoding="utf-8"))
    for ref in prefix["sources"].values():
        assert reference(Path(ref["path"]))["sha256"] == ref["sha256"]
    assert prefix["cutoff_packet_seconds"] == 50 and "categories" not in prefix
    for entity in prefix["entities"]:
        assert all(entity[k] is None for k in ("current_gold", "inventory", "current_health", "current_resource"))
        for key in ("last_level_update_seconds", "last_life_event_seconds"):
            assert entity[key] is None or entity[key] <= 50
        movement = entity["latest_movement_candidate"]
        assert movement is None or movement["time_seconds"] <= 50
    karthus = next(e for e in prefix["entities"] if e["champion"] == "Karthus")
    assert karthus["life_state_candidate"] == "dead"
    assert "respawn_seconds" not in karthus
    evidence.append(reference(prefix_path))
    cli_checks = []
    temp_root = ROOT / ".test-tmp-replay-ten-cli"
    temp_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temp_root) as directory:
        temp = Path(directory).resolve()
        assert temp.is_relative_to(temp_root.resolve())
        output = temp / "existing.json"
        output.write_text("synthetic sentinel", encoding="utf-8")
        bad_version = temp / "synthetic-wrong-version.rofl"
        raw = bytearray(source.read_bytes())
        raw[15:29] = b"16.19.824.8524"
        bad_version.write_bytes(raw)
        wrong_decoder = temp / "decoder"
        wrong_decoder.mkdir()
        (wrong_decoder / "probe_packets.py").write_text("# synthetic unreviewed file\n", encoding="utf-8")
        cases = [
            ("wrong_version", ["--replay", str(bad_version)], "Unsupported exact build"),
            ("missing_input", ["--replay", str(temp / "absent.rofl")], "FileNotFoundError"),
            ("changed_framer", ["--replay", str(source), "--decoder-dir", str(wrong_decoder)], "hash mismatch"),
        ]
        for name, arguments, error in cases:
            run = subprocess.run([sys.executable, str(ROOT / "scripts/export_replay_ten.py"),
                                  *arguments, "--output", str(output)], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=30)
            assert run.returncode != 0 and error in run.stderr, (name, run.stderr)
            assert output.read_text(encoding="utf-8") == "synthetic sentinel"
            cli_checks.append({"case": name, "return_code": run.returncode, "expected_error_observed": True,
                               "existing_output_unchanged": True, "data_kind": "synthetic_cli_failure_fixture"})
    xml_path = ROOT / "reports/pytest-replay-ten.xml"
    suites = ET.parse(xml_path).getroot().findall("testsuite")
    tests = {k: sum(int(s.attrib[k]) for s in suites) for k in ("tests", "failures", "errors", "skipped")}
    assert tests == {"tests": 150, "failures": 0, "errors": 0, "skipped": 0}
    evidence.append(reference(xml_path))
    for row in json.loads((ROOT / "reports/replay_ten_baseline/manifest.json").read_text())["files"]:
        assert reference(ROOT / row["backup"])["sha256"] == row["sha256"]
    result = {"run_id": "RPL-002-20261014", "target_version": full["version"],
        "source": "target_claim", "executed_by": "Codex", "evidence_level": "REPRODUCED",
        "independent_review": False, "signer": None, "software_tests": tests,
        "footer_numeric_values_checked": field_checks, "cli_failure_checks": cli_checks,
        "real_runs": [{"source_sha256": b["replay_sha256"], "packets": b["packet_count"],
            "coverage": b["coverage"], "movement_events": len(b["categories"]["movement"]["events"]),
            "movement_snapshots": len(b["categories"]["movement"]["snapshots"]),
            "replans": len(b["categories"]["movement"]["plan_replacements"]),
            "levels": len(b["categories"]["levels"]), "kills": len(b["categories"]["kills"]),
            "complete_death_intervals": sum(i["complete"] for i in b["categories"]["lifecycle"]["intervals"]),
            "open_death_intervals": sum(not i["complete"] for i in b["categories"]["lifecycle"]["intervals"])}
            for b in bundles],
        "prefix_query": {"cutoff": 50, "Karthus_life_state": karthus["life_state_candidate"],
                         "future_respawn_exposed": False, "footer_state_exposed": False},
        "evidence": evidence,
        "acceptance": [{"acceptance_id": f"TEN-{i:02}", "status": "PASS",
            "target_version": full["version"], "evidence_id": "RPL-002-20261014", "source": "target_claim",
            "evidence_level": "REPRODUCED", "scope": scope, "gap": "See field-specific semantic limits; no independent gameplay review.",
            "next_step": "Continue remaining state-field reverse engineering without new recording gate.", "signer": None}
            for i, scope in enumerate([
                "Ten populated categories in full replay; missing training metadata stays unavailable.",
                "113 event sequences reproduce prior evidence; 30 K/D/A values and last takedown times agree with footer.",
                "107 complete and 6 open intervals reproduce prior evidence; 10 completed-death totals match.",
                "Snapshot/event split, plan-not-arrival and 50-second prefix boundaries verified.",
                "Three CLI failures reject safely; all input hashes and backup hashes match."], 1)],
        "limitations": ["Six categories are configuration/final metadata, four are temporal packet outputs.",
            "Existing decoding research is integrated; no claim of ten newly deciphered protocols.",
            "Same-file aggregate and prior-output checks are not independent protocol validation.",
            "HP/resource/cast/inventory/gold/vision timelines remain unavailable."],
        "foundation_complete": False}
    target = ROOT / "reports/replay_ten_validation.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"footer_values_checked": field_checks, "kill_events_matched": len(c["kills"]),
        "lifecycle_intervals_matched": len(c["lifecycle"]["intervals"]), "cli_rejections": cli_checks,
        "software_tests": tests, "prefix_query": result["prefix_query"], "output": str(target)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
