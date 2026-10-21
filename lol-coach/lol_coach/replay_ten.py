"""Ten useful replay outputs with explicit final-state and event boundaries.

Reuses the investigated exact-build movement, level and lifecycle grammars.
This is a retrospective evidence export, not an omniscient coaching input.
"""
import math

from .replay_fields import analyze, location, read_metadata

CATEGORIES = {
    "T01": ("participants", "阵容与阵营"),
    "T02": ("loadouts", "符文与召唤师技能配置"),
    "T03": ("inventory", "结算装备"),
    "T04": ("economy", "结算经济"),
    "T05": ("creep_score", "结算补刀"),
    "T06": ("combat_totals", "结算伤害与治疗"),
    "T07": ("movement", "移动计划与移速记录"),
    "T08": ("levels", "等级候选时间线"),
    "T09": ("kills", "击杀参与者与时间"),
    "T10": ("lifecycle", "死亡与复活区间"),
}


def number(player, key):
    value = player.get(key)
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"Boolean in numeric metadata {key}")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid numeric metadata {key}") from exc
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"Nonfinite/negative metadata {key}")
    return int(result) if result.is_integer() else result


def footer_categories(stats):
    output = {name: [] for name, _ in list(CATEGORIES.values())[:6]}
    for index, player in enumerate(stats):
        common = {"participant_index": index, "champion": player.get("SKIN"),
                  "source": f"footer.statsJson[{index}]", "temporal_scope": "final_metadata_only"}
        output["participants"].append({**common, "team_id": number(player, "TEAM"),
                                       "position_raw": player.get("TEAM_POSITION")})
        output["loadouts"].append({**common,
            "summoner_spell_ids": [number(player, f"SUMMONER_SPELL_{i}") for i in (1, 2)],
            "rune_ids": [number(player, f"PERK{i}") for i in range(6)],
            "stat_shard_ids": [number(player, f"STAT_PERK_{i}") for i in range(3)],
            "primary_style_id": number(player, "PERK_PRIMARY_STYLE"),
            "secondary_style_id": number(player, "PERK_SUB_STYLE"),
            "mid_match_changes_decoded": False})
        output["inventory"].append({**common,
            "slots": [{"slot": i, "item_id": number(player, f"ITEM{i}"),
                       "source_field": f"ITEM{i}"} for i in range(7)],
            "purchase_times": None})
        output["economy"].append({**common, "gold_earned": number(player, "GOLD_EARNED"),
            "gold_spent": number(player, "GOLD_SPENT"), "current_gold": None,
            "gold_timeline": None})
        output["creep_score"].append({**common, "lane_minions": number(player, "MINIONS_KILLED"),
            "neutral_minions": number(player, "NEUTRAL_MINIONS_KILLED"),
            "experience": number(player, "EXP"), "last_hit_times": None})
        fields = ("TOTAL_DAMAGE_DEALT_TO_CHAMPIONS", "PHYSICAL_DAMAGE_DEALT_TO_CHAMPIONS",
                  "MAGIC_DAMAGE_DEALT_TO_CHAMPIONS", "TRUE_DAMAGE_DEALT_TO_CHAMPIONS",
                  "TOTAL_DAMAGE_TAKEN", "TOTAL_HEAL", "TOTAL_HEAL_ON_TEAMMATES",
                  "TOTAL_DAMAGE_SHIELDED_ON_TEAMMATES")
        output["combat_totals"].append({**common, "values_by_source_field": {
            key: number(player, key) for key in fields}, "individual_damage_events": None})
    return output


def event_base(packet):
    return {"time_seconds": packet["time"], "packet": location(packet)}


