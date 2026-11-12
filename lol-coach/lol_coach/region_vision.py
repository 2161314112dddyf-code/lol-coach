"""Time- and team-scoped queries against replay transitions and observed ground.

HUD samples apply only at the sampled frame. A native enter/leave persists to
the next event in the same channel. Neither implies vision of adjacent terrain.
"""
import math
import re


def valid_time(value):
    return type(value) in (float, int) and math.isfinite(value) and value >= 0


def validate_index(index):
    if (index.get("schema") != "vision-evidence/v1" or not index.get("version")
            or not re.fullmatch(r"[0-9a-f]{64}", index.get("source_sha256", ""))
            or not valid_time(index.get("end_seconds")) or not isinstance(index.get("observations"), list)):
        raise ValueError("Invalid replay vision evidence header")
    for row in index["observations"]:
        when = row["time_seconds"]
        available = row.get("available_at_seconds", when)
        if (row["team_id"] not in (100, 200) or row["mode"] not in ("transition", "sample")
                or not isinstance(row["subject"], str) or not row["subject"].startswith(("entity:", "ground:"))
                or not row["subject"].split(":", 1)[1] or type(row["visible"]) not in (bool, type(None))
                or not valid_time(when) or not valid_time(available) or not when <= available <= index["end_seconds"]
                or not isinstance(row.get("source"), dict) or not row["source"].get("kind")):
            raise ValueError("Invalid vision evidence row")
    for row in index.get("enemy_positions_in_view", []):
        if (row.get("team_id") not in (100, 200) or not re.fullmatch(r"entity:0x[0-9a-f]+", row.get("subject", ""))
                or not valid_time(row.get("time_seconds")) or row["time_seconds"] > index["end_seconds"]
                or not isinstance(row.get("xz"), list) or len(row["xz"]) != 2
                or not all(type(c) in (float, int) and math.isfinite(c) for c in row["xz"])
                or row.get("source", {}).get("opcode") != "0x482"
                or row.get("visibility_record", {}).get("opcode") != "0x4d5"):
            raise ValueError("Invalid sight-bound enemy position")
    return index


def checked_indexes(indexes):
    if not indexes:
        raise ValueError("At least one vision evidence file is required")
    for item in indexes:
        validate_index(item)
        if (item["source_sha256"], item["version"]) != (indexes[0]["source_sha256"], indexes[0]["version"]):
            raise ValueError("Vision evidence from different replays or builds")
    return indexes


