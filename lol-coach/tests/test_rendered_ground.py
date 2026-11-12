import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

from scripts.query_rendered_ground import sample_render
from lol_coach.ngrid import Grid


def test_render_query_abstains_at_a_mixed_boundary_and_outside_view():
    ref = np.full((120,160,3), 100, dtype=np.uint8)
    pose = dict(fieldOfView=70, cameraPosition=dict(x=500,y=150,z=500))
    grid = Grid((0,0,0),(1000,20,1000),10,100,100,(0,)*10000,
                dict(height_samples=dict(minimum=0, maximum=10)))
    def query(on, x):
        return sample_render({True:on, False:ref}, pose, grid, x, 500)
    assert query(ref,500)['shading'] == 'clear'
    assert query(ref//2,500)['shading'] == 'dark'
    both = ref.copy()
    both[:,:80] //= 2
    assert query(both,500)['shading'] == 'unknown'
    assert query(ref,0)['reason'] == 'outside_camera_footprint'
