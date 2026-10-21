"""Synthetic selection metadata; runtime observations are never manufactured."""
import hashlib
import pytest
from lol_coach.map_selection import build_policy, verified_bytes, query_selected_grid, REVIEWED_MAPSKIN_DOC_SHA256


def inputs():
    return ({'dataset':{'latestPatch':'16.20','latestBuild':8248524}},
            {'sha256':REVIEWED_MAPSKIN_DOC_SHA256},
            {'patch':'16.20','local_metadata':{'code':{'version':'16.20.8248524+code'},'content':{'version':'16.20.8248524+content'}},
             'navigation_reference_audit':{'container_grid_source':{}}})


def test_documented_rule_is_not_runtime_observation():
    policy=build_policy(*inputs())
    assert policy['analysis_default']=='container'
    assert policy['runtime_observed'] is False


@pytest.mark.parametrize('change',['patch','build','docs','missing_grid'])
def test_unreviewed_mismatched_rule_rejected(change):
    meta,docs,m=inputs()
    if change=='patch':meta['dataset']['latestPatch']='16.21'
    if change=='build':meta['dataset']['latestBuild']=1
    if change=='docs':docs['sha256']='0'*64
    if change=='missing_grid':m['navigation_reference_audit']={}
    with pytest.raises(ValueError):build_policy(meta,docs,m)


def test_verified_bytes_and_tamper(tmp_path):
    p=tmp_path/'x';p.write_bytes(b'synthetic')
    ref={'evidence_path':'x','sha256':hashlib.sha256(b'synthetic').hexdigest()}
    assert verified_bytes(tmp_path,ref)==b'synthetic'
    p.write_bytes(b'changed')
    with pytest.raises(ValueError):verified_bytes(tmp_path,ref)


def test_evidence_escape_rejected(tmp_path):
    with pytest.raises(ValueError):verified_bytes(tmp_path,{'evidence_path':'../outside','sha256':'0'*64})


def test_no_silent_fallback_to_old_grid(tmp_path):
    with pytest.raises(ValueError,match='not audited'):query_selected_grid(tmp_path,{},10,20)


def test_invalid_source_rejected(tmp_path):
    with pytest.raises(ValueError,match='Unknown grid'):query_selected_grid(tmp_path,{},10,20,'other')
