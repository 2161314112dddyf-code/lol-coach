def normalize(payload, champion, patch, evidence):
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise ValueError("Not a Data Dragon champion detail")
    item = payload["data"].get(champion)
    if not isinstance(item, dict) or item.get("id") != champion:
        raise ValueError("Champion identity missing or mismatched")
    version = payload.get("version")
    if version is not None and version != patch:
        raise ValueError("Response version differs from requested patch")
    stats = item.get("stats") or {}
    fields = {}
    for name, raw, unit in [("base_move_speed", "movespeed", "game_units/second"),
                            ("base_attack_range", "attackrange", "game_units"),
                            ("base_health", "hp", "health_points"),
                            ("base_mana", "mp", "mana_points")]:
        value = stats.get(raw)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise ValueError(f"Non-numeric stat: {raw}")
        fields[name] = {"value": value, "unit": unit,
                        "source_field": f"data.{champion}.stats.{raw}",
                        "missing_reason": "not present in source" if value is None else None}
    abilities = []
    passive = item.get("passive") or {}
    abilities.append({"slot": "passive", "name": passive.get("name"),
                      "raw_description": passive.get("description"),
                      "missing_reason": None if passive.get("description") is not None else "not present in source",
                      "source_field": f"data.{champion}.passive.description"})
    for i, spell in enumerate(item.get("spells") or []):
        abilities.append({"slot": "QWER"[i] if i < 4 else str(i), "id": spell.get("id"),
                          "name": spell.get("name"), "raw_description": spell.get("description"),
                          "missing_reason": None if spell.get("description") is not None else "not present in source",
                          "source_field": f"data.{champion}.spells[{i}].description"})
    return {"schema_version": "0.1", "data_kind": "synthetic" if payload.get("fixture_kind") == "synthetic" else "real_official_static_data",
            "champion_id": champion, "champion_key": item.get("key"), "name": item.get("name"),
            "data_version": version, "requested_patch": patch,
            "data_version_status": "verified_response_version" if version else "unverified_missing_version",
            "target_client_version_status": "unverified", "map": None, "mode": None,
            "map_mode_reason": "static champion data, not a match observation",
            "base_stats": fields, "abilities": abilities,
            "complex_skill_ranges": None, "complex_cooldowns": None,
            "mechanics_missing_reason": "raw descriptions are not validated interaction mechanics",
            "ally_interactions": None, "opponent_interactions": None,
            "interaction_status": "not_verified; requires lineup-specific mechanics and human evidence",
            "source": {k: evidence.get(k) for k in ("source_id", "requested_url", "final_url", "retrieved_at_utc", "sha256", "evidence_path")}}