def combat_events(packets, owners):
    """Preserve same-frame owner sequence; never join across chunks or times."""
    pending, kills, life_events, intervals = [], [], [], []
    open_deaths = {}
    for p in packets:
        if p["stream"] != 1 or p["channel"] != 1:
            continue
        if not math.isfinite(p["time"]) or p["time"] < 0:
            raise ValueError("Invalid packet timestamp")
        pending = [q for q in pending if q["chunk"] == p["chunk"]
                   and abs(q["time"] - p["time"]) < .001]
        if p["opcode"] == 0x3B:
            pending.append(p)
        if p["param"] not in owners:
            continue
        entity = hex(p["param"])
        if p["opcode"] == 0x28:
            if len(p["payload"]) != 5:
                raise ValueError("Unknown champion death payload shape")
            ids = [q["param"] for q in pending]
            if (not ids or ids[0] != p["param"] or len(ids) != len(set(ids))
                    or any(i not in owners for i in ids)):
                raise ValueError("Invalid death participation sequence")
            if entity in open_deaths:
                raise ValueError("Second death before a decoded respawn")
            base = event_base(p)
            kills.append({**base, "victim_entity_id": entity,
                          "killer_entity_id": hex(ids[-1]) if len(ids) > 1 else None,
                          "assist_entity_ids": [hex(i) for i in ids[1:-1]],
                          "owner_sequence": [{"entity_id": hex(q["param"]), "packet": location(q)}
                                             for q in pending],
                          "non_champion_killer_identity": None,
                          "evidence_kind": "transferred_same_build_event_grammar"})
            death = {**base, "kind": "death", "entity_id": entity}
            open_deaths[entity] = death
            life_events.append(death)
            pending = []
        elif p["opcode"] == 0x45E:
            if len(p["payload"]) != 13:
                raise ValueError("Unknown champion respawn payload shape")
            if entity not in open_deaths:
                raise ValueError("Respawn without an observed death")
            death = open_deaths.pop(entity)
            duration = p["time"] - death["time_seconds"]
            if duration <= 0:
                raise ValueError("Nonpositive death interval")
            respawn = {**event_base(p), "kind": "respawn_candidate", "entity_id": entity}
            life_events.append(respawn)
            intervals.append({"entity_id": entity, "death_seconds": death["time_seconds"],
                "respawn_seconds": p["time"], "duration_seconds": duration,
                "complete": True, "death_packet": death["packet"], "respawn_packet": respawn["packet"]})
    for entity, death in open_deaths.items():
        intervals.append({"entity_id": entity, "death_seconds": death["time_seconds"],
                          "respawn_seconds": None, "duration_seconds": None, "complete": False,
                          "death_packet": death["packet"], "respawn_packet": None})
    return kills, {"events": life_events, "intervals": sorted(intervals, key=lambda x: x["death_seconds"])}


def validate_combat(kills, lifecycle, identities, stats):
    checks = []
    if not identities:
        return checks
    for event in kills:
        victim = identities[event["victim_entity_id"]]
        killer_id = event["killer_entity_id"]
        if killer_id is not None:
            killer = identities[killer_id]
            if stats[victim]["TEAM"] == stats[killer]["TEAM"]:
                raise ValueError("Same-team kill contradicts profile")
            if any(stats[identities[a]]["TEAM"] != stats[killer]["TEAM"]
                   for a in event["assist_entity_ids"]):
                raise ValueError("Cross-team assist contradicts profile")
    for entity, index in identities.items():
        player = stats[index]
        actual = [sum(e["killer_entity_id"] == entity for e in kills),
                  sum(e["victim_entity_id"] == entity for e in kills),
                  sum(entity in e["assist_entity_ids"] for e in kills)]
        expected = [number(player, k) for k in ("CHAMPIONS_KILLED", "NUM_DEATHS", "ASSISTS")]
        takedowns = [e["time_seconds"] for e in kills if e["killer_entity_id"] == entity
                     or entity in e["assist_entity_ids"]]
        last = math.floor(takedowns[-1]) if takedowns else None
        spans = [s for s in lifecycle["intervals"] if s["entity_id"] == entity]
        dead_total = sum(s["duration_seconds"] for s in spans if s["complete"])
        expected_dead = number(player, "TOTAL_TIME_SPENT_DEAD")
        if actual != expected or math.floor(dead_total) != expected_dead:
            raise ValueError("Combat/lifecycle totals disagree with final metadata")
        if takedowns and last != number(player, "LAST_TAKEDOWN_TIME"):
            raise ValueError("Last takedown time disagrees with final metadata")
        checks.append({"entity_id": entity, "champion": player["SKIN"], "kda": actual,
                       "metadata_kda": expected, "last_takedown_floor_seconds": last,
                       "complete_dead_seconds": dead_total, "metadata_dead_seconds": expected_dead,
                       "status": "PASS", "scope": "same-file aggregate consistency"})
    return checks


