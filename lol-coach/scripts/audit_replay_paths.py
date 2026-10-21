"""Offline candidate-path audit for existing controlled samples; no interpolation."""
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lol_coach.http import save_json
from lol_coach.map_pipeline import load_bundle
from lol_coach.map_selection import verified_bytes,query_selected_grid
from lol_coach.ngrid import parse_ngrid,parse_overlay
from lol_coach.path_audit import audit_polyline

old,manifest=load_bundle(ROOT,'16.20','Default')
query_selected_grid(ROOT,manifest,604,612)  # Enforce reviewed selection policy.
source=manifest['navigation_reference_audit']['container_grid_source']
grid=parse_ngrid(verified_bytes(ROOT/'data',source))
overlays=[]
for o in manifest['overlays']:
    parsed=parse_overlay(verified_bytes(ROOT/'data',o['source']),grid.width,grid.height)
    overlays.append({'source':o['source'],**parsed})
reports=[]
for stem in ('HN1-11363048522','HN1-11363093470'):
    path=ROOT.parent/(stem+'-movement.json');raw=path.read_bytes();data=json.loads(raw)
    replay=Path(data['source'])
    if hashlib.sha256(replay.read_bytes()).hexdigest()!=data['source_sha256']:raise ValueError('Replay hash mismatch')
    if data['version']!='16.20.824.8524':raise ValueError('Unexpected replay version')
    rows=[]
    for packet in data['packets']:
        if packet['stream']!=1:continue
        for record in packet['records']:
            if record['entity_id']!='0x400000ae':continue
            points=record['map_waypoints_assuming_legacy_origin']
            row={'time_seconds':packet['time'],'flags':record['flags'],'extra_byte':record['extra_byte'],
                 'points_candidate_xz':points,'role':'single_packet_planned_polyline_or_start_point'}
            try:
                row['container_grid']=audit_polyline(grid,points,overlays)
                row['skin_grid_comparison']=audit_polyline(old,points)
            except ValueError as e:row['input_error']=str(e)
            rows.append(row)
    summary={'records':len(rows),'multi_point_planned_paths':sum(len(r['points_candidate_xz'])>1 for r in rows),
             'container_status_counts':dict(Counter(r.get('container_grid',{}).get('status','input_error') for r in rows)),
             'records_with_uncertain_flags':sum(bool(r.get('container_grid',{}).get('uncertain_flag_contacts')) for r in rows),
             'records_touching_overlay_regions':sum(bool(r.get('container_grid',{}).get('overlay_region_contacts')) for r in rows)}
    reports.append({'replay_path':str(replay),'replay_sha256':data['source_sha256'],
                    'movement_report_path':str(path),'movement_report_sha256':hashlib.sha256(raw).hexdigest(),
                    'entity':'0x400000ae','identity_source':'prior controlled-experiment context; not independently decoded',
                    'origin_hypothesis':data['map_origin_hypothesis'],'summary':summary,'records':rows})
report={'data_kind':'real_asset_comparison_of_unverified_decoder_candidates','patch':'16.20',
        'grid_source':source,'selection_policy':manifest['navigation_selection_policy'],
        'replays':reports,'decision_input_eligible':False,
        'limitations':['Packet waypoints are plans, not verified traversed trajectories',
                       'Successive records are not joined; discontinuities/teleports are not treated as walking',
                       'Flags use zero-radius boundary-inclusive contact; unknown bits and overlays remain unresolved',
                       'This is offline retrospective validation, not a time-t decision input'],
        'user_observation_needed_for':'actual movement/arrival, champion identity and action end state'}
save_json(ROOT/'reports/replay_path_audit.json',report)
print(json.dumps([{'replay':Path(r['replay_path']).name,**r['summary']} for r in reports],indent=2))
