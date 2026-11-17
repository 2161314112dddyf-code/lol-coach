"""Reproduce the HUD-clocked, reset-to-full Gromp clear in the 16.22 practice replay."""
import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from lol_coach.movement_1622 import iter_path_samples
from lol_coach.replay_container import container_info, packets

VIDEO_SHA = '89117fc721eef61a4fbb683a0c88bf3b5922dfdef3365ee5588a604047ccab01'
REPLAY_SHA = '2febca32e5e32b182ded7dcccdcc0f2c41405d51e41115b058a5f2d7824e3692'
START = (103.5158, 103.549566667)
END = (107.7347, 107.774366667)


def measure(video, replay, output):
    raw = replay.read_bytes()
    with video.open('rb') as f:
        video_digest = hashlib.file_digest(f, 'sha256').hexdigest()
    if hashlib.sha256(raw).hexdigest() != REPLAY_SHA or video_digest != VIDEO_SHA:
        raise ValueError('This annotation requires the reviewed video and replay pair')
    info = container_info(raw)
    player, = json.loads(info['metadata']['statsJson'])
    assert info['version'] == '16.22.836.1077' and player['SKIN'] == 'Pantheon'
    output.mkdir(parents=True, exist_ok=True)
    cam = cv2.VideoCapture(str(video))
    frames = []
    smite_icon = None
    n = 0
    max_icon_drift = 0
    try:
        # The MP4 has variable frame spacing. Use decoded PTS, not nominal frame rate.
        cam.set(cv2.CAP_PROP_POS_MSEC, START[0] * 1000)
        while True:
            ok, image = cam.read()
            pts = cam.get(cv2.CAP_PROP_POS_MSEC) / 1000
            if not ok or pts > END[1]+0.001:
                break
            assert image.shape[:2] == (1440, 2560)
            n += 1
            # D-icon and charge numeral are visibly constant across the action.
            icon = image[1266:1314, 1342:1390].astype('float32')
            if smite_icon is None:
                smite_icon = icon
            max_icon_drift = max(max_icon_drift, float(np.abs(icon-smite_icon).mean()))
            if any(abs(pts-t)<.0002 for t in (*START, *END)):
                name = f'pts-{pts:.6f}.jpg'
                encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 94])[1].tobytes()
                (output/name).write_bytes(encoded)
                frames.append(dict(pts=pts, file=name, sha256=hashlib.sha256(encoded).hexdigest()))
    finally:
        cam.release()
    assert len(frames)==4 and n>=90 and max_icon_drift<9
    packet, = [p for p in packets(raw) if p['stream']==1 and p['chunk']==69 and
               p['offset']==8848 and p['opcode']==0x267 and p['payload'].hex()=='3b3e085b42a7c1c1']
    death = packet['time']
    last_sample = max((s for s in iter_path_samples(raw, at_seconds=death) if s['entity_id']==0x400000ae),
                      key=lambda s:s['time_seconds'])
    elapsed = [round(END[0]-START[1], 4), round(END[1]-START[0], 4)]
    # Skills, items, health and Smite below were read on the four identified native video frames.
    # The separate metadata query supplies the selected rune page; terminal inventory is not used as its clock.
    result = dict(schema='observed-jungle-clear/v1', champion='Pantheon', build=info['version'],
                  map_id=11, mode='practice_tool', camp='gromp', camp_sequence=['ChaosOwlBear'],
                  level=18, item_ids=[6699,3031,3036,6333,2517], control_wards=2, trinket_id=3340,
                  perk_ids=[int(player[f'PERK{i}']) for i in range(6)],
                  stat_shards=[int(player[f'STAT_PERK_{i}']) for i in range(3)],
                  skill_ranks=dict(Q=5,W=5,E=5,R=3), solo=True, leash=False, smite_casts=0,
                  operations='After an earlier pull and full reset, re-engaged at full monster HP. Physical hits and abilities; Q/W/E entered cooldown, R remained available.',
                  start=dict(criterion='first hit after reset: no impact then 677 damage', hud_clock='03:15',
                             monster_hp=4818, hp=2684, mana=844, max_hp=2684, max_mana=844, position='at red-side Gromp'),
                  end=dict(criterion='last alive then first death reward +90', hud_clock='03:19', hp=2617, mana=670,
                           max_hp=2684, max_mana=844, level=18, camp='ChaosOwlBear',
                           last_observed_player_xz=last_sample['world_waypoints_xz'][0],
                           position_sample_time=last_sample['time_seconds'], position_source=last_sample['source'],
                           packet_time=death, packet_source=dict(chunk=69,offset=8848,opcode='0x267')),
                  start_video_bounds_seconds=list(START), end_video_bounds_seconds=list(END),
                  observed_elapsed_seconds=elapsed, uninterrupted_recording_frames=n,
                  max_smite_icon_mean_pixel_difference=round(max_icon_drift,4), frames=frames,
                  source_replay_sha256=REPLAY_SHA, source_video_sha256=video_digest,
                  rune_source='same-game terminal rune selection', reading='manual HUD annotation; source-bound reproducibility',
                  applicability='Historical full-health single Gromp after reset, level-18 five-item practice setup; no live ETA.',
                  decision_input_eligible=False)
    (output/'observed-clear.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    print(json.dumps(dict(elapsed=elapsed,n=n,death=death,smite_icon_drift=max_icon_drift)))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video',type=Path)
    parser.add_argument('replay',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    measure(args.video,args.replay,args.output)
