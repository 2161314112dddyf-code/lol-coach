from hashlib import sha256
from io import BytesIO
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from lol_coach.cn_lane_profiles import fetch_lane_profile
from lol_coach.http import EvidenceClient


QUERY = dict(patch="16.22", lane="UTILITY", champion_id=80)


def example_client(root, changes=None):
    data = {
        "duration": {"dtstatdate": "20261112", "data_details": "1_51_18#6_49_32"},
        "partner": {"dtstatdate": "20261111", "data_details": "1_876_55.7_4476_2493"},
        "build": {"dtstatdate": "20261112", "core_details": "6655,3100,3094_1_15.16_51.92",
                  "starting_details": "2003,2003_1_93.74_49.25", "shoes_details": "",
                  "forth_details": "", "fifth_details": "", "sixth_details": ""},
    }
    for table, overrides in (changes or {}).items():
        data[table].update(overrides)

    class Response(BytesIO):
        status = 200
        headers = {"Content-Type": "application/json"}

        def geturl(self):
            return self.url

    def serve(request, timeout):
        name = urlsplit(request.full_url).path.rsplit("_", 1)[-1]
        response = Response(json.dumps({"code": 0, "data": {"result": json.dumps(data[name])}}).encode())
        response.url = request.full_url
        return response

    return EvidenceClient(root, opener=serve, interval=0)


def test_refresh_and_replay_with_per_table_evidence(tmp_path):
    client = example_client(tmp_path)
    profile = fetch_lane_profile(client, **QUERY, refresh=True)
    assert (profile["patch"], profile["lane"], profile["champion_id"], profile["queue"]) == (
        "16.22", "UTILITY", 80, None)
    duration, build, partner = (profile["tables"][k] for k in ("duration", "build", "partner"))
    assert [(row["game_end_minutes_from"], row["game_end_minutes_to"], row["win_rate_pct"])
            for row in duration["rows"]] == [(None, 20, 51), (40, None, 49)]
    assert duration["rows"][0]["lane_rank"] == 18 and duration["rows"][0]["sample_size"] is None
    assert build["rows"][0]["item_ids"] == [2003, 2003]
    assert build["rows"][1] == dict(category="core", item_ids=[6655, 3100, 3094], rank=1,
                                    pick_rate_pct=15.16, win_rate_pct=51.92, wins=None, sample_size=None)
    assert partner["rows"] == [dict(partner_id=876, partner_lane=None, rank=1, win_rate_pct=55.7,
                                    wins=2493, sample_size=4476)]
    assert partner["stat_date"] == "2026-11-11" and build["stat_date"] == "2026-11-12"
    for table in profile["tables"].values():
        assert parse_qs(urlsplit(table["source_url"]).query) == dict(
            itier=["255"], version_id=["16.22"], lane=["SUPPORT"], championid=["80"])
        assert sha256((tmp_path / table["evidence_path"]).read_bytes()).hexdigest() == table["sha256"]
    client.opener = lambda *args, **kwargs: pytest.fail("offline attempted network")
    assert fetch_lane_profile(client, **QUERY, offline=True) == profile
    with pytest.raises(ValueError, match="cache_miss"):
        fetch_lane_profile(client, **{**QUERY, "patch": "16.21"}, offline=True)


@pytest.mark.parametrize("changes", [
    {"duration": {"data_details": "7_51_24"}}, {"duration": {"data_details": "1_NaN_1"}},
    {"duration": {"data_details": "6_49_32#6_48_31"}}, {"duration": {"dtstatdate": "20261332"}},
    {"build": {"core_details": "6655,0_1_25_55"}}, {"build": {"starting_details": "2003_1_105_44"}},
    {"partner": {"data_details": "1_876_55.7_2493_4476"}},
    {"partner": {"data_details": "1_876_45_4476_2493"}},
])
def test_malformed_rows_raise(tmp_path, changes):
    with pytest.raises(ValueError):
        fetch_lane_profile(example_client(tmp_path, changes), **QUERY)


def test_empty_shortlist_carries_no_claim_about_unlisted_partners(tmp_path):
    profile = fetch_lane_profile(example_client(tmp_path, {"partner": {"data_details": ""}}), **QUERY)
    assert profile["tables"]["partner"]["rows"] == []
