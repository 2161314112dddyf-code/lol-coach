"""Synthetic linked-object tests, never real spawn evidence."""
import copy
import math
import pytest
from lol_coach.geometry_context import extract_context, compare_navigation, compare_spawn


def fixture():
    def spawn(name, x):
        return {'name': name, '__type': 'GdsMapObject', 'type': 1,
                'transform': [[1,0,0,0],[0,1,0,0],[0,0,1,0],[x,10,20,1]]}
    return {'container': {'__type': 'MapContainer', 'components': [None, {'__type':'MapNavGrid','NavGridPath':'grid'}],
                          'chunks': {'main':'chunk'}},
            'chunk': {'__type':'MapPlaceableContainer','items': {'a':spawn('__Spawn_T1',10),'b':spawn('__Spawn_T2',100)}}}


def test_only_linked_landmarks():
    d=fixture();d['unlinked']=copy.deepcopy(d['chunk'])
    assert extract_context(d,'container')['spawn_bases']['__Spawn_T1']['position_xyz']==[10,10,20]


@pytest.mark.parametrize('change',['duplicate','missing','nan','parent','rotation','nav_ambiguous'])
def test_reject_unsupported_or_ambiguous(change):
    d=fixture()
    if change=='duplicate':d['chunk']['items']['c']=copy.deepcopy(d['chunk']['items']['a'])
    if change=='missing':del d['chunk']['items']['b']
    if change=='nan':d['chunk']['items']['a']['transform'][3][0]=math.nan
    if change=='parent':d['chunk']['transform']=[]
    if change=='rotation':d['chunk']['items']['a']['transform'][0][0]=-1
    if change=='nav_ambiguous':d['container']['components'].append({'__type':'MapNavGrid','NavGridPath':'other'})
    with pytest.raises(ValueError):extract_context(d,'container')


@pytest.mark.parametrize('a,b,status',[('A','a','references_agree_runtime_unverified'),('a','b','conflicting_navigation_references')])
def test_no_implicit_navigation_priority(a,b,status):
    result=compare_navigation(a,b)
    assert result['status']==status
    assert result['runtime_selected_path'] is None


def test_spawn_offset_is_testable_hypothesis_not_calibration():
    result=compare_spawn([604,612],[394,171,461],[160,0,120])
    assert result['candidate_minus_hypothesis_xz']==[50,31]
    assert result['exact_spawn_verified'] is False