def movement_records(packets, owners, decoder, inverse):
    events, snapshots, replacements, failures = [], [], [], []
    active = {}
    decoded_packets = 0
    for packet_index, p in enumerate(packets):
        if p["opcode"] != 0xC9 or p["stream"] not in (1, 2):
            continue
        try:
            decoded = decoder(p["payload"], inverse)
        except ValueError as exc:
            failures.append({**event_base(p), "reason": str(exc)})
            continue
        decoded_packets += 1
        for ordinal, record in enumerate(decoded["records"]):
            if int(record["entity_id"], 16) not in owners:
                continue
            points = record["map_waypoints_assuming_legacy_origin"]
            item = {**event_base(p), "record_id": f"{packet_index}:{ordinal}",
                    "entity_id": record["entity_id"], "speed_candidate": record["speed"],
                    "relative_waypoints": record["relative_waypoints"],
                    "map_waypoints_under_origin_hypothesis": points,
                    "kind": "path_plan" if len(points) > 1 else "single_point_candidate",
                    "flags": record["flags"], "extra_byte": record["extra_byte"],
                    "decoded_byte_range": [record["decoded_offset"], record["decoded_end"]],
                    "actual_arrival": None, "actual_traversed_path": None}
            if p["stream"] == 2:
                snapshots.append(item)
                continue
            entity = item["entity_id"]
            if len(points) > 1:
                if entity in active:
                    replacements.append({"entity_id": entity, "time_seconds": p["time"],
                        "superseded_record_id": active[entity], "new_record_id": item["record_id"],
                        "old_endpoint_arrived": None})
                active[entity] = item["record_id"]
            else:
                active.pop(entity, None)
            events.append(item)
    return {"events": events, "snapshots": snapshots, "plan_replacements": replacements,
            "decoded_packet_count_all_entities": decoded_packets, "failures": failures,
            "origin_hypothesis": [7358, 7412], "map_id": None,
            "coordinate_scope": "Legacy-origin coordinates; map mode is not established by this export."}


def build_bundle(raw, packets, decoder, inverse):
    version, metadata, stats = read_metadata(raw)
    base = analyze(raw, packets)
    if not base["identity_directory"]["same_owners_in_each_keyframe"]:
        raise ValueError("Owner directory changes require a new profile")
    owners = {int(o["entity_id"], 16) for o in base["identity_directory"]["owners"]}
    identities = {}
    if base["identity_directory"]["association"] == "known-source-only metadata mapping":
        identities = {hex(0x40000034 + i): i for i in range(len(stats))}
    kills, lifecycle = combat_events(packets, owners)
    combat_checks = validate_combat(kills, lifecycle, identities, stats)
    movement = movement_records(packets, owners, decoder, inverse)
    if movement["failures"]:
        raise ValueError(f"Movement profile failed on {len(movement['failures'])} packets")
    if base["rejected_level_packets"] or any(c["status"] == "FAIL" for c in base["level_checks"]):
        raise ValueError("Level profile has rejected or inconsistent records")
    categories = footer_categories(stats)
    categories.update(movement=movement, levels=base["level_events"], kills=kills, lifecycle=lifecycle)
    coverage = category_coverage(categories)
    return {"schema": "replay-ten/v1", "version": version, "replay_sha256": base["replay_sha256"],
            "game_length_metadata_ms": metadata.get("gameLength"), "packet_count": len(packets),
            "decision_input_eligible": False, "categories": categories, "coverage": coverage,
            "identity_directory": base["identity_directory"], "entity_to_participant": identities,
            "checks": {"combat": combat_checks, "levels": base["level_checks"]},
            "unavailable_dynamic_fields": ["current_health", "current_resource", "experience_timeline",
                "spell_cast_name_target_time", "current_gold", "inventory_timeline", "vision_state"],
            "limitations": ["Existing grammars are reused; ten outputs do not imply ten newly cracked packet families.",
                "Footer configuration is not proof it remained unchanged throughout the match.",
                "Snapshot coordinates are separate from movement events; plans are not observed arrivals.",
                "Kills/respawns/levels have bounded internal evidence, not general cross-build certification.",
                "No-events output does not prove level 1 or an initial alive state.",
                "Full replay observer data is not equivalent to what the player could see."]}


