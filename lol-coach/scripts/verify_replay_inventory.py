"""Reproduce inventory corpus exports and prefix checks from the four files."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from export_replay_inventory import ROOT,build


def main():
    output=ROOT/'data/private/replay_inventory';output.mkdir(parents=True,exist_ok=True)
    rows=[]
    for name in ('11360086609','11363048522','11363093470','11372643015'):
        source=Path('C:/Users/21613/Documents/League of Legends/Replays')/f'HN1-{name}.rofl'
        result=build(source)
        path=output/(source.stem+'.json')
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        prefix=build(source,50)
        expected=[e for e in result['events'] if e['time_seconds']<=50]
        if prefix['events']!=expected:raise ValueError('Prefix contains changed/future events')
        for invalid in (-1,float('nan'),float('inf'),1000):
            try:build(source,invalid)
            except ValueError:pass
            else:raise ValueError('Invalid cutoff accepted')
        rows.append(dict(source=str(source),source_sha256=result['source_sha256'],counts=result['counts'],
            unresolved=len(result['unresolved']),state_barriers=len(result['state_barriers']),
            prefix_check='PASS',invalid_cutoff_check='PASS',output=str(path),output_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    economy=json.loads((ROOT/'reports/inventory_economy_validation.json').read_text(encoding='utf8'))
    suite=ET.parse(ROOT/'reports/pytest-replay-inventory.xml').getroot().find('testsuite')
    result=dict(task='RPL-003C',generated_at_utc=datetime.now(timezone.utc).isoformat(),
        target_version='16.20.824.8524',executed_by='Codex',independent_review=None,human_signoff=None,
        corpus=rows,pytest=dict(suite.attrib),economy_counts=economy['counts'],
        acceptance=[
          dict(id='DYN-03/observed-operations',status='PASS',scope='347 bounded packets in four supplied replays; 190 full-match updates map to 65 observed IDs'),
          dict(id='DYN-03/complete-inventory',status='INSUFFICIENT_EVIDENCE',scope='Undo/resync and consumption incomplete; two economy contradictions retained'),
          dict(id='DYN-05/prefix',status='PASS',scope='Prefix identity and invalid cutoff refusal on all four supplied files'),
          dict(id='DYN-02',status='INSUFFICIENT_EVIDENCE',scope='Cost anchors only; no accepted new cast decoder'),
          dict(id='DYN-04',status='INSUFFICIENT_EVIDENCE',scope='Team-correlated candidate payload, no visibility decoder')])
    (ROOT/'reports/replay_inventory_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(corpus=rows,pytest=result['pytest'],economy_counts=result['economy_counts']),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