def visibility_query(indexes, team, subject, at):
    """Query already validated evidence. Never extrapolate a sampled pixel."""
    if team not in (100, 200) or not valid_time(at) or at > max(i["end_seconds"] for i in indexes):
        raise ValueError("Invalid observer team or time outside recorded replay")
    if not isinstance(subject, str) or not subject.startswith(("entity:", "ground:")):
        raise ValueError("Use an entity: or ground: subject")
    rows = [r for i in indexes if at <= i["end_seconds"] for r in i["observations"]
            if r["team_id"] == team and r["subject"] == subject
            and r.get("available_at_seconds", r["time_seconds"]) <= at]
    samples = [r for r in rows if r["mode"] == "sample" and r["time_seconds"] == at]
    transitions = [r for r in rows if r["mode"] == "transition"]
    # Keep channel ordering for simultaneous on/off packets. A later observer
    # marking a *sample* does not extend it past its timestamp.
    active = []
    if transitions:
        last = max(r["time_seconds"] for r in transitions)
        latest = [r for r in transitions if r["time_seconds"] == last]
        if len(latest) > 1 and all(isinstance(r["source"].get("chunk"), int)
                                  and isinstance(r["source"].get("decompressed_offset", r["source"].get("offset")), int)
                                  for r in latest):
            def packet_order(r):
                src = r["source"]
                return (src["chunk"], src.get("decompressed_offset", src.get("offset")))
            last_order = max(map(packet_order, latest))
            latest = [r for r in latest if packet_order(r) == last_order]
        active = latest
    # A null barrier ends the licensed interpretation of a stream. A new HUD
    # sample can still establish the answer at that one observed frame.
    if samples and all(r["visible"] is None for r in active):
        active = []
    if active and not samples:
        known = {r["visible"] for r in active}
        contradictions = [r for r in rows if r["mode"] == "sample"
                          and r["time_seconds"] >= active[0]["time_seconds"]
                          and r["visible"] is not None and r["visible"] not in known]
        if contradictions:
            active = active + [max(contradictions, key=lambda r: r["time_seconds"])]
    evidence = active + samples
    values = {r["visible"] for r in evidence}
    visible = next(iter(values)) if len(values) == 1 else None
    if visible is None:
        basis = "conflicting_evidence" if len(values) > 1 else "unobserved_or_unresolved"
    else:
        basis = "sample_and_transition" if active and samples else ("sample" if samples else "transition")
    methods = set()
    for r in evidence:
        src = r["source"]
        if src["kind"] == "rofl_packet":
            method = "stationary_object_ground_inference" if subject.startswith("ground:") else "entity_visibility_channel"
        elif src["kind"] == "player_hud":
            method = "player_hud_sample"
        else:
            method = src["kind"]
        methods.add(method)
    result = {"subject": subject, "team_id": team, "at_seconds": at, "visible": visible, "basis": basis,
            "methods": sorted(methods),
            "evidence": [{"mode": r["mode"], "time_seconds": r["time_seconds"],
                          "available_at_seconds": r.get("available_at_seconds", r["time_seconds"]),
                          "source": r["source"]} for r in evidence]}
    samples = [r for i in indexes if at <= i["end_seconds"] for r in i.get("enemy_positions_in_view", [])
               if r["subject"] == subject and r["team_id"] == team and r["time_seconds"] <= at]
    if samples:
        last = max(samples, key=lambda r:(r["time_seconds"], r["source"]["chunk"], r["source"]["offset"]))
        result["last_observed_position"] = dict(xz=last["xz"], sampled_at=last["time_seconds"],
            age_seconds=at-last["time_seconds"], source=last["source"], visibility_record=last["visibility_record"])
    return result


def frame_queries(indexes, version, replay_hash, team, at, subjects=(), *, hud_frame=None):
    checked_indexes(indexes)
    if (indexes[0]["version"], indexes[0]["source_sha256"]) != (version, replay_hash):
        raise ValueError("Vision evidence does not match decision replay")
    if team not in (100, 200) or not valid_time(at) or at > max(i["end_seconds"] for i in indexes):
        raise ValueError("Invalid decision viewpoint or time")
    def eligible_sample(row):
        src = row["source"]
        if row["mode"] != "sample" or not (src["kind"] == "player_hud" or "video_sha256" in src):
            return True
        # An aggregate labelled 02:23 may contain images from later than
        # ROFL t=143.000. Only use it for the matched decision screenshot.
        if (not hud_frame or not src.get("video_sha256") or hud_frame.get("video_sha256") != src["video_sha256"]
                or not valid_time(hud_frame.get("pts"))):
            return False
        expected = src.get("frame_sha256", src.get("image_sha256"))
        if expected and hud_frame.get("frame_sha256") != expected:
            return False
        if "pts_first" in src and "pts_last" in src:
            return src["pts_first"] <= hud_frame["pts"] <= src["pts_last"]
        return src.get("pts", src.get("video_seek_seconds")) == hud_frame["pts"]
    indexes = [{**i, "observations": [r for r in i["observations"] if eligible_sample(r)]} for i in indexes]
    if not subjects:
        # Discover only observed subjects from the prefix. Listing an unknown
        # dragon/ward from the full-match roster can itself leak its identity.
        subjects = sorted({r["subject"] for i in indexes for r in i["observations"]
                           if r["subject"].startswith("ground:") and r["team_id"] == team
                           and (r["mode"] == "transition" or r["time_seconds"] == at)
                           and r.get("available_at_seconds", r["time_seconds"]) <= at})
    return [visibility_query(indexes, team, s, at) for s in dict.fromkeys(subjects)]


