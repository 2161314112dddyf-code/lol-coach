"""Frozen, build-specific rune rules used for champion damage in classic Summoner's Rift."""
import json
from pathlib import Path
import re


BUILD = '16.22.836.1077'
PROFILE = Path(__file__).with_name('profiles') / 'rune_damage_16_22.json'


def rune_damage_profile(build):
    if not isinstance(build, str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+){3}', build):
        return None
    path = PROFILE.with_name(f"rune_damage_{build.replace('.', '_')}.json")
    if not path.is_file():
        if build != BUILD:
            return None
        path = PROFILE
    data = json.loads(path.read_bytes())
    if (data.get('schema'), data.get('build')) != ('rune-damage-rules/v1', build):
        raise ValueError('invalid rune damage archive')
    if not data.get('rules') or not isinstance(data['rules'], dict) or not data.get('sources'):
        raise ValueError('rune damage archive needs rules and source evidence')
    return data
