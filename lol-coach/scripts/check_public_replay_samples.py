"""Check two pinned HF matches through the existing model-input compiler and replay one inventory trace."""
import argparse
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.decision_contract import output_schema
from lol_coach.reasoning_frame import compile_frame, digest, model_messages
from scripts.research_inventory_time import op_states

# These exact byte ranges and the first complete JSONL row are documented in the experiment report.
EXPECTED = {
    "prefix": "d9e6cf20263a2852df338655b20cecc58f840c8c4f55ea12d5462be92a7171a0",
    "features": "3847d6be0990b556dd339ccd0cfda9ce540c0f757bc90204104bf298f83b12b9",
    "events": "cbece384fd9a6735570a35dfbe57e9d0100a9f010fa9b7a135bdf26c87f47482",
}
CASES = ("2877290_1", "2877291_1")
TEAM_FIELDS = {"hp": "health", "hp_max": "max_health", "mana": "resource",
               "mana_max": "max_resource", "level": "level"}
SELF_FIELDS = {"current_gold": "current_gold", "total_gold": "total_gold", "xp": "experience"}


def checked_bytes(path, key):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != EXPECTED[key]:
        raise ValueError(f"Unexpected {key} sample. Check revision, byte range and line endings.")
    return data


def project(arrays, meta, columns, at, team, source):
    """Conservative research projection. No enemy visibility feed or coordinate conversion is available."""
    rows = np.flatnonzero(arrays["t"] == at)
    assert len(rows) == 1
    row = rows.item()
    roster = meta["participants"]
    assert [h["participant_id"] for h in roster] == list(range(1, 11))
    actor = next(h["participant_id"] for h in roster if h["team"] == team)
    heroes, evidence = [], {}
    for pos, member in enumerate(roster):
        pid = member["participant_id"]
        entity = f"participant:{pid}"
        hero = {"entity_id": entity, "team_id": member["team"], "champion": member["champion"],
                "visibility": {"value": None}, "inventory": {}, "observed_now": {}, "private_economy": {}}
        heroes.append(hero)
        if member["team"] != team:
            continue
        fields = TEAM_FIELDS | (SELF_FIELDS if pid == actor else {})
        for col, field in fields.items():
            key = f"X_champ/{row}/{pos}/{columns.index(col)}"
            value = float(arrays["X_champ"][row, pos, columns.index(col)])
            evidence[key] = {"time_seconds": at, "entity_id": entity, "field": field}
            dest = "private_economy" if col in SELF_FIELDS else "observed_now"
            hero[dest][field] = {"value": value, "evidence_id": key, "observed_at_seconds": at}
    return {"schema": "macro-snapshot/v1", "version": meta["patch"], "source_sha256": source,
            "context": {"at_seconds": at, "observer_team_id": team, "player_entity_id": f"participant:{actor}"},
            "heroes": heroes, "evidence": evidence, "recent_public_combat": []}


def messages(snapshot):
    return model_messages(compile_frame(snapshot, max_principles=0), output_schema())


def check_team(arrays, meta, columns, team, source):
    enemies = [i for i, h in enumerate(meta["participants"]) if h["team"] != team]
    enemy_ids = {f"participant:{i + 1}" for i in enemies}
    actor = next(i for i, h in enumerate(meta["participants"]) if h["team"] == team)
    results = []
    for at in (600, 601):
        snap = project(arrays, meta, columns, at, team, source)
        original = messages(snap)
        frame = json.loads(original[1]["content"])["decision_frame"]
        facts = list(frame["facts"].values())
        assert all(f["observed_at_seconds"] <= at for f in facts)
        assert all(f["field"] in {"identity", "visibility"} for f in facts if f["entity_id"] in enemy_ids)
        assert all(f["value"] is None for f in facts if f["entity_id"] in enemy_ids and f["field"] == "visibility")
        assert all(f["entity_id"] == frame["decision"]["player_entity_id"] for f in facts if f["field"] in SELF_FIELDS.values())
        row = np.flatnonzero(arrays["t"] == at).item()
        hp = arrays["X_champ"][row, actor, columns.index("hp")].item()
        own_hp = next(f for f in facts if f["entity_id"] == f"participant:{actor + 1}" and f["field"] == "health")
        assert hp == own_hp["value"]
        # Perturb raw inputs upstream, then rebuild the full model messages from scratch.
        changed = dict(arrays, X_champ=arrays["X_champ"].copy())
        changed["X_champ"][row+1:] = -111
        assert messages(project(changed, meta, columns, at, team, source)) == original
        changed["X_champ"][row, enemies] = -222
        modified_meta = dict(meta, winning_team=-333, label=-333, duration_s=-333)
        for key in ("y", "wards", "X_items", "X_item_cd", "X_team", "X_global", "X_champ_kda"):
            changed[key] = None
        assert messages(project(changed, modified_meta, columns, at, team, source)) == original
        changed["X_champ"][row, actor, columns.index("hp")] += 1
        assert messages(project(changed, modified_meta, columns, at, team, source)) != original
        late = deepcopy(snap)
        first = next(iter(late["evidence"].values()))
        first["available_at_seconds"] = at + 1
        try:
            messages(late)
        except ValueError as exc:
            assert "not available" in str(exc)
        else:
            raise AssertionError("Compiler accepted future availability")
        results.append({"at": at, "facts": len(facts), "frame_id": frame["frame_id"],
                        "messages_sha256": digest(original), "own_hp": hp,
                        "owned_item_columns_in_source": int(arrays["X_items"].shape[-1]),
                        "decision_inventory": frame["unknowns"]["current_inventory"],
                        "decision_cooldowns": frame["unknowns"]["current_cooldowns"]})
    return results


