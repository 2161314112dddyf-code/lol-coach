"""Immutable, patch-scoped updates shared by the source updater and offline review."""
from datetime import datetime, time, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import re

from .cn_lane_stats import fetch_matchup
from .combat_catalog import archive_game_sources, fetch_combat_catalog, roster_ability_profiles, validate_build
from .file_model_bridge import atomic_json
from .http import EvidenceClient
from .riot_review_data import COMBAT_BASE_SCOPE, fetch_riot_review_data


DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "data/private/review_sources"
LOCALE = "zh_CN"
CLIENT_BASE_BUILD = "16.22.836.1077"
CLIENT_BASE_PROFILE = Path(__file__).resolve().parent / "profiles/champion_combat_base_16_22.json"


def client_combat_bases(build):
    """Exact-build character definitions, independently reproducible from the client WADs."""
    if build != CLIENT_BASE_BUILD or not CLIENT_BASE_PROFILE.is_file():
        return {}
    profile = json.loads(CLIENT_BASE_PROFILE.read_bytes())
    if (profile.get('schema'), profile.get('build')) != ('client-combat-base/v1',build):
        raise ValueError('invalid pinned client champion stat profile')
    return {name:dict(build=build, stats=row['stats'], source={**row['source'], 'fields':profile['fields']},
                      scope=profile['scope']) for name,row in profile['champions'].items()}


def _instant(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("absolute UTC timestamp required")
    return stamp.astimezone(timezone.utc)


def _digest(record):
    return sha256(json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                             allow_nan=False).encode()).hexdigest()


def _records(root, patch):
    if not re.fullmatch(r"[0-9]+\.[0-9]+", patch):
        return
    for path in sorted((Path(root) / "snapshots" / patch).glob("*.json"), reverse=True):
        try:
            record = json.loads(path.read_bytes())
            if (record.get("schema") == "review-source-update/v1" and record["patch"] == patch
                    and record['riot']['locale'] == LOCALE and _digest(record) == path.stem.split("_")[-1]):
                yield path, record
        except (OSError, TypeError, ValueError, AttributeError, KeyError):
            continue


