"""Verify named Faelight geometry, ward buff lifetimes, and local sight properties."""
import argparse
from collections import Counter
from hashlib import sha256
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lol_coach.faelights_1622 import (PAD_FIELD,faelight_intervals,faelight_query,load_faelights)
from lol_coach.movement_1622 import TEN_PLAYER, reviewed_ward_sources
from lol_coach.wad import WadReader
from scripts.research_character_properties import Reader, fnv


def checked_geometry(wad, atlas):
    """Independently traverse the PROP graph and compare each runtime vertex."""
    raw,_ = wad.extract_bytes(PAD_FIELD)
    profile = json.loads((ROOT/'lol_coach/profiles/faelights_16_22.json').read_text())
    chunk = profile['chunk']
    fields = ['items','transform','name','MapGroup','Region','shapeData','Vertices','visionRegion',chunk]
    reader = Reader(raw,{fnv(name):name for name in fields})
    if reader.read(4)!=b'PROP' or reader.number('I')!=3:
        raise ValueError('Unexpected material format')
    for _ in range(reader.count('I')):
        reader.string()
    types = [reader.number('I') for _ in range(reader.count('I'))]
    items = None
    for _ in types:
        size = reader.number('I')
        end = reader.pos+size
        key,count = reader.fmt('IH')
        if key == fnv(chunk):
            items = dict(reader.fields(count)['items'])
            if reader.pos != end:
                raise ValueError('Chunk size mismatch')
            break
        reader.pos = end
    if not items:
        raise ValueError('Faelight chunk missing')
    groups = {tuple(v['transform'][12:15]):v['name'] for v in items.values() if v['__type']=='MapGroup'}
    for pad in atlas['pads']:
        source = items[pad['pad_entry']]
        center = source['transform']
        link = source['{08a3d83e}']['visionRegion']
        shape = items[link]
        matrix = shape['transform']
        vertices = shape['Region']['shapeData']['Vertices']
        if (groups[tuple(center[12:15])] != pad['name'] or link!=pad['region_entry']
                or pad['center_xz'] != [center[12],center[14]]):
            raise ValueError('Named pad or referenced region mismatch')
        expected = [[sum(coord*matrix[i*4+axis] for i,coord in enumerate((*v,1)))
                     for axis in (0,2)] for v in vertices]
        if expected != pad['polygon_xz']:
            raise ValueError('World polygon mismatch')
    return dict(material_sha256=sha256(raw).hexdigest(),pads=len(atlas['pads']),
                vertices=sum(len(p['polygon_xz']) for p in atlas['pads']))


def radii(game):
    names = {fnv(s):s for s in ('CharacterRecord','mCharacterName','perceptionBubbleRadius')}
    map_wad = WadReader(game/'DATA/FINAL/Maps/Shipping/Map11.wad.client')
    models = ['SightWard','VisionWard','JammerDevice','BlueTrinket','YellowTrinket',
              'Turret','SRUAP_Turret_Order5','SRUAP_Turret_Chaos5']
    models += [f'SRU_{team}Minion{role}' for team in ('Order','Chaos')
               for role in ('Melee','Ranged','Siege','Super')]
    champions = ['Aatrox','Jayce','TwistedFate','Caitlyn','Pantheon','Yone','MasterYi',
                 'Katarina','KogMaw','TahmKench','Lux']
    results = {}
    for model in models+champions:
        wad = WadReader(game/f'DATA/FINAL/Champions/{model}.wad.client') if model in champions else map_wad
        blob,ref = wad.extract_bytes(f'data/characters/{model}/{model}.bin')
        records = [r for r in Reader(blob,names).parse()['entries'].values()
                   if r.get('__type')=='CharacterRecord' and r.get('mCharacterName')==model]
        values = {r.get('perceptionBubbleRadius') for r in records}
        if len(values) != 1:
            raise ValueError(f'Conflicting or missing {model} character definition')
        results[model] = dict(radius=next(iter(values)),sha256=ref['sha256'],file=ref['internal_path'])
    return results


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('game_dir',type=Path)
    parser.add_argument('replays',nargs='+',type=Path)
    args=parser.parse_args()
    atlas=load_faelights(args.game_dir)
    wad=WadReader(args.game_dir/'DATA/FINAL/Maps/Shipping/Map11.wad.client')
    result=dict(geometry=checked_geometry(wad,atlas),characters=radii(args.game_dir),replays=[])
    for replay in args.replays:
        raw=replay.read_bytes()
        wards=reviewed_ward_sources(raw)
        intervals=faelight_intervals(raw,wards,atlas)
        stats=Counter('open_at_end' if r['end_seconds'] is None else
                      'early_exit' if r['end_seconds']-r['start_seconds']<44.5 else
                      'normal_exit' for r in intervals)
        row=dict(source_sha256=sha256(raw).hexdigest(),ward_count=len(wards),buff_pairs=len(intervals),
                 ends=dict(stats))
        if row['source_sha256']==TEN_PLAYER:
            scene=next(r for r in intervals if r['entity_id']==0x40008a27)
            point=[2450,7550]
            row['scenario']=dict(pad=scene['pad_name'],team_id=100,point=point,
                source_distance=math.dist(point,scene['registration_xz']),
                buff_begin=scene['start_seconds'],buff_end=scene['end_seconds'],
                expected_contributions={str(t):bool(faelight_query(intervals,100,t,point)['contributions'])
                                        for t in (949,950.5,994,996)})
        result['replays'].append(row)
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
