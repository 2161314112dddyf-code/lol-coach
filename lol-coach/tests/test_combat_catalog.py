from copy import deepcopy

import pytest

from lol_coach import combat_catalog, review_data_store
from lol_coach.reasoning_frame import digest, lookup_reference
from test_round_chain import bundle_at, freeze


BUILD = '16.22.836.1077'


def frame(at=448, build=BUILD, inventory=(3133,)):
    bundle = bundle_at(at)
    f = bundle['frame']
    f['decision']['build'] = build
    actor = f['decision']['player_entity_id']
    f['facts']['self_panel'] = dict(entity_id=actor, field='personal_client_state', observed_at_seconds=at,
        temporal_scope='personal_native_observation', value=dict(rune_ids={'keystone':8010},
        inventory=[dict(item_id=i, count=1) for i in inventory]))
    f['facts']['other_panel'] = {**f['facts']['self_panel'], 'entity_id':'other',
                                 'value':dict(inventory=[dict(item_id=9999,count=1)])}
    return freeze(bundle)


class Source:
    def __init__(self, item_name='锯齿短匕'):
        self.item_name = item_name

    def fetch(self, source_id, url, **kwargs):
        assert kwargs == dict(expect_json=True, refresh=True)
        payload = (dict(type='item',version='16.22.1',data={str(i):dict(name=self.item_name)
                    for i in (3133,3134,9999)}) if url.endswith('item.json') else
                   [dict(id=8000, slots=[dict(runes=[dict(id=8010,name='征服者',key='Conqueror',longDesc='文本')])])])
        return dict(requested_url=url, final_url=url, http_status=200, sha256=digest(payload),
                    retrieved_at_utc='2026-11-16T00:00:00Z', evidence_path='synthetic'), payload


def publish(root, monkeypatch, source):
    monkeypatch.setattr(review_data_store, 'fetch_riot_review_data',
        lambda *a, **k: dict(locale='zh_CN',version='16.22.1',champions={'Pantheon':dict(champion_id=80)}))
    return review_data_store.refresh_sources(root,'16.22.1',['Pantheon'],force=True,client=source,combat_build=BUILD)


def pinned(bundle):
    return lookup_reference(bundle, bundle['frame']['task']['combat_reference'])


def test_versioned_offline_load_preserves_previous_revision_and_selects_only_own_items(tmp_path, monkeypatch):
    publish(tmp_path, monkeypatch, Source('第一版'))
    original = frame()
    first, = combat_catalog.preload_combat([original], tmp_path)
    old = pinned(first)
    assert set(old['items']) == {'3133'} and set(old['runes']) == {'8010'}
    assert old['rune_rules']['build'] == BUILD
    assert 'combat_reference' not in original['frame']['task']
    publish(tmp_path, monkeypatch, Source('第二版'))
    later = frame(750, inventory=(3134,7777))
    continued, = combat_catalog.preload_combat([later], tmp_path, previous=first)
    current, = combat_catalog.preload_combat([later], tmp_path)
    assert pinned(continued)['items']['3134']['name'] == '第一版'
    assert pinned(continued)['missing_items'] == ['7777']
    assert pinned(current)['items']['3134']['name'] == '第二版'
    assert old['catalog_sha256'] == pinned(continued)['catalog_sha256'] != pinned(current)['catalog_sha256']
    assert combat_catalog.preload_combat([first],tmp_path/'absent')[0] == first
    stripped, = combat_catalog.preload_combat([first],tmp_path/'absent',disabled=True)
    assert stripped['frame'] == original['frame']
    assert stripped['reference_library'] == original['reference_library']
    with pytest.raises(ValueError, match='disabled'):
        combat_catalog.preload_combat([later], tmp_path, previous=first, disabled=True)
    changed = deepcopy(first)
    changed['reference_library'][changed['frame']['task']['combat_reference']]['items'].clear()
    with pytest.raises(ValueError,match='changed'):
        combat_catalog.preload_combat([changed], tmp_path)


def test_wrong_build_and_failed_refresh_cannot_publish_rules(tmp_path, monkeypatch):
    publish(tmp_path, monkeypatch, Source())
    original = frame(build='16.22.836.1078')
    assert combat_catalog.preload_combat([original], tmp_path) == [original]
    files = list((tmp_path/'snapshots'/'16.22').glob('*.json'))
    class Failing(Source):
        def fetch(self, source_id, url, **kwargs):
            if url.endswith('/item.json'):
                raise ValueError('network failed')
            return super().fetch(source_id,url,**kwargs)
    with pytest.raises(ValueError,match='network failed'):
        publish(tmp_path, monkeypatch, Failing())
    assert list((tmp_path/'snapshots'/'16.22').glob('*.json')) == files
    with pytest.raises(ValueError,match='exact game build'):
        combat_catalog.validate_build('16.23.1.1','16.22.1')


def test_original_nameless_item_ids_survive_sync_and_are_marked_unknown_in_review(tmp_path, monkeypatch):
    publish(tmp_path, monkeypatch, Source(''))
    _, row = next(review_data_store._records(tmp_path, '16.22'))
    assert row['combat_catalog']['unnamed_item_ids'] == ['3133','3134','9999']
    loaded, = combat_catalog.preload_combat([frame()], tmp_path)
    assert pinned(loaded)['items'] == {} and pinned(loaded)['missing_items'] == ['3133']


def test_later_personal_inventory_uses_published_lethality_and_does_not_double_deduct_shred():
    from lol_coach.damage_scenario import armor_penetration
    values = dict(armor_after_reductions=70, use_reviewed_armor_penetration=True)
    inventory = [dict(item_id=i, count=1) for i in (1036, 3071, 3111, 3364, 6697)]
    items = {str(row['item_id']): {} for row in inventory}
    items['6697']['raw_description'] = '<attention>18</attention>穿甲'
    profile = {'passive_percent_armor_penetration_by_rank':[.1,.2,.3]}
    result = armor_penetration(values, {'items': items}, inventory, profile, 2)
    assert result['effective_armor'] == 38 and result['total_flat_armor_penetration'] == 18
    items['6697']['raw_description'] = '<attention>15</attention>穿甲'
    assert armor_penetration(values, {'items': items}, inventory, profile, 2)['effective_armor'] is None


def test_exact_build_rule_updates_are_discoverable_without_replacing_history(tmp_path, monkeypatch):
    import json
    from lol_coach import ability_damage_data as skills, rune_damage_data as perks
    build = '16.22.836.9999'
    skill = json.loads(skills.PROFILE.read_bytes())
    page = json.loads(perks.PROFILE.read_bytes())
    for module in (skills, perks):
        monkeypatch.setattr(module, 'PROFILE', tmp_path / module.PROFILE.name)
    (tmp_path/'pantheon_ability_damage_16_22_836_9999.json').write_text(json.dumps({**skill, 'build':build}))
    rules = tmp_path/'rune_damage_16_22_836_9999.json'
    rules.write_text(json.dumps({**page, 'build':build}))
    assert skills.damage_profile(build, 'Pantheon', 'R')['build'] == build
    assert perks.rune_damage_profile(build)['build'] == build
    assert skills.damage_profile('16.22.836.9998', 'Pantheon', 'R') is None
    assert perks.rune_damage_profile('16.22.836.9998') is None
    rules.write_text(json.dumps(page))
    with pytest.raises(ValueError, match='invalid rune damage archive'):
        perks.rune_damage_profile(build)
