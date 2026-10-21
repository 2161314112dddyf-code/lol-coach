"""Extract real video frames without OCR or inferred game coordinates."""
import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--step', type=float, default=5)
    parser.add_argument('--times', type=float, nargs='+')
    args = parser.parse_args()
    if args.step <= 0:
        parser.error('--step must be positive')
    cap = cv2.VideoCapture(str(args.video.resolve()))
    if not cap.isOpened():
        raise ValueError('Video could not be opened')
    fps = cap.get(cv2.CAP_PROP_FPS)
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if fps <= 0 or count <= 0:
        raise ValueError('Missing valid frame rate/count')
    args.output.mkdir(parents=True, exist_ok=True)
    metadata = {'source': str(args.video.resolve()),
                'sha256': hashlib.sha256(args.video.read_bytes()).hexdigest(),
                'size_bytes': args.video.stat().st_size, 'fps_reported': fps,
                'frame_count_reported': count, 'duration_seconds_derived': count / fps,
                'width': int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                'height': int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                'time_basis': 'frame index / reported FPS; game clock annotated separately',
                'frames': []}
    times = args.times or np.arange(0, count / fps, args.step).tolist()
    tiles = []
    for requested in times:
        index = round(requested * fps)
        if index < 0 or index >= count:
            raise ValueError(f'Frame outside video: {requested}')
        cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = cap.read()
        if not ok:
            raise ValueError(f'Cannot decode frame {index}')
        name = f'frame_{index:06d}.png'
        if not cv2.imwrite(str(args.output / name), frame):
            raise OSError('Failed to save frame')
        metadata['frames'].append({'index': index, 'video_seconds': index / fps,
                                   'reported_position_ms': cap.get(cv2.CAP_PROP_POS_MSEC),
                                   'file': name})
        width = 640
        tile = cv2.resize(frame, (width, round(frame.shape[0] * width / frame.shape[1])))
        tile = cv2.copyMakeBorder(tile, 28, 0, 0, 0, cv2.BORDER_CONSTANT)
        cv2.putText(tile, f'video {index / fps:.3f}s | frame {index}', (8, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, .55, (255, 255, 255), 1)
        tiles.append(tile)
    cap.release()
    for start in range(0, len(tiles), 8):
        group = tiles[start:start + 8]
        if len(group) % 2:
            group.append(np.zeros_like(group[0]))
        sheet = np.vstack([np.hstack(group[i:i+2]) for i in range(0, len(group), 2)])
        cv2.imwrite(str(args.output / f'sheet_{start // 8:02d}.jpg'), sheet)
    (args.output / 'manifest.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in metadata.items() if k != 'frames'}, indent=2))


if __name__ == '__main__':
    main()
