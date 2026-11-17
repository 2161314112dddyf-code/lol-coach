"""Join reviewed native HUD ring measurements to their original player-issued packets."""
import hashlib
import json
from math import isfinite
from pathlib import Path

from .movement_1622 import RED_JUNGLE_REPLAY


PRIVATE = Path(__file__).resolve().parents[1] / 'data/private'
# Pin the measured report itself. An absent private capture leaves the wire reader usable.
REVIEWED = {
    RED_JUNGLE_REPLAY: ('ping-landmark-20261116/personal/mapped-markers.json',
                        'a46091bc6f2a853f1b84fe920f2f7f18cdccefccb6cb7982d36d9d126d4eaf23')
}
LANDMARKS = {'Turret_TChaos_L0_P3_511845594_0': '红方下路外塔', 'Dragon': '小龙出生点'}


def marker_observations(replay_sha256, build):
    binding = REVIEWED.get(replay_sha256)
    if not binding:
        return {}, None
    path, expected_hash = binding
    file = PRIVATE / path
    if not file.is_file():
        return {}, None
    raw = file.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise ValueError('reviewed_ping_hud_report_changed')
    report = json.loads(raw)
    if (report['replay_sha256'], report['build'], report['map_id']) != (replay_sha256, build, 11):
        raise ValueError('ping_hud_report_scope_mismatch')
    result = {}
    for row in report['rows']:
        key = row['source']['chunk'], row['source']['offset']
        if key in result:
            raise ValueError('duplicate_ping_hud_source')
        result[key] = row
    return result, expected_hash


def verified_region(event, packet, row):
    if (row['source'] != event['source'] or row['wire'] != packet['payload'][2:10].hex()
            or (row['t'], row['team_id'], row['sender'], row['kind']) !=
               (event['time_seconds'], event['team_id'], event['sender_champion'], event['kind'])):
        raise ValueError('ping_hud_packet_mismatch')
    end = row['observed_through']
    x, z = row['hud_estimate_world_xz']
    if (not isfinite(end) or end < row['t'] or not all(isfinite(v) and 0 <= v <= 15000 for v in (x, z))
            or row['exact_packet_marker_xz'] is not None):
        raise ValueError('invalid_ping_hud_measurement')
    region = dict(basis='native_hud_ring_estimate', map_id=11, observed_through_seconds=end,
                  xz_rounded_to_100=[round(v/100)*100 for v in (x,z)])
    landmark = row.get('landmark')
    if landmark and landmark['name'] in LANDMARKS:
        rx, rz = landmark['xz']
        dx, dz = x-rx, z-rz
        north_south = '北' if dz > 0 else '南'
        east_west = '东' if dx > 0 else '西'
        direction = (east_west if abs(dx) > .41*abs(dz) else '') + (north_south if abs(dz) > .41*abs(dx) else '')
        distance = round(landmark['distance_world']/100)*100
        region['description'] = f'{LANDMARKS[landmark["name"]]}{direction}约{distance}地图单位'
    return region
