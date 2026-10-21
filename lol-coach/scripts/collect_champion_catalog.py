"""Cache a fixed official champion catalog/details and normalize offline evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lol_coach.http import EvidenceClient,save_json
from lol_coach.champion import normalize


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline',action='store_true')
    args=parser.parse_args()
    patch='16.20.1';store=ROOT/'data/research/champion_catalog'
    client=EvidenceClient(store,timeout=12,retries=0,interval=.5)
    evidence,catalog=client.fetch('champion-catalog-'+patch,
        f'https://ddragon.leagueoflegends.com/cdn/{patch}/data/en_US/champion.json',expect_json=True,offline=args.offline)
    if not catalog or catalog.get('version')!=patch:raise ValueError('Fixed-version catalog unavailable')
    names=sorted(catalog['data']);rows=[];failed=[]
    out=ROOT/'data/normalized'/patch/'en_US/catalog';out.mkdir(parents=True,exist_ok=True)
    for index,name in enumerate(names):
        ref,data=client.fetch('champion-'+name+'-'+patch,
            f'https://ddragon.leagueoflegends.com/cdn/{patch}/data/en_US/champion/{name}.json',expect_json=True,offline=args.offline)
        if not data:
            failed.append(dict(champion=name,source=ref));continue
        normalized=normalize(data,name,patch,ref)
        if len(normalized['abilities'])!=5:raise ValueError('Incomplete basic ability set: '+name)
        path=out/(name+'.json');save_json(path,normalized)
        rows.append(dict(champion=name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),source=ref))
        if (index+1)%20==0:print(json.dumps(dict(processed=index+1,total=len(names),failed=len(failed))),flush=True)
    result=dict(schema='champion-catalog-evidence/v1',patch=patch,catalog_source=evidence,
        expected_names=names,normalized=rows,failures=failed,coverage_complete=set(names)=={r['champion'] for r in rows},
        scope='Official base stats/passive/QWER raw descriptions; not deep matchup mechanics or current cooldowns',
        exact_client_semantic_compatibility='not_independently_verified')
    save_json(out/'manifest.json',result)
    print(json.dumps(dict(total=len(names),normalized=len(rows),failed=len(failed),complete=result['coverage_complete'])),flush=True)
    if failed:raise SystemExit(1)


if __name__=='__main__':main()
