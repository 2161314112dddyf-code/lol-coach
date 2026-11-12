import json
from pathlib import Path

from lol_coach import map11_tower_anchors
from lol_coach.ngrid import Grid
from lol_coach.ward_coverage import ward_contributions
from lol_coach.hero_sight import visible_path_starts
from lol_coach.region_vision import visibility_query
from lol_coach.region_vision import allied_ward_positions


def test_only_current_allied_sources_contribute_without_granting_team_visibility():
    grid = Grid((0, 0, 0), (100, 10, 100), 10, 10, 10, (0,) * 100, {})
    ward = dict(entity_id=71, team_id=100, item_id=3340, start_seconds=2, end_seconds=10,
                start_source={}, positions=[dict(time_seconds=3, world_xz=[25, 25], source={})])
    def query(team, at, overlays=(), wards=(ward,)):
        return ward_contributions(wards, team, at, [55, 25], [grid, grid], overlays)
    assert not query(200, 5)['contributions']
    assert not query(100, 2.5)['contributions']
    assert not query(100, 10)['contributions']
    assert query(100, 5)['observed_team_ground_visibility'] is None
    assert query(100, 5)['contributions'][0]['estimate'] == 'clear'
    assert query(100, 5, [(3,2,4,3)])['contributions'][0]['estimate'] == 'indeterminate'
    family = dict(ward, item_id=None, family='sight_ward')
    assert query(100, 5, wards=[family])['contributions'][0]['radius_basis'].startswith('conditional')
    far = dict(ward, family='farsight_ward', item_id=None, end_seconds=None)
    assert query(100, 5, wards=[far])['contributions'][0]['radius_units'] == 500
    assert not query(100, 5, wards=[dict(ward, item_id=123)])['contributions']


def test_tower_name_requires_exact_keyframe_layout_and_tracks_first_known_time(monkeypatch):
    profile = json.loads((Path(map11_tower_anchors.__file__).with_name('profiles')
                          / 'turret_map11_16_22.json').read_bytes())
    tower = profile['towers'][0]
    sig = next(bytes.fromhex(s) for s in tower['wire_names'] if s.startswith('5d'))
    code = 0x11 if len(sig) == 32 else 0x12
    def packet(entity, at, body, stream=2):
        return dict(param=entity, time=at, opcode=0x402, chunk=1, offset=0, payload=body, stream=stream)
    body = bytes([0,0,0,code]) + sig + b'\x10'
    rows = [packet(1, 60, body), packet(1, 0, body), packet(2, 1, body, 1),
            packet(3, 1, body[:-1]+b'\x00'), packet(4, 1, bytes(4)+body[4:]), packet(5, 1, b'')]
    monkeypatch.setattr(map11_tower_anchors, 'packets', lambda raw: rows)
    result = map11_tower_anchors.tower_landmarks(b'', profile['version'])
    assert list(result) == [1]
    assert result[1]['available_at_seconds'] == 0
    assert result[1]['map_reference_xz'] == tower['xz']


def test_last_seen_uses_only_opposing_team_visible_path_starts_and_freezes_in_fog():
    def event(t, state, offset, observer=200):
        return dict(subject="entity:0x42", mode="transition", team_id=observer, time_seconds=t, visible=state,
                    source=dict(kind="rofl_packet", opcode="0x4d5" if state else "0x35b", chunk=1, offset=offset))
    def path(t, offset, x):
        return dict(entity_id=0x42, time_seconds=t, world_waypoints_xz=[[x, 900], [99999, 99999]],
                    source=dict(opcode="0x482", chunk=1, offset=offset))
    events = [event(1, True, 10), event(2, False, 30), event(3, True, 50, observer=100),
              event(6, True, 80)]
    samples = [path(1, 9, 10), path(1.5, 20, 20), path(2, 28, 30), path(4, 60, 40), path(7, 90, 50)]
    seen = visible_path_starts(samples, {0x42:{"team_id":100}}, events)
    assert [(r["time_seconds"],r["xz"]) for r in seen] == [(1.5,[20,900]), (7,[50,900])]
    index = dict(observations=events, end_seconds=20, enemy_positions_in_view=seen)
    result = visibility_query([index], 200, 'entity:0x42', 5)
    assert result['visible'] is False
    assert result['last_observed_position']['xz'] == [20,900]
    assert result['last_observed_position']['age_seconds'] == 3.5
    assert 'last_observed_position' not in visibility_query([index], 100, 'entity:0x42', 5)


def test_no_future_ward_location_removal_or_opponent_eye_in_decision():
    ward = dict(entity_id=6, team_id=100, family='sight_ward', start_seconds=2, end_seconds=4,
                positions=[dict(time_seconds=3,world_xz=[80,80],source={})],
                spatial_record=dict(time_seconds=2,center_xz=[60,60],source={}), placement_source={})
    index = dict(end_seconds=10, ward_placements=[ward, dict(ward, entity_id=7, team_id=200)])
    assert not allied_ward_positions([index], 100, 1)
    observed, = allied_ward_positions([index], 100, 2)
    assert observed['xz'] == [60,60] and observed['subject'] == 'entity:0x6'
    assert 'end_seconds' not in observed
    assert not allied_ward_positions([index], 100, 4)
    stale = dict(end_seconds=3, ward_placements=[dict(ward, end_seconds=None)])
    assert not allied_ward_positions([index,stale], 100, 4)
    assert not allied_ward_positions([index,dict(stale,end_seconds=10)], 100, 4)
