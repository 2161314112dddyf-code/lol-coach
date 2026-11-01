"""Connect scheduled inputs to verified lineup references and the existing runner."""
import argparse,hashlib,json,sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lol_coach.lineup_rules import build_lineup_bundle
from lol_coach.lineup_references import attach_lineup_references
from lol_coach.reasoning_frame import model_messages,lookup_reference
from lol_coach.decision_contract import output_schema
from lol_coach.round_chain import _check_bundle


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')


def main():
    p=argparse.ArgumentParser();p.add_argument('--sequence',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.resolve()
    if not out.is_relative_to((ROOT/'data/private').resolve()):raise ValueError('Private output required')
    out.mkdir(parents=True,exist_ok=False);sequence=json.loads((a.sequence/'sequence.json').read_bytes());mechanisms=build_lineup_bundle(ROOT/'data/research/champion_catalog')
    cnpath=ROOT/'docs/回合复盘方案_v0.1/CN_SOURCE_INDEX.json';cn=json.loads(cnpath.read_bytes());sources={r['url']:r for r in cn['sources']}
    jobs=[];coverage=None
    for row in sequence['selected']:
        original=a.sequence/row['path']/'bundle.json'
        if sha(original)!=row['bundle_sha256']:raise ValueError('Scheduled input changed')
        b=attach_lineup_references(json.loads(original.read_bytes()),mechanisms);_check_bundle(b)
        for rid in b['frame']['references']:lookup_reference(b,rid)
        folder=out/row['checkpoint_id'];folder.mkdir();write(folder/'bundle.json',b);write(folder/'messages.json',model_messages(b,output_schema()))
        jobs.append(dict(at_seconds=row['at_seconds'],checkpoint_id=row['checkpoint_id'],bundle=str(folder/'bundle.json'),bundle_sha256=sha(folder/'bundle.json'),frame_id=b['frame']['frame_id']))
        if coverage is None:
            heroes=[];principles=[]
            for hero in b['frame']['lineup']:
                ref=lookup_reference(b,'champion:'+hero['champion']);heroes.append(dict(champion=hero['champion'],entity_id=hero['entity_id'],
                    ally_count=len(hero['allied_ids']),opponent_count=len(hero['opponent_ids']),abilities=len(ref['abilities']),source_url=ref['source_url'],patch=ref['patch'],dynamic_readiness=None))
            for rid,desc in b['frame']['references'].items():
                if rid.startswith('principle:'):
                    source=sources.get(desc['source_url']);assert source is not None
                    assert source['reading_level'] not in ('entry_metadata','platform_generated_summary')
                    principles.append(dict(id=rid,url=desc['source_url'],reading_level=source['reading_level'],verified_cn_match_eval=source['eligible_for_verified_cn_match_eval']))
            coverage=dict(champions=heroes,conditional_interactions=b['audit']['lineup_reference_ids'],principles=principles,
                source_index_count=len(cn['sources']),reading_levels=dict(Counter(r['reading_level'] for r in cn['sources'])),
                source_index_sha256=sha(cnpath),new_sources_read=0,
                gap='This lineup has basic source coverage; pairwise mechanisms are partial. No dynamic readiness or verified CN match tactical labels.')
    result=dict(schema='ready-review-sequence/v1',sequence_sha256=sha(a.sequence/'sequence.json'),jobs=jobs,coverage=coverage,
        code_hashes={n:sha(ROOT/n) for n in ('lol_coach/lineup_references.py','scripts/finalize_review_sequence.py')},
        actual_model_calls=0,tactical_accuracy=None)
    write(out/'manifest.json',result);print(json.dumps(dict(prepared=len(jobs),heroes=len(coverage['champions']),abilities=sum(x['abilities'] for x in coverage['champions']),interactions=len(coverage['conditional_interactions']),principles=len(coverage['principles']))))


if __name__=='__main__':main()
