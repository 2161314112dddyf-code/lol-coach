"""Read every video frame; compare seeks and stabilize visible health bars.

Pixel stabilization is diagnostic only, not a world-coordinate measurement.
Regions refer to this manually inspected phone video, not a general detector.
"""
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / 'data/private/movement_11372643015'


def bar(frame, roi):
    x0, y0, x1, y1 = roi
    mask = cv2.inRange(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV), (25, 65, 115), (90, 255, 255))
    region = np.zeros_like(mask)
    region[y0:y1, x0:x1] = mask[y0:y1, x0:x1]
    region = cv2.morphologyEx(region, cv2.MORPH_OPEN, np.ones((1, 7), np.uint8))
    boxes = [cv2.boundingRect(c) for c in cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]]
    boxes = [b for b in boxes if 50 <= b[2] <= 85 and 3 <= b[3] <= 16 and b[2] / b[3] > 4]
    # Ambiguity remains missing; do not choose a convenient detection.
    return boxes[0] if len(boxes) == 1 else None


def background_mask(frame, box):
    mask = np.full(frame.shape[:2], 255, np.uint8)
    mask[:100] = 0
    mask[550:] = 0
    mask[:, :170] = 0
    if box:
        x, y, w, h = box
        mask[max(0, y-30):min(720, y+230), max(0, x-90):min(1280, x+w+90)] = 0
    return mask


def main():
    manifest = json.loads((PRIVATE / 'video_detail/manifest.json').read_text())
    source = Path(manifest['source'])
    if hashlib.sha256(source.read_bytes()).hexdigest() != manifest['sha256']:
        raise ValueError('Video source changed')
    destination = PRIVATE / 'timing'
    destination.mkdir(exist_ok=True)
    scenes = [
        {'id': 'fountain', 'frames': list(range(0, 34, 3)), 'reference': 0, 'roi': [570, 140, 710, 260], 'crop': [500, 140, 760, 440]},
        {'id': 'top_stop', 'frames': list(range(270, 364, 3)), 'reference': 330, 'roi': [560, 120, 740, 500], 'crop': [540, 150, 770, 480]},
        {'id': 'base_stop', 'frames': list(range(570, 634, 3)), 'reference': 600, 'roi': [370, 60, 690, 430], 'crop': [340, 190, 700, 570]},
        {'id': 'final_stop', 'frames': list(range(645, 748, 3)), 'reference': 744, 'roi': [420, 30, 1130, 430], 'crop': [600, 20, 1120, 400]},
    ]
    wanted = {n for s in scenes for n in s['frames']} | {s['reference'] for s in scenes}
    comparisons = {f['index']: f for f in manifest['frames']}
    cap = cv2.VideoCapture(str(source))
    frames, pts, seeks, count, prior, equal_neighbors = {}, [], [], 0, None, []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        pts.append(cap.get(cv2.CAP_PROP_POS_MSEC) / 1000)
        if count in wanted:
            frames[count] = frame
        if count in comparisons:
            saved = cv2.imread(str(PRIVATE / 'video_detail' / comparisons[count]['file']))
            seeks.append({'index': count, 'identical_pixels': bool(np.array_equal(frame, saved))})
        digest = hashlib.sha256(frame.tobytes()).digest()
        if digest == prior:
            equal_neighbors.append(count)
        prior = digest
        count += 1
    cap.release()
    if count != manifest['frame_count_reported'] or not all(x['identical_pixels'] for x in seeks):
        raise ValueError('Sequential read differs from prior evidence')
    reports = []
    orb = cv2.ORB_create(5000)
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    for scene in scenes:
        ref = frames[scene['reference']]
        ref_box = bar(ref, scene['roi'])
        if ref_box is None:
            raise ValueError('Reference bar is ambiguous: ' + scene['id'])
        kr, dr = orb.detectAndCompute(ref, background_mask(ref, ref_box))
        rows, tiles = [], []
        for index in scene['frames']:
            frame = frames[index]
            box = bar(frame, scene['roi'])
            row = {'frame': index, 'video_seconds': index / 30,
                   'reported_pts_seconds': pts[index], 'bar_box_pixels': box}
            if box is None:
                row['status'] = 'bar_missing_or_ambiguous'
                rows.append(row)
                continue
            k, d = orb.detectAndCompute(frame, background_mask(frame, box))
            good = [m for m, other in matcher.knnMatch(d, dr, k=2) if m.distance < .7 * other.distance]
            if len(good) < 30:
                row['status'] = 'insufficient_background_matches'
                rows.append(row)
                continue
            src = np.float32([k[m.queryIdx].pt for m in good])
            dst = np.float32([kr[m.trainIdx].pt for m in good])
            cv2.setRNGSeed(0)
            matrix, inside = cv2.findHomography(src, dst, cv2.RANSAC, 2)
            if matrix is None or int(inside.sum()) < 30:
                row['status'] = 'background_alignment_failed'
                rows.append(row)
                continue
            predicted = cv2.perspectiveTransform(src.reshape(-1, 1, 2), matrix).reshape(-1, 2)
            error = np.linalg.norm(predicted-dst, axis=1)[inside.ravel().astype(bool)]
            x, y, w, h = box
            center = cv2.perspectiveTransform(np.float32([[[x+w/2, y+h/2]]]), matrix)[0, 0]
            row.update(status='pixel_diagnostic_only', aligned_bar_center=center.tolist(),
                       background_inliers=int(inside.sum()), median_reprojection_error_pixels=float(np.median(error)))
            rows.append(row)
            if index % 15 == 0 or index == scene['frames'][-1]:
                aligned = cv2.warpPerspective(frame, matrix, (1280, 720))
                a, b, c, e = scene['crop']
                tile = aligned[b:e, a:c]
                tile = cv2.resize(tile, (260, 260))
                tile = cv2.copyMakeBorder(tile, 25, 0, 0, 0, cv2.BORDER_CONSTANT)
                cv2.putText(tile, f'{index/30:.2f}s | {index}', (5, 18), 0, .5, (255,255,255), 1)
                tiles.append(tile)
        while len(tiles) % 4:
            tiles.append(np.zeros_like(tiles[0]))
        sheet = np.vstack([np.hstack(tiles[i:i+4]) for i in range(0, len(tiles), 4)])
        cv2.imwrite(str(destination / (scene['id']+'.jpg')), sheet)
        reports.append({**scene, 'rows': rows})
    result = {'data_kind': 'real_video_pixel_diagnostics', 'video_sha256': manifest['sha256'],
              'sequential_frame_count': count, 'seek_comparisons': seeks,
              'max_pts_minus_index_over_fps_seconds': max(abs(t-i/30) for i,t in enumerate(pts)),
              'exact_duplicate_neighbor_frames': equal_neighbors,
              'scenes': reports,
              'limitations': ['Same video, not independent recording.', 'Health bar and ground homography give relative image motion, not world coordinates.',
                             'Parallax, HUD animation, compression and detector errors remain possible.', 'Movement events require visual review, not threshold-only classification.']}
    (ROOT / 'reports/video_timing_diagnostics.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'sequential_frames': count,
                      'seek_comparisons': len(seeks),
                      'all_seek_comparisons_identical': all(x['identical_pixels'] for x in seeks),
                      'scenes': [{'id': s['id'], 'sampled': len(s['rows']),
                                  'usable_pixel_diagnostics': sum(r['status'] == 'pixel_diagnostic_only' for r in s['rows'])}
                                 for s in reports],
                      'output': str(ROOT / 'reports/video_timing_diagnostics.json')}, indent=2))


if __name__ == '__main__':
    main()
