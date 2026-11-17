"""Project an independent public match onto the same single-player frozen-frame contract."""
import argparse
import hashlib
import io
import json
import tarfile
from pathlib import Path

import numpy as np

from lol_coach.file_model_bridge import atomic_json
from lol_coach.reasoning_frame import compile_frame
from scripts.check_public_replay_samples import checked_bytes, project
from scripts.reasoning import new_directory


def prepare(prefix, features, output):
    data = prefix.read_bytes()
    if hashlib.sha256(data).hexdigest() != '92667e7061966349b6fdefde7e607af38e189b514d24a60c603172bdbae18329':
        raise ValueError('unexpected pinned dataset prefix')
    case = '2877292_1'
    names = {case + '/meta.json', case + '/sequence.npz'}
    members = {}
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for member in archive:
            if member.name in names:
                members[member.name] = archive.extractfile(member).read()
            if members.keys() == names:
                break
    meta = json.loads(members[case + '/meta.json'])
    blob = members[case + '/sequence.npz']
    source = hashlib.sha256(blob).hexdigest()
    columns = json.loads(checked_bytes(features, 'features'))['X_champ']
    player, = [p for p in meta['participants'] if p['team'] == 100 and p['role'] == 'Jungle']
    with np.load(io.BytesIO(blob), allow_pickle=False) as arrays:
        # Fix clocks before reading a player's state. Both independent readers get identical inputs.
        for at in (300, 600):
            snapshot = project(arrays, meta, columns, at, 100, source, player_id=player['participant_id'])
            bundle = compile_frame(snapshot, max_principles=0)
            atomic_json(output / f'{at}.json', bundle)
    atomic_json(output / 'source.json', dict(match=case, build=meta['patch'], npz_sha256=source,
                observer_team=100, player=player['champion'], role=player['role'], clocks=[300, 600],
                ignored=['enemy state', 'postgame labels', 'future snapshots']))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--features', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.prefix, args.features, new_directory(args.output))
