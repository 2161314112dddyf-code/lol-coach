"""Published updates, frozen historical knowledge and refresh failure are separate."""
from datetime import datetime, timezone
import pytest

from lol_coach import review_data_store as store
from lol_coach.review_subject import _information_cutoff


def test_log_cutoff_uses_a_conservative_bound_even_on_another_machine():
    prefix = b'000000.000| ALWAYS| Logging started at '
    assert _information_cutoff(prefix + b'2026-11-12T13:36:20.793') == '2026-11-11T23:36:20.793000+00:00'
    assert _information_cutoff(prefix + b'2026-11-12T13:36:20+08:00') == '2026-11-12T05:36:20+00:00'
    assert _information_cutoff(b'unknown') is None


def test_refresh_publishes_complete_snapshots_and_keeps_earlier_stats(tmp_path, monkeypatch):
    names = ['Caitlyn', 'KogMaw', 'Pantheon']
    pairs = [('BOTTOM', 'Caitlyn', 'KogMaw')]
    seen = {'time':'2026-11-10T09:00:00Z', 'day':'2026-11-09', 'rate':41, 'calls':0}
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat(seen.get('published', seen['time']).replace('Z', '+00:00')).astimezone(tz)
    monkeypatch.setattr(store, 'datetime', Clock)
    def riot(client, **kwargs):
        assert kwargs['refresh']
        seen['calls'] += 1
        champions = {name:dict(champion_id=i, abilities={}, source=dict(sha256='a'*64,
                     requested_url='example.test', retrieved_at_utc=seen['time'])) for i,name in enumerate(names, 1)}
        return dict(version='16.22.1', locale='zh_CN', champions=champions)
    def tencent(client, **kwargs):
        if seen['rate'] is None:
            raise ValueError('upstream failed')
        return {k:kwargs[k] for k in ('champion_id','opponent_id','patch','lane')} | dict(
            stat_date=seen['day'], retrieved_at_utc=seen['time'], win_rate_pct=seen['rate'])
    monkeypatch.setattr(store, 'fetch_riot_review_data', riot)
    monkeypatch.setattr(store, 'fetch_matchup', tencent)
    def update(force=False):
        return store.refresh_sources(tmp_path, '16.22.1', names, pairs, force=force)
    assert update()['status'] == 'updated'
    assert update()['status'] == 'fresh_cache' and seen['calls'] == 1
    seen.update(time='2026-11-13T00:00:00Z', day='2026-11-12', rate=58)
    assert update(True)['status'] == 'updated'
    frame = dict(decision=dict(build='16.22.836.1077'), lineup=[
        dict(entity_id='a',champion='Caitlyn'),dict(entity_id='b',champion='KogMaw')],
        task=dict(bottom_lane_actors=dict(carry='a',enemy_carry='b'),
                  match_information_cutoff_utc='2026-11-11T00:00:00Z'))
    def context(): return store.context_for_frame(tmp_path, frame)
    assert [s['win_rate_pct'] for s in context()['cn_lane_stats']] == [41]
    assert set(context()['champions']) == {'Caitlyn','KogMaw'}
    # A response requested before the game but published after its start is ineligible.
    frame['task']['match_information_cutoff_utc'] = '2026-11-13T00:00:01Z'
    seen.update(time='2026-11-13T00:00:00.5Z', published='2026-11-13T00:00:03Z', rate=99)
    update(True)
    assert context()['cn_lane_stats'][0]['win_rate_pct'] == 58
    frame['task']['match_information_cutoff_utc'] = '2026-11-14T00:00:00Z'
    assert context()['cn_lane_stats'][0]['win_rate_pct'] == 99
    before = context()
    seen['rate'] = None
    with pytest.raises(ValueError, match='upstream failed'):
        update(True)
    assert context() == before and len(list((tmp_path/'snapshots'/'16.22').glob('*.json'))) == 3
    frame['task'].pop('match_information_cutoff_utc')
    assert context()['cn_lane_stats'] == []
    assert context()['availability']['cn_lane_stats'] == 'unknown_match_cutoff'
    frame['task']['match_information_cutoff_utc'] = '2026-11-01T00:00:00Z'
    assert context()['availability']['cn_lane_stats'] == 'no_verified_pregame_snapshot'
    frame['task']['bottom_lane_actors'] = dict(carry='b', enemy_carry='a')
    assert context()['availability']['cn_lane_stats'] == 'no_matching_pair'
    frame['decision']['build'] = '16.21.123'
    assert context() is None


