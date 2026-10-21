"""Narrow byte candidates using actual component removals, with witnesses."""
from collections import defaultdict
import json
import struct
from research_inventory_events import ROOT
from research_inventory_constraints import CATALOG, compatible, extend, leb


def main():
    r=json.loads((ROOT/'data/research/inventory_events.json').read_text(encoding='utf8'))
    c=json.loads((ROOT/'data/research/inventory_constraints.json').read_text(encoding='utf8'))
    calibration=json.loads((ROOT/'data/research/inventory_calibration.json').read_text(encoding='utf8'))
    catalog=json.loads(CATALOG.read_text(encoding='utf8'))['data']
    mapping={int(k):v for k,v in c['item_byte_pairs'].items()}
    prices={int(k):v for k,v in c['price_byte_pairs'].items()}
    candidates={row['signature'][-4:]:set(row['candidates']) for row in c['signatures']}
    for code,value in calibration['item_labels'].items():candidates[code]={value}
    # Archangel transformation records are outside the normal-signature scan.
    for e in r['events']:
        if e['kind']=='slot_update' and e['item_wire'] not in candidates:
            code=e['item_wire']
            if code:
                candidates[code]={int(i) for i in catalog if compatible(mapping,leb(int(i)),bytes.fromhex(code)) and
                    (not e['price_wire'] or compatible(prices,struct.pack('<f',catalog[i]['gold']['total']),bytes.fromhex(e['price_wire'])))}
    def descendants(i):
        result=set()
        for component in catalog[str(i)].get('from',[]):
            component=int(component)
            result.add(component);result.update(descendants(component))
        return result
    state={};pending=defaultdict(list);relations=[]
    for e in r['events']:
        entity=e['entity_id'];slots=state.setdefault(entity,[None]*10);index=e['slot']
        if e['kind']=='slot_clear':
            pending[entity].append(dict(code=slots[index],time=e['time_seconds'],source=e['source']))
            slots[index]=None
        elif e['kind']=='slot_swap':
            other=e['other_slot']
            if other is None:other=calibration['swap_b'][e['other_slot_wire']]
            slots[index],slots[other]=slots[other],slots[index]
        else:
            for removed in pending[entity]:
                if removed['code'] and removed['code']!=e['item_wire'] and abs(e['time_seconds']-removed['time'])<0.002:
                    relations.append(dict(component_wire=removed['code'],result_wire=e['item_wire'],entity_id=entity,
                        time_seconds=e['time_seconds'],remove_source=removed['source'],update_source=e['source']))
            pending[entity]=[];slots[index]=e['item_wire']
    witnesses=[];conflicts=[]
    for _ in range(10):
        changed=False
        for relation in relations:
            old,new=relation['component_wire'],relation['result_wire']
            if len(candidates.get(old,set()))==1 and len(candidates.get(new,set()))>1:
                component=next(iter(candidates[old]))
                narrowed={i for i in candidates[new] if component in descendants(i)}
                if narrowed and narrowed!=candidates[new]:
                    witnesses.append({**relation,'result_before':sorted(candidates[new]),'result_after':sorted(narrowed),'component_item_id':component})
                    candidates[new]=narrowed;changed=True
                    if len(narrowed)==1:extend(mapping,leb(next(iter(narrowed))),bytes.fromhex(new))
            if len(candidates.get(new,set()))!=1 or not candidates.get(old):continue
            parent=next(iter(candidates[new]));allowed=descendants(parent)
            if not allowed:continue  # Transform/nonpurchase not a recipe.
            narrowed=candidates[old]&allowed
            if not narrowed:
                if relation not in conflicts:conflicts.append(relation)
                continue
            if narrowed!=candidates[old]:
                witnesses.append({**relation,'before':sorted(candidates[old]),'after':sorted(narrowed),'result_item_id':parent})
                candidates[old]=narrowed;changed=True
                if len(narrowed)==1:extend(mapping,leb(next(iter(narrowed))),bytes.fromhex(old))
        for code,values in candidates.items():
            narrowed={i for i in values if compatible(mapping,leb(i),bytes.fromhex(code))}
            if not narrowed:raise ValueError(f'Empty candidates {code}')
            if narrowed!=values:candidates[code]=narrowed;changed=True
        if not changed:break
    result=dict(status='RECIPE_CONSTRAINED_CANDIDATES',source_sha256=r['source_sha256'],
       candidates={code:sorted(values) for code,values in candidates.items()},
       item_byte_pairs=mapping,witnesses=witnesses,recipe_conflicts=conflicts,
       limitation='Component relation inferred from near-simultaneous removal/update. Catalog compatibility is tested only for observed recipes.')
    (ROOT/'data/research/inventory_recipes.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(codes=len(candidates),resolved=sum(len(v)==1 for v in candidates.values()),
       ambiguous={k:sorted(v) for k,v in candidates.items() if len(v)!=1},witnesses=witnesses,conflicts=conflicts),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
