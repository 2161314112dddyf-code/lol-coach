from copy import deepcopy
from importlib.util import find_spec
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import pytest

from lol_coach import review_data_store
from lol_coach.decision_contract import output_schema
from lol_coach.reasoning_frame import compile_frame, model_messages
from lol_coach.review_external_context import bind_session_external_data
from lol_coach.round_chain import _check_bundle
from lol_coach.round_tools import round_call
from test_macro_snapshot import bundles, query
from test_round_chain import bundle_at, freeze


def reference(snapshot):
    return dict(schema='synthetic', snapshot_id=snapshot, patch='16.22',
                champions={'A': {'mechanic': 'SYNTHETIC_MECHANIC'}}, cn_lane_stats=[],
                availability={'cn_lane_stats': 'post_game_snapshot_excluded'})


def test_session_pins_one_snapshot_and_tool_returns_only_eligible_content(monkeypatch, tmp_path):
    calls = []
    cutoff = '2026-11-11T23:36:20Z'

    def load(root, frame):
        calls.append((root, frame['task']['match_information_cutoff_utc']))
        return reference(str(len(calls)))

    monkeypatch.setattr(review_data_store, 'context_for_frame', load)
    source = [bundle_at(10), bundle_at(20)]
    first, second = bind_session_external_data(source, tmp_path, cutoff=cutoff)
    assert calls == [(tmp_path, cutoff)]
    for bundle in (first, second):
        frame = _check_bundle(bundle)
        ref = frame['task']['external_data_reference']
        assert frame['references'][ref]['snapshot_id'] == '1'
        assert frame['task']['match_information_cutoff_utc'] == cutoff
        plan = round_call(bundle, 'review_round_plan', {})
        assert plan['external_data'] == reference('1')
        assert round_call(bundle, 'get_reference', {'reference_id': ref}) == plan['external_data']
        messages = model_messages(bundle, output_schema(frame))
        assert 'review_round_plan.external_data' in messages[0]['content']
        assert 'SYNTHETIC_MECHANIC' not in messages[1]['content']
        assert 'SYNTHETIC_MECHANIC' not in str(frame['facts'])
    assert first['frame']['frame_id'] != source[0]['frame']['frame_id']
    assert 'external_data_reference' not in source[0]['frame']['task']

    reused, = bind_session_external_data([source[1]], tmp_path, previous=first)
    assert reused == second and len(calls) == 1
    pinned, = bind_session_external_data([first], tmp_path)
    assert pinned == first and len(calls) == 1
    with pytest.raises(ValueError, match='cutoff_mismatch'):
        bind_session_external_data([first], tmp_path, cutoff='2030-01-01T00:00:00Z')
    with pytest.raises(ValueError, match='disabled_requires_previous_card'):
        bind_session_external_data([second], tmp_path, previous=first, disabled=True)
    removed, = bind_session_external_data([first], tmp_path, disabled=True)
    assert 'external_data' not in round_call(removed, 'review_round_plan', {})
    assert ref not in removed['reference_library'] and ref not in removed['frame']['references']


def test_frozen_content_changes_or_conflicting_snapshots_are_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(review_data_store, 'context_for_frame', lambda root, frame: reference('a'))
    first, = bind_session_external_data([bundle_at(10)], tmp_path)
    monkeypatch.setattr(review_data_store, 'context_for_frame', lambda root, frame: reference('b'))
    second, = bind_session_external_data([bundle_at(20)], tmp_path)
    with pytest.raises(ValueError, match='conflicting_frozen_snapshots'):
        bind_session_external_data([first, second], tmp_path)
    ref = second['frame']['task']['external_data_reference']
    second['reference_library'][ref]['champions']['A']['mechanic'] = 'changed'
    with pytest.raises(ValueError, match='Reference content changed'):
        round_call(second, 'review_round_plan', {})
    different = deepcopy(bundle_at(20))
    different['frame']['lineup'][0]['champion'] = 'other'
    with pytest.raises(ValueError, match='lineup_or_role_mismatch'):
        bind_session_external_data([freeze(different)], tmp_path, previous=first)


def test_empty_store_preserves_old_frames(tmp_path):
    source = [bundle_at(10), bundle_at(20)]
    assert bind_session_external_data(source, tmp_path, cutoff='2026-11-11T23:36:20Z') == source


def test_verified_roles_are_independent_of_support_review(monkeypatch, tmp_path):
    subject = {'roster': [
        dict(team_id=100, champion='A', assigned_role='MIDDLE'),
        dict(team_id=100, champion='B', assigned_role='TOP'),
        dict(team_id=200, champion='C', assigned_role='MIDDLE')]}
    def inspect(root, frame):
        assert 'bottom_lane_actors' not in frame['task']
        assert frame['task']['external_lane_roles'] == {
            'ally': {'MIDDLE': 'self', 'TOP': 'ally'}, 'enemy': {'MIDDLE': 'enemy'}}
        return reference('a')
    monkeypatch.setattr(review_data_store, 'context_for_frame', inspect)
    first, = bind_session_external_data([bundle_at(10)], tmp_path, subject=subject)
    task = first['frame']['task']
    assert task['external_lane_roles']['ally']['MIDDLE'] == 'self' and 'bottom_lane_review' not in task
    next_frame, = bind_session_external_data([bundle_at(20)], tmp_path, previous=first)
    assert next_frame['frame']['task']['external_lane_roles'] == task['external_lane_roles']
    changed = deepcopy(subject)
    changed['roster'][0]['assigned_role'] = 'JUNGLE'
    with pytest.raises(ValueError, match='role_mismatch'):
        bind_session_external_data([first], tmp_path, subject=changed)
    next_frame['frame']['task']['roam_actors'] = {'ally_mid': 'ally'}
    with pytest.raises(ValueError, match='role_mismatch'):
        bind_session_external_data([freeze(next_frame)], tmp_path, previous=first)