def test_profiles_follow_verified_lanes_allies_and_each_table_date(monkeypatch, tmp_path):
    from lol_coach import cn_lane_profiles, riot_review_data

    names = ['A', 'B', 'C', 'D']
    source = dict(sha256='a'*64, requested_url='https://example.test', retrieved_at_utc='2026-11-10T09:00:00Z')
    monkeypatch.setattr(riot_review_data, 'fetch_item_names', lambda *a, **kw: dict(items={'1001': '鞋'}, source=source))
    champions = {name: dict(champion_id=i, source=source) for i, name in enumerate(names, 1)}
    monkeypatch.setattr(store, 'fetch_riot_review_data', lambda *a, **k: dict(
        version='16.22.1', locale='zh_CN', champions=champions))
    def matchup(_client, **kw):
        return {k: kw[k] for k in ('lane', 'champion_id', 'opponent_id')} | dict(
            retrieved_at_utc=source['retrieved_at_utc'], stat_date='2026-11-09', win_rate_pct=50)
    monkeypatch.setattr(store, 'fetch_matchup', matchup)
    def profile(_client, *, lane, champion_id, **kw):
        tables = {key: dict(stat_date='2026-11-09', retrieved_at_utc=source['retrieved_at_utc'], rows=[])
                  for key in ('partner', 'build', 'duration')}
        tables['partner']['rows'] = [dict(partner_id=i) for i in range(1, 5)]
        tables['build']['stat_date'] = '2100-01-01'
        tables['build']['rows'] = [dict(item_ids=[1001, 99999])]
        return dict(lane=lane, champion_id=champion_id, tables=tables)
    monkeypatch.setattr(cn_lane_profiles, 'fetch_lane_profile', profile)
    pairs = [('BOTTOM', 'A', 'B'), ('SUPPORT', 'C', 'D')]
    store.refresh_sources(tmp_path, '16.22.1', names, pairs, include_profiles=True)
    frame = dict(decision=dict(build='16.22.123.456'), lineup=[dict(entity_id=n, champion=n) for n in names],
                 task=dict(external_lane_roles={'ally': {'BOTTOM': 'A', 'UTILITY': 'C'},
                                                'enemy': {'BOTTOM': 'B', 'UTILITY': 'D'}},
                           match_information_cutoff_utc='2099-01-01T00:00:00Z'))
    ctx = store.context_for_frame(tmp_path, frame)
    assert len(ctx['cn_lane_stats']) == 2
    tables = {(p['table'], p['champion_id']): p for p in ctx['cn_lane_profiles']}
    assert tables['partner', 1]['rows'] == [dict(partner_id=3)]
    assert tables['partner', 2]['rows'] == [dict(partner_id=4)]
    assert set(metric for metric, _ in tables) == {'duration', 'partner'}
    frame['task']['match_information_cutoff_utc'] = '2100-01-03T00:00:00Z'
    builds = [p for p in store.context_for_frame(tmp_path, frame)['cn_lane_profiles'] if p['table'] == 'build']
    assert builds[0]['rows'][0]['item_names'] == ['鞋', None]
    frame['task'].pop('match_information_cutoff_utc')
    assert store.context_for_frame(tmp_path, frame)['cn_lane_profiles'] == []


