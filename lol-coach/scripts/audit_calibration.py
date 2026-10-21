"""Read explicitly supplied local evidence; save only allowlisted log fields."""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.calibration import parse_session_log, bind_bundle, inspect_track
from lol_coach.map_pipeline import load_bundle
from lol_coach.http import save_json


def source(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return raw, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--log', required=True)
    p.add_argument('--replay', required=True)
    p.add_argument('--track', required=True)
    p.add_argument('--game-id', required=True)
    p.add_argument('--patch', required=True)
    args = p.parse_args()
    try:
        log, log_ref = source(args.log)
        replay, replay_ref = source(args.replay)
        track_raw, track_ref = source(args.track)
        track = json.loads(track_raw)
        if track['source_sha256'] != replay_ref['sha256']:
            raise ValueError('Track is not associated with the supplied replay hash')
        if Path(args.replay).stem != 'HN1-' + args.game_id:
            raise ValueError('This audited adapter requires the HN1 replay filename to match GameID')
        session = parse_session_log(log.decode('utf-8', errors='strict'), args.game_id)
        if session['version'].encode() not in replay:
            raise ValueError('Log version string absent from replay bytes')
        grid, manifest = load_bundle(ROOT, args.patch, session['map_skin'])
        binding = bind_bundle(session, manifest)
        rows = inspect_track(track['track'], grid)
        report = {'schema_version': '0.1', 'created_at_utc': datetime.now(timezone.utc).isoformat(),
                  'data_kind': 'real_local_evidence_with_unverified_decoder_candidates',
                  'sources': {'log': log_ref, 'replay': replay_ref, 'track': track_ref},
                  'association_limit': 'GameID-to-replay link uses original filename; no new ROFL GameID decoder',
                  'session': session, 'asset_binding': binding,
                  'base_grid_sha256': grid.summary['raw_sha256'],
                  'origin_hypothesis': track['origin'], 'identity': track['identity'],
                  'user_annotations_from_prior_report': track['user_annotations'],
                  'candidate_records': rows,
                  'calibration_status': 'needs_independent_visual_observations',
                  'missing': ['independent position/landmark observations', 'map ID/mode evidence',
                              'active overlay selection and application semantics',
                              'unit-radius and collision checks', 'measured action completion states'],
                  'decision_input_eligible': False}
        out = ROOT / 'reports/calibration_audit.json'
        save_json(out, report)
        print(json.dumps({'output': str(out), 'candidate_records': len(rows), 'session': session,
                          'binding': binding, 'calibration_status': report['calibration_status']}, ensure_ascii=False, indent=2))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print('Calibration audit failed:', exc)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
