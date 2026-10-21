"""Cache fixed-patch object-name references, with bounded reads and failures."""
import argparse
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lol_coach.http import EvidenceClient,save_json


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--offline',action='store_true');args=parser.parse_args()
    client=EvidenceClient(ROOT/'data/research/object_sources',timeout=20,retries=0,max_bytes=32_000_000)
    rows=[]
    for name,path,is_json in [
        ('map12-base','data/maps/mapgeometry/map12/base.materials.bin.json',True),
        ('map12-bloom','data/maps/mapgeometry/map12/bloom.materials.bin.json',True),
        ('map12-bilgewater','data/maps/mapgeometry/map12/bilgewater.materials.bin.json',True),
        ('turret-records','data/characters/turret/turret.bin.json',True)]:
        ref,data=client.fetch(name,'https://raw.communitydragon.org/16.20/game/'+path,expect_json=is_json,offline=args.offline)
        rows.append(ref)
        print({k:ref.get(k) for k in ['source_id','status','http_status','sha256']},flush=True)
    save_json(ROOT/'reports/object_reference_materials.json',rows)


if __name__=='__main__':main()
