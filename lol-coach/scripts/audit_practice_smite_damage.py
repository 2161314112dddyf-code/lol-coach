"""Check one manually annotated, source-bound Smite hit against the damage calculator."""
import argparse
import hashlib
import json
from pathlib import Path

import cv2

from lol_coach.damage_calculator import calculate_damage
from lol_coach.replay_container import container_info
from lol_coach.wad import WadReader
from scripts.audit_practice_gromp import REPLAY_SHA, VIDEO_SHA


# Original video PTS, displayed target HP and D charges. The first row separates
# the preceding physical hit. The target panel updates after the floating text.
HUD = (
    (119.903367, 9712, 2), (119.943900, 9458, 2), (119.976567, 9458, 1),
    (120.018133, 9458, 1), (120.050500, 8058, 1), (120.766933, 8058, 1),
)
SMITE_HUD_DAMAGE = 1400
TABLE_SHA = 'a66c16185f2b2e224564230014e1c178f513526e7633f43c64148afa6de64fc9'


def measure(video, replay, locale_wad, output):
    with video.open('rb') as file:
        video_sha = hashlib.file_digest(file, 'sha256').hexdigest()
    raw = replay.read_bytes()
    if video_sha != VIDEO_SHA or hashlib.sha256(raw).hexdigest() != REPLAY_SHA:
        raise ValueError('HUD annotations require the reviewed video and ROFL')
    info = container_info(raw)
    player, = json.loads(info['metadata']['statsJson'])
    if info['version'] != '16.22.836.1077' or player['SKIN'] != 'Pantheon':
        raise ValueError('unexpected build or player')
    table, source = WadReader(locale_wad).extract_bytes('data/menu/en_us/lol.stringtable', 40_000_000)
    type_binding = b'<trueDamage>@spell.SummonerSmite:Smite2ndUpgradedDamage@ true damage</trueDamage>'
    if source['sha256'] != TABLE_SHA or type_binding not in table:
        raise ValueError('expected the reviewed Primal Smite monster-damage tooltip')
    output.mkdir(parents=True, exist_ok=True)
    camera = cv2.VideoCapture(str(video))
    frames = []
    try:
        camera.set(cv2.CAP_PROP_POS_MSEC, (HUD[0][0] - 0.2) * 1000)
        for time, hp, charges in HUD:
            while True:
                ok, frame = camera.read()
                pts = camera.get(cv2.CAP_PROP_POS_MSEC) / 1000
                if not ok or pts > time + 0.0002:
                    raise ValueError(f'reviewed video frame missing at {time}')
                if abs(pts - time) < 0.0002:
                    break
            name = f'smite-{time:.6f}.jpg'
            encoded, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
            if not encoded:
                raise ValueError('could not encode evidence frame')
            data = buf.tobytes()
            (output / name).write_bytes(data)
            frames.append(dict(video_pts=pts, hp=hp, d_charges=charges, image=name,
                               image_sha256=hashlib.sha256(data).hexdigest()))
    finally:
        camera.release()

    after = calculate_damage([dict(label='Primal Smite', damage_type='true', raw_damage=SMITE_HUD_DAMAGE)])
    observed_loss = frames[1]['hp'] - frames[4]['hp']
    if observed_loss != after['after_resistance_total']:
        raise AssertionError('observed health loss does not match the calculated damage')
    receipt = dict(
        schema='observed-smite-damage/v1', source_video_sha256=video_sha, source_replay_sha256=REPLAY_SHA,
        build=info['version'], player='Pantheon', target='Cloud Drake', mode='practice_tool',
        player_level=18, target_level=18, target_max_hp=10000, target_panel_mr=100,
        player_panel_ad=416, player_panel_ap=0, source_frames=frames,
        damage_type_binding=dict(tooltip='Primal Smite against monsters', source=source,
                                 token=type_binding.decode()),
        official_tier_source='https://www.leagueoflegends.com/en-us/news/game-updates/patch-26-1-notes/',
        advertised_raw_damage=SMITE_HUD_DAMAGE, floating_white_damage=1400,
        observed_hp_loss=observed_loss, calculated_damage=after['after_resistance_total'],
        status='matched_one_true_damage_event',
        method='Manual readings of the native video frames bound to their input hash and PTS. '
               'The enhanced jungle spell HUD shows 1400 before the hit; D loses one charge. '
               'Target panel updates on the subsequent frames. No OCR or hit attribution from the replay.',
        scope='One monster-targeted Smite. The target panel MR is a displayed stat; no effective '
              'resistance is required by this calculation. No Pantheon skill or resistance curve validated.',
    )
    (output / 'observed-smite.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n',
                                                encoding='utf-8')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', type=Path)
    parser.add_argument('replay', type=Path)
    parser.add_argument('locale_wad', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    evidence = measure(args.video, args.replay, args.locale_wad, args.output)
    print(json.dumps({key: evidence[key] for key in ('status', 'observed_hp_loss', 'calculated_damage')}))
