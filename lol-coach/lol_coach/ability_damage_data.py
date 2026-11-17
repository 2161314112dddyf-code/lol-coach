"""Exact-build, pre-mitigation champion ability formulas for standard Summoner's Rift."""
from copy import deepcopy
from functools import lru_cache
import json
import math
from pathlib import Path
import re


PROFILE = Path(__file__).with_name('profiles') / 'pantheon_ability_damage_16_22.json'


@lru_cache(maxsize=64)
def _catalog(path, modified, size):
    return json.loads(path.read_bytes())


def damage_profile(build, champion, slot):
    """Return an independently editable description only for a supported exact build."""
    if (not isinstance(build, str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+){3}', build)
            or not isinstance(champion, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9]*', champion)):
        return None
    path = PROFILE.with_name(f"{champion.lower()}_ability_damage_{build.replace('.', '_')}.json")
    if not path.is_file():
        if (build, champion) != ('16.22.836.1077', 'Pantheon'):
            return None
        path = PROFILE
    stamp = path.stat()
    data = _catalog(path, stamp.st_mtime_ns, stamp.st_size)
    if (build, champion) != (data['build'], data['champion']):
        raise ValueError('ability damage archive mismatches its champion or exact build')
    if slot not in data['abilities']:
        return None
    return deepcopy(dict(build=build, champion=champion, slot=slot, source=data['source'],
                         scope=data['scope'], **data['abilities'][slot]))


def raw_component(profile, component, ranks, stats, *, low_health=False):
    """Evaluate one explicitly selected hit. Unknown inputs never become zero."""
    part = profile['components'][component]
    if low_health:
        part = {**part, **part['low_health']}
    rank_slot = part['rank_slot']
    rank = ranks.get(rank_slot)
    missing = []
    if part.get('requires_zero_ap') and stats.get('ap') != 0:
        missing.append('ap' if stats.get('ap') is None else 'unverified_low_health_throw_ap_ratio')
    if rank is None:
        missing.append('rank_' + rank_slot)
    elif type(rank) is not int or not 1 <= rank <= len(part['base_by_rank']):
        raise ValueError(f'unsupported rank for {rank_slot}')
    required = list(part['coefficients'])
    if 'multiply_by' in part:
        required.append(part['multiply_by'])
    for stat in required:
        value = stats.get(stat)
        if value is None:
            missing.append(stat)
        elif type(value) not in (float, int) or not math.isfinite(value):
            raise ValueError(f'invalid numeric input for {stat}')
    raw = None
    if not missing:
        raw = part['base_by_rank'][rank-1] + sum(coef * stats[stat] for stat,coef in part['coefficients'].items())
        if 'multiply_by' in part:
            raw *= stats[part['multiply_by']]
        if not math.isfinite(raw) or raw < 0:
            raise ValueError('invalid raw damage result')
    return dict(label=part['label'], damage_type=part['damage_type'], raw_damage=raw, missing=missing)
