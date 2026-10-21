"""Read public source entries only; never run third-party code."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.http import EvidenceClient, save_json

client = EvidenceClient(ROOT / "data")
results = []
for name, repo in [("ngrid", "FrankTheBoxMonster/LoL-NGRID-converter"),
                   ("rofl", "Mowokuma/ROFL"), ("meraki", "meraki-analytics/lolstaticdata")]:
    record, info = client.fetch(name + "-repo", "https://api.github.com/repos/" + repo, expect_json=True)
    results.append(record)
    if not isinstance(info, dict) or "default_branch" not in info:
        continue
    record, commit = client.fetch(name + "-commit", f"https://api.github.com/repos/{repo}/commits/{info['default_branch']}", expect_json=True)
    results.append(record)
    if not isinstance(commit, dict) or "sha" not in commit:
        continue
    sha = commit["sha"]
    for filename in ("README.md", "LICENSE"):
        rec, _ = client.fetch(name + "-" + filename, f"https://raw.githubusercontent.com/{repo}/{sha}/{filename}")
        rec["content_version"] = sha
        results.append(rec)
    rec, tree = client.fetch(name + "-tree", f"https://api.github.com/repos/{repo}/git/trees/{sha}?recursive=1", expect_json=True)
    results.append(rec)
    if name == "ngrid" and isinstance(tree, dict):
        for entry in tree.get("tree", []):
            path = entry["path"]
            if path.endswith(".cs") and "/obj/" not in path and entry.get("size", 0) < 200000:
                rec, _ = client.fetch("ngrid-code", f"https://raw.githubusercontent.com/{repo}/{sha}/{path}")
                rec["content_version"] = sha
                results.append(rec)
for name, url in [
    ("map11-latest", "https://raw.communitydragon.org/latest/game/data/maps/shipping/map11/"),
    ("map11-16.20", "https://raw.communitydragon.org/16.20/game/data/maps/shipping/map11/"),
    ("clear-sheet", "https://docs.google.com/spreadsheets/d/1jE8bnlnIJnmWv9pnVW9veMKRXJNaaJf5tneQB3xUkbI/edit")]:
    rec, _ = client.fetch(name, url)
    results.append(rec)
save_json(ROOT / "reports/entry_evidence.json", results)
for rec in results:
    print(rec["source_id"], rec["status"], rec["evidence_path"], flush=True)