def category_coverage(categories):
    """A populated shell full of nulls is not a completed category."""
    coverage = []
    for category_id, (key, label) in CATEGORIES.items():
        value = categories[key]
        count = len(value["events"]) if key in ("movement", "lifecycle") else len(value)
        complete = count
        if category_id <= "T06":
            complete = 0
            for row in value:
                required = {
                    "participants": lambda: [row["champion"], row["team_id"]],
                    "loadouts": lambda: row["summoner_spell_ids"] + row["rune_ids"] + row["stat_shard_ids"]
                        + [row["primary_style_id"], row["secondary_style_id"]],
                    "inventory": lambda: [slot["item_id"] for slot in row["slots"]],
                    "economy": lambda: [row["gold_earned"], row["gold_spent"]],
                    "creep_score": lambda: [row["lane_minions"], row["neutral_minions"], row["experience"]],
                    "combat_totals": lambda: list(row["values_by_source_field"].values()),
                }[key]()
                complete += all(v is not None and v != "" for v in required)
        status = "available" if complete == count and count else "partial" if count else "unavailable" if category_id <= "T06" else "no_events"
        coverage.append({"id": category_id, "key": key, "label": label, "record_count": count,
                         "complete_record_count": complete, "status": status,
                         "temporal_scope": "final_metadata_only" if category_id <= "T06" else "retrospective_packet_events",
                         "semantic_scope": "direct_footer_fields" if category_id <= "T06" else "bounded_investigated_profile"})
    return coverage


def state_at(bundle, cutoff):
    """Retrospective prefix query; deliberately excludes footer and future ends."""
    if isinstance(cutoff, bool) or not isinstance(cutoff, (int, float)) or not math.isfinite(cutoff) or cutoff < 0:
        raise ValueError("Invalid cutoff")
    states = {o["entity_id"]: {"entity_id": o["entity_id"], "champion": o["champion"],
              "level_candidate": None, "last_level_update_seconds": None,
              "life_state_candidate": "unknown", "last_life_event_seconds": None,
              "kills": 0, "deaths": 0, "assists": 0, "latest_movement_candidate": None,
              "current_health": None, "current_resource": None, "current_gold": None, "inventory": None}
              for o in bundle["identity_directory"]["owners"]}
    categories = bundle["categories"]
    for event in categories["levels"]:
        if event["packet_time_seconds"] <= cutoff:
            s = states[event["entity_id"]]
            s.update(level_candidate=event["level_candidate"], last_level_update_seconds=event["packet_time_seconds"])
    for event in categories["lifecycle"]["events"]:
        if event["time_seconds"] <= cutoff:
            s = states[event["entity_id"]]
            s.update(life_state_candidate="dead" if event["kind"] == "death" else "alive_after_respawn_candidate",
                     last_life_event_seconds=event["time_seconds"])
    for event in categories["kills"]:
        if event["time_seconds"] <= cutoff:
            states[event["victim_entity_id"]]["deaths"] += 1
            if event["killer_entity_id"] is not None:
                states[event["killer_entity_id"]]["kills"] += 1
            for entity in event["assist_entity_ids"]:
                states[entity]["assists"] += 1
    for event in categories["movement"]["events"]:
        if event["time_seconds"] <= cutoff:
            states[event["entity_id"]]["latest_movement_candidate"] = event
    return {"cutoff_packet_seconds": cutoff, "decision_input_eligible": False,
            "scope": "retrospective prefix; vision filtering not implemented", "entities": list(states.values())}


