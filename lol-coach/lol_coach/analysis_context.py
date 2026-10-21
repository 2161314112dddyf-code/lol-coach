"""Join prefix observations with separately labelled, source-checked references."""
import copy
import hashlib
import json
from pathlib import Path
import re

from .macro_snapshot import build_snapshot, render_markdown
from .replay_vision import VERSION
from .tower_vision import enemy_tower_view


def cached_champion(root, name, patch='16.20.1'):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9]+', name) or patch != '16.20.1':
        raise ValueError('Unsupported champion/reference version')
    root = Path(root).resolve()
    url = f'https://ddragon.leagueoflegends.com/cdn/{patch}/data/en_US/champion/{name}.json'
    record = json.loads((root/'cache'/(hashlib.sha256(url.encode()).hexdigest()+'.json')).read_text(encoding='utf8'))
    path = (root/record['evidence_path']).resolve()
    if not path.is_relative_to(root) or record.get('requested_url') != url or record.get('http_status') != 200:
        raise ValueError('Invalid official source cache')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != record['sha256']:
        raise ValueError('Champion source hash mismatch')
    doc = json.loads(raw)
    if doc.get('version') != patch or doc.get('data', {}).get(name, {}).get('id') != name:
        raise ValueError('Champion source identity mismatch')
    champ = doc['data'][name]
    abilities = [dict(slot='P', name=champ['passive']['name'], description=champ['passive']['description'],
                      pointer=f'/data/{name}/passive')]
    for slot, spell in zip('QWER', champ['spells'], strict=True):
        abilities.append(dict(slot=slot, id=spell['id'], name=spell['name'], description=spell['description'],
            tooltip=spell['tooltip'], reference_cooldown_by_rank=spell['cooldown'],
            reference_cost_by_rank=spell['cost'], reference_range_by_rank=spell['range'],
            unresolved_parameters=sorted(set(re.findall(r'\{\{\s*(.*?)\s*\}\}', spell['tooltip']))),
            pointer=f'/data/{name}/spells/{len(abilities)-1}'))
    return dict(champion=name, patch=patch, kind='official_static_reference', base_stats=champ['stats'],
        abilities=abilities, current_castable=None, current_cooldowns=None, current_skill_ranks=None,
        exact_client_compatibility='not_independently_verified', actual_match_observation=False,
        source=dict(url=url, sha256=record['sha256'], retrieved_at_utc=record['retrieved_at_utc']))


def clean_source(source):
    return {k: source[k] for k in ('stream','chunk','offset','decompressed_offset','opcode','payload_sha256') if k in source}


def join_towers(snapshot, towers, vision):
    if towers.get('schema') != 'turret-state/v1' or vision.get('schema') != 'named-tower-vision/v1':
        raise ValueError('Unsupported tower schema')
    if any(d.get('version') != VERSION or d.get('source', {}).get('sha256') != snapshot['source_sha256'] for d in (towers, vision)):
        raise ValueError('Tower build/replay mismatch')
    at = snapshot['context']['at_seconds'];team = snapshot['context']['observer_team_id']
    # An identity first learned later in a timestamp cannot license an earlier sample.
    def key(row):
        s=row['source']
        return row['time_seconds'],s['chunk'],s.get('offset',s.get('decompressed_offset'))
    filtered=copy.deepcopy(towers)
    first={}
    for row in sorted(filtered['identity_events'],key=key):
        if row['time_seconds']<=at:first.setdefault(row['entity_id'],row)
    filtered['identity_events']=list(first.values())
    filtered['health_samples']=[r for r in filtered['health_samples']
        if r['entity_id'] in first and key(r)>=key(first[r['entity_id']])]
    view = enemy_tower_view(filtered, vision, at, team)
    rows = []
    for entity, state in sorted(view['towers'].items()):
        identity_row = state['identity'];identity = identity_row['identity']
        def samples(raw):
            if raw is None:return None
            return {k: dict(value=v['value'], observed_at_seconds=v['observed_at_seconds'],
                            age_seconds=at-v['observed_at_seconds'], source=clean_source(v['source']))
                    for k,v in raw.items() if k in ('health','max_health')}
        transition=state['last_transition']
        rows.append(dict(entity_id=entity,
            identity={k: identity[k] for k in ('name','team','lane','role')},
            identity_observed_at_seconds=identity_row['time_seconds'], identity_source=clean_source(identity_row['source']),
            visible=state['visible'], observed_now=samples(state['current_observed']),
            last_observed=samples(state['last_observed']), last_observed_is_current_hidden_state=False,
            last_transition=None if transition is None else dict(time_seconds=transition['time_seconds'],
                visible=transition['visible'],source=clean_source(transition['source'])),
            current_exact_health=False, runtime_map_id=None))
    snapshot['world']['enemy_towers'] = dict(status='partial_observations', towers=rows,
        evidence_level='cross_checked_binary_inference_without_independent_UI_confirmation',
        complete_world_vision=False, limitations=view['limitations'])
    return snapshot


