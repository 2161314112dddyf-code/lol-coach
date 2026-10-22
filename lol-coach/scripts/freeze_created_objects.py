"""Freeze bounded, evidence-derived model and position tables."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def main():
    folder=ROOT/'data/private/replay_completion'
    names=json.loads((folder/'pet_names_research.json').read_text())
    positions=json.loads((folder/'creation_positions_research.json').read_text())
    if names['unresolved']or positions['conflicts']:raise ValueError('Unresolved calibration contradictions')
    tables={tuple(m['table'])for m in positions['carry_models']}
    if len(tables)!=1:raise ValueError('Coordinate codec models disagree')
    full=list(next(iter(tables)))
    if sorted(full)!=list(range(256)):raise ValueError('Coordinate codec not bijective')
    profile=dict(version='16.20.824.8524',model_names=sorted({r['identity']['name']for r in names['rows']}),
        name_modes=names['specs'],position_byte_pairs={i:v for i,v in enumerate(full)},
        position_codec=dict(operations='swap adjacent bits; rotate-left 6; xor; add modulo 256; xor',
            parameters={k:v for k,v in positions['carry_models'][0].items()if k!='table'},
            observed_byte_count=len(positions['byte_pairs']),
            extrapolated_plain_bytes=[i for i in range(256)if str(i)not in positions['byte_pairs']]),
        position_gap_selector={0:16,1:16,2:16,3:15,4:15,6:15,7:16},
        calibration_scope=dict(name_anchor_records=len(names['anchors']),name_records_total=len(names['rows']),
            position_anchor_records=len(positions['anchors']),position_byte_coverage=len(positions['byte_pairs'])),
        sources=[dict(replay=Path(r['path']).name,sha256=r['sha256'])for r in names['sources']],
        limitations=['Four byte values use the uniquely fitted formula rather than direct calibration',
            'Header and owner/team fields not decoded','Model identity does not prove sight radius or vision grant'])
    (ROOT/'lol_coach/profiles/created_objects_16_20.json').write_text(json.dumps(profile,indent=2)+'\n')
    print(json.dumps(profile['calibration_scope']))


if __name__=='__main__':main()
