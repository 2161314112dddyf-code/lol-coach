"""Version-matched geometry, navigation conflicts, and cross-replay spawn audit."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.http import EvidenceClient, save_json
from lol_coach.map_pipeline import load_bundle, keep
from lol_coach.wad import WadReader
from lol_coach.ngrid import parse_ngrid, render_flags_png
from lol_coach.geometry_context import extract_context, compare_navigation, compare_spawn


def verified_json(source):
    raw = (ROOT / 'data' / source['evidence_path']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != source['sha256']:
        raise ValueError('Stored evidence hash mismatch')
    return json.loads(raw)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--offline', action='store_true')
    args = p.parse_args()
    grid, manifest = load_bundle(ROOT, '16.20', 'Default')
    config = verified_json(manifest['public_config_json'])
    skin = config[manifest['selection']['object']]
    container_key = skin['mMapContainerLink']
    if container_key != 'Maps/MapGeometry/Map11/Base_SRX':
        raise ValueError('This scoped audit expects the known Base_SRX container')
    internal = 'data/maps/mapgeometry/map11/base_srx.materials.bin'
    wad = WadReader(manifest['archive']['path'])
    geometry_raw, local = wad.extract_bytes(internal)
    local.update(keep(ROOT / 'data', geometry_raw))
    client = EvidenceClient(ROOT / 'data', timeout=25)
    url = 'https://raw.communitydragon.org/16.20/game/' + internal
    binary, _ = client.fetch('spawn-geometry-bin', url, offline=args.offline)
    json_source, geometry = client.fetch('spawn-geometry-json', url + '.json', expect_json=True, offline=args.offline)
    if binary.get('sha256') != local['sha256'] or not isinstance(geometry, dict):
        raise ValueError('Versioned geometry unavailable or local/public BIN mismatch')
    context = extract_context(geometry, container_key)
    nav = compare_navigation(skin['mNavigationMesh'], context['navigation_path'])
    raw, alternate_source = wad.extract_bytes(context['navigation_path'])
    alternate_source.update(keep(ROOT / 'data', raw, '.aimesh_ngrid'))
    alternate = parse_ngrid(raw)
    if (grid.bounds_min, grid.bounds_max, grid.cell_size, grid.width, grid.height) != (alternate.bounds_min, alternate.bounds_max, alternate.cell_size, alternate.width, alternate.height):
        raise ValueError('Navigation grids have incompatible coordinate frames')
    nav.update(base_grid_sha256=grid.summary['raw_sha256'], container_grid_source=alternate_source,
               container_grid_summary=alternate.summary,
               differing_flag_cells=sum(a != b for a,b in zip(grid.flags, alternate.flags)))
    render_flags_png(alternate, ROOT / 'data/maps/16.20/Default/container_flags.png')

    respawn_key = config['Maps/Shipping/Map11/Modes/PRACTICETOOL']['DefaultRespawnPoints']
    offsets = {x['Team']:x['FirstSpawnPositionOffset'] for x in config[respawn_key]['RespawnPoints']}
    replays = []
    for stem in ('HN1-11360086609','HN1-11363048522','HN1-11363093470'):
        path = ROOT.parent / (stem + '-movement.json')
        movement_raw = path.read_bytes()
        movement = json.loads(movement_raw)
        replay = Path(movement['source'])
        digest = hashlib.sha256(replay.read_bytes()).hexdigest()
        if digest != movement['source_sha256']:
            raise ValueError('Original replay hash mismatch')
        if movement['version'] != '16.20.824.8524':
            raise ValueError('Unexpected movement source version')
        samples = []
        times = [packet['time'] for packet in movement['packets'] if packet['stream'] == 1]
        for packet in movement['packets']:
            if packet['stream'] != 1 or not 0 <= packet['time'] < 1:
                continue
            for record in packet['records']:
                if record.get('extra_byte') != 1 or record.get('flags') != 3:
                    continue
                position = record['map_waypoints_assuming_legacy_origin'][0]
                comparisons = {name:compare_spawn(position, item['position_xyz'], offsets[team])
                               for team,name in [(100,'__Spawn_T1'),(200,'__Spawn_T2')]
                               for item in [context['spawn_bases'][name]]}
                samples.append({'time_seconds':packet['time'], 'entity_id':record['entity_id'],
                                'position_candidate_xz':position, 'relative_position_candidate':record['relative_waypoints'][0],
                                'side_assignment':'not_decoded; compare both landmarks',
                                'comparisons':comparisons,
                                'skin_grid_query':grid.cell_at(*position), 'container_grid_query':alternate.cell_at(*position)})
        replays.append({'replay_path':str(replay), 'replay_sha256':digest,
                        'movement_path':str(path), 'movement_sha256':hashlib.sha256(movement_raw).hexdigest(),
                        'version':movement['version'], 'origin_hypothesis':movement['map_origin_hypothesis'],
                        'first_decoded_game_stream_time':min(times) if times else None,
                        'early_spawn_candidates':samples})
    center = [(grid.bounds_min[i] + grid.bounds_max[i]) / 2 for i in (0,2)]
    report = {'data_kind':'real_local_and_versioned_public_data_with_decoder_hypotheses',
              'geometry_evidence':{'local':local,'public_binary':binary,'public_json':json_source},
              'context':context, 'navigation_reference_audit':nav,
              'respawn_config_object':respawn_key, 'offsets_by_team':offsets,
              'replays':replays, 'origin_independently_solved':False,
              'origin_geometry_comparison': {
                  'ngrid_bounds_center_xz':center,
                  'legacy_origin_xz':[7358,7412],
                  'center_minus_legacy_origin_xz':[center[0]-7358,center[1]-7412],
                  'interpretation':'Bounds-center agreement supports origin hypothesis; packet rounding rule not verified'},
              'findings':['Two controlled replays repeat the same lower-side initial candidate',
                          'Opposite-side candidate supports regional placement, not an exact spawn-slot rule',
                          'MapSkin and MapContainer reference different actual NGRID assets'],
              'limitations':['Unknown slot/placement rules; base plus offset is only a tested hypothesis',
                             'Shared decoder/origin means repeated coordinates are not independent world-coordinate calibration',
                             'Navigation priority and active overlays remain unknown; no collision or travel-time claims']}
    save_json(ROOT / 'reports/map_context_audit.json', report)
    manifest['navigation_reference_audit'] = nav
    save_json(ROOT / 'data/maps/16.20/Default/manifest.json', manifest)
    print(json.dumps({'navigation_status':nav['status'],'differing_flag_cells':nav['differing_flag_cells'],
                      'spawn_bases':context['spawn_bases'],
                      'replays':[{ 'first_time':r['first_decoded_game_stream_time'],'candidates':len(r['early_spawn_candidates'])} for r in replays]},indent=2))


if __name__ == '__main__':
    main()
