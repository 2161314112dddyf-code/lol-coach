import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
from lol_coach.vision_minimap import ground_classes, minimap_point


PALETTE = {"land":{"visible":[115,154,143],"fogged":[42,57,52]},
           "river":{"visible":[145,126,22],"fogged":[54,46,6]}}


def image(color):
    return np.full((19, 19, 3), color, dtype=np.uint8)


@pytest.mark.parametrize("state, desired", [("fogged",False),("visible",True)])
def test_shading_may_change_without_changing_surface(state, desired):
    old = image(PALETTE["land"]["fogged"])
    current = image(PALETTE["land"][state])
    mask = np.ones(old.shape[:2],dtype=np.uint8)
    result = ground_classes(current,old,mask,PALETTE)
    assert minimap_point(result,0.5,0.5)["visible"] is desired


@pytest.mark.parametrize("condition", ["map_mask","icon","edge","surface_change","unknown_background"])
def test_abstains_when_the_point_or_its_background_is_unsuitable(condition):
    old = image(PALETTE["land"]["fogged"])
    current = image(PALETTE["land"]["visible"])
    mask = np.ones(old.shape[:2],dtype=np.uint8)
    if condition=="icon":
        current[9,9]=[255,255,255]
    elif condition=="edge":
        current[:,10:]=PALETTE["land"]["fogged"]
    elif condition=="surface_change":
        current=image(PALETTE["river"]["visible"])
    elif condition=="unknown_background":
        old=image([0,0,0])
    else:
        mask[9,9]=0
    assert minimap_point(ground_classes(current,old,mask,PALETTE),0.5,0.5)["visible"] is None


@pytest.mark.parametrize("u,v", [(1,0),(-.1,.5),(.5,float("nan"))])
def test_normalized_positions_cannot_wrap_or_index_outside(u,v):
    with pytest.raises(ValueError):
        minimap_point(np.zeros((3,3),dtype=np.uint8),u,v)
