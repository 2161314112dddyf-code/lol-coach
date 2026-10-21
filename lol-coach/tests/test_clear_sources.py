"""Synthetic source HTML; listed times must never become measured durations."""
import pytest
from lol_coach.clear_sources import extract_clear_candidates


def table(row=None):
    headers=['row','Champion','Patch','Camps','Smite(s)','Time','Path','Link','Player','Notes/Details:']
    row=row or ['84','Ivern','26.19','6','1','02:17','Blue->Gromp','https://example.test/video','synthetic author','']
    render=lambda cells:'<tr>'+''.join('<td>'+c+'</td>' for c in cells)+'</tr>'
    return '<table>'+render(headers)+render(row)+'</table>'


def test_no_time_or_patch_promotion():
    r=extract_clear_candidates(table(),'Ivern')[0]
    assert r['reported']['Time']=='02:17'
    assert r['reported']['notes'] is None
    assert r['elapsed_seconds'] is None and r['end_game_time_seconds'] is None
    assert r['action_model_eligible'] is False and r['video_reviewed'] is False


def test_exact_champion_filter():
    assert extract_clear_candidates(table(),'IvernOther')==[]


def test_missing_values_are_unknown():
    r=extract_clear_candidates(table(['84','Ivern','','','','','','','','']),'Ivern')[0]
    assert r['reported']['Patch'] is None


@pytest.mark.parametrize('html',['<p>Ivern 02:17</p>',table()+table(),table(['84','Ivern'])])
def test_malformed_or_ambiguous_tables_rejected(html):
    with pytest.raises(ValueError):extract_clear_candidates(html,'Ivern')
