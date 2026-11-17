"""Read the version-filtered Tencent 101 lane matchup table without player identifiers."""

from datetime import date
import json
import re
from urllib.parse import urlencode

from .http import EvidenceClient


ENDPOINT = "https://mlol.qt.qq.com/go/battle_info/odp_proxy/lol_101strategy_confront"
LANES = {"TOP", "JUNGLE", "MIDDLE", "BOTTOM", "SUPPORT", "UTILITY"}


def _table(payload):
    if not isinstance(payload, dict) or type(payload.get("code")) is not int or payload["code"] != 0:
        raise ValueError("Tencent 101 returned a service error")
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("result"), str):
        raise ValueError("missing Tencent 101 matchup table")
    table = json.loads(data["result"])
    if not isinstance(table, dict) or not re.fullmatch(r"[0-9]{8}", str(table.get("dtstatdate", ""))):
        raise ValueError("invalid Tencent 101 statistics date")
    day = date.fromisoformat(str(table["dtstatdate"])).isoformat()
    entries = {}
    for field in ("high_op_details", "low_op_details"):
        rows = table.get(field)
        if not isinstance(rows, str):
            raise ValueError("missing Tencent 101 matchup list")
        for row in rows.split("#") if rows else ():
            parts = row.split("_")
            if len(parts) != 4 or not re.fullmatch(r"[1-9][0-9]*", parts[1]):
                raise ValueError("invalid Tencent 101 matchup row")
            target = int(parts[1])
            rate = float(parts[2])
            if target in entries or not 0 <= rate <= 100:
                raise ValueError("duplicate opponent or invalid Tencent 101 win rate")
            entries[target] = rate
    if not entries:
        raise ValueError("empty Tencent 101 matchup table")
    return day, entries


def fetch_matchup(client: EvidenceClient, *, patch: str, lane: str, champion_id: int,
                  opponent_id: int, refresh: bool = False, offline: bool = False) -> dict:
    """Return one listed full-game win rate or an explicit absence from the published shortlist."""
    if (not isinstance(patch, str) or not re.fullmatch(r"[1-9][0-9]*\.[1-9][0-9]*", patch)
            or lane not in LANES or any(type(n) is not int or n < 1 for n in (champion_id, opponent_id))):
        raise ValueError("invalid Tencent 101 patch, lane or champion ID")
    if refresh and offline:
        raise ValueError("cannot refresh Tencent 101 offline")
    # The League game-start roster uses UTILITY, whereas Tencent 101 expects SUPPORT.
    provider_lane = "SUPPORT" if lane == "UTILITY" else lane
    query = urlencode(dict(itier=255, version_id=patch, lane=provider_lane, championid=champion_id))
    url = f"{ENDPOINT}?{query}"
    record, payload = client.fetch("tencent101-lane-matchup", url, expect_json=True,
                                   refresh=refresh, offline=offline)
    if payload is None:
        raise ValueError(f"Tencent 101 matchup unavailable ({record['status']})")
    day, entries = _table(payload)
    rate = entries.get(opponent_id)
    return dict(schema="cn-lane-matchup/v1", source="tencent101", region="CN",
                patch=patch, patch_basis="requested_version_id_not_echoed", lane=lane, tier=255,
                queue=None, champion_id=champion_id, opponent_id=opponent_id,
                metric="full_game_win_rate_pct", status="listed" if rate is not None else "not_listed",
                win_rate_pct=rate, sample_size=None, stat_date=day, source_url=url,
                retrieved_at_utc=record["retrieved_at_utc"], sha256=record["sha256"],
                evidence_path=record["evidence_path"])
