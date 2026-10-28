"""Prepare paired synthetic inputs or check already generated model answers."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lol_coach.reasoning_simulation import prepare_cases,check_answers


def main():
    p=argparse.ArgumentParser(description=__doc__);subs=p.add_subparsers(dest='command',required=True)
    prep=subs.add_parser('prepare');prep.add_argument('--output',type=Path,required=True)
    check=subs.add_parser('check');check.add_argument('--cases',type=Path,required=True)
    check.add_argument('--answers',type=Path,required=True);check.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.command=='prepare':
        r=prepare_cases(a.output);print(json.dumps({'output':str(a.output),'case_ids':r['case_ids'],'synthetic':True}));return 0
    r=check_answers(a.cases,a.answers,a.output)
    print(json.dumps({'status':r['status'],'cases':len(r['cases']),'tactical_quality':r['tactical_quality']}))
    return 0 if r['status']=='PASS' else 2


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,OSError,KeyError) as exc:
        print('simulate_reasoning: '+str(exc),file=sys.stderr);raise SystemExit(2)
