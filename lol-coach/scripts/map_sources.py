"""Save format-reference evidence; never execute downloaded source."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.http import EvidenceClient, save_json

client = EvidenceClient(ROOT / "data")
rows = []
for name, repo, branch, files in [
    ("cdtb", "CommunityDragon/CDTB", "master", ["cdtb/wad.py", "LICENSE", "cdtb/export.py"]),
    ("ltk", "LeagueToolkit/LeagueToolkit", "main", ["LICENSE"]),
]:
    rec, commit = client.fetch(name + "-map-commit", f"https://api.github.com/repos/{repo}/commits/{branch}", expect_json=True)
    rows.append(rec)
    if not commit or "sha" not in commit:
        print(name, rec["status"], flush=True)
        continue
    sha = commit["sha"]
    rec, tree = client.fetch(name + "-map-tree", f"https://api.github.com/repos/{repo}/git/trees/{sha}?recursive=1", expect_json=True)
    rows.append(rec)
    if tree:
        paths = [e["path"] for e in tree.get("tree", []) if any(t in e["path"].lower() for t in ("navigation", "navgrid", "ngrid"))]
        print(name, sha, paths, flush=True)
        files += [p for p in paths if p.endswith(".cs")]
    for path in files:
        rec, _ = client.fetch(name + "-map-reference", f"https://raw.githubusercontent.com/{repo}/{sha}/{path}")
        rec["content_version"] = sha
        rows.append(rec)
        print(path, rec["status"], rec["evidence_path"], flush=True)
save_json(ROOT / "reports/map_source_evidence.json", rows)
