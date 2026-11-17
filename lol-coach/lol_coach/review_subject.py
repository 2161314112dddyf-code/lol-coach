"""Bind a personal review to one original replay, game log and local player."""
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re

from .replay_container import container_info
from .round_chain import _check_bundle, _source


# These 16.22 footers have no GameID. The original file pairs were matched
# during the ten-player and practice-game audits. The filename is never used.
_REVIEWED_PAIRS = {
    "cf9bd72a98818d85f6ccf800c929142579831713d9e0c6e9c6194eac20f98e4f": (
        "11461276459", "38c4e68af377eda994b90cb97e7d86b74697a7d7cf32c23ebbfe3c69eb62e912"),
    "2febca32e5e32b182ded7dcccdcc0f2c41405d51e41115b058a5f2d7824e3692": (
        "11461236084", "78c6200ee02d250ea7d2f5070abafc312c4bda037b4092c2bf25517fb019f91b"),
}


def _log_roster(log):
    roster = []
    roles = {}
    local = []
    # Match the fixed roster fields. The display name may contain spaces
    # or game vocabulary and must never set the LOCAL marker.
    pattern = re.compile(
        rb"\bROST\| CONNECTION READY \| Team(Order|Chaos) \d+\) '.*' "
        rb"(?:(\*\*LOCAL\*\*) )?- Champion\(([A-Za-z0-9]+)\) "
        rb"SkinID\(\d+\) TeamBuilderRole\(([^)]*)\) PUUID\(([^)]*)\)"
    )
    for line in log.splitlines():
        if b"ROST| CONNECTION READY |" not in line:
            continue
        match = pattern.search(line)
        if not match:
            raise ValueError("unrecognized_game_log_roster_row")
        side, marker, champion, role, puuid = match.groups()
        entry = (100 if side == b"Order" else 200, champion.decode("ascii"))
        if role in (b"TOP", b"JUNGLE", b"MIDDLE", b"BOTTOM", b"UTILITY"):
            roles[entry] = role.decode("ascii")
        roster.append(entry)
        if marker:
            local.append((*entry, puuid.decode("ascii")))
    if len(local) != 1 or not local[0][2]:
        raise ValueError("missing_or_ambiguous_local_roster_player")
    return roster, local[0], roles


def _download_evidence(replay_path, log_path, match_id, modified):
    start = re.match(r"(\d{4}-\d\d-\d\dT\d\d-\d\d-\d\d)_\d+_LeagueClient\.log$", log_path.name)
    if not start:
        return []
    # These are local wall-clock timestamps. This workflow is run on the
    # machine that wrote the game logs. The filename has one-second precision.
    epoch = datetime.strptime(start[1], "%Y-%m-%dT%H-%M-%S").timestamp()
    content = log_path.read_bytes()
    game = match_id.encode("ascii")
    request = cache = None
    events = []
    for number, line in enumerate(content.splitlines(), 1):
        if b"rcp-be-lol-replays|" not in line:
            continue
        message = line.split(b"rcp-be-lol-replays|", 1)[1].strip()
        if message == b"DownloaderSubmodule: Rofl download job started":
            request = cache = None
        elif message.startswith(b"DownloaderSubmodule: server request, download from GAMHS for game "):
            request = number if message.endswith(b"'" + game + b"'") else None
            cache = None
        elif request and message.startswith(b"FileManager: caching metadata for Replay gameId "):
            record = re.fullmatch(rb"FileManager: caching metadata for Replay gameId '(\d+)', roflPath '(.+)'", message)
            cache = None
            if record and record[1] == game:
                recorded_path = Path(record[2].decode("utf-8", errors="replace"))
                if recorded_path.is_absolute() and recorded_path.resolve() == replay_path:
                    cache = number
        elif message == b"DownloaderSubmodule: Rofl download job ending":
            clock = re.match(rb"^(\d+\.\d+)\|", line)
            if request and cache and clock:
                delta = abs(epoch + float(clock[1]) - modified)
                if delta <= 2:
                    events.append(dict(log_sha256=hashlib.sha256(content).hexdigest(),
                                       request_line=request, path_line=cache, completion_line=number,
                                       mtime_delta_seconds=round(delta, 3)))
            request = cache = None
    return events


def _information_cutoff(log):
    """Earliest UTC instant consistent with the original game log's opening timestamp."""
    first = log.partition(b'\n')[0].strip()
    stamp = re.fullmatch(rb'0+\.0+\|\s*ALWAYS\| Logging started at (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)?)', first)
    if not stamp:
        return None
    try:
        started = datetime.fromisoformat(stamp[1].decode('ascii').replace('Z', '+00:00'))
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone(timedelta(hours=14)))
        return started.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError):
        return None


def _download_logs(game_log_path, modified):
    game_logs = game_log_path.parent.parent
    if game_logs.name != "GameLogs":
        return []
    directory = game_logs.parent / "LeagueClient Logs"
    day = datetime.fromtimestamp(modified).date()
    return [p for d in (day, day - timedelta(days=1))
            for p in directory.glob(f"{d.isoformat()}T*_LeagueClient.log")]


