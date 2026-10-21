"""Offline entrypoint for time-specific context, movement evidence and travel queries."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lol_coach.action_evidence import conditional_travel,movement_timeline,render_timeline
from lol_coach.analysis_context import build_context,render_context
from lol_coach.lineup_rules import build_lineup_bundle
from lol_coach.ngrid import parse_ngrid
from lol_coach.path_audit import audit_polyline
from scripts.export_macro_snapshot import load_inputs


def load(path,inputs):
    raw=path.read_bytes();inputs.append(dict(path=str(path.resolve()),sha256=hashlib.sha256(raw).hexdigest()))
    return json.loads(raw)


def checked_human_cards(inputs):
    # Rebuild from reviewed source paraphrases, not free-form model completion.
    from scripts.collect_human_cases import CASES
    cards=load(ROOT/'data/knowledge/human_decision_cases.json',inputs)
    root=(ROOT/'data/research/human_sources').resolve()
    for card in cards['cards']:
        expected=next((c for c in CASES if c['id']==card['id']),None)
        if expected is None or any(card.get(k)!=v for k,v in expected.items()):
            raise ValueError('Human card differs from reviewed source interpretation')
        source=card['source'];path=(root/source['evidence_path']).resolve()
        if not path.is_relative_to(root) or source.get('http_status')!=200 or source.get('requested_url')!=card['url']:
            raise ValueError('Invalid human source')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=source['sha256'] or card['marker'] not in raw.decode('utf8'):
            raise ValueError('Human source evidence mismatch')
        inputs.append(dict(path=str(path),sha256=source['sha256']))
    return cards


def context(replay_id,at,team,player=None,window=30):
    bundles,inputs=load_inputs(replay_id)
    t=ROOT/'data/private/turret_state'/f'{replay_id}.json'
    v=ROOT/'data/private/tower_vision'/f'{replay_id}.json'
    paired=t.exists() and v.exists()
    towers=load(t,inputs) if paired else None
    vision=load(v,inputs) if paired else None
    cache=ROOT/'data/research/champion_catalog'
    cards=checked_human_cards(inputs)
    mechanics=build_lineup_bundle(cache)
    data=build_context(bundles,at=at,team=team,player=player,window=window,cache_root=cache,
        human_cards=cards,mechanisms=mechanics,towers=towers,tower_vision=vision)
    return data,render_context(data),inputs


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    c=sub.add_parser('context');c.add_argument('--replay-id',required=True);c.add_argument('--at',type=float,required=True)
    c.add_argument('--team',type=int,choices=(100,200),required=True);c.add_argument('--player');c.add_argument('--window',type=float,default=30)
    sub.add_parser('timeline')
    c=sub.add_parser('travel');c.add_argument('--points',required=True,help='JSON array of [x,z] game coordinates')
    c.add_argument('--speed',type=float,required=True);c.add_argument('--audit-map11',action='store_true',help='Audit against cached Map11 base grid; not a match-map binding')
    for c in sub.choices.values():c.add_argument('--output',type=Path,required=True)
    a=p.parse_args();target=a.output.resolve()
    if not target.is_relative_to((ROOT/'data/private/analysis').resolve()) or target.suffix!='.json':
        raise ValueError('Output must be JSON under data/private/analysis')
    outputs=[target,target.with_suffix('.md'),target.with_suffix('.manifest.json')]
    if any(f.exists() for f in outputs):raise ValueError('Choose new output files; existing evidence is never overwritten')
    inputs=[]
    if a.command=='context':data,md,inputs=context(a.replay_id,a.at,a.team,a.player,a.window)
    elif a.command=='timeline':
        report=load(ROOT/'reports/movement_video_validation.json',inputs)
        for field,pathkey in [('replay','path'),('video','source')]:
            path=Path(report[field][pathkey]);digest=hashlib.sha256(path.read_bytes()).hexdigest()
            if digest!=report[field]['sha256']:raise ValueError('Original movement source changed')
            inputs.append(dict(path=str(path),sha256=digest))
        data=movement_timeline(report);md=render_timeline(data)
    else:
        points=json.loads(a.points);data=conditional_travel(points,a.speed)
        if a.audit_map11:
            report=load(ROOT/'reports/replay_path_audit.json',inputs);source=report['grid_source']
            path=ROOT/'data'/source['evidence_path'];raw=path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=source['sha256']:raise ValueError('Grid hash mismatch')
            data['navigation_reference']=dict(map_id=11,asset_sha256=source['sha256'],
                input_coordinate_basis='caller_supplied_world_xz',runtime_map_binding=False,
                audit=audit_polyline(parse_ngrid(raw),points))
            inputs.append(dict(path=str(path),sha256=source['sha256']))
        md='# 条件路线计算\n\n'+json.dumps(data,ensure_ascii=False,indent=2)+'\n'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    target.with_suffix('.md').write_text(md,encoding='utf8')
    modules=['scripts/analysis.py','lol_coach/analysis_context.py','lol_coach/action_evidence.py',
             'lol_coach/macro_snapshot.py','lol_coach/tower_vision.py','lol_coach/replay_vision.py',
             'lol_coach/mechanism_rules.py','scripts/collect_human_cases.py','lol_coach/lineup_rules.py',
             'lol_coach/profiles/lineup_interactions_16_20_1.json','lol_coach/profiles/pantheon_mechanisms_16_20_1.json',
             'lol_coach/ngrid.py','lol_coach/path_audit.py']
    manifest=dict(schema='offline-analysis-artifacts/v1',inputs=inputs,
        implementation={m:hashlib.sha256((ROOT/m).read_bytes()).hexdigest() for m in modules},
        outputs={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in outputs[:2]},network_used=False)
    target.with_suffix('.manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(output=str(target),coverage=data.get('coverage'),events=len(data.get('events',[]))),ensure_ascii=False))


if __name__=='__main__':main()
