"""Evaluate optional external review labels across every scanned time."""
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lol_coach.review_evaluation import evaluate_scan_labels


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--sequence',type=Path,required=True);p.add_argument('--labels',type=Path)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.resolve()
    if not out.is_relative_to((ROOT/'data/private').resolve()):raise ValueError('Private output required')
    out.mkdir(parents=True,exist_ok=False);raw=a.sequence.read_bytes();s=json.loads(raw);labels=json.loads(a.labels.read_bytes()) if a.labels else []
    report=evaluate_scan_labels(s,labels);report['source_sequence_sha256']=hashlib.sha256(raw).hexdigest()
    report['labels_source_sha256']=hashlib.sha256(a.labels.read_bytes()).hexdigest() if a.labels else None
    (out/'evaluation.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    template=[dict(source_frame_id=r['frame_id'],at_seconds=r['at_seconds'],author=None,needs_reconsideration=None) for r in s['scan_decisions']]
    (out/'labels_template.json').write_text(json.dumps(template,indent=2),encoding='utf8');print(json.dumps(report))


if __name__=='__main__':main()
