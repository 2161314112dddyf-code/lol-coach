"""Acquire patch-pinned Riot champion descriptions for a replay review."""
import math
import re

from .champion import normalize


COMBAT_BASE_SCOPE = ("Riot Data Dragon 发布的一级属性和成长参数。成长字段为零仍须核对客户端。"
                     "这些数值不能直接作为当前护甲、魔抗或额外攻击力。")


def _check_release(version, locale):
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("A numbered Data Dragon version is required")
    if not isinstance(locale, str) or not re.fullmatch(r"[a-z]{2}_[A-Z]{2}", locale):
        raise ValueError("Invalid Data Dragon locale")


def fetch_item_names(client, *, version, locale, refresh=False):
    """Return the localized names Riot published for item IDs in this exact release."""
    _check_release(version, locale)
    url = f"https://ddragon.leagueoflegends.com/cdn/{version}/data/{locale}/item.json"
    evidence, payload = client.fetch(f"riot-items-{version}-{locale}", url, expect_json=True, refresh=refresh)
    if (evidence.get("http_status") != 200 or evidence.get("requested_url") != url
            or evidence.get("final_url") != url or not isinstance(payload, dict)):
        raise ValueError(f"Unconfirmed Data Dragon item source for {version}/{locale}")
    if payload.get("type") != "item" or payload.get("version") != version:
        raise ValueError(f"Unconfirmed Data Dragon item catalog version for {version}/{locale}")
    rows = payload.get("data")
    if not isinstance(rows, dict) or not rows:
        raise ValueError("Missing Data Dragon item catalog")
    names = {}
    unnamed = []
    for item_id, row in rows.items():
        if (not isinstance(item_id, str) or not re.fullmatch(r"[1-9][0-9]*", item_id)
                or not isinstance(row, dict) or not isinstance(row.get("name"), str)):
            raise ValueError(f"Invalid Data Dragon item entry: {item_id}")
        if row["name"].strip():
            names[item_id] = row["name"]
        else:
            unnamed.append(item_id)
    source = {key: evidence[key] for key in ("source_id", "requested_url", "final_url", "retrieved_at_utc",
                                            "sha256", "evidence_path", "http_status", "cache_hit")}
    source["content_version"] = payload["version"]
    return dict(items=names, unnamed_item_ids=unnamed, source=source)


