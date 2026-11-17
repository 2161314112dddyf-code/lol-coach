"""A player's own status from a clock-locked native replay. Never index enemy rows."""
from collections import Counter
import hashlib
import json
from pathlib import Path

from .hero_sight import reviewed_heroes
from .reasoning_frame import digest, number


SAMPLE_ROOT = Path(__file__).resolve().parents[1] / 'data/private/player_state'


def valid_status(source, value):
    if not isinstance(value, dict):
        return False
    if source == 'native_replay_self_hud_bars':
        required = {'health_fraction_interval','resource_fraction_interval'}
        return (required <= value.keys() <= required | {'R_indicator'}
                and all(isinstance(value[k], list) and len(value[k]) == 2 and all(number(x) for x in value[k])
                        and 0 <= value[k][0] <= value[k][1] <= 1 for k in required)
                and value.get('R_indicator') in (None,'lit_no_visible_cooldown_overlay','cooldown_sweep_visible'))
    keys = {'level','is_dead','respawn_timer_seconds','inventory','summoner_spells','rune_ids','creep_score'}
    if source != 'native_replay_liveclient_allplayers_self' or value.keys() != keys:
        return False
    timer = value['respawn_timer_seconds']
    spells = value['summoner_spells']
    runes = value['rune_ids']
    items = value['inventory']
    return (type(value['level']) is int and 1 <= value['level'] <= 18
            and type(value['creep_score']) is int and value['creep_score'] >= 0
            and type(value['is_dead']) is bool
            and (number(timer) and timer >= 0 if value['is_dead'] else timer is None)
            and isinstance(items,list) and len(items) <= 7
            and all(isinstance(i,dict) and i.keys() == {'item_id','count'}
                    and all(type(n) is int and n > 0 for n in i.values()) for i in items)
            and isinstance(spells,list) and len(spells)==2 and all(isinstance(s,str) and 0<len(s)<=100 for s in spells)
            and isinstance(runes,dict) and runes.keys()=={'keystone','primaryRuneTree','secondaryRuneTree'}
            and all(type(n) is int and n >= 0 for n in runes.values()))


def own_live_sample(doc, clock, replay_sha256, team, player):
    roster = reviewed_heroes(replay_sha256)
    actor = roster.get(int(player, 16))
    when = doc['gameData']['gameTime']
    if (not actor or actor['team_id'] != team or not number(when) or not number(clock)
            or when < 0 or abs(when - clock) > .002 or doc['gameData']['mapNumber'] != 11):
        raise ValueError('native_player_state_clock_or_roster_mismatch')
    side = 'ORDER' if team == 100 else 'CHAOS'
    rows = [r for r in doc['allPlayers'] if r['team'] == side and
            r['rawChampionName'] == 'game_character_displayname_' + actor['name']]
    if len(rows) != 1:
        raise ValueError('native_player_not_unique')
    row = rows[0]
    level, dead, respawn = row['level'], row['isDead'], row['respawnTimer']
    if (type(level) is not int or not 1 <= level <= 18 or type(dead) is not bool
            or not number(respawn) or respawn < 0):
        raise ValueError('invalid_native_player_fields')
    items = Counter()
    for item in row['items']:
        iid, count = item['itemID'], item['count']
        if type(iid) is not int or iid <= 0 or type(count) is not int or count < 1:
            raise ValueError('invalid_native_inventory_sample')
        items[iid] += count
    runes = row['runes']
    value = dict(level=level, is_dead=dead, respawn_timer_seconds=respawn if dead else None,
                 inventory=[dict(item_id=iid, count=n) for iid, n in sorted(items.items())],
                 creep_score=row['scores']['creepScore'],
                 summoner_spells=[row['summonerSpells'][k]['displayName']
                                  for k in ('summonerSpellOne', 'summonerSpellTwo')],
                 rune_ids={k: runes[k]['id'] for k in ('keystone', 'primaryRuneTree', 'secondaryRuneTree')})
    if not valid_status('native_replay_liveclient_allplayers_self', value):
        raise ValueError('invalid_native_status_snapshot')
    return dict(source='native_replay_liveclient_allplayers_self', time=when, value=value,
                sha256=digest(dict(replay=replay_sha256, team=team, entity=player, time=when, value=value)))


def load_own_observations(index, team, player, at, root=None):
    sha = index['source_sha256']
    if int(player, 16) not in reviewed_heroes(sha):
        return []
    directory = (SAMPLE_ROOT if root is None else root) / sha / player
    result = []
    for source in ('native_replay_liveclient_allplayers_self', 'native_replay_self_hud_bars'):
        path = directory / (source + '.json')
        if not path.is_file():
            continue
        raw = path.read_bytes()
        receipt = json.loads(raw)
        if (receipt.get('schema') != 'own-replay-state/v1' or receipt['source_sha256'] != sha
                or receipt['team_id'] != team or receipt['entity_id'] != player or receipt['build'] != index['version']):
            raise ValueError('native_player_state_scope_mismatch')
        eligible = [r for r in receipt['samples'] if 0 <= r['time'] <= at and at - r['time'] <= 1]
        if eligible:
            newest = max(r['time'] for r in eligible)
            same_time = [r for r in eligible if r['time'] == newest]
            if len(same_time) != 1:
                raise ValueError('ambiguous_native_player_sample')
            row = same_time[0]
            if (row['source'] != source or not valid_status(source, row['value'])
                    or row['sha256'] != digest(dict(replay=sha, team=team, entity=player,
                                                   time=row['time'], value=row['value']))):
                raise ValueError('invalid_native_player_state_evidence')
            result.append(dict(**row, index_sha256=hashlib.sha256(raw).hexdigest()))
    return result
