"""Synthetic log/track cases; no game observations are generated here."""
import copy
import math
import pytest

from lol_coach.calibration import parse_session_log, bind_bundle, inspect_track
from lol_coach.ngrid import Grid

LOG = '''Command Line: secret-example-not-for-retention
Build Version: Version 16.20.824.8524
GameStartData::GameID=123
GameStartInfo GPP match Id = abc-123, mapskin = Default
'''


def test_allowlist_and_unknowns():
    row = parse_session_log(LOG, '123')
    assert 'secret-example' not in str(row)
    assert row['active_overlays'] is None
    assert row['map_id'] is None
    assert row['evidence'][2]['line'] == 4


@pytest.mark.parametrize('text,game_id', [(LOG, '124'), (LOG, '../123'),
    (LOG.replace('GameID=123', 'GameID=0'), '123'),
    (LOG + 'GameStartData::GameID=456', '123'),
    (LOG.replace('mapskin = Default', 'skin missing'), '123')])
def test_log_rejects_missing_conflicting_wrong_session(text, game_id):
    with pytest.raises(ValueError): parse_session_log(text, game_id)


def manifest():
    return {'map_skin': 'Default', 'local_metadata': {'code': {'version': '16.20.8248524+code'},
                                                    'content': {'version': '16.20.8248524+content'}}}


def test_binding_does_not_promote_to_runtime_truth():
    b = bind_bundle(parse_session_log(LOG, '123'), manifest())
    assert b['status'] == 'skin_and_build_matched'
    assert b['runtime_terrain_verified'] is False
    assert b['actual_passability'] is None


@pytest.mark.parametrize('field', ['skin', 'build'])
def test_mismatched_assets_rejected(field):
    m = manifest()
    if field == 'skin': m['map_skin'] = 'Other'
    else: m['local_metadata']['content']['version'] = '16.19.8248524+content'
    with pytest.raises(ValueError): bind_bundle(parse_session_log(LOG, '123'), m)


def track():
    return [{'time_seconds': 10, 'map_waypoints_assuming_legacy_origin': [[10, 20], [60, 20]]},
            {'time_seconds': 12, 'map_waypoints_assuming_legacy_origin': [[15, 20]]}]


def grid():
    return Grid((0, -1, 0), (100, 1, 100), 50, 2, 2, (0, 2, 0, 0), {})


def test_planned_destination_and_elapsed_are_not_arrival_or_duration():
    rows = inspect_track(track(), grid())
    assert rows[0]['points'][1]['role'] == 'planned_waypoint_candidate'
    assert rows[0]['points'][1]['arrival_time_seconds'] is None
    assert rows[0]['points'][1]['grid_query']['actual_passability'] is None
    assert rows[1]['elapsed_since_previous_record_seconds'] == 2
    assert rows[1]['action_duration_seconds'] is None


@pytest.mark.parametrize('change', ['nan_time', 'reorder', 'nan_coord', 'outside', 'empty'])
def test_bad_candidates_rejected(change):
    t = copy.deepcopy(track())
    if change == 'nan_time': t[0]['time_seconds'] = math.nan
    if change == 'reorder': t.reverse()
    if change == 'nan_coord': t[0]['map_waypoints_assuming_legacy_origin'][0][0] = math.inf
    if change == 'outside': t[0]['map_waypoints_assuming_legacy_origin'][0][0] = 101
    if change == 'empty': t[0]['map_waypoints_assuming_legacy_origin'] = []
    with pytest.raises(ValueError): inspect_track(t, grid())
