"""Produce one evidence-linked conditional comparison, without a tactical score."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--snapshot',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    target=a.output.resolve();md=target.with_suffix('.md')
    if not target.is_relative_to((ROOT/'data/private/analysis').resolve()) or target.exists() or md.exists():
        raise ValueError('Choose new files under data/private/analysis')
    raw=a.snapshot.read_bytes();s=json.loads(raw)
    if s.get('schema')!='macro-snapshot/v1' or s['context']['observer_team_id']!=100:
        raise ValueError('This worked question is scoped to the 100-team sample')
    heroes={h['champion']:h for h in s['heroes']}
    if not all(k in heroes for k in ['Zyra','MasterYi','Veigar']):raise ValueError('Required matchup absent')
    if heroes['MasterYi']['visibility']['value'] is not True or heroes['MasterYi']['relation']!='enemy' or any(heroes[k]['relation']!='ally' for k in ['Zyra','Veigar']):
        raise ValueError('This question requires a currently visible enemy Yi and allied Zyra/Veigar')
    rules={r['rule_id']:r for r in s['foundation']['conditional_mechanisms']}
    if 'zyra_masteryi_slow_immunity' not in rules or 'veigar_zyra_control_followup' not in rules:raise ValueError('Grounded rules absent')
    facts=[]
    for name in ['Zyra','Veigar','MasterYi']:
        h=heroes[name]
        facts.append(dict(champion=name,entity_id=h['entity_id'],visibility=h['visibility'],
            health_sample=(h['observed_now'] or {}).get('health'),position_candidate=h['position_candidate']))
    actions=[
        dict(action='依靠婕拉植物减速限制剑圣后再接近',objective='限制追击或为集火创造窗口',
            rule_id='zyra_masteryi_slow_immunity',status='cannot_establish_now',
            conditional_reason='若剑圣大招在植物尝试减速时有效，不能把该减速计入收益；当前大招状态未解。',
            allied_follow_up='需要队友位置、可用技能与命中条件',enemy_response='剑圣大招的减速免疫及其他敌人的跟进',
            required_facts=['剑圣大招起止','植物身份与攻击目标','双方可用技能','正确地图与相关路线'],
            travel_and_execution_time=None,expected_end_state=None,benefit=None,risk=None,opportunity_cost=None,
            abort_or_replan_conditions=['确认剑圣大招有效时，取消依赖植物减速的收益估计','目标离开视野后不能沿用其当前位置']),
        dict(action='等待小法笼边控制条件，再用婕拉 E 衔接',objective='通过控制形成可跟进窗口',
            rule_id='veigar_zyra_control_followup',status='conditional_candidate_not_recommendation',
            conditional_reason='笼子存在与目标站在笼内都不等于已经晕眩；必须满足触碰笼边、可受控、婕拉 E 可用与命中条件。',
            allied_follow_up='需要参与队友实际可到场与伤害条件',enemy_response='规避笼边、规避藤蔓及其他可用反制',
            required_facts=['小法 E 可用性与笼边碰撞','婕拉 E 可用性与命中','目标免控状态','等待期间兵线和目标损失'],
            travel_and_execution_time=None,expected_end_state=None,benefit=None,risk=None,opportunity_cost=None,
            abort_or_replan_conditions=['没有笼边碰撞证据时不按已晕目标规划','队友无法跟进或等待成本过高时重新比较其他行动'])]
    out=dict(schema='conditional-action-comparison/v1',kind='project_reasoning_example_not_validated_tactical_recommendation',
        question='能否依靠婕拉减速或控制衔接，限制当时可见的剑圣？',context=s['context'],
        snapshot_sha256=hashlib.sha256(raw).hexdigest(),facts=facts,actions=actions,
        referenced_rules={k:rules[k] for k in ['zyra_masteryi_slow_immunity','veigar_zyra_control_followup']},
        evidence=s['evidence'],preferred_action=None,
        conclusion='可以指出各行动依赖什么、何种条件会失效；现有资料不能确定当时唯一最优行动，也不能计算必胜或必达。')
    lines=['# 一个时刻的条件行动比较','',out['question'],'',
           f"时刻：{s['context']['at_seconds']} 秒；观察队伍：100。项目推论示例，未做独立战术质量评价。",'',
           '| 英雄 | 可见 | 生命采样 | 观察时间 / 年龄（秒） | 证据 |','| --- | --- | --- | --- | --- |']
    for f in facts:
        h=f['health_sample'];lines.append(f"| {f['champion']} | {f['visibility']['value']} | {round(h['value'],2) if h else '未知'} | {str(round(h['observed_at_seconds'],3))+' / '+str(round(h['age_seconds'],3)) if h else '未知'} | {h['evidence_id'] if h else '无'} |")
    lines+=['','生命是带年龄的采样；位置仍为路径起点候选，不由它自动推算抵达。','']
    for action in actions:
        lines+=[f"## {action['action']}",'',action['conditional_reason'],'',
            '仍需：'+'、'.join(action['required_facts'])+'。','',
            '耗时、结束状态、收益、风险和机会成本：未确定。','',
            '改变计划的条件：'+'；'.join(action['abort_or_replan_conditions'])+'。','']
    lines+=[out['conclusion'],'','完整来源、规则条件和包证据见同名 JSON。','']
    target.write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8');md.write_text('\n'.join(lines),encoding='utf8')
    print(json.dumps(dict(output=str(target),facts=len(facts),actions=len(actions),preferred_action=None)))


if __name__=='__main__':main()
