"""Bind damage numbers to actual tool calls; prose entailment needs separate review."""
from copy import deepcopy
from .reasoning_frame import digest, number


def damage_receipts(bundle, result):
    queries, receipts = {}, []
    for event in result['trace']:
        if event['event']=='model_response':
            for query in event['response'].get('tool_requests',[]):
                queries[query['id']] = query
        if event['event']!='tool_results':
            continue
        for output in event['results']:
            if output.get('name')!='calculate_ability_damage':
                continue
            query=queries.get(output['id'])
            value=output['content']
            if (not query or query['name']!=output['name']
                    or value['frame_id']!=bundle['frame']['frame_id']
                    or value['target_id']!=query['arguments']['target_id']
                    or value['assumptions']!=query['arguments']['assumptions']
                    or value['hits']!=query['arguments']['hits']):
                raise ValueError('damage receipt does not match the frozen query')
            runes=value.get('rune_damage') or {}
            health=query['arguments']['assumptions'].get('shield_scenario',{}).get('health_before')
            loss=runes.get('conditional_hp_loss_interval')
            remaining=None
            if number(health) and isinstance(loss,list) and len(loss)==2 and all(number(x) for x in loss):
                remaining=[max(0,health-loss[1]),max(0,health-loss[0])]
            receipts.append(dict(query=deepcopy(query),result_sha256=digest(value),
                frame_id=value['frame_id'],target=value.get('target'),
                conditional_damage_interval=runes.get('after_resistance_total_interval'),
                conditional_health_loss_interval=loss,conditional_health_remaining_interval=remaining,
                cast_sequence=value.get('cast_sequence'),conditions=value.get('conditions',[]),
                meaning='所选命中与假设下的计算；不证明实际命中、技能可用或击杀。'))
    return receipts


def render_damage_receipts(receipts):
    if not receipts:
        return ''
    lines=['','## 本次工具的条件算例','',
           '以下数值由查询回执生成；血盾、抗性和命中假设仅对该算例成立，不是实际扣血。','',
           '| 对象与命中 | 含已建模符文的伤害区间 | 条件下剩余生命 |',
           '| --- | --- | --- |']
    def fmt(values):
        if values is None: return '未知'
        return '～'.join(f'{v:.2f}' for v in values)
    for receipt in receipts:
        hits=' + '.join(h['slot']+'.'+h['component'] for h in receipt['query']['arguments']['hits'])
        lines.append(f"| {receipt['target']} · {hits} | {fmt(receipt['conditional_damage_interval'])} | "
                     f"{fmt(receipt['conditional_health_remaining_interval'])} |")
    return '\n'.join(lines)+'\n'
