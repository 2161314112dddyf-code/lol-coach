"""Synthetic communication events exercise the information boundary, not the replay decoder."""
import pytest

from lol_coach.reasoning_frame import compile_frame, model_messages
from lol_coach.round_tools import round_call
from test_macro_snapshot import bundles, query


def ping(sender='ally', kind='on_my_way', when=7, team=100, **extra):
    return dict(time_seconds=when, team_id=team, sender_entity_id=sender, kind=kind,
                source={'chunk': 18, 'offset': 31415}, marker_xz=[101, 202], **extra)


def delivery(scope, who, when):
    key = 'team_id' if scope == 'team' else 'player_entity_id'
    return {'scope': scope, key: who, 'at_seconds': when, 'source': {'chunk': 18, 'offset': 31418}}


def index(snap, events):
    return dict(schema='review-ping-index/v1', status='verified', source_sha256=snap['source_sha256'],
                build=snap['version'], events=events)


def test_synthetic_roster_and_delivery_window_are_independent(bundles):
    snap = query(bundles, at=8, player='self')
    outgoing = ping('self', 'assist_me', 5)
    delivered = ping(delivery=delivery('player', 'self', 7.5))
    team = ping('ally', 'enemy_missing', 8, delivery=delivery('team', 100, 8))
    ignored = [ping(), ping(delivery=delivery('player', 'ally', 8)),
               ping(delivery=delivery('player', 'self', 8.1)), ping(delivery=delivery('team', 200, 8)),
               ping('enemy', team=200, delivery=delivery('team', 100, 8)),
               ping('self', when=4.999), ping('self', when=8.001), ping('self', 'unsupported_type')]
    bundle = compile_frame(snap, ping_index=index(snap, [*ignored, delivered, team, outgoing]), ping_window_seconds=3)
    result = round_call(bundle, 'review_round_plan', {})['team_pings']
    assert result['window_start_seconds'] == 5 and result['through_seconds'] == 8
    assert [(e['kind'], e['known_as']) for e in result['events']] == [
        ('assist_me', 'own_sent'), ('on_my_way', 'delivered_to_player'), ('enemy_missing', 'delivered_to_team')]
    assert result['response_to_ping'] == result['player_attention'] == 'unknown'
    assert all(e['marker_xz'] == [101, 202] for e in result['events'])
    same = compile_frame(snap, ping_index=index(snap, [delivered, team, outgoing]), ping_window_seconds=3)
    assert same['frame'] == bundle['frame']
    for event in result['events']:
        fid = event['fact_id']
        assert bundle['frame']['facts'][fid]['field'] == 'map_ping_sent'
        assert bundle['audit']['fact_sources'][fid]['send']['offset'] == 31415
    assert '31415' not in str(model_messages(bundle, {})) and '31418' not in str(result)


def test_source_binding_and_old_frames_remain_distinct(bundles):
    snap = query(bundles, at=8, player='self')
    base = compile_frame(snap)
    assert 'team_pings' not in round_call(base, 'review_round_plan', {})
    source = index(snap, [])
    for k in ('build', 'source_sha256', 'schema'):
        changed = {**source, k: 'other'}
        with pytest.raises(ValueError, match='does_not_match_replay'):
            compile_frame(snap, ping_index=changed)
    no_evidence = compile_frame(snap, ping_index=source)
    report = round_call(no_evidence, 'review_round_plan', {})['team_pings']
    assert report['coverage'] == 'verified_events_only' and report['events'] == []
    assert no_evidence['frame']['frame_id'] != base['frame']['frame_id']


def test_optional_team_channel_keeps_unconfirmed_receipt_out_of_personal_facts(bundles):
    snap = query(bundles, at=8, player='self')
    expected = {'assist_me','enemy_missing','on_my_way','push','all_in','retreat','need_vision','enemy_vision'}
    accepted = [ping('ally', kind, when=6, channel='team') for kind in sorted(expected)]
    excluded = [ping('enemy', 'assist_me', team=200, channel='team'), ping('ally', 'command', channel='team'),
                ping('ally', 'get_back', channel='team'),
                ping('ally', 'on_my_way', when=8.001, channel='team')]
    bundle = compile_frame(snap, ping_index=index(snap, accepted + excluded))
    report = round_call(bundle, 'review_round_plan', {})['team_pings']
    assert report['events'] == []
    assert not [f for f in bundle['frame']['facts'].values() if f['field'] == 'map_ping_sent']
    body = round_call(bundle, 'get_reference', {'reference_id': report['team_channel_lookup']['reference_id']})
    assert {e['kind'] for e in body['events']} == expected
    assert len(body['events']) == 8 and 'league-of-legends/gameplay/smart-ping' in body['channel_rules_source']
    assert all(e['sender_entity_id'] == 'ally' and e['personal_receipt'] == 'unknown' for e in body['events'])
    assert body['player_attention'] == body['response_to_ping'] == 'unknown'
    unknown = compile_frame(snap, ping_index={**index(snap, []), 'status': 'unsupported_replay', 'build': None})
    assert round_call(unknown, 'review_round_plan', {})['team_pings']['coverage'] == 'unsupported_replay'
