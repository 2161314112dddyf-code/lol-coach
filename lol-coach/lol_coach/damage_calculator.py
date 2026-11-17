"""Compute the resistance stage of damage, given raw amounts for specified hits.

Signed armor and MR curves use archived mechanics references. Effective
resistances are inputs, independent of how items, buffs or penetration were established.
"""
from math import fsum, isfinite


FORMULA_SOURCE = "https://wiki.leagueoflegends.com/en-us/Armor"
TRUE_DAMAGE_SOURCE = "https://journals.le.ac.uk/index.php/jist/article/download/744/696/1519"
SOURCE_DIGESTS = {
    FORMULA_SOURCE: "5d659bf6d94f4e61905f959304ca18394903d4284a9222f7a1abbf8c4318ce7c",
    "https://wiki.leagueoflegends.com/en-us/Magic_resistance":
        "aa5c52f7f57e1dd9e27d418d5aeead67f3ffd6e56b3787c40243e1b34a25f4c5",
    TRUE_DAMAGE_SOURCE: "bb9b5ec0eb73bf3a36c05cbb3a04c351dc8a9f3f80b614581432eb333804b0c4",
}
RESISTANCE_FIELD = {"physical": "effective_armor", "magic": "effective_magic_resist", "true": None}


def _finite(value, field):
    if value is None:
        return None
    if type(value) not in (int, float):
        raise ValueError(f"{field} must be a finite number or null")
    try:
        valid = isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"{field} must be finite")
    return float(value)


def _multiplier(resistance):
    if resistance >= 0:
        return 100 / (100 + resistance)
    return 2 - 100 / (100 - resistance)


def _total(values):
    if any(value is None for value in values):
        return None
    try:
        return fsum(values)
    except OverflowError as exc:
        raise ValueError("damage total exceeds numeric range") from exc


def calculate_damage(parts, *, effective_armor=None, effective_magic_resist=None, pre_hit_resistances=None):
    """Apply one target's effective resistances to components for one hit scenario.

    For mixed combos include only distinct hits that coexist in the chosen
    scenario. Named per-hit resistances override the shared baseline. Make
    separate calls for mutually exclusive hit zones. A missing input is null.
    Zero resistance is a valid explicit input, never the default.
    """
    resistances = {"effective_armor": _finite(effective_armor, "effective_armor"),
                   "effective_magic_resist": _finite(effective_magic_resist, "effective_magic_resist")}
    if not isinstance(parts, (list, tuple)) or not parts:
        raise ValueError("at least one damage part is required")
    overrides = {} if pre_hit_resistances is None else pre_hit_resistances
    if not isinstance(overrides, dict):
        raise ValueError("pre_hit_resistances must be keyed by damage label")
    rows = []
    for part in parts:
        if not isinstance(part, dict) or set(part) != {"label", "damage_type", "raw_damage"}:
            raise ValueError("each damage part requires label, damage_type and raw_damage")
        label, kind = part["label"], part["damage_type"]
        if not isinstance(label, str) or not label.strip():
            raise ValueError("a damage part must have a label")
        if not isinstance(kind, str) or kind not in RESISTANCE_FIELD:
            raise ValueError("unknown damage type")
        raw = _finite(part["raw_damage"], "raw_damage")
        if raw is not None and raw < 0:
            raise ValueError("raw damage cannot be negative")
        field = RESISTANCE_FIELD[kind]
        local = overrides.get(label, {})
        if not isinstance(local, dict) or not local.keys() <= resistances.keys():
            raise ValueError("invalid per-hit resistance record")
        current = {**resistances, **{key: _finite(v, key) for key,v in local.items()}}
        multiplier = 1.0
        if field is not None:
            resistance = current[field]
            multiplier = None if resistance is None else _multiplier(resistance)
        missing = []
        if raw is None:
            missing.append("raw_damage")
        if multiplier is None and raw != 0:
            missing.append(field)
        after = None
        if not missing:
            after = 0.0 if raw == 0 else _finite(raw * multiplier, "after_resistance")
        rows.append(dict(label=label, damage_type=kind, raw_damage=raw, multiplier=multiplier,
                         effective_resistance=current[field] if field else None, after_resistance=after, missing=missing))
    if overrides.keys() - {row['label'] for row in rows}:
        raise ValueError("per-hit resistance supplied outside the specified damage parts")
    return dict(parts=rows, raw_total=_total([r["raw_damage"] for r in rows]),
                after_resistance_total=_total([r["after_resistance"] for r in rows]),
                effective_resistances=resistances,
                formula_source=FORMULA_SOURCE, true_damage_source=TRUE_DAMAGE_SOURCE,
                source_sha256=dict(SOURCE_DIGESTS),
                scope="假设列出的各段均命中同一目标，逐段按给定有效护甲或魔抗结算。"
                      "有效抗性须已计入适用穿透与削减。护盾、格挡、额外增减伤、触发效果和实际扣血另核。")
