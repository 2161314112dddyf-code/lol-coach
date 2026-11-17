"""Synthetic wall/color controls for a native minimap variant match."""
import pytest

np = pytest.importorskip('numpy')
pytest.importorskip('cv2')
Image = pytest.importorskip('PIL.Image')

from lol_coach.minimap_terrain import select_variant


def test_shape_and_color_must_both_replicate_across_map():
    y,x=np.indices((170,169))
    wall=(x//9+y//17)%2==0
    other=(x//11+y//8)%2==0
    def texture(blocked, color):
        a=np.zeros((170,169,4),dtype='uint8')
        a[:,:,:3]=color
        a[:,:,3]=255*(~blocked)
        return Image.fromarray(a)
    correct=texture(wall,(115,167,79))
    wrong_color=texture(wall,(138,72,161))
    wrong_wall=texture(other,(115,167,79))
    native=np.asarray(correct)[:,:,:3]*(~wall)[:,:,None]
    variants={'correct':correct,'same_wall':wrong_color,'other_shape':wrong_wall}
    winner,proof=select_variant(native,variants)
    assert winner=='correct' and set(proof['finalists'])=={'correct','same_wall'}
    variants['indistinguishable']=correct
    with pytest.raises(ValueError,match='ambiguous_minimap_terrain_color'):
        select_variant(native,variants)
