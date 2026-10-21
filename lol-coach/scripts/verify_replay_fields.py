"""Verify saved real exports and derive the bounded level codebook evidence."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.replay_fields import LEVEL_CODES, VERSION


def main():
    exports = []
    file_refs = []
    for game_id in (11360086609, 11363048522, 11363093470, 11372643015):
        path = ROOT / f"data/private/replay_fields/HN1-{game_id}.json"
        raw = path.read_bytes()
        result = json.loads(raw)
        if result["version"] != VERSION or result["decision_input_eligible"]:
            raise ValueError("Version or semantic boundary changed")
        for source in result["sources"].values():
            if hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest() != source["sha256"]:
                raise ValueError("Changed source: " + source["path"])
        file_refs.append({"path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(raw).hexdigest()})
        exports.append(result)
    full = exports[0]
    reconstructed = {}
    training_owners = ("0x40000034", "0x40000038")
    for owner in training_owners:
        events = [e for e in full["level_events"] if e["entity_id"] == owner]
        check = next(c for c in full["level_checks"] if c["entity_id"] == owner)
        last = check["metadata_final_level"]
        for level, event in zip(range(last-len(events)+1, last+1), events):
            suffix = bytes.fromhex(event["payload_hex"])[-1]
            if reconstructed.get(suffix, level) != level:
                raise ValueError("Inconsistent inferred suffix")
            reconstructed[suffix] = level
    if reconstructed != LEVEL_CODES:
        raise ValueError("Saved codebook does not match discovery evidence")
    if len(full["level_checks"]) != 10 or any(c["status"] != "PASS" for c in full["level_checks"]):
        raise ValueError("Final-level internal check failed")
    if len(full["level_events"]) != 150 or len(exports[1]["level_events"]) != 12:
        raise ValueError("Unexpected real event counts")
    if [e["level_candidate"] for e in exports[1]["level_events"]] != list(range(2, 14)):
        raise ValueError("Cross-file sequence changed")
    if any(e["level_events"] for e in exports[2:]):
        raise ValueError("No-update controls changed")
    xml_path = ROOT / "reports/pytest-replay-fields.xml"
    suites = ET.parse(xml_path).getroot().findall("testsuite")
    totals = {k: sum(int(s.attrib[k]) for s in suites) for k in ("tests", "failures", "errors", "skipped")}
    if totals["tests"] != 126 or any(totals[k] for k in ("failures", "errors", "skipped")):
        raise ValueError("Software run is incomplete or failed")
    for item in json.loads((ROOT / "reports/replay_fields_baseline/manifest.json").read_text())["files"]:
        if hashlib.sha256((ROOT / item["backup"]).read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Backup hash mismatch")
    summary = [{"game_id": game_id, "replay_sha256": e["replay_sha256"],
                "packets": e["packet_count"], "owner_candidates": len(e["identity_directory"]["owners"]),
                "keyframes": e["identity_directory"]["keyframe_count"],
                "level_events": len(e["level_events"]), "rejected": len(e["rejected_level_packets"]),
                "excluded_non_directory_packets": e["excluded_level_packet_counts"].get("non_directory_owner", 0),
                "internal_final_level_matches": sum(c["final_level_matches"] is True for c in e["level_checks"])}
               for game_id, e in zip((11360086609, 11363048522, 11363093470, 11372643015), exports)]
    checks = [
        ("RPL-01", "PASS", "Four exports regenerated; replay/framer/decoder/exporter hashes match current files.", None),
        ("RPL-02", "PASS", "Bounded profile evidence and cross-file unknowns recorded; not a general level-decoder certification.",
         "Independent numeric labels for practice events and payload champion-name decoding remain absent."),
        ("RPL-03", "PASS", "19 targeted synthetic checks and 107 existing tests passed.", None),
        ("RPL-04", "PASS", "Footer fields isolated; all semantic candidates marked ineligible for time-t decisions.",
         "Health/resource/spell state remains unavailable."),
    ]
    report = {
        "run_id": "RPL-001-20261014", "target_version": VERSION,
        "spec": "docs/REPLAY_FIELDS_TASK.md", "source": "target_claim", "executed_by": "Codex",
        "evidence_level": "REPRODUCED", "independent_review": False, "signer": None,
        "exports": file_refs, "real_runs": summary, "software_tests": totals,
        "test_evidence": {"path": str(xml_path.relative_to(ROOT)), "sha256": hashlib.sha256(xml_path.read_bytes()).hexdigest()},
        "level_codebook": {hex(k): v for k, v in LEVEL_CODES.items()},
        "discovery": {"owners_used_to_reconstruct_table": list(training_owners),
                      "remaining_owner_checks": 8, "blind_holdout": False,
                      "method": "Post-hoc final level minus event count, then one level per event; suffix must agree across owners.",
                      "independent_cross_file_numeric_validation": "INSUFFICIENT_EVIDENCE"},
        "bounded_negative_probes": [
            "Plaintext Pantheon/MissFortune/Aphelios/MasterYi absent from packet payloads in all four samples.",
            "Rotation+odd-affine per-byte champion-string scan on streams 2/3 of full and latest replay: zero matches.",
            "Shared monoalphabetic champion-name mapping on 0x0186/0x0445 with bounded anchor/permutation variants: zero matches.",
            "These negatives reject only those probes, not existence of identity data; exploratory commands retained in chat trace.",
        ],
        "reference_research": [
            {"url": "https://github.com/shyunku-libraries/rofl-parser", "use": "Older-build structural/semantic separation; no code executed or current-build profile imported."},
            {"url": "https://raw.githubusercontent.com/shyunku/rofl-parser/decoder-artifacts/index.json", "observed_web_status": 404},
        ],
        "acceptance": [{"acceptance_id": aid, "target_version": VERSION, "status": status,
                        "evidence_id": "RPL-001-20261014", "source": "target_claim", "executed_by": "Codex",
                        "evidence_level": "REPRODUCED", "scope": scope, "gap": gap,
                        "next_step": "Continue offline state-field decoding; no new recording required.", "signer": None}
                       for aid, status, scope, gap in checks],
        "foundation_complete": False,
    }
    (ROOT / "reports/replay_fields_validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"real_runs": summary, "software_tests": totals, "checks": "passed within documented scope"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
