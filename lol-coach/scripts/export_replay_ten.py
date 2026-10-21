"""Read one saved exact-build replay and export ten explicitly scoped outputs."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
from lol_coach.replay_fields import read_metadata
from lol_coach.replay_ten import build_bundle, render_markdown, state_at

HASHES = {
    "probe_packets.py": "a8cdd4230912cc9adfb9c2d085357f8441aee12cc04fb4140cf9f6139abc0116",
    "decode_movement_1620.py": "807546189d11b158d0d7d6e7cb032ffee760a7d3b3bc3071c5a514081f1a7923",
    "controlled-byte-synthesis.json": "c4e2f5bac8bb6706626dd8a7197c9a4e84511d782f807c3e31ec7c9e3f1693f2",
}


def reference(path):
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def load_reviewed(directory):
    refs = {}
    for name, expected in HASHES.items():
        refs[name] = reference(directory / name)
        if refs[name]["sha256"] != expected:
            raise ValueError("Reviewed dependency hash mismatch: " + name)
    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    framer = load("probe_packets", directory / "probe_packets.py")
    movement = load("reviewed_movement_1620", directory / "decode_movement_1620.py")
    models = [x for x in json.loads((directory / "controlled-byte-synthesis.json").read_text()) if x["status"] == "sat"]
    if len(models) != 1 or sorted(models[0]["table"]) != list(range(256)):
        raise ValueError("Expected one frozen bijective table")
    inverse = bytes(models[0]["table"].index(i) for i in range(256))
    return framer, movement, inverse, refs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="JSON path; matching Markdown is also written")
    parser.add_argument("--decoder-dir", type=Path, default=ROOT.parent)
    parser.add_argument("--at", type=float, help="Export only a retrospective packet-time prefix state")
    args = parser.parse_args()
    raw = args.replay.read_bytes()
    read_metadata(raw)
    framer, movement, inverse, refs = load_reviewed(args.decoder_dir)
    for path in (args.replay, ROOT / "lol_coach/replay_ten.py", ROOT / "lol_coach/replay_fields.py", Path(__file__)):
        refs[path.name] = reference(path)
    if hashlib.sha256(raw).hexdigest() != refs[args.replay.name]["sha256"]:
        raise ValueError("Replay changed between metadata and framing")
    output = args.output.resolve()
    if output.suffix.lower() != ".json":
        raise ValueError("Output must end in .json")
    markdown_path = output.with_suffix(".md")
    inputs = {Path(r["path"]).resolve() for r in refs.values()}
    if output in inputs or markdown_path in inputs:
        raise ValueError("Cannot overwrite an input")
    bundle = build_bundle(raw, list(framer.packets(args.replay)), movement.decode_packet, inverse)
    if args.at is not None:
        if args.at > bundle["game_length_metadata_ms"] / 1000:
            raise ValueError("Cutoff is beyond the recorded match")
        result = state_at(bundle, args.at)
        result.update(schema="replay-prefix/v1", version=bundle["version"], replay_sha256=bundle["replay_sha256"])
        markdown = f"# 回放前缀查询\n\n包时间截止 {args.at} 秒。结果见同名 JSON；不含结算数值，视野过滤尚未实现。\n"
    else:
        result, markdown = bundle, render_markdown(bundle)
    result["sources"] = refs
    for ref in refs.values():
        if reference(Path(ref["path"]))["sha256"] != ref["sha256"]:
            raise ValueError("Input changed during export")
    output.parent.mkdir(parents=True, exist_ok=True)
    for path, content in ((output, json.dumps(result, ensure_ascii=False, indent=2)+"\n"), (markdown_path, markdown)):
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
    print(json.dumps({"replay": args.replay.name, "packets": bundle["packet_count"],
        "available_categories": sum(c["status"] == "available" for c in bundle["coverage"]),
        "movement_events": len(bundle["categories"]["movement"]["events"]),
        "level_events": len(bundle["categories"]["levels"]), "kills": len(bundle["categories"]["kills"]),
        "complete_death_intervals": sum(s["complete"] for s in bundle["categories"]["lifecycle"]["intervals"]),
        "open_death_intervals": sum(not s["complete"] for s in bundle["categories"]["lifecycle"]["intervals"]),
        "cutoff": args.at, "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