def allied_ward_positions(indexes, team, at):
    """Report this team's placements and their last sampled locations as of the cut."""
    found = {}
    removed = {(w["entity_id"], w["start_seconds"]) for i in indexes for w in i.get("ward_placements", [])
               if w["team_id"] == team and w["end_seconds"] is not None
               and w["end_seconds"] <= min(at, i["end_seconds"])}
    bonus_ended = {(r["entity_id"], r["start_seconds"]) for i in indexes for r in (i.get("faelight_intervals") or [])
                   if r["team_id"] == team and r["end_seconds"] is not None
                   and r["end_seconds"] <= min(at, i["end_seconds"])}
    for index in indexes:
        if index["end_seconds"] < at:
            continue
        bonus_by_ward = {r["entity_id"]:r for r in (index.get("faelight_intervals") or [])
                         if r["team_id"] == team and r["start_seconds"] <= at and
                         at < r["start_seconds"]+45 and (r["end_seconds"] is None or at < r["end_seconds"])}
        for ward in index.get("ward_placements", []):
            if ward["team_id"] != team or ward["start_seconds"] > at:
                continue
            if (ward["entity_id"], ward["start_seconds"]) in removed:
                continue
            samples = [p for p in ward["positions"] if p["time_seconds"] <= at]
            region = ward.get("spatial_record")
            if region and region["time_seconds"] <= at:
                samples.append(dict(time_seconds=region["time_seconds"], world_xz=region["center_xz"],
                                    source=region["source"]))
            if not samples:
                continue
            sample = max(samples, key=lambda p:p["time_seconds"])
            entity = "entity:"+hex(ward["entity_id"])
            if entity in found and found[entity]["sampled_at"] > sample["time_seconds"]:
                continue
            found[entity] = dict(subject=entity, family=ward["family"], placed_at=ward["start_seconds"],
                sampled_at=sample["time_seconds"], xz=sample["world_xz"], source=sample["source"],
                placement_record=ward["placement_source"])
            bonus = bonus_by_ward.get(ward["entity_id"])
            if bonus and (bonus["entity_id"], bonus["start_seconds"]) not in bonus_ended:
                found[entity]["faelight_pad"] = bonus["pad_name"]
                found[entity]["faelight_sources"] = bonus["start_sources"]
    return list(found.values())


def channel_intervals(indexes, team, subject, start, end):
    """Measure durations only on persistent ROFL channels, in [start, end)."""
    if not valid_time(start) or not valid_time(end) or end <= start:
        raise ValueError("Specify a nonempty interval on the game clock")
    if end > max(i["end_seconds"] for i in indexes):
        raise ValueError("Interval exceeds replay duration")
    # Point samples have no measured duration. In particular, adjacent
    # screenshots cannot fill the unobserved time between them.
    streams = [{**i, "enemy_positions_in_view": [], "observations": [r for r in i["observations"]
               if r["team_id"] == team and r["subject"] == subject and r["mode"] == "transition"]}
               for i in indexes]
    times = {start, end}
    for stream in streams:
        for row in stream["observations"]:
            available = row.get("available_at_seconds", row["time_seconds"])
            if start < available < end:
                times.add(available)
        if start < stream["end_seconds"] < end:
            times.add(stream["end_seconds"])
    ordered = sorted(times)
    spans = []
    totals = {"visible": 0.0, "hidden": 0.0, "unknown": 0.0}
    for left, right in zip(ordered, ordered[1:]):
        # A stream ending precisely at the left edge does not support any
        # duration to its right.
        active = [s for s in streams if s["end_seconds"] > left]
        answer = visibility_query(active, team, subject, left)
        value = answer["visible"]
        totals[{True: "visible", False: "hidden", None: "unknown"}[value]] += right - left
        spans.append({"start": left, "end": right, "visible": value, "basis": answer["basis"],
                      "methods": answer["methods"], "evidence": answer["evidence"]})
    return {"subject": subject, "team_id": team, "spans": spans, "seconds": totals,
            "basis": "recorded_transitions_only"}
