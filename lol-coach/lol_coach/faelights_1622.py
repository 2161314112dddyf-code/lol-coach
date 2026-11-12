"""Build-matched Faelight polygons and replay-native ward bonus lifetimes."""
from collections import defaultdict
from hashlib import sha256
from importlib.resources import files
import json
import math
import struct

from .movement_1622 import PANTHEON, TEN_PLAYER, _ref
from .replay_container import packets
from .vision_regions_1622 import ward_region_observations
from .wad import WadReader

PAD_FIELD = 'data/maps/mapgeometry/map11/base_srx.materials.bin'
BUFFS = (bytes.fromhex('0d1f00d1affc6250'),bytes.fromhex('2d532212d1affc6250'))
BONUS_OFF = bytes.fromhex('991b47')


def load_faelights(game_dir):
    """Read the named pad/visionRegion transforms and referenced shape vertices."""
    archive = WadReader(game_dir/'DATA/FINAL/Maps/Shipping/Map11.wad.client')
    blob, ref = archive.extract_bytes(PAD_FIELD)
    profile = json.loads(files('lol_coach').joinpath('profiles/faelights_16_22.json').read_bytes())
    if sha256(blob).hexdigest() != profile['material_sha256']:
        raise ValueError('Faelight material differs from the reviewed 16.22 Map11 asset')
    pads = []
    for item in profile['pads']:
        center = struct.unpack_from('<16f',blob,item['pad_transform'])
        transform = struct.unpack_from('<16f',blob,item['region_transform'])
        polygon = []
        for i in range(item['vertex_count']):
            x,y,z = struct.unpack_from('<3f',blob,item['vertices_offset']+12*i)
            polygon.append([x*transform[0]+y*transform[4]+z*transform[8]+transform[12],
                            x*transform[2]+y*transform[6]+z*transform[10]+transform[14]])
        pads.append(dict(name=item['name'],center_xz=[center[12],center[14]],polygon_xz=polygon,
                         pad_entry=item['pad_entry'],region_entry=item['region_entry']))
    return dict(source=ref,pads=pads)


def faelight_intervals(raw, wards, atlas):
    """Bind both native same-ward buffs to the uniquely nearest named pad.

    Proximity alone cannot activate a pad. The ward region is explicitly
    registered at placement, even when the first movement observation is later.
    """
    digest = sha256(raw).hexdigest()
    if digest not in (PANTHEON,TEN_PLAYER):
        raise ValueError('Unsupported Faelight replay')
    if not wards:
        return []
    regions = {w['entity_id']:w['spatial_record'] for w in wards if w.get('spatial_record')}
    if any(w['entity_id'] not in regions for w in wards):
        regions = {r['entity_id']:r for r in ward_region_observations(raw,wards)}
    by_id = {w['entity_id']:w for w in wards}
    adds, removals = defaultdict(dict), defaultdict(list)
    for p in packets(raw):
        w = by_id.get(p['param'])
        if p['stream'] != 1 or not w:
            continue
        if p['opcode'] == 0x22b and p['time'] == w['start_seconds']:
            for tail in BUFFS:
                if p['payload'].endswith(tail):
                    adds[p['param']][tail] = p
        if p['opcode'] == 0x2b3 and p['payload'].endswith(BONUS_OFF):
            removals[p['param']].append(p)
    rows = []
    for entity, anchors in adds.items():
        if len(anchors) != 2 or entity not in regions:
            continue
        w, region = by_id[entity], regions[entity]
        distances = sorted((math.dist(region['center_xz'],pad['center_xz']),i)
                           for i,pad in enumerate(atlas['pads']))
        distance, index = distances[0]
        # The positive activations are well separated from competing pads.
        if distance > 200 or distances[1][0] < distance+500:
            continue
        pad = atlas['pads'][index]
        ends = [p for p in removals[entity] if p['time'] >= w['start_seconds']]
        if len(ends) > 1:
            raise ValueError('Unexpected repeat of Faelight bonus expiry')
        off = ends[0] if ends else None
        candidates = [(off['time'],_ref(off))] if off else []
        if w['end_seconds'] is not None:
            candidates.append((w['end_seconds'],w['end_source']))
        end_time,end_source = min(candidates,key=lambda r:r[0]) if candidates else (None,None)
        rows.append(dict(entity_id=entity,team_id=w['team_id'],pad_name=pad['name'],
            center_xz=pad['center_xz'],registration_xz=region['center_xz'],
            distance_from_pad=distance,polygon_xz=pad['polygon_xz'],
            start_seconds=w['start_seconds'],end_seconds=end_time,
            start_sources=[_ref(anchors[key]) for key in BUFFS], end_source=end_source,
            region_source=region['source'],asset_source=atlas['source'],
            region_entry=pad['region_entry'],replay_sha256=digest))
    return sorted(rows,key=lambda row:row['start_seconds'])


def inside_polygon(polygon,point):
    """Return True for the interior, False for the exterior and None for an edge."""
    x,z = point
    inside = False
    for i, (ax,az) in enumerate(polygon):
        bx,bz = polygon[i-1]
        cross = (x-ax)*(bz-az)-(z-az)*(bx-ax)
        if abs(cross)<1e-7 and min(ax,bx)<=x<=max(ax,bx) and min(az,bz)<=z<=max(az,bz):
            return None
        if (az>z)!=(bz>z) and x < ax+(z-az)*(bx-ax)/(bz-az):
            inside = not inside
    return inside


def faelight_query(intervals, team, at, world_xz):
    if (team not in (100,200) or not math.isfinite(at) or at<0
            or len(world_xz)!=2 or not all(math.isfinite(x) for x in world_xz)):
        raise ValueError('Invalid Faelight query')
    contributions = []
    for row in intervals:
        if row['team_id'] != team or at < row['start_seconds']:
            continue
        if row['end_seconds'] is not None and at>=row['end_seconds']:
            continue
        if at >= row['start_seconds']+45:
            continue
        if inside_polygon(row['polygon_xz'],world_xz) is not True:
            continue
        contributions.append({k:row[k] for k in ('entity_id','pad_name','start_seconds','start_sources',
                                                  'region_source','region_entry','asset_source')})
    return dict(estimated_visible=True if contributions else None,observed_team_visibility=None,
                basis='ward_bonus_buff_and_map_polygon', contributions=contributions,
                assumes_ward_not_nearsighted=True)
