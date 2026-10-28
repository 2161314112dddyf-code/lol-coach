"""Check bounded affiliation decoding against the calibration and repeats.

This reports calibration consistency separately from repeated observations.
Neither category is independent game UI confirmation.
"""
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from export_replay_ten import reference
from export_skill_ranks import STEMS


def main():
    folder=ROOT/'data/private/replay_completion';repeat_checks=[];all_rows=[];sources=[]
    for stem in STEMS:
        path=folder/(stem+'-created-objects.json');bundle=json.loads(path.read_text(encoding='utf8'))
        if reference(Path(bundle['source']['path']))!=bundle['source']:raise ValueError('Replay changed')
        sources.append(reference(path));seen={}
        for row in bundle['events']:
            value=row['identity'];signature=(value['model_name'],value.get('team_label'),value.get('reference_entity_id'))
            if row['entity_id']in seen:
                old=seen[row['entity_id']]
                repeat_checks.append(dict(replay=stem,entity=row['entity_id'],model_team_stable=old[:2]==signature[:2],
                    reference_stable_or_unknown=old[2]is None or signature[2]is None or old[2]==signature[2]))
            seen[row['entity_id']]=signature
        all_rows.extend(bundle['events'])
    calibration=json.loads((folder/'creation_reference_research.json').read_text(encoding='utf8'))
    full=json.loads((folder/(STEMS[0]+'-created-objects.json')).read_text(encoding='utf8'))
    lookup={(r['entity_id'],r['time_seconds']):r for r in full['events']if r['source']['stream']==1}
    anchors=[]
    for anchor in calibration['anchors']:
        row=lookup[anchor['entity_id'],anchor['time']]
        anchors.append(dict(anchor,decoded=row['identity'].get('reference_entity_id'),
            consistent=row['identity'].get('reference_entity_id')==anchor['parent']))
    lanes=json.loads((folder/(STEMS[0]+'-lane-identities.json')).read_text(encoding='utf8'))
    supers=[r for r in lanes['events']if r['identity']['kind']=='super']
    source_meta=json.loads((ROOT/'data/research/rpl008_unit_sources/sources_corrected.json').read_text(encoding='utf8'))
    static_checks=[]
    for src in source_meta:
        raw=(ROOT/'data/research/rpl008_unit_sources'/src['evidence_path']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=src['sha256']:raise ValueError('Static minion source changed')
        static_checks.append(dict(url=src['final_url'],sha256=src['sha256'],verified=True))
    summary=dict(records=len(all_rows),team_labels=sum(r['identity'].get('team_label')is not None for r in all_rows),
        decoded_references=sum(r['identity'].get('reference_entity_id')is not None for r in all_rows),
        calibration_anchors=len(anchors),anchor_conflicts=sum(not a['consistent']for a in anchors),
        repeat_checks=len(repeat_checks),repeat_conflicts=sum(not c['model_team_stable']or not c['reference_stable_or_unknown']for c in repeat_checks),
        super_crosschecks=len(supers))
    if summary['anchor_conflicts']or summary['repeat_conflicts']:raise ValueError('Affiliation contradiction')
    report=dict(summary=summary,sources=sources,anchors=anchors,repeats=repeat_checks,
        static_sources=static_checks,super_evidence=supers,
        limitations=['Reference is not ownership: neutral Poro can reference a hero',
        'Neutral label does not claim numeric team 300','Static sources pin patch 16.20, not exact platform build',
        'Neither affiliation nor super classification proves region visibility'])
    (folder/'creation_affiliation_validation.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(summary))


if __name__=='__main__':main()
