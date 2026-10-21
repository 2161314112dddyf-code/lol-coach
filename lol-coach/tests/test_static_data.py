import hashlib
import json
from io import BytesIO
from urllib.error import URLError, HTTPError

import pytest

from lol_coach.champion import normalize
from lol_coach.http import EvidenceClient


@pytest.fixture
def synthetic():
    return {"fixture_kind": "synthetic", "version": "test.1", "data": {"Ivern": {
        "id": "Ivern", "key": "427", "stats": {"movespeed": 321, "attackrange": 123, "hp": 456, "mp": 789},
        "passive": {"description": "synthetic passive"}, "spells": [{"description": "synthetic Q"}]}}}


def test_mapping(synthetic):
    result = normalize(synthetic, "Ivern", "test.1", {})
    assert result["base_stats"]["base_move_speed"]["value"] == 321
    assert result["base_stats"]["base_attack_range"]["value"] == 123
    assert result["base_stats"]["base_health"]["value"] == 456
    assert result["base_stats"]["base_mana"]["value"] == 789
    assert result["abilities"][1]["slot"] == "Q"
    assert result["target_client_version_status"] == "unverified"


def test_missing_unknown(synthetic):
    synthetic["data"]["Ivern"]["stats"] = {}
    result = normalize(synthetic, "Ivern", "test.1", {})
    assert all(f["value"] is None and f["missing_reason"] for f in result["base_stats"].values())
    assert result["ally_interactions"] is None


def test_no_version_proof(synthetic):
    del synthetic["version"]
    assert normalize(synthetic, "Ivern", "test.1", {})["data_version_status"] == "unverified_missing_version"


def test_version_mismatch(synthetic):
    with pytest.raises(ValueError, match="version"):
        normalize(synthetic, "Ivern", "other", {})


def test_bad_stat(synthetic):
    synthetic["data"]["Ivern"]["stats"]["hp"] = "unknown"
    with pytest.raises(ValueError, match="Non-numeric"):
        normalize(synthetic, "Ivern", "test.1", {})


class Response(BytesIO):
    status = 200
    def __init__(self, body, content_type="application/json"):
        super().__init__(body)
        self.headers = {"Content-Type": content_type}
    def geturl(self):
        return "https://synthetic.example/final"


@pytest.mark.parametrize("body,ctype,status", [
    (b'{"version":"test.1"}', "application/json", "json_parsed_fields_unverified"),
    (b"{broken", "application/json", "invalid_json"),
    (b"<html>synthetic</html>", "text/html", "non_json")])
def test_http_classification(tmp_path, body, ctype, status):
    client = EvidenceClient(tmp_path, opener=lambda *a, **kw: Response(body, ctype), interval=0)
    record, data = client.fetch("synthetic", "https://synthetic.example", expect_json=True)
    assert record["status"] == status
    assert hashlib.sha256((tmp_path / record["evidence_path"]).read_bytes()).hexdigest() == record["sha256"]
    assert record["final_url"] == "https://synthetic.example/final"
    assert data is None if status != "json_parsed_fields_unverified" else data["version"] == "test.1"


def test_failure_and_retry(tmp_path):
    calls = []
    def fail(*a, **kw):
        calls.append(1)
        raise URLError("synthetic failure")
    record, data = EvidenceClient(tmp_path, opener=fail, interval=0).fetch("synthetic", "https://synthetic.example", expect_json=True)
    assert record["status"] == "network_error" and data is None
    assert len(calls) == 2 and len(record["attempts"]) == 2
    assert list((tmp_path / "attempts").glob("*.json"))


def test_blocked_no_retry(tmp_path):
    def fail(*a, **kw):
        raise HTTPError("https://synthetic.example", 403, "synthetic denied", {}, BytesIO(b"denied"))
    record, data = EvidenceClient(tmp_path, opener=fail, interval=0).fetch("synthetic", "https://synthetic.example")
    assert record["status"] == "blocked" and len(record["attempts"]) == 1 and data is None


def test_cache_and_trace(tmp_path, synthetic):
    client = EvidenceClient(tmp_path, opener=lambda *a, **kw: Response(json.dumps(synthetic).encode()), interval=0)
    first, _ = client.fetch("synthetic", "https://synthetic.example", expect_json=True)
    client.opener = lambda *a, **kw: pytest.fail("Offline cache attempted network")
    second, payload = client.fetch("synthetic", "https://synthetic.example", expect_json=True, offline=True)
    assert second["cache_hit"] and first["retrieved_at_utc"] == second["retrieved_at_utc"]
    normalized = normalize(payload, "Ivern", "test.1", second)
    assert (tmp_path / normalized["source"]["evidence_path"]).exists()


def test_corrupt_cache_offline(tmp_path):
    client = EvidenceClient(tmp_path, opener=lambda *a, **kw: Response(b"{}"), interval=0)
    first, _ = client.fetch("synthetic", "https://synthetic.example")
    (tmp_path / first["evidence_path"]).write_bytes(b"tampered")
    record, _ = client.fetch("synthetic", "https://synthetic.example", offline=True)
    assert record["status"] == "cache_miss"
