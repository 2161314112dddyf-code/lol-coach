"""Synthetic leakage regressions for the optional MCP research tool."""
from importlib.util import find_spec
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from lol_coach.reasoning_frame import compile_frame, digest
from lol_coach.review_sightings import check_sighting_answer, enemy_sightings
from test_macro_snapshot import bundles, query


def sample_frame(bundles, *, team=100, sampled_at=4, age=4):
    frame = compile_frame(query(bundles, at=8, player='self'))['frame']
    value = dict(visible=False, team_id=team,
                 last_observed_position=dict(xz=[20, 80], sampled_at=sampled_at, age_seconds=age))
    fact = dict(entity_id='entity:enemy', field='observer_visibility', value=value,
                temporal_scope='queried_at_decision_time', observed_at_seconds=5, age_seconds=3)
    fid = 'f_' + digest(fact)[:20]
    frame['facts'][fid] = fact
    frame['vision_fact_ids'] = [fid]
    del frame['frame_id']
    frame['frame_id'] = 'frame_' + digest(frame)[:24]
    return frame


def test_hidden_position_is_returned_only_as_an_aged_sample(bundles):
    frame = sample_frame(bundles)
    result = enemy_sightings(frame)
    assert result['at_seconds'] == 8 and result['observer_team_id'] == 100
    row, = result['opponents']
    assert row['fact_id'] in frame['vision_fact_ids']
    assert row['visible'] is False
    assert row['last_observed_path_start'] == dict(xz=[20, 80], sampled_at=4, age_seconds=4)
    assert 'current_position' not in row


def test_older_frame_without_a_visibility_channel_still_returns_unknown(bundles):
    frame = compile_frame(query(bundles, at=0, player='self'))['frame']
    row, = enemy_sightings(frame)['opponents']
    assert row['visible'] is None and row['last_observed_path_start'] is None
    assert frame['facts'][row['fact_id']]['field'] == 'visibility'


@pytest.mark.parametrize('overrides,reason', [
    ({'team': 200}, 'ambiguous_observer'),
    ({'sampled_at': 9, 'age': -1}, 'invalid_position_sample'),
    ({'age': 1}, 'invalid_position_sample'),
])
def test_no_wrong_observer_future_or_false_freshness(bundles, overrides, reason):
    with pytest.raises(ValueError, match=reason):
        enemy_sightings(sample_frame(bundles, **overrides))


def test_edited_frame_is_rejected(bundles):
    frame = sample_frame(bundles)
    frame['decision']['at_seconds'] = 9
    with pytest.raises(ValueError, match='invalid_frozen_frame'):
        enemy_sightings(frame)


def test_host_checks_sighting_claims_and_rejects_unsupported_route_conclusion(bundles):
    frame = sample_frame(bundles)
    correct = dict(visible=False, last_xz=[20.0, 80.0], position_fact_id=frame['vision_fact_ids'][0],
                   entrance_safety_proven=False)
    assert check_sighting_answer(frame, 'enemy', correct)['accepted']
    wrong = dict(correct, visible=0, position_fact_id='another_fact', entrance_safety_proven=True)
    result = check_sighting_answer(frame, 'enemy', wrong)
    assert not result['accepted']
    assert result['mismatched_fields'] == ['visible', 'position_fact_id', 'entrance_safety_proven']
    with pytest.raises(ValueError, match='opponent_outside_frame'):
        check_sighting_answer(frame, 'self', correct)


def test_stdio_discovery_call_and_scope_denials(bundles, tmp_path):
    interpreter = os.environ.get('REVIEW_MCP_PYTHON')
    if not interpreter and find_spec('mcp') is None:
        pytest.skip('optional review-mcp dependency is absent')
    frame = sample_frame(bundles)
    path = tmp_path / 'frame.json'
    path.write_text(json.dumps(frame), encoding='utf8')
    proc = subprocess.run([interpreter or sys.executable, '-m', 'scripts.review_sightings_mcp',
                           'probe', str(path)], cwd=Path(__file__).resolve().parents[1],
                          capture_output=True, text=True, timeout=45)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result['structured_result'] == enemy_sightings(frame)
    assert result['rejected_scope_overrides'] == 2
