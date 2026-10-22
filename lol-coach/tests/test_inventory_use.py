"""Synthetic boundary fixtures; real replay evidence is in the research run."""
import pytest
from lol_coach.inventory_use import decode_use


@pytest.mark.parametrize('payload,slot,stacks,charges',[
    ('05b7',0,1,1),('c3b7',2,1,0),('ccb6da',6,0,None),('b4b7da',6,2,None)])
def test_observed_field_forms(payload,slot,stacks,charges):
    value=decode_use(bytes.fromhex(payload))
    assert (value['slot'],value['stack_count'],value['remaining_charges'])==(slot,stacks,charges)
    assert value['cooldown_seconds'] is None


@pytest.mark.parametrize('payload',['','05','05b700','84b6ec','05b8','44b5'])
def test_unknown_or_truncated(payload):
    with pytest.raises(ValueError):decode_use(bytes.fromhex(payload))


def test_version_gate():
    with pytest.raises(ValueError):decode_use(bytes.fromhex('05b7'),version='16.21')
