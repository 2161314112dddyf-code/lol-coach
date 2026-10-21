"""Archive public clear-guide entrypoints, retaining missing measurement conditions."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lol_coach.http import EvidenceClient

SOURCES=[
    ('yi-historical-guide','https://www.mobafire.com/league-of-legends/build/12-9-complete-guide-to-yi-pathing-builds-runes-etc-602700'),
    ('pantheon-video-entry','https://www.youtube.com/watch?v=we4j2iJe9HM')]


def main():
    p=argparse.ArgumentParser();p.add_argument('--offline',action='store_true');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    target=a.output.resolve()
    if not target.is_relative_to(ROOT/'data') or target.exists():raise ValueError('Choose a new data output')
    client=EvidenceClient(ROOT/'data/research/clear_sources',timeout=15,retries=0)
    rows=[]
    for name,url in SOURCES:
        source,_=client.fetch(name,url,offline=a.offline)
        row=dict(id=name,url=url,source=source,status='INSUFFICIENT_EVIDENCE',video_viewed=False,
            measured_record_accepted=False,actual_duration_seconds=None,end_health=None,end_resource=None,
            measured_skill_order=None,measured_items=None,measured_runes=None,smite_events=None,
            start_and_end_definition=None,end_position=None,end_level=None)
        if name=='yi-historical-guide' and source.get('http_status')==200:
            raw=(ROOT/'data/research/clear_sources'/source['evidence_path']).read_text(encoding='utf8')
            markers=['The Full Clear-Red Side','Time-3:15','0MKyejOOrEs']
            row['passage_markers_present']={m:m in raw for m in markers}
            if all(row['passage_markers_present'].values()):
                row.update(source_patch_claim='12.9 in guide title; embedded video build not independently checked',
                    source_claim_summary='Author describes red, krugs, raptors, wolves, then blue/gromp and labels the route 3:15.',
                    source_time_label_seconds=195,time_label_is_measured_elapsed=False,
                    linked_video='https://youtu.be/0MKyejOOrEs',current_patch_applicability=False)
        if name=='pantheon-video-entry' and source.get('http_status')==200:
            raw=(ROOT/'data/research/clear_sources'/source['evidence_path']).read_text(encoding='utf8')
            marker='ytInitialPlayerResponse = '
            if marker in raw:
                try:
                    player,_=json.JSONDecoder().raw_decode(raw.split(marker,1)[1])
                    row['page_playability_status']=player.get('playabilityStatus',{}).get('status')
                    details=player.get('videoDetails',{})
                    row['page_metadata']={k:details.get(k) for k in ('videoId','title','author','lengthSeconds')}
                except (ValueError,TypeError) as exc:
                    row['metadata_parse_error']=str(exc)
        rows.append(row)
    out=dict(schema='jungle-clear-source-candidates/v1',candidates=rows,accepted_complete_records=0,
        limitations=['HTML access is not video observation','Guide-wide builds are not the measured run loadout',
                    'Completion clock must not be treated as elapsed duration','End HP/resource and full conditions remain missing'])
    target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps([dict(id=r['id'],http_status=r['source']['http_status'],status=r['source']['status'],markers=r.get('passage_markers_present')) for r in rows]))


if __name__=='__main__':main()
