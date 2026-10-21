"""Curated, provenance-checked mechanic claims and source-reported clear candidates."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lol_coach.http import save_json
from lol_coach.map_selection import verified_bytes
from lol_coach.clear_sources import extract_clear_candidates

official=json.loads((ROOT/'data/normalized/16.20.1/en_US/Ivern.json').read_text(encoding='utf-8'))
raw=json.loads(verified_bytes(ROOT/'data',official['source']))
if raw['version']!='16.20.1' or raw['data']['Ivern']['key']!='427':raise ValueError('Wrong official sample')
meraki_source=next(r for r in json.loads((ROOT/'reports/source_audit.json').read_text(encoding='utf-8')) if r['source_id']=='meraki-ivern')
meraki=json.loads(verified_bytes(ROOT/'data',meraki_source))
sheet_source=next(r for r in json.loads((ROOT/'reports/entry_evidence.json').read_text(encoding='utf-8')) if r['source_id']=='clear-sheet')
candidates=extract_clear_candidates(verified_bytes(ROOT/'data',sheet_source).decode('utf-8'),'Ivern')
save_json(ROOT/'data/normalized/clear_candidates/Ivern.json',{'champion':'Ivern','source':sheet_source,
           'license_or_reuse_permission':'unverified_local_evidence_only','candidates':candidates})

# Explicitly reviewed summaries; implications are analysis, not quotations from sources.
specs=[
 ('passive','grove_cycle','野怪营地需经历种植、成长、解放；静态描述没有给出本局耗时。',
  ['队友是否协助守护营地、是否需要同时支援'],['对手是否可入侵、营地是否已被处理'],
  '不能将艾翁的刷野行为统一建模为持续攻击野怪。','data.Ivern.passive.description'),
 ('Q','ally_followup','Q 命中敌人造成伤害与禁锢，并允许队友向被禁锢目标突进。',
  ['哪些队友在可跟进位置','队友当前攻击距离、位移与控制状态'],['目标当前位置、控制/免控状态','其他敌方英雄能否反打'],
  '命中后的行动价值取决于谁能跟进及落点风险，不能只看自身伤害。','data.Ivern.spells[0].description'),
 ('W','brush_and_attacks','官方描述包含创造草丛，以及艾翁和附近队友在草丛中的普攻增益。',
  ['队友是否能持续普攻','队友与草丛的相对位置'],['敌方是否可利用草丛接近','敌方可见性及反制能力'],
  '草丛会改变局部信息和攻击条件；不能默认它只给己方收益。','data.Ivern.spells[1].description'),
 ('E','ally_shield_explosion','E 为友方提供护盾，延迟爆炸伤害并减速敌人。',
  ['可施加护盾的队友及其位置','队友即将受到的威胁和移动计划'],['爆炸时敌人与护盾目标的距离','敌方控制和追击条件'],
  '护盾目标与队友移动会影响保护和爆炸收益，应分别比较。','data.Ivern.spells[2].description'),
 ('R','daisy_control','召唤小菊协助战斗，重施放可下达攻击或移动指令。',
  ['队友是否能配合控制、分担承伤'],['敌方能否击杀或控制小菊','敌方英雄与路线位置'],
  '需要将小菊状态和指令纳入行动后状态，不能只把它当一次伤害。','data.Ivern.spells[3].description')]
claims=[]
for slot,identifier,claim,allies,enemies,inference,pointer in specs:
    claims.append({'id':identifier,'slot':slot,'claim_zh':claim,
                   'evidence':{'source':'official_ddragon','json_pointer_description':pointer},
                   'evidence_status':'official_versioned_description_not_in_game_interaction_test',
                   'ally_context_required':allies,'opponent_context_required':enemies,
                   'analysis_implication':{'text':inference,'origin':'project_analysis_not_source_quote'},
                   'numeric_action_duration_seconds':None,'match_applicability':'unknown_without_match_state'})
conflict={'id':'E_refresh_condition','official_pointer':'data.Ivern.spells[2].description',
          'official_summary':'未命中敌人时护盾刷新。',
          'meraki_pointer':'abilities.E[0].effects[2].description',
          'meraki_summary':'未伤害敌方英雄且原护盾在持续时间结束时仍存在，才重新施加护盾。',
          'status':'condition_scope_discrepancy_unresolved','runtime_rule':None,
          'needed_cases':['爆炸只命中小兵/野怪','护盾先被打破且爆炸未命中英雄','命中敌方英雄'],
          'do_not_infer':'不从简短官方描述或版本不明社区条目单独生成精确刷新规则'}
review={'schema_version':'0.1','champion':'Ivern','data_kind':'curated_static_mechanic_claims_not_simulation',
        'sources':{'official_ddragon':official['source'],'meraki':meraki_source},
        'official_data_version':'16.20.1','client_compatibility':'not_verified',
        'meraki_version_status':'unverified_latest','meraki_patch_last_changed':meraki.get('patchLastChanged'),
        'claims':claims,'unresolved_discrepancies':[conflict],
        'lineup_specific_recommendations':None,'full_clear_duration_seconds':None,
        'limitations':['No ally/opponent roster or contemporaneous visibility supplied',
                       'Meraki numeric timings are not accepted as current-patch measurements',
                       'Source-reported clear times are not observed action durations']}
save_json(ROOT/'data/normalized/16.20.1/en_US/Ivern.mechanics.json',review)
print(json.dumps({'claims':len(claims),'unresolved_discrepancies':1,'source_reported_clear_candidates':len(candidates),
                  'usable_measured_action_samples':0},indent=2))
