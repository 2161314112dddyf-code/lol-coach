"""Synthetic Tencent response and verified offline replay through the HTTP cache."""
from hashlib import sha256
from io import BytesIO
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from lol_coach.cn_lane_stats import fetch_matchup
from lol_coach.http import EvidenceClient


QUERY = dict(patch="16.22", lane="BOTTOM", champion_id=51, opponent_id=96)


def client_for(tmp_path, **changes):
    table = dict(dtstatdate="20261112", high_op_details="1_15_50.2_1.5",
                 low_op_details="1_96_46.32_-0.11")
    table.update(changes)
    body = json.dumps({"code": 0, "data": {"result": json.dumps(table)}}).encode()

    class Response(BytesIO):
        status = 200
        headers = {"Content-Type": "application/json"}

        def geturl(self):
            return self.url

    def get(request, timeout):
        response = Response(body)
        response.url = request.full_url
        return response

    return EvidenceClient(tmp_path, opener=get, interval=0)


def test_matchup_refresh_and_offline_reads_same_evidence(tmp_path):
    client = client_for(tmp_path)
    result = fetch_matchup(client, **QUERY, refresh=True)
    assert (result["win_rate_pct"], result["sample_size"], result["status"]) == (46.32, None, "listed")
    assert result["stat_date"] == "2026-11-12" and result["region"] == "CN"
    assert parse_qs(urlsplit(result["source_url"]).query) == {
        "itier": ["255"], "lane": ["BOTTOM"], "championid": ["51"], "version_id": ["16.22"]}
    assert sha256((tmp_path / result["evidence_path"]).read_bytes()).hexdigest() == result["sha256"]
    client.opener = lambda *a, **kw: pytest.fail("offline attempted network")
    assert fetch_matchup(client, **QUERY, offline=True) == result
    absent = fetch_matchup(client, **{**QUERY, "opponent_id": 99}, offline=True)
    assert absent["status"] == "not_listed" and absent["win_rate_pct"] is None
    with pytest.raises(ValueError, match="cache_miss"):
        fetch_matchup(client, **{**QUERY, "patch":"16.21"}, offline=True)


@pytest.mark.parametrize("fields", [
    {"dtstatdate":"20261199"}, {"low_op_details":"1_96_995_0"}, {"low_op_details":"1_96_NaN_0"},
    {"low_op_details":"bad"}, {"high_op_details":"1_96_49.7_12"}, {"low_op_details":"", "high_op_details":""}])
def test_invalid_or_ambiguous_table_is_not_published(tmp_path, fields):
    with pytest.raises(ValueError):
        fetch_matchup(client_for(tmp_path, **fields), **QUERY)


def test_game_utility_role_queries_tencent_support_and_shares_its_cached_table(tmp_path):
    client = client_for(tmp_path)
    row = fetch_matchup(client, **{**QUERY, "lane": "UTILITY"})
    assert parse_qs(urlsplit(row["source_url"]).query)["lane"] == ["SUPPORT"]
    again = fetch_matchup(client, **{**QUERY, "lane":"SUPPORT"}, offline=True)
    assert row["sha256"] == again["sha256"]


@pytest.mark.parametrize("changes", [{"patch":"latest"}, {"lane":"RANKED"}, {"champion_id":"51"}, {"opponent_id":True}])
def test_bad_query_rejected_before_fetch(tmp_path, changes):
    client = client_for(tmp_path)
    client.opener = lambda *a, **kw: pytest.fail("invalid query reached network")
    with pytest.raises(ValueError, match="invalid Tencent"):
        fetch_matchup(client, **{**QUERY, **changes})
