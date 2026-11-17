"""Match installed Map11 background variants to the native minimap at a decision cutoff."""
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
import xxhash

from .minimap_assets import MAP_CONFIG, _read_config, _texture_bytes, decode_base_minimap
from .wad import WadReader


def norm_color(rgb):
    return rgb / np.maximum(1, rgb.sum(axis=2, keepdims=True))


def select_variant(rgb, candidates):
    """Rank wall silhouettes first, then compare color only where finalists differ."""
    wall = (rgb.max(axis=2) < 23).astype(float)
    target = norm_color(rgb)
    shape = (rgb.shape[1], rgb.shape[0])
    yy, xx = np.indices(rgb.shape[:2])
    interior = (xx >= 18) & (xx < shape[0]-18) & (yy >= 18) & (yy < shape[1]-18)
    walls, colors = {}, {}
    for key, image in candidates.items():
        a = np.asarray(image).astype('float32')
        alpha = a[:,:,3]/255.
        walls[key] = cv2.resize(1-alpha,shape,interpolation=cv2.INTER_AREA)
        colors[key] = norm_color(cv2.resize(a[:,:,:3]*alpha[:,:,None],shape,interpolation=cv2.INTER_AREA))
    variable = (np.std(np.stack(list(walls.values())),axis=0)>.1) & interior
    if variable.sum()<200:
        raise ValueError('insufficient_distinct_terrain_silhouettes')
    scores = {k:float(np.corrcoef(wall[variable], a[variable])[0,1]) for k,a in walls.items()}
    best = max(scores.values())
    finalists = [k for k,v in scores.items() if best-v<.04]
    if not np.isfinite(best) or best < .60:
        raise ValueError('unsupported_minimap_wall_match')
    contests = []
    winners = []
    for k in finalists:
        wins = 0
        for other in finalists:
            if k == other:
                continue
            diff = np.linalg.norm(colors[k]-colors[other],axis=2)
            selected = ((diff>.035) & (rgb.sum(axis=2)>60) & (xx>8) & (xx<shape[0]-9)
                        & (yy>8) & (yy<shape[1]-8))
            nearer = (np.linalg.norm(target-colors[k],axis=2)<np.linalg.norm(target-colors[other],axis=2))
            # Require spatial replication; a nearby champion icon or single HUD cell can't select the texture.
            halves=[selected & (yy < shape[1]//2),selected & (yy >= shape[1]//2)]
            fractions=[float(nearer[h].mean()) if h.any() else 0 for h in halves]
            supported = all(h.sum()>=35 for h in halves) and min(fractions)>.56
            wins += int(supported)
            contests.append(dict(candidate=k,against=other,counts=[int(h.sum()) for h in halves],
                                  fractions=[round(v,3) for v in fractions]))
        if wins == len(finalists)-1:
            winners.append(k)
    if len(winners)!=1:
        raise ValueError('ambiguous_minimap_terrain_color')
    return winners[0],dict(wall_pixel_count=int(variable.sum()),wall_scores=scores,finalists=finalists,
                            spatial_color_comparisons=contests)


def verify_terrain(bundle, assets, game_dir, clip):
    frame = bundle['frame']
    origin, decision = frame['task']['review_origin'],frame['decision']
    at = decision['at_seconds']
    receipt = json.loads((clip/'receipt.json').read_bytes())
    if (receipt['source_replay_sha256']!=origin['replay_sha256'] or receipt['build']!=assets['build']
            or receipt['match'].rsplit('-',1)[-1]!=str(origin['match_id']) or not receipt['start']<=at<=receipt['end']):
        raise ValueError('terrain_hud_source_or_time_mismatch')
    wad = WadReader(game_dir/'DATA/FINAL/Maps/Shipping/Map11.wad.client')
    cfg, ref = wad.extract_bytes(MAP_CONFIG)
    if ref['sha256'] != assets['config_sha256'] or hashlib.sha256(wad.index_bytes).hexdigest()!=assets['wad_index_sha256']:
        raise ValueError('terrain_archive_source_mismatch')
    keys = _read_config(cfg,assets['skin'],variant_hashes=True)
    if len(keys)!=15 or assets['world_extent']!=[0,0,14850,14850]:
        raise ValueError('unsupported_minimap_variant_set')
    candidates={f'{k:016x}':decode_base_minimap(_texture_bytes(wad,k)) for k in keys}
    crops, refs = [], []
    for name, expected in sorted(receipt['frames'].items()):
        t = receipt['start'] + int(Path(name).stem)/receipt['fps']
        if not at-4<=t<=at:
            continue
        if Path(name).name!=name or not name.endswith('.png'):
            raise ValueError('invalid_terrain_frame_name')
        img=clip/name
        if hashlib.sha256(img.read_bytes()).hexdigest()!=expected:
            raise ValueError('terrain_hud_frame_hash_mismatch')
        with Image.open(img) as im:
            if im.size!=(1280,720):
                raise ValueError('terrain_hud_layout_mismatch')
            crops.append(np.asarray(im.convert('RGB').crop((1103,541,1272,711))))
        refs.append(dict(time=t,sha256=expected,file=name))
    if len(crops)<8 or at-refs[-1]['time']>1.01/receipt['fps']:
        raise ValueError('insufficient_native_frames_before_cutoff')
    choices=[]
    for images in (crops[::2],crops[1::2]):
        choices.append(select_variant(np.median(images,axis=0),candidates))
    key, stats=choices[0]
    if choices[1][0]!=key:
        raise ValueError('inconsistent_minimap_terrain_across_frames')
    names=[f'assets/maps/info/map11/2dlevelminimap_{skin}_baron{i}.tex'
           for skin in ('base','mountain','ocean','cloud','hextech') for i in (1,2,3)]
    name,=[s for s in names if f'{xxhash.xxh64_intdigest(s.encode()):016x}'==key]
    proof=dict(schema='native-minimap-variant/v1',source_sha256=origin['replay_sha256'],at=at,
               build=assets['build'],frame_id=frame['frame_id'],texture_key=key,texture_path=name,
               skin=assets['skin'],hud_roi=[1103,541,1272,711],native_frames=refs,
               candidate_count=len(candidates),odd_frames=stats,even_frames=choices[1][1],
               usage='Static map art selection only. No spectator object coordinates enter the personal projection.')
    return candidates[key],proof