def refresh_sources(root, version, champions, matchups=(), *, max_age_hours=6, force=False, client=None,
                    include_profiles=False, combat_build=None, game_dir=None):
    """Publish a whole requested batch only after every requested upstream read succeeds."""
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("supply exact Data Dragon version, for example 16.22.1")
    names = sorted(set(champions))
    pairs = [tuple(pair) for pair in matchups]
    if not names or any(len(p) != 3 or p[1] not in names or p[2] not in names for p in pairs):
        raise ValueError("each lane pair needs both champions in the requested roster")
    pairs = sorted({("UTILITY" if lane == "SUPPORT" else lane, ally, enemy) for lane, ally, enemy in pairs})
    if not 0 <= max_age_hours <= 8760:
        raise ValueError("max_age_hours outside [0,8760]")
    patch = version.rsplit(".", 1)[0]
    scope = dict(version=version, champions=names, matchups=[list(p) for p in pairs])
    if combat_build is not None:
        from .rune_damage_data import rune_damage_profile
        validate_build(combat_build, version)
        scope['combat_build'] = combat_build
        scope['combat_catalog_format'] = 2
        rune_rules = rune_damage_profile(combat_build)
        ability_profiles = roster_ability_profiles(combat_build, names)
        scope['rune_rules_sha256'] = _digest(rune_rules)
        scope['ability_profiles_sha256'] = _digest(ability_profiles)
    if game_dir is not None:
        if not combat_build:
            raise ValueError('archiving game assets requires an exact combat build')
        scope['archive_game_assets'] = True
    if include_profiles:
        if not pairs:
            raise ValueError("lane profiles require a confirmed lane pair")
        scope["include_profiles"] = True
    prior = next(((path, row) for path, row in _records(root, patch) if row["scope"] == scope), None)
    now = datetime.now(timezone.utc)
    if prior and not force:
        age = now - _instant(prior[1]["completed_at_utc"])
        if timedelta() <= age < timedelta(hours=max_age_hours):
            return dict(status="fresh_cache", snapshot=str(prior[0]))
    client = client or EvidenceClient(Path(root) / "evidence")
    riot = fetch_riot_review_data(client, version=version, locale=LOCALE, champions=names, refresh=True)
    ids = {name: row["champion_id"] for name, row in riot["champions"].items()}
    stats = [fetch_matchup(client, patch=patch, lane=lane, champion_id=ids[a], opponent_id=ids[b], refresh=True)
             for lane, a, b in pairs]
    profiles = []
    if include_profiles:
        from .cn_lane_profiles import fetch_lane_profile
        from .riot_review_data import fetch_item_names
        catalog = fetch_item_names(client, version=version, locale=LOCALE, refresh=True)
        lane_champions = sorted({(lane, ids[name]) for lane, ally, enemy in pairs for name in (ally, enemy)})
        profiles = [fetch_lane_profile(client, patch=patch, lane=lane, champion_id=champion_id, refresh=True)
                    for lane, champion_id in lane_champions]
        for profile in profiles:
            build = profile["tables"]["build"]
            for build_row in build["rows"]:
                build_row["item_names"] = [catalog["items"].get(str(item)) for item in build_row["item_ids"]]
            build["item_name_source"] = {key: catalog["source"][key] for key in
                                         ("requested_url", "sha256", "retrieved_at_utc")}
    completed = datetime.now(timezone.utc)
    row = dict(schema="review-source-update/v1", patch=patch, scope=scope,
               completed_at_utc=completed.isoformat(), riot=riot, cn_lane_stats=stats)
    if combat_build is not None:
        row['combat_catalog'] = fetch_combat_catalog(client, combat_build, version, rune_rules, ability_profiles)
        if game_dir is not None:
            row['combat_catalog']['client_assets'] = archive_game_sources(root, game_dir, row['combat_catalog'], names)
        completed = datetime.now(timezone.utc)
        row['completed_at_utc'] = completed.isoformat()
    if include_profiles:
        row["cn_lane_profiles"] = profiles
    path = Path(root) / "snapshots" / patch / (completed.strftime("%Y%m%dT%H%M%S%fZ_") + _digest(row) + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(path, row)
    return dict(status="updated", snapshot=str(path))


def _lane_roles(frame, champions):
    t = frame.get("task", {})
    roles = {**t.get("bottom_lane_actors", {}), **t.get("roam_actors", {})}
    roster = {h["entity_id"]: champions.get(h.get("champion"), {}).get("champion_id") for h in frame["lineup"]}
    result = {"ally": {}, "enemy": {}}
    for lane, a, b in (("BOTTOM", "carry", "enemy_carry"), ("UTILITY", "support", "enemy_support"),
                       ("MIDDLE", "ally_mid", "enemy_mid"), ("TOP", "ally_top", "enemy_top"),
                       ("JUNGLE", "ally_jungle", "enemy_jungle")):
        for side, legacy_key in (("ally", a), ("enemy", b)):
            confirmed = t.get("external_lane_roles", {}).get(side, {}).get(lane)
            champion = roster.get(confirmed or roles.get(legacy_key))
            if champion:
                result[side][lane] = champion
    return result


def _pregame(table, cutoff, published):
    if cutoff is None or published > cutoff:
        return False
    day = datetime.fromisoformat(table["stat_date"]).date()
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=timezone(timedelta(hours=8)))
    return max(end, _instant(table["retrieved_at_utc"])) <= cutoff


def _availability(eligible, matched, cutoff):
    if eligible:
        return "pregame_snapshot"
    if not matched:
        return "no_matching_pair"
    return "unknown_match_cutoff" if cutoff is None else "no_verified_pregame_snapshot"