def test_conflicting_static_values_under_one_game_patch_are_withheld(tmp_path, monkeypatch):
    def riot(client, *, version, **kw):
        champion = dict(champion_id=1, abilities=dict(R=version), source=dict(
            sha256='0'*64, requested_url='https://example.test', retrieved_at_utc='2026-11-10T09:00:00Z'))
        return dict(version=version, locale='zh_CN', champions={'A': champion})
    monkeypatch.setattr(store, 'fetch_riot_review_data', riot)
    for version in ('16.22.1', '16.22.2'):
        store.refresh_sources(tmp_path, version, ['A'])
    frame = dict(decision=dict(build='16.22.100.200'), lineup=[dict(entity_id='a', champion='A')], task={})
    context = store.context_for_frame(tmp_path, frame)
    assert context['champions'] == {}
    assert context['availability']['ambiguous_champion_static_data'] == ['A']


def test_poller_honors_stop_file_before_request(tmp_path, monkeypatch, capsys):
    import sys
    from scripts import refresh_review_sources as cli
    stop = tmp_path / 'STOP'
    stop.touch()
    monkeypatch.setattr(sys, 'argv', ['refresh', '--version', 'current', '--champions', 'Pantheon',
                                     '--interval-minutes', '360', '--stop-file', str(stop)])
    monkeypatch.setattr(cli, 'current_riot_version', lambda *args: pytest.fail('unexpected HTTP'))
    assert cli.main() == 0
    assert 'polling_stopped' in capsys.readouterr().out


@pytest.mark.parametrize('reversed_order', [True, False])
def test_same_release_legacy_combat_data_and_real_conflicts(tmp_path, monkeypatch, reversed_order):
    stats = {'armor': {'level_1':24, 'growth':4.2, 'source_fields':['armor','armorperlevel']}}
    records = [{}, {'combat_base_stats':stats}]
    if reversed_order:
        records.reverse()
    source = dict(sha256='a'*64, requested_url='https://example.test', retrieved_at_utc='2026-11-10T09:00:00Z')
    def publish(fields, version='16.22.1'):
        row = dict(champion_id=1, abilities={}, source=source, **fields)
        monkeypatch.setattr(store, 'fetch_riot_review_data', lambda *a, **kw: dict(
            version=version, locale='zh_CN', champions={'Jhin':row}))
        store.refresh_sources(tmp_path, version, ['Jhin'], force=True)
    frame = dict(decision=dict(build='16.22.836.1077'), lineup=[dict(entity_id='a',champion='Jhin')])
    for record in records:
        publish(record)
    hero = store.context_for_frame(tmp_path, frame)['champions']['Jhin']
    assert hero['combat_base_stats'] == stats
    assert hero['client_combat_base_stats']['stats']['attack_damage']['growth'] == 4.4
    frame['decision']['build'] = '16.22.836.1078'
    hero = store.context_for_frame(tmp_path, frame)['champions']['Jhin']
    assert hero['combat_base_stats'] == stats and 'client_combat_base_stats' not in hero
    source['sha256'] = 'b'*64
    publish({}, '16.22.2')
    assert 'combat_base_stats' not in store.context_for_frame(tmp_path, frame)['champions']['Jhin']
    publish({'combat_base_stats':{'armor':{'level_1':999}}}, '16.22.2')
    result = store.context_for_frame(tmp_path, frame)
    assert result['champions'] == {} and result['availability']['ambiguous_champion_static_data'] == ['Jhin']


def test_available_client_profile_preserves_replay_build_and_source(monkeypatch, tmp_path):
    snap = store.client_combat_bases(store.CLIENT_BASE_BUILD)
    assert len(snap) == 10
    pantheon = snap['Pantheon']
    assert pantheon['build'] == store.CLIENT_BASE_BUILD
    assert pantheon['stats']['attack_damage'] == {'level_1':64, 'growth':3.3}
    assert pantheon['source']['record'] == 'Characters/Pantheon/CharacterRecords/Root'
    assert pantheon['source']['fields']['magic_resist'] == ['baseMR.BaseValue','mrPerLevel.BaseValue']
    assert pantheon['source']['sha256'] == '366f02ef3dee9859140fc9faedc120b58b41a913d20c3f23db78b422cceed9ac'
    monkeypatch.setattr(store,'CLIENT_BASE_PROFILE', tmp_path / 'missing.json')
    assert store.client_combat_bases(store.CLIENT_BASE_BUILD) == {}
