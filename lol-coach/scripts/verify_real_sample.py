"""Real downloaded evidence smoke check; separate from synthetic unit tests."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.champion import normalize
from lol_coach.http import save_json

target = ROOT / "data/normalized/16.20.1/en_US/Ivern.json"
manifest = json.loads(target.with_suffix(".manifest.json").read_text(encoding="utf-8"))
raw = (ROOT / "data" / manifest["evidence_path"]).read_bytes()
assert hashlib.sha256(raw).hexdigest() == manifest["sha256"]
assert manifest["http_status"] == 200
assert manifest["requested_url"] == "https://ddragon.leagueoflegends.com/cdn/16.20.1/data/en_US/champion/Ivern.json"
versions_evidence = manifest["versions_evidence"]
versions_raw = (ROOT / "data" / versions_evidence["evidence_path"]).read_bytes()
assert hashlib.sha256(versions_raw).hexdigest() == versions_evidence["sha256"]
assert "16.20.1" in json.loads(versions_raw)
normalized = normalize(json.loads(raw), "Ivern", "16.20.1", manifest)
assert normalized == json.loads(target.read_text(encoding="utf-8"))
assert all(f["value"] is not None for f in normalized["base_stats"].values())
assert len(normalized["abilities"]) == 5
assert normalized["data_version_status"] == "verified_response_version"
assert normalized["target_client_version_status"] == "unverified"
result = {"status": "passed", "kind": "real_downloaded_static_data_smoke",
          "network_fetch": "executed previously; this command verifies saved responses offline",
          "patch": "16.20.1", "champion": "Ivern", "sha256": manifest["sha256"],
          "retrieved_at_utc": manifest["retrieved_at_utc"],
          "checks": ["raw SHA256", "version-list evidence", "exact normalization reproduction", "four base fields", "five descriptions", "target-client unverified"]}
save_json(ROOT / "reports/real_sample_smoke.json", result)
print(json.dumps(result, ensure_ascii=False, indent=2))
