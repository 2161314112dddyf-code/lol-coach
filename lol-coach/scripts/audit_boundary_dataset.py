"""Audit scan case hashes, time boundaries and replay grouping; optional external labels."""
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lol_coach.boundary_dataset import audit_cases


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--scan',type=Path,required=True)
    p.add_argument('--labels',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    out=a.output.resolve()
    if not out.is_relative_to((ROOT/'data/private').resolve()) or out.exists():raise ValueError('Use a new private output file')
    root=a.scan.resolve();summary=json.loads((root/'summary.json').read_bytes());cases=[]
    for row in summary['cases']:
        path=(root/row['file']).resolve()
        if not path.is_relative_to(root):raise ValueError('Case path escapes scan')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=row['sha256']:raise ValueError('Case changed')
        case=json.loads(raw)
        if case['split_group']!=row['split_group']:raise ValueError('Replay group changed')
        cases.append(case)
    result=audit_cases(cases,json.loads(a.labels.read_bytes()) if a.labels else [])
    result['scan_summary_sha256']=hashlib.sha256((root/'summary.json').read_bytes()).hexdigest()
    result['labels_source']=dict(path=str(a.labels),sha256=hashlib.sha256(a.labels.read_bytes()).hexdigest()) if a.labels else None
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,indent=2),encoding='utf8');print(json.dumps(result))


if __name__=='__main__':main()