def test_pregame_hero_tables_are_read_individually_and_survive_reuse(monkeypatch, tmp_path):
    detail = reference('stats_ready')
    first_row = dict(item_id=888, marker='SYNTHETIC_BUILD_SENTINEL')
    table = dict(side='ally', lane='MIDDLE', champion_id=11, table='equip', rows=[first_row],
                 stat_date='2026-10-20', source_url='https://example.test/profile')
    partner = dict(table, table='partner', rows=[{'partner_id': 2}])
    detail['cn_lane_profiles'] = [table, partner]
    monkeypatch.setattr(review_data_store, 'context_for_frame', lambda root, frame: detail)
    first, = bind_session_external_data([bundle_at(10)], tmp_path)
    summary = round_call(first, 'review_round_plan', {})['external_data']
    assert first_row['marker'] not in str(summary)
    builds, partners = summary['cn_lane_profiles']
    assert builds['champion_id'] == 11 and builds['row_count'] == 1 and builds['source_url'] == table['source_url']
    assert round_call(first, 'get_reference', dict(reference_id=builds['reference_id'])) == table
    assert round_call(first, 'get_reference', dict(reference_id=partners['reference_id'])) == partner
    assert 'get_reference' in summary['profile_lookup']
    reused, = bind_session_external_data([bundle_at(20)], tmp_path, previous=first)
    assert round_call(reused, 'get_reference', dict(reference_id=builds['reference_id'])) == table
    removed, = bind_session_external_data([first], tmp_path, disabled=True)
    with pytest.raises(ValueError, match='not available for this frame'):
        round_call(removed, 'get_reference', dict(reference_id=builds['reference_id']))
    first['reference_library'][partners['reference_id']]['rows'].clear()
    with pytest.raises(ValueError, match='Reference content changed'):
        bind_session_external_data([first], tmp_path)


def test_cli_reads_local_store_through_mcp_and_honors_opt_out(bundles, tmp_path, monkeypatch):
    interpreter = os.environ.get('REVIEW_MCP_PYTHON')
    if not interpreter and find_spec('mcp') is None:
        pytest.skip('optional review-mcp dependency is absent')
    root = Path(__file__).resolve().parents[1]
    sessions = root / 'data/private/reasoning_sessions'
    sessions.mkdir(parents=True, exist_ok=True)
    store = tmp_path / 'store'
    def riot(client, *, version, locale, **kw):
        return dict(version=version, locale=locale, champions={
            name: dict(champion_id=i, abilities={}, source=dict(sha256='0'*64,
                       requested_url='https://example.test/synthetic', retrieved_at_utc='2026-01-01T00:00:00Z'))
            for i, name in enumerate(kw['champions'], 1)})
    monkeypatch.setattr(review_data_store, 'fetch_riot_review_data', riot)
    review_data_store.refresh_sources(store, '16.22.1', ['A', 'UNRELATED'])
    with TemporaryDirectory(dir=sessions) as parent:
        command = [interpreter or sys.executable, '-m', 'scripts.run_review_agent', '--perspective', 'comparison',
                   '--lane', 'mid', '--target', 'dragon', '--help-seconds', '5', '--backend', 'probe']
        for at in (8, 9):
            bundle = compile_frame(query(bundles, at=at, player='self'))
            bundle['audit']['source_replay_sha256'] = 'a' * 64
            bundle['frame']['decision']['build'] = '16.22.123'
            path = tmp_path / f'{at}.json'
            path.write_text(json.dumps(freeze(bundle)), encoding='utf-8')
            command.extend(['--bundle', str(path)])
        for name, options in [('enabled', ['--external-data-dir', str(store)]), ('disabled', ['--no-external-data'])]:
            output = Path(parent) / name
            proc = subprocess.run(command + options + ['--output', str(output)], cwd=root, capture_output=True, timeout=75)
            assert proc.returncode == 0, proc.stderr.decode(errors='replace')
            steps = json.loads((output / 'manifest.json').read_bytes())['steps']
            assert len(steps) == 2 and all(step['direct_equals_mcp'] for step in steps)
            assert steps[0]['external_data_snapshot_id'] == steps[1]['external_data_snapshot_id']
            for path in sorted(output.glob('*/evidence.json')):
                plan = json.loads(path.read_bytes())['review_round_plan']
                if name == 'enabled':
                    assert plan['external_data']['snapshot_id'] == steps[0]['external_data_snapshot_id']
                    assert set(plan['external_data']['champions']) == {'A'}
                else:
                    assert steps[0]['external_data_snapshot_id'] is None and 'external_data' not in plan
