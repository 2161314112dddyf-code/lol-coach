"""Synthetic geometry tests; no in-game path is asserted."""
import math
import pytest
from lol_coach.ngrid import Grid
from lol_coach.path_audit import segment_cells,audit_polyline


def grid():return Grid((0,-1,0),(30,1,30),10,3,3,(0,2,0,0,128,0,0,0,0),{})


def test_segment_detects_wall_between_open_endpoints():
    r=audit_polyline(grid(),[[5,5],[25,5]])
    assert r['blocking_flag_contacts']==[{'cell_x':1,'cell_z':0,'raw_flags':2}]
    assert r['actual_duration_seconds'] is None and r['actual_passability'] is None


def test_corner_supercover_and_reverse():
    g=grid();cells=segment_cells(g,[5,5],[15,15])
    assert cells==[(0,0),(0,1),(1,0),(1,1)]
    assert cells==segment_cells(g,[15,15],[5,5])


def test_grid_boundary_both_sides():
    assert segment_cells(grid(),[10,1],[10,29])==[(0,0),(0,1),(0,2),(1,0),(1,1),(1,2)]


def test_stationary_and_unknown_bit():
    r=audit_polyline(grid(),[[15,15]])
    assert r['planned_polyline_length_game_units']==0
    assert len(r['uncertain_flag_contacts'])==1
    assert r['actual_distance_travelled'] is None


def test_outer_edge_does_not_add_invalid_cells():
    assert segment_cells(grid(),[0,0],[5,5])==[(0,0)]


def test_bend_does_not_connect_endpoints_directly():
    assert not audit_polyline(grid(),[[5,5],[5,25],[25,25],[25,5]])['blocking_flag_contacts']


def test_overlay_contact_does_not_apply_flags():
    overlay={'source':{'internal_path':'synthetic'},'regions':[{'x':0,'z':0,'width':1,'height':1,'flags':[2]}]}
    r=audit_polyline(grid(),[[5,5]], [overlay])
    assert not r['blocking_flag_contacts']
    assert r['overlay_region_contacts'][0]['active'] is None


@pytest.mark.parametrize('point',[[math.nan,0],[0,math.inf],[30,0],[-1,0],[True,2],[1]])
def test_invalid_coordinates_rejected(point):
    with pytest.raises(ValueError):segment_cells(grid(),point,[5,5])


def test_empty_rejected():
    with pytest.raises(ValueError):audit_polyline(grid(),[])