def load_review_subject(replay_path: Path, game_log_path: Path, download_log_path: Path | None = None) -> dict:
    replay_path = Path(replay_path).resolve()
    game_log_path = Path(game_log_path).resolve()
    raw = replay_path.read_bytes()
    log = game_log_path.read_bytes()
    replay_hash = hashlib.sha256(raw).hexdigest()
    log_hash = hashlib.sha256(log).hexdigest()
    ids = set(re.findall(rb"\bGameStartData::GameID=(\d+)\s*$", log, re.MULTILINE))
    if len(ids) != 1:
        raise ValueError("missing_or_conflicting_game_log_match_id")
    match_id = ids.pop().decode("ascii")
    reviewed_pair = _REVIEWED_PAIRS.get(replay_hash)
    if reviewed_pair and reviewed_pair[0] != match_id:
        raise ValueError("replay_and_game_log_match_id_mismatch")
    metadata = container_info(raw)["metadata"]
    rows = json.loads(metadata.get("statsJson", "[]"))
    if not isinstance(rows, list) or not rows or any(not isinstance(r, dict) for r in rows):
        raise ValueError("missing_replay_roster")
    ids_in_footer = {str(metadata[k]) for k in ("gameId", "gameID") if k in metadata}
    ids_in_footer.update(str(row["GAME_ID"]) for row in rows if "GAME_ID" in row)
    download = None
    if ids_in_footer and ids_in_footer != {match_id}:
        raise ValueError("replay_and_game_log_match_id_mismatch")
    if download_log_path is not None or not ids_in_footer:
        modified = replay_path.stat().st_mtime
        candidates = ([Path(download_log_path)] if download_log_path is not None
                      else _download_logs(game_log_path, modified))
        records = [r for path in candidates for r in _download_evidence(replay_path, path, match_id, modified)]
        if len(records) > 1:
            raise ValueError("ambiguous_replay_client_download")
        if records:
            download = records[0]
        elif download_log_path is not None:
            raise ValueError("replay_client_download_unverified")
    if ids_in_footer:
        match_id_source = "replay_footer_and_game_log"
    elif download:
        match_id_source = "authenticated_client_download"
    else:
        if reviewed_pair != (match_id, log_hash):
            raise ValueError("replay_and_game_log_pair_unverified")
        match_id_source = "reviewed_file_pair_and_game_log"
    try:
        roster = [(int(row["TEAM"]), row["SKIN"]) for row in rows]
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("invalid_replay_roster") from exc
    logged, (team, champion, local_puuid), roles = _log_roster(log)
    if Counter(roster) != Counter(logged):
        raise ValueError("replay_and_game_log_roster_mismatch")
    local_rows = [row for row, player in zip(rows, roster) if player == (team, champion)]
    if len(local_rows) != 1 or local_rows[0].get("PUUID") != local_puuid:
        raise ValueError("replay_and_game_log_local_player_mismatch")
    return dict(match_id=match_id, match_id_source=match_id_source, download_evidence=download, replay_sha256=replay_hash,
                log_sha256=log_hash, local_champion=champion, local_team_id=team,
                match_information_cutoff_utc=_information_cutoff(log),
                roster_count=len(roster), roster=[dict(team_id=t, champion=c, assigned_role=roles.get((t, c)))
                                                  for t, c in roster])


def _assigned_actors(frame, subject, roles):
    candidates = {}
    for row in subject['roster']:
        allied = row['team_id'] == frame['decision']['observer_team_id']
        key = roles.get((allied, row.get('assigned_role')))
        if key is None:
            continue
        relation = 'ally' if allied else 'enemy'
        matches = [hero['entity_id'] for hero in frame['lineup']
                   if hero['champion'] == row['champion'] and hero['relation'] == relation]
        candidates.setdefault(key, []).append(matches)
    return {key: rows[0][0] for key, rows in candidates.items() if len(rows) == 1 and len(rows[0]) == 1}


def bottom_lane_actors(frame, subject):
    """Assigned duos at game start. Their presence and ability to follow need current observations."""
    actors = _assigned_actors(frame, subject, {(True, 'UTILITY'): 'support', (True, 'BOTTOM'): 'carry',
                                              (False, 'UTILITY'): 'enemy_support', (False, 'BOTTOM'): 'enemy_carry'})
    if len(actors) == 4 and actors['support'] == frame['decision']['player_entity_id']:
        return actors
    return None


def roam_actors(frame, subject):
    roles = {(allied, position): f"{side}_{lane}"
             for allied, side in [(True, 'ally'), (False, 'enemy')]
             for position, lane in [('MIDDLE', 'mid'), ('JUNGLE', 'jungle'), ('TOP', 'top')]}
    return _assigned_actors(frame, subject, roles)


def validate_review_subject(subject: dict, bundle: dict) -> None:
    frame = _check_bundle(bundle)
    if _source(bundle) != subject["replay_sha256"]:
        raise ValueError("personal_review_replay_mismatch")
    decision = frame["decision"]
    if decision["observer_team_id"] != subject["local_team_id"]:
        raise ValueError("personal_review_observer_team_mismatch")
    selected = [r for r in frame["lineup"] if r["entity_id"] == decision["player_entity_id"]]
    if (len(selected) != 1 or selected[0]["relation"] != "ally"
            or selected[0]["champion"] != subject["local_champion"]):
        raise ValueError("personal_review_local_player_mismatch")
