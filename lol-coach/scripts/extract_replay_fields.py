"""Export bounded field research without training/refitting on the input replay."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.replay_fields import analyze, read_metadata

FRAMER_SHA = "a8cdd4230912cc9adfb9c2d085357f8441aee12cc04fb4140cf9f6139abc0116"


def reference(path):
    raw = path.read_bytes()
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--decoder-dir", type=Path, default=ROOT.parent)
    args = parser.parse_args()
    output = args.output.resolve()
    framer_path = args.decoder_dir / "probe_packets.py"
    if output in {args.replay.resolve(), framer_path.resolve()}:
        raise ValueError("Output must not overwrite an input")
    raw = args.replay.read_bytes()
    read_metadata(raw)  # Reject a wrong build before importing or framing.
    framer_ref = reference(framer_path)
    if framer_ref["sha256"] != FRAMER_SHA:
        raise ValueError("Reviewed packet framer hash mismatch")
    spec = importlib.util.spec_from_file_location("reviewed_rofl_framer", framer_path)
    framer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(framer)
    result = analyze(raw, list(framer.packets(args.replay)))
    result["sources"] = {
        "replay": reference(args.replay), "framer": framer_ref,
        "decoder": reference(ROOT / "lol_coach/replay_fields.py"),
        "exporter": reference(Path(__file__)),
    }
    if result["sources"]["replay"]["sha256"] != result["replay_sha256"]:
        raise ValueError("Replay changed during processing")
    if not result["identity_directory"]["same_owners_in_each_keyframe"]:
        raise ValueError("Changing owner directory requires a new profile")
    if any(x["status"] == "FAIL" for x in result["level_checks"]):
        raise ValueError("Level sequence contradicts current profile")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({"replay": args.replay.name, "packet_count": result["packet_count"],
                      "level_events": len(result["level_events"]),
                      "rejected": len(result["rejected_level_packets"]),
                      "internally_matched_final_levels": sum(c["status"] == "PASS" for c in result["level_checks"]),
                      "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
