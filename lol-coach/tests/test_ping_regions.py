"""Synthetic marker measurements test packet binding and projection, not HUD accuracy."""
from copy import deepcopy
import hashlib
import json

import pytest

from lol_coach import ping_regions
from lol_coach.replay_pings import decode_ping_packet
from lol_coach.reasoning_frame import compile_frame
from lol_coach.round_tools import round_call
from test_macro_snapshot import bundles, query
from test_review_pings import index, ping


def sample():
    packet = dict(stream=1, channel=1, opcode=63, chunk=8, offset=15, time=7.0, param=0,
                  payload=bytes.fromhex('d5c32a09e34ef777a58c65c693'))
    event = decode_ping_packet(packet, {0x400000b4: dict(name='Pantheon', team_id=200)})
    row = dict(source=event['source'].copy(), wire=packet['payload'][2:10].hex(), t=7.0,
               team_id=200, sender='Pantheon', kind='on_my_way', observed_through=8.0,
               hud_estimate_world_xz=[12010,3402], exact_packet_marker_xz=None)
    return packet, event, row


@pytest.mark.parametrize('field,changed', [('t', 7.2), ('sender', 'Jayce'), ('team_id', 100),
    ('kind', 'push'), ('wire', 'wrong'), ('source', {'chunk': 18}), ('observed_through', 6.99)])
def test_conflicting_marker_is_rejected(field, changed):
    packet, event, row = sample()
    with pytest.raises(ValueError):
        ping_regions.verified_region(event, packet, {**row, field:changed})


def test_private_report_hash_and_replay_are_both_checked(tmp_path, monkeypatch):
    _, _, row = sample()
    report = dict(replay_sha256='synthetic', build='build', map_id=11, rows=[row])
    raw = json.dumps(report).encode()
    sha = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(ping_regions, 'PRIVATE', tmp_path)
    monkeypatch.setattr(ping_regions, 'REVIEWED', {'synthetic': ('markers.json', sha), 'wrong': ('markers.json', sha)})
    assert ping_regions.marker_observations('synthetic', 'build') == ({}, None)
    path = tmp_path/'markers.json'
    path.write_bytes(raw)
    assert ping_regions.marker_observations('synthetic', 'build') == ({(8,15):row},sha)
    with pytest.raises(ValueError, match='scope'):
        ping_regions.marker_observations('wrong', 'build')
    path.write_bytes(raw+b' ')
    with pytest.raises(ValueError, match='changed'):
        ping_regions.marker_observations('synthetic', 'build')


def test_dragon_marker_uses_the_dragon_spawn_and_preserves_estimated_precision():
    packet, event, row = sample()
    row.update(hud_estimate_world_xz=[10126,4581], landmark={
        'name':'Dragon','xz':[9866.1484375,4414.01416015625],'distance_world':309})
    marker = ping_regions.verified_region(event, packet, row)
    assert marker['description']=='小龙出生点东北约300地图单位'
    assert marker['xz_rounded_to_100']==[10100,4600] and event['marker_xz'] is None


def test_marker_uses_last_hud_frame_and_stays_on_the_issuing_side(bundles):
    packet, event, measurement = sample()
    region = ping_regions.verified_region(event, packet, measurement)
    estimates = dict(marker_region=region, marker_report_sha256='fake_capture')
    events = [ping('self', **estimates), ping('ally', channel='team', **estimates),
              ping('enemy', team=200, channel='team', **estimates)]
    for row in events:
        row['marker_xz'] = None
    for t in (7.999,8.0):
        snap = query(bundles, at=t, player='self')
        bundle = compile_frame(snap, ping_index=index(snap, deepcopy(events)))
        view = round_call(bundle,'review_round_plan',{})['team_pings']
        own, = view['events']
        channel, = round_call(bundle,'get_reference',{'reference_id':view['team_channel_lookup']['reference_id']})['events']
        assert own['sender_entity_id']=='self' and channel['sender_entity_id']=='ally'
        assert 'marker_xz' not in own and channel['personal_receipt']=='unknown'
        if t < 8:
            assert 'marker_region' not in own and 'marker_region' not in channel
            assert 'fake_capture' not in str(bundle)
        else:
            assert own['marker_region']==channel['marker_region']==region
            assert region['xz_rounded_to_100']==[12000,3400]
            assert bundle['audit']['fact_sources'][own['fact_id']]['hud_report_sha256']=='fake_capture'