def render_markdown(bundle):
    lines = ["# 回放十类信息", "", f"版本：{bundle['version']}；源 SHA256：{bundle['replay_sha256']}", "",
             "配置/结算与带时间的事件分别输出。候选字段不作为已验证的临场决策输入。", "",
             "| 编号 | 信息 | 记录数 | 时间范围 | 状态 |", "| --- | --- | ---: | --- | --- |"]
    for row in bundle["coverage"]:
        lines.append(f"| {row['id']} | {row['label']} | {row['record_count']} | {row['temporal_scope']} | {row['status']} |")
    lines += ["", "## 阵容（结算字段）", "", "| 索引 | 英雄 | 阵营 ID |", "| --- | --- | --- |"]
    for player in bundle["categories"]["participants"]:
        lines.append(f"| {player['participant_index']} | {player['champion']} | {player['team_id']} |")
    categories = bundle["categories"]
    lines += ["", "## 配置与结算数值（不能当作当时状态）", "",
              "| 英雄 | 召唤师技能 ID | 符文 ID | 结算装备槽 0–6 |", "| --- | --- | --- | --- |"]
    for loadout, inventory in zip(categories["loadouts"], categories["inventory"]):
        lines.append(f"| {loadout['champion']} | {loadout['summoner_spell_ids']} | {loadout['rune_ids']} | {[s['item_id'] for s in inventory['slots']]} |")
    lines += ["", "| 英雄 | 金币获得 / 花费 | 兵 / 野怪补刀 | 经验 | 对英雄伤害 | 承受伤害 | 治疗 |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for econ, cs, combat in zip(categories["economy"], categories["creep_score"], categories["combat_totals"]):
        v = combat["values_by_source_field"]
        lines.append(f"| {econ['champion']} | {econ['gold_earned']} / {econ['gold_spent']} | {cs['lane_minions']} / {cs['neutral_minions']} | {cs['experience']} | {v['TOTAL_DAMAGE_DEALT_TO_CHAMPIONS']} | {v['TOTAL_DAMAGE_TAKEN']} | {v['TOTAL_HEAL']} |")
    lines += ["", "## 事件示例（各取前五条，完整数据在 JSON）", ""]
    for event in bundle["categories"]["kills"][:5]:
        lines.append(f"- {event['time_seconds']:.3f}s：受害实体 {event['victim_entity_id']}，击杀实体 {event['killer_entity_id']}，助攻 {', '.join(event['assist_entity_ids']) or '无'}。")
    for event in bundle["categories"]["levels"][:5]:
        lines.append(f"- {event['packet_time_seconds']:.3f}s：{event['entity_id']} 等级候选 {event['level_candidate']}。")
    for event in bundle["categories"]["movement"]["events"][:5]:
        lines.append(f"- {event['time_seconds']:.3f}s：{event['entity_id']} {event['kind']}，移速候选 {event['speed_candidate']}，相对路径 {event['relative_waypoints']}。")
    life = bundle["categories"]["lifecycle"]
    lines += ["", f"死亡区间：完整 {sum(s['complete'] for s in life['intervals'])}，未闭合 {sum(not s['complete'] for s in life['intervals'])}。",
              "", "尚未解出的动态字段：" + "、".join(bundle["unavailable_dynamic_fields"]),
              "", "十类统计是可用输出覆盖，不是十种新破解协议。原始样本未修改。"]
    return "\n".join(lines) + "\n"