def check_state(prefix, features):
    results = {}
    with tarfile.open(fileobj=io.BytesIO(prefix)) as archive:
        # The tar is intentionally partial. Only request complete members in stream order.
        for case in CASES:
            members = {}
            while len(members) < 2:
                member = archive.next()
                if member is None:
                    raise ValueError("Missing sample in tar prefix")
                if member.name in (case + "/meta.json", case + "/sequence.npz"):
                    members[Path(member.name).name] = archive.extractfile(member).read()
            meta = json.loads(members["meta.json"])
            source = hashlib.sha256(members["sequence.npz"]).hexdigest()
            with np.load(io.BytesIO(members["sequence.npz"]), allow_pickle=False) as archive_arrays:
                arrays = dict(archive_arrays)
            results[case] = {"build": meta["patch"], "samples": len(arrays["t"]), "npz_sha256": source,
                             "teams": {team: check_team(arrays, meta, features["X_champ"], team, source)
                                       for team in (100, 200)}}
    return results


def check_inventory(data):
    events = json.loads(data)["events"]
    actions, cooldowns, casts = [], {}, {}
    for index, event in enumerate(events):
        kind, row = next(iter(event.items()))
        if kind in {"BuyItem", "SwapItem", "UseItem", "RemoveItem"} and row["net_id"] == 1073741854 and row["time"] <= 19:
            actions.append((row["time"], index, kind, row))
        if row.get("time") == 300.0995 and row.get("slot") == 0:
            if kind == "CastSpellAns" and row["spell_name"] == "RocketGrab":
                casts[row["caster_net_id"]] = row["cooldown"]
            if kind == "DoSetCooldown":
                cooldowns[row["net_id"]] = row["cooldown"]
    actions.sort()
    assert [op[2] for op in actions] == ["BuyItem"] * 3 + ["SwapItem"]
    normalized = []
    for time, index, kind, row in actions:
        # The checkpoint utility uses this pair to order ties. Here the source is JSONL row 0.
        op = {"entity_id": row["net_id"], "time_seconds": time,
              "source": {"chunk": 0, "decompressed_offset": index}}
        if kind == "BuyItem":
            op.update(kind="slot_update", slot=row["slot"], item_id=row["item_id"])
        else:
            op.update(kind="slot_swap", slot=row["source_slot"], other_slot=row["target_slot"])
        normalized.append(op)
    actor = normalized[0]["entity_id"]
    timeline = op_states(normalized)[actor]
    before, slots = timeline[-2][1], timeline[-1][1]
    assert before == {0: 1054, 1: 2003, 6: 3340} and slots == {0: 2003, 1: 1054, 6: 3340}
    assert op_states(normalized[:-1])[actor][-1][1] == before
    assert len(casts) == 1
    entity, cast_cd = next(iter(casts.items()))
    assert cast_cd > 0 and cooldowns[entity] == 0
    return {"events": len(events), "source_rows_zero_based": [x[1] for x in actions],
            "before": before, "after": slots, "rocketgrab_same_time_fields": [cast_cd, cooldowns[entity]]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in EXPECTED:
        parser.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    if not __debug__:
        raise RuntimeError("Run without -O so that sample checks are enabled.")
    state = check_state(checked_bytes(args.prefix, "prefix"), json.loads(checked_bytes(args.features, "features")))
    inventory = check_inventory(checked_bytes(args.events, "events"))
    print(json.dumps({"state": state, "inventory": inventory}, indent=2))
