from lol_coach.faelights_1622 import faelight_query, inside_polygon
from lol_coach.movement_1622 import minion_class


def test_concave_region_edges_and_indent():
    polygon = [(0,0),(4,0),(4,4),(2,2),(0,4)]
    assert inside_polygon(polygon,(2,1)) is True
    assert inside_polygon(polygon,(2,3)) is False
    assert inside_polygon(polygon,(3,3)) is None


def test_bonus_is_team_and_interval_specific_and_hides_future_expiry():
    row = dict(entity_id=9,team_id=100,pad_name='synthetic',polygon_xz=[(0,0),(0,2),(2,2),(2,0)],
               start_seconds=3,end_seconds=6,start_sources=[{}],region_source={},region_entry='a',asset_source={})
    positive = faelight_query([row],100,3,(1,1))
    assert positive['estimated_visible'] is True and positive['observed_team_visibility'] is None
    assert 'end_seconds' not in positive['contributions'][0]
    assert faelight_query([row],200,4,(1,1))['estimated_visible'] is None
    assert faelight_query([row],100,2.99,(1,1))['estimated_visible'] is None
    assert faelight_query([row],100,6,(1,1))['estimated_visible'] is None
    assert faelight_query([row],100,4,(3,1))['estimated_visible'] is None


def test_no_open_ended_estimate_on_missing_expiry():
    row = dict(team_id=100,polygon_xz=[(0,0),(0,2),(2,0)],start_seconds=12,end_seconds=None)
    assert faelight_query([row],100,57,(.1,.1))['contributions'] == []
    # A later packet in the full replay cannot extend the prefix's certainty.
    assert faelight_query([dict(row, end_seconds=57.25)],100,57.1,(.1,.1)) == faelight_query(
        [row],100,57.1,(.1,.1))


def test_three_native_minion_class_tags_ignore_network_id_body():
    assert minion_class(bytes.fromhex('0cffe95c988b73f5119b9e1e6b1e3dde')) == 'melee'
    assert minion_class(bytes.fromhex('9cf16b5a98a3960151db650e6b1e3d58')) == 'ranged'
    assert minion_class(bytes.fromhex('9cb9845c98ac47ad517b33edb71e3d6b')) == 'siege'
    # A second tag-like bit sequence also occurs inside this entity ID.
    assert minion_class(bytes.fromhex('0efafd5c98e498792e13db539b5a4e0e3d9a')) == 'ranged'