def context_for_frame(root, frame):
    """Newest verified static release for this patch; stats must be demonstrably pre-game."""
    build = str(frame["decision"].get("build", ""))
    if not re.fullmatch(r"\d+\.\d+(?:\.\d+)*", build):
        return None
    patch = ".".join(build.split(".")[:2])
    rows = list(_records(root, patch))
    if not rows:
        return None
    lineup = {h.get("champion") for h in frame["lineup"]}
    cutoff_value = frame.get("task", {}).get("match_information_cutoff_utc")
    try:
        cutoff = _instant(cutoff_value) if cutoff_value else None
    except (ValueError, TypeError, AttributeError):
        cutoff = None
    champions = {}
    ambiguous = set()
    combat_stats = {}
    combat_sources = {}
    for _, record in rows:
        for name, champ in record['riot']['champions'].items():
            if name not in lineup or name in ambiguous:
                continue
            source = champ['source']
            publication = (record['riot']['version'], source['sha256'])
            coverage = combat_sources.setdefault(name, {})
            coverage.setdefault(publication, False)
            if 'combat_base_stats' in champ:
                stats = champ['combat_base_stats']
                if name in combat_stats and combat_stats[name] != stats:
                    ambiguous.add(name)
                    del champions[name]
                    continue
                combat_stats[name] = stats
                coverage[publication] = True
            values = {key: value for key, value in champ.items() if key not in ('source', 'combat_base_stats')}
            if name in champions:
                # A replay build confirms major.minor. Two contradictory releases in
                # that patch cannot both establish this champion's historical data.
                if any(champions[name].get(k) != v for k, v in values.items()):
                    ambiguous.add(name)
                    del champions[name]
                continue
            champions[name] = values
            champions[name]['source'] = {key: source[key] for key in ('sha256','requested_url','retrieved_at_utc')}
            champions[name]['static_version'] = record['riot']['version']
    # An older normalizer omitted these fields. A richer extraction of identical
    # bytes covers that publication, independent of archive order. An unexamined
    # release in the same patch cannot certify historical combat values.
    for name, champion in champions.items():
        if all(combat_sources[name].values()):
            champion['combat_base_stats'] = combat_stats[name]
            champion['combat_base_stats_scope'] = COMBAT_BASE_SCOPE
    client_bases = client_combat_bases(build)
    for name in champions.keys() & client_bases.keys():
        champions[name]['client_combat_base_stats'] = client_bases[name]
    if not champions and not ambiguous:
        return None
    roles = _lane_roles(frame, champions)
    wanted = {(lane, ally, roles["enemy"][lane]) for lane, ally in roles["ally"].items() if lane in roles["enemy"]}
    admissible = {}
    found = False
    profiles = {}
    found_profile = False
    for _, record in rows:
        published = _instant(record["completed_at_utc"])
        for stat in record['cn_lane_stats']:
            key = (stat['lane'], stat['champion_id'], stat['opponent_id'])
            if key not in wanted:
                continue
            found = True
            observed = _instant(stat['retrieved_at_utc'])
            if (_pregame(stat, cutoff, published) and
                    (key not in admissible or observed > _instant(admissible[key]['retrieved_at_utc']))):
                admissible[key] = {k:v for k,v in stat.items() if k != 'evidence_path'}
        for profile in record.get("cn_lane_profiles", []):
            lane, hero = profile["lane"], profile["champion_id"]
            for side, assigned in roles.items():
                if assigned.get(lane) != hero:
                    continue
                found_profile = True
                for metric, table in profile["tables"].items():
                    key = (side, lane, hero, metric)
                    if not _pregame(table, cutoff, published):
                        continue
                    if key in profiles and _instant(profiles[key]["retrieved_at_utc"]) >= _instant(table["retrieved_at_utc"]):
                        continue
                    entry = {k: v for k, v in table.items() if k != "evidence_path"}
                    if metric == "partner":
                        entry["rows"] = [r for r in entry["rows"] if r["partner_id"] in assigned.values() and r["partner_id"] != hero]
                    dimensions = {k: profile.get(k) for k in ("source", "region", "patch", "patch_basis", "tier", "queue")}
                    profiles[key] = dict(entry, **dimensions, side=side, lane=lane, champion_id=hero, table=metric)
    payload = dict(schema="external-review-context/v1", patch=patch, champions=champions,
                   cn_lane_stats=[admissible[k] for k in sorted(admissible)],
                   cn_lane_profiles=[profiles[k] for k in sorted(profiles)],
                   availability=dict(champions="patch_static_reference", cn_lane_stats=_availability(admissible, found, cutoff),
                                     cn_lane_profiles=_availability(profiles, found_profile, cutoff),
                                     match_information_cutoff_utc=cutoff_value))
    if ambiguous:
        payload["availability"]["ambiguous_champion_static_data"] = sorted(ambiguous)
        if not champions:
            payload["availability"]["champions"] = "conflicting_patch_static_data"
    return {**payload, "snapshot_id": _digest(payload)}