def current_riot_version(client, *, patch=None):
    """Read the newest listed Data Dragon publication globally or within a replay patch."""
    url = "https://ddragon.leagueoflegends.com/api/versions.json"
    evidence, versions = client.fetch("ddragon-versions", url, expect_json=True, refresh=True)
    if (evidence.get("http_status") != 200 or evidence.get("requested_url") != url
            or evidence.get("final_url") != url or not isinstance(versions, list) or not versions
            or not all(isinstance(v, str) and v for v in versions)
            or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", versions[0])):
        raise ValueError(f"Riot Data Dragon version list unavailable or invalid ({evidence.get('status')})")
    source = {key: evidence[key] for key in ("requested_url", "final_url", "retrieved_at_utc", "sha256",
                                            "evidence_path", "http_status")}
    if patch is None:
        return dict(version=versions[0], source=source)
    if not re.fullmatch(r'[0-9]+\.[0-9]+', patch):
        raise ValueError('expected numbered replay patch')
    matching = [v for v in versions if re.fullmatch(re.escape(patch) + r'\.[0-9]+', v)]
    if not matching:
        raise ValueError(f'no Data Dragon release for replay patch {patch}')
    return dict(version=matching[0], patch=patch, published_releases=matching, source=source)


def _rank_values(spell, field):
    values = spell.get(field)
    if values is None:
        return None
    if (not isinstance(values, list) or not values
            or any(type(v) not in (float, int) or not math.isfinite(v) or v < 0 for v in values)):
        raise ValueError(f"Invalid Data Dragon {field} for {spell.get('id')}")
    return values


def _combat_base_stats(item):
    """Published level-one values and growth parameters, without runes, items or buffs."""
    rows = {}
    stats = item.get("stats") or {}
    for name, field in (("attack_damage", "attackdamage"), ("armor", "armor"),
                        ("magic_resist", "spellblock"), ("health", "hp")):
        growth = field + "perlevel"
        if field not in stats and growth not in stats:
            continue
        values = [stats.get(field), stats.get(growth)]
        if any(v is not None and (type(v) not in (int, float) or not math.isfinite(v)) for v in values):
            raise ValueError(f"Invalid Data Dragon combat stat for {item['id']}: {field}/{growth}")
        rows[name] = dict(level_1=values[0], growth=values[1], source_fields=[field, growth])
    return rows


def fetch_riot_review_data(client, *, version, locale, champions, refresh=False, offline=False):
    """Return a complete set or raise. Ranges and cooldowns are static source values by rank."""
    _check_release(version, locale)
    if (not isinstance(champions, (list, tuple)) or not champions
            or any(not isinstance(ch, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", ch) for ch in champions)):
        raise ValueError("Pass a nonempty list of Data Dragon champion IDs")
    if offline and refresh:
        raise ValueError("Offline and refresh cannot be combined")

    results = {}
    seen_keys = set()
    for champion in dict.fromkeys(champions):
        url = f"https://ddragon.leagueoflegends.com/cdn/{version}/data/{locale}/champion/{champion}.json"
        evidence, payload = client.fetch(f"riot-champion-{version}-{locale}-{champion}", url,
                                         expect_json=True, refresh=refresh, offline=offline)
        if not isinstance(payload, dict) or evidence.get("http_status") != 200:
            raise ValueError(f"Data Dragon {champion} unavailable ({evidence.get('status')}, HTTP {evidence.get('http_status')})")
        if payload.get("version") != version:
            raise ValueError(f"Unconfirmed Data Dragon version for {champion}")
        if evidence.get("requested_url") != url or evidence.get("final_url") != url:
            raise ValueError(f"Unconfirmed Data Dragon source URL for {champion}")
        data = payload.get("data")
        item = data.get(champion) if isinstance(data, dict) else None
        if not isinstance(item, dict) or item.get("id") != champion:
            raise ValueError(f"Unconfirmed Data Dragon champion identity for {champion}")
        key = item.get("key")
        if not isinstance(key, str) or not re.fullmatch(r"[1-9][0-9]*", key):
            raise ValueError(f"Invalid Data Dragon champion key for {champion}")
        if key in seen_keys:
            raise ValueError(f"Ambiguous Data Dragon champion key for {champion}")
        seen_keys.add(key)
        spells = item.get("spells")
        if (not isinstance(spells, list) or len(spells) != 4 or not isinstance(item.get("passive"), dict)
                or not all(isinstance(s, dict) and isinstance(s.get("id"), str) and s["id"] for s in spells)):
            raise ValueError(f"Incomplete Data Dragon spell list for {champion}")
        normalized = normalize(payload, champion, version, evidence)
        abilities = {}
        for i, entry in enumerate(normalized["abilities"]):
            if not all(isinstance(v, str) and v.strip() for v in (entry["name"], entry["raw_description"])):
                raise ValueError(f"Missing Data Dragon ability text for {champion} {entry['slot']}")
            ability = dict(name=entry["name"], description=entry["raw_description"])
            if i:
                spell = spells[i-1]
                ability.update(id=spell["id"], range_by_rank=_rank_values(spell, "range"),
                               cooldown_by_rank=_rank_values(spell, "cooldown"))
            abilities[entry["slot"]] = ability
        source = dict(normalized["source"], http_status=evidence["http_status"], cache_hit=evidence["cache_hit"])
        results[champion] = dict(champion_id=int(key), name=normalized["name"], base_stats=normalized["base_stats"],
                                 abilities=abilities, source=source)
        combat_stats = _combat_base_stats(item)
        if combat_stats:
            results[champion]["combat_base_stats"] = combat_stats
    return dict(schema="riot-review-data/v1", version=version, locale=locale,
                scope="official_static_champion_data", combat_base_stats_scope=COMBAT_BASE_SCOPE, champions=results)
