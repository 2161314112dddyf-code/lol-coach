"""Source-checked additions for the actual replay lineups."""
import json
from pathlib import Path
from .mechanism_rules import build_bundle,load_spec


def build_lineup_bundle(cache_root):
    extension=json.loads((Path(__file__).with_name('profiles')/'lineup_interactions_16_20_1.json').read_text(encoding='utf8'))
    if extension['schema']!='lineup-interaction-extension/v1' or extension['patch']!='16.20.1':
        raise ValueError('Unsupported lineup extension')
    spec=load_spec()
    spec['sources'].update(extension['sources'])
    spec['interactions'].extend(extension['interactions'])
    return build_bundle(cache_root,spec)
