"""Extract unchanged frames and clock crops from one already supplied video.

This creates diagnostic views only. It never reads predictions or labels arrivals.
"""
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
    args = parser.parse_args()
    video_hash = hashlib.sha256(args.video.read_bytes()).hexdigest()
    if video_hash != 'c71effa29b0af009a47fb24789dce4a503fc5398517d8425a3d46a5e91720522':
        raise ValueError('Expected original supplied video')
    args.output.mkdir(parents=True, exist_ok=False)
    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise ValueError('Video open failed')
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps != 30:
        raise ValueError('Unexpected FPS')
    wanted = set(range(327, 373)) | set(range(429, 445)) | set(range(582, 607))
    records, tiles = [], []
    index = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if index in wanted:
            path = args.output / f'frame_{index:06d}.png'
            if not cv2.imwrite(str(path), frame):
                raise OSError('Frame write failed')
            records.append(dict(frame=index,video_seconds=index/fps,
                reported_pts_seconds=cap.get(cv2.CAP_PROP_POS_MSEC)/1000,
                path=str(path.resolve()),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            if 327<=index<=372:
                # Exact source pixels retained separately; diagnostic nearest-
                # neighbour scaling only, never generative restoration or OCR.
                crop=frame[15:90,1180:1280]
                tile=cv2.resize(crop,(400,300),interpolation=cv2.INTER_NEAREST)
                tile=cv2.copyMakeBorder(tile,28,0,0,0,cv2.BORDER_CONSTANT)
                cv2.putText(tile,f'{index} | {index/fps:.3f}s',(8,20),0,.6,(255,255,255),1)
                tiles.append(tile)
        index+=1
    cap.release()
    sheets=[]
    for start in range(0,len(tiles),12):
        group=tiles[start:start+12]
        while len(group)%3:
            group.append(np.zeros_like(group[0]))
        sheet=np.vstack([np.hstack(group[i:i+3]) for i in range(0,len(group),3)])
        path=args.output/f'clock_sheet_{start//12:02d}.png'
        if not cv2.imwrite(str(path),sheet):
            raise OSError('Sheet write failed')
        sheets.append(dict(path=str(path.resolve()),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    result=dict(schema='existing-video-extraction/v1',video_path=str(args.video.resolve()),
        video_sha256=video_hash,implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        fps=fps,total_sequential_frames=index,records=records,clock_sheets=sheets,
        clock_crop_xyxy=[1180,15,1280,90],no_predictions_read=True,
        scope='Pure source extraction; human/AI visual review required; no inferred game coordinates')
    if index!=748 or len(records)!=len(wanted):
        raise ValueError('Frame coverage mismatch')
    with (args.output/'manifest.json').open('x',encoding='utf8') as handle:
        json.dump(result,handle,ensure_ascii=False,indent=2)
    print(json.dumps(dict(frames=index,selected=len(records),sheets=len(sheets),video_sha256=video_hash)))


if __name__=='__main__':
    main()
