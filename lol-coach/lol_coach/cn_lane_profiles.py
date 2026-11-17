"""Version-filtered Tencent 101 duration, build and partner tables for one lane."""

from datetime import date
import json
import re
from urllib.parse import urlencode

from .cn_lane_stats import LANES
from .http import EvidenceClient


_URL = "https://mlol.qt.qq.com/go/battle_info/odp_proxy/lol_101strategy_"
_END_MINUTES = {1: (None, 20), 2: (20, 25), 3: (25, 30), 4: (30, 35),
                5: (35, 40), 6: (40, None)}
_BUILD_GROUPS = {"starting_details": "starting", "shoes_details": "boots",
                 "core_details": "core", "forth_details": "fourth_item",
                 "fifth_details": "fifth_item", "sixth_details": "sixth_item"}


def _entries(table, field, length):
    value = table.get(field)
    if not isinstance(value, str):
        raise ValueError(f"missing Tencent 101 profile field {field}")
    for raw in value.split("#") if value else ():
        parts = raw.split("_")
        if len(parts) != length:
            raise ValueError(f"malformed Tencent 101 profile field {field}")
        yield parts


def _integer(raw, minimum=1):
    if not re.fullmatch(r"[0-9]+", raw) or int(raw) < minimum:
        raise ValueError("invalid Tencent 101 integer")
    return int(raw)


def _percent(raw):
    value = float(raw)
    if not 0 <= value <= 100:
        raise ValueError("invalid Tencent 101 percentage")
    return value


def _duration(table):
    rows = []
    for bucket, rate, rank in _entries(table, "data_details", 3):
        bucket_id = _integer(bucket)
        if bucket_id not in _END_MINUTES or any(row["bucket_id"] == bucket_id for row in rows):
            raise ValueError("unknown or duplicate Tencent 101 duration bucket")
        low, high = _END_MINUTES[bucket_id]
        rows.append(dict(bucket_id=bucket_id, game_end_minutes_from=low, game_end_minutes_to=high,
                         win_rate_pct=_percent(rate), lane_rank=_integer(rank),
                         wins=None, sample_size=None))
    return rows


def _build(table):
    rows = []
    for field, category in _BUILD_GROUPS.items():
        for items, rank, pick, win in _entries(table, field, 4):
            rows.append(dict(category=category, item_ids=[_integer(item) for item in items.split(",")],
                             rank=_integer(rank), pick_rate_pct=_percent(pick),
                             win_rate_pct=_percent(win), wins=None, sample_size=None))
    return rows


def _partner(table):
    rows = []
    for rank, partner, rate, count, won in _entries(table, "data_details", 5):
        total, wins, pct = _integer(count), _integer(won, minimum=0), _percent(rate)
        # The source reports its percentage to two decimal places (omitting trailing zeros).
        if wins > total or abs(100 * wins / total - pct) > 0.00500001:
            raise ValueError("inconsistent Tencent 101 partner wins, sample size and percentage")
        rows.append(dict(partner_id=_integer(partner), partner_lane=None, rank=_integer(rank),
                         win_rate_pct=pct, wins=wins, sample_size=total))
    return rows


def _decode(payload):
    if not isinstance(payload, dict) or type(payload.get("code")) is not int or payload["code"] != 0:
        raise ValueError("Tencent 101 profile service error")
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("result"), str):
        raise ValueError("missing Tencent 101 profile result")
    table = json.loads(data["result"])
    if not isinstance(table, dict) or not re.fullmatch(r"[0-9]{8}", str(table.get("dtstatdate", ""))):
        raise ValueError("invalid Tencent 101 profile statistics date")
    return date.fromisoformat(str(table["dtstatdate"])).isoformat(), table


def fetch_lane_profile(client: EvidenceClient, *, patch: str, lane: str, champion_id: int,
                       refresh: bool = False, offline: bool = False) -> dict:
    """Fetch each table with its own source date, fetch time and raw-response hash."""
    if (not isinstance(patch, str) or not re.fullmatch(r"[1-9][0-9]*\.[1-9][0-9]*", patch)
            or lane not in LANES or type(champion_id) is not int or champion_id < 1):
        raise ValueError("invalid Tencent 101 patch, lane or champion ID")
    if refresh and offline:
        raise ValueError("cannot refresh Tencent 101 offline")
    provider_lane = "SUPPORT" if lane == "UTILITY" else lane
    query = urlencode(dict(itier=255, version_id=patch, lane=provider_lane, championid=champion_id))
    tables = {}
    for name, parse_rows in (("duration", _duration), ("build", _build), ("partner", _partner)):
        url = f"{_URL}{name}?{query}"
        record, payload = client.fetch(f"tencent101-lane-{name}", url, expect_json=True,
                                       refresh=refresh, offline=offline)
        if payload is None:
            raise ValueError(f"Tencent 101 {name} unavailable ({record['status']})")
        day, table = _decode(payload)
        tables[name] = dict(stat_date=day, retrieved_at_utc=record["retrieved_at_utc"],
                            sha256=record["sha256"], source_url=url,
                            evidence_path=record["evidence_path"], rows=parse_rows(table))
    return dict(schema="cn-lane-profile/v1", source="tencent101", region="CN", patch=patch,
                patch_basis="requested_version_id_not_echoed", lane=lane, tier=255, queue=None,
                champion_id=champion_id, tables=tables)