def build_context(bundles, *, at, team, player=None, cache_root, human_cards, mechanisms,
                  towers=None, tower_vision=None, window=30):
    """Preserve macro-snapshot/v1 and add optional reference namespaces."""
    snapshot=build_snapshot(*bundles,at=at,team=team,player=player,window=window)
    if (towers is None) != (tower_vision is None):raise ValueError('Both tower inputs are required')
    if towers is not None:join_towers(snapshot,towers,tower_vision)
    else:snapshot['world']['enemy_towers']=dict(status='unknown',towers=[],reason='Paired tower state/visibility exports unavailable for this replay')
    refs={h['champion']:cached_champion(cache_root,h['champion']) for h in snapshot['heroes'] if h['champion'] is not None}
    if human_cards.get('schema') != 'conditional-human-experience/v1':raise ValueError('Invalid human cards')
    if mechanisms.get('schema') != 'champion-mechanisms/v1':raise ValueError('Invalid mechanism bundle')
    applicable=[]
    for interaction in snapshot['composition']['interactions']:
        actor=next(h for h in snapshot['heroes'] if h['entity_id']==interaction['actor_id'])
        interaction['static_reference_champion']=actor['champion']
        # References describe capabilities; they do not certify ready skills or tactical advantage.
        interaction['grounded_capabilities']=dict(status='static_descriptions_available' if actor['champion'] is not None else 'unknown_identity',
            reference=f"foundation.champions.{actor['champion']}" if actor['champion'] is not None else None,current_available_capabilities=None)
        for rule in mechanisms['interactions']:
            if actor['champion'] != rule['participants'][0]:continue
            ids=interaction['allied_ids'] if rule['relationship']=='ally' else interaction['opponent_ids']
            for other in snapshot['heroes']:
                if other['entity_id'] in ids and other['champion']==rule['participants'][1]:
                    applicable.append(dict(rule_id=rule['id'],actor_id=actor['entity_id'],other_id=other['entity_id'],
                        status='conditions_unknown', required_conditions=copy.deepcopy(rule['requires']),
                        satisfied_conditions=None, reference_rule=copy.deepcopy(rule)))
    snapshot['foundation']=dict(schema='analysis-foundation-references/v1',champions=refs,
        human_experience=copy.deepcopy(human_cards['cards']),conditional_mechanisms=applicable,
        mechanism_sources=copy.deepcopy(mechanisms['sources']) if applicable else {},
        scope='References and conditional hypotheses; never automatically promoted to observed state',
        historical_experience_applicability='not_established_for_this_match',
        exact_client_compatibility='static patch 16.20.1; client build compatibility not independently verified')
    snapshot['analysis_contract']['usable'].extend(['source_checked_lineup_static_descriptions','historical_conditional_experience'])
    if towers is not None:snapshot['analysis_contract']['usable'].append('named_enemy_tower_visible_health_samples')
    snapshot['coverage']=dict(static_champions=len(refs),static_abilities=sum(len(r['abilities']) for r in refs.values()),
        unknown_champion_entity_ids=[h['entity_id'] for h in snapshot['heroes'] if h['champion'] is None],
        historical_experience_cards=len(human_cards['cards']),lineup_matching_conditional_rules=len(applicable),
        unresolved=['runtime_map_and_mode','navigation_binding_and_actual_arrival_time','minion_identity_and_waves',
                    'camp_identity_and_respawn','ward_and_area_vision','actual_casts_and_cooldowns',
                    'complete_inventory_and_undo_consumption','condition_complete_jungle_clear_records',
                    'more_lineup_interaction_rules'],complete_macro_analysis_ready=False)
    return snapshot


def render_context(snapshot):
    # Keep the existing core report; its old global gaps paragraph is superseded below.
    base=render_markdown(snapshot).split('## 当前缺口')[0]
    c=snapshot['coverage']
    lines=[base,'## 已连接的基础资料','',f"本局 {c['static_champions']} 名英雄、{c['static_abilities']} 个被动/技能来源；{c['historical_experience_cards']} 张历史真人经验卡。",
           '每名英雄均关联队友与对手。静态技能描述不代表当前技能可用；历史经验不直接给出本局行动结论。','',
           '## 敌塔可知观测','','| 名称 | 可见 | 生命采样 | 采样年龄（秒） |','| --- | --- | --- | --- |']
    for t in snapshot['world'].get('enemy_towers',{}).get('towers',[]):
        hp=(t['observed_now'] or {}).get('health')
        lines.append(f"| {t['identity']['name']} | {t['visible']} | {hp['value'] if hp else '未知'} | {round(hp['age_seconds'],3) if hp else '未知'} |")
    lines+=['','## 仍不能自动下结论的部分','',
        '地图/模式与导航绑定、实际到场时间、兵线/营地身份、区域视野、实际施法/冷却、完整背包与撤销/消耗、条件完整刷野记录仍缺。',
        f"本阵容匹配现有条件规则 {c['lineup_matching_conditional_rules']} 项；不匹配时不硬套潘森规则。",'',
        'JSON 保留原 macro-snapshot/v1 的时刻事实结构，另附 foundation 来源参考、coverage 缺口。分析仍须列证据、候选行动、机会成本和改变计划的条件。','']
    return '\n'.join(lines)
