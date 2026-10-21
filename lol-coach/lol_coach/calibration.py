"""Conservative local-log binding and candidate coordinate inspection.

No packet decoding, interpolation or ground-truth position claims happen here.
"""
import math
import re


def parse_session_log(text, game_id):
    if not re.fullmatch(r"[0-9]+", game_id):
        raise ValueError("game_id must contain digits")
    patterns = {
        "game_id": r"GameStartData::GameID=(\d+)\b",
        "version": r"Build Version: Version (\d+\.\d+\.\d+\.\d+)\b",
        "map_skin": r"GameStartInfo GPP match Id = [\w-]+, mapskin = (\w+)\b",
    }
    values = {key: set() for key in patterns}
    evidence = []
    for number, line in enumerate(text.splitlines(), 1):
        # Never retain full log lines: command lines may contain connection keys.
        for key, pattern in patterns.items():
            match = re.search(pattern, line)
            if match:
                value = match.group(1)
                values[key].add(value)
                evidence.append({"line": number, "field": key, "value": value})
    if any(len(v) != 1 for v in values.values()):
        raise ValueError("Missing or conflicting session-log fields")
    result = {key: next(iter(v)) for key, v in values.items()}
    if result["game_id"] != game_id:
        raise ValueError("Log GameID does not match requested live session")
    return {**result, "evidence": evidence, "map_id": None, "mode": None,
            "active_overlays": None, "status": "live_session_log_fields_verified"}


def bind_bundle(session, manifest):
    if session["map_skin"] != manifest["map_skin"]:
        raise ValueError("Session and asset map skins differ")
    # exe 16.20.824.8524 corresponds to metadata 16.20.8248524.
    major, minor, build, revision = session["version"].split(".")
    expected = f"{major}.{minor}.{build}{revision}"
    for metadata in manifest["local_metadata"].values():
        if metadata["version"].split("+")[0] != expected:
            raise ValueError("Session and asset builds differ")
    return {"status": "skin_and_build_matched", "map_id_verified": False,
            "runtime_terrain_verified": False, "actual_passability": None,
            "reason": "Log does not establish map ID, active overlays or collision semantics"}


def inspect_track(track, grid):
    rows = []
    previous = None
    for record in track:
        t = record["time_seconds"]
        points = record["map_waypoints_assuming_legacy_origin"]
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0:
            raise ValueError("Invalid candidate time")
        if previous is not None and t <= previous:
            raise ValueError("Candidate times must be strictly increasing")
        if not points:
            raise ValueError("Candidate record has no points")
        mapped = []
        for i, point in enumerate(points):
            if len(point) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in point):
                raise ValueError("Invalid candidate coordinate")
            mapped.append({"role": "packet_start_candidate" if i == 0 else "planned_waypoint_candidate",
                           "x": point[0], "z": point[1], "grid_query": grid.cell_at(*point),
                           "visually_observed": False, "arrival_time_seconds": None})
        rows.append({"time_seconds": t, "elapsed_since_previous_record_seconds": None if previous is None else t - previous,
                     "elapsed_meaning": "packet_record_interval_not_action_duration",
                     "points": mapped, "action_duration_seconds": None})
        previous = t
    return rows
