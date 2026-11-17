"""Verify two first-clear HUD annotations against their original screenshots and ROFL."""
import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image

from lol_coach.file_model_bridge import atomic_json
from lol_coach.reasoning_frame import digest
from lol_coach.replay_container import container_info, packets
from lol_coach.round_camps import DEFAULT_CAMP_ROOT


SHA = '02fe29bdcd74eb69d182d5f22f2f2175f07a37a89df2cb44c83c6a5d3e0c744c'
ACTOR = '0x400000b4'
BUILD = '16.22.836.1077'
CASES = [
    dict(camp='blue', locator='ChaosBlueBuff1', clip=47, gold=90, level=1, monster_start_hp=2300,
         reviewed=[55.25,55.5,56,60,64,68,72,75,77,78,78.5,78.75],
         hp=[2300,2229,2150,1899,1662,1333,1081,831,752,673,652],
         frames_digest='25b59996c0b2f35a102880c5b7862b87683bbe4418bd545089279f225c9b35a8',
         chunk=5, reward=(322281,'fe3e0e5b4275c1cd'), entity_packet=(323639,0x40000327)),
    dict(camp='gromp', locator='ChaosOwlBear', clip=77, gold=80, level=2, monster_start_hp=2050,
         reviewed=[79.25,79.5,82,85,87,91,95,98,99.5,100,100.75,101],
         hp=[2050,1991,1705,1420,1303,986,517,312,112,83,23],
         frames_digest='60f0ba6e245987eb069733b4ba621f04f79816a91cddd30003b8e60d308a7153',
         chunk=6, reward=(179989,'bb3e0e5b42c5c1c1'), entity_packet=(180797,0x400004f6))]


def reviewed_frames(root, case):
    folder = root / f"clip-{case['clip']}"
    receipt = json.loads((folder/'receipt.json').read_bytes())
    if (receipt['source_replay_sha256'], receipt['build'], receipt['start'], receipt['fps']) != (SHA, BUILD, case['clip'], 4):
        raise ValueError('render receipt mismatch')
    frames = {}
    for t in case['reviewed']:
        name = f"{int((t-case['clip'])*4):06d}.png"
        path = folder/name
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if sha != receipt['frames'][name]:
            raise ValueError('HUD frame hash mismatch')
        frames[t] = dict(time=t, clip_start=case['clip'], file=name, sha256=sha)
    if digest([f['sha256'] for f in frames.values()]) != case['frames_digest']:
        raise ValueError('images differ from the reviewed annotations')
    return folder, frames


def hud_bars(path):
    with Image.open(path) as im:
        if im.size != (1280,720):
            raise ValueError('wrong HUD geometry')
        # Red roster second portrait, Pantheon, in both shots. Each bar spans 28 physical pixels.
        hp = sum(im.getpixel((x,208))[1] >= 75 for x in range(1231,1259))
        mana = sum(im.getpixel((x,214))[2] >= 95 for x in range(1231,1259))
        return dict(hp_bar_pixels=hp, mana_bar_pixels=mana, full_bar_pixels=28)


def save_verified(path, value):
    if path.is_file():
        if json.loads(path.read_bytes()) != value:
            raise ValueError(f'Existing evidence differs: {path}')
    else:
        atomic_json(path, value)


def measure(replay, root, player_state, output):
    raw = replay.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SHA:
        raise ValueError('unreviewed match')
    info = container_info(raw)
    footer, = [p for p in json.loads(info['metadata']['statsJson']) if p['SKIN']=='Pantheon']
    self_data = json.loads(player_state.read_bytes())
    if (info['version'], self_data['source_sha256'], self_data['team_id'], self_data['entity_id']) != (BUILD,SHA,200,ACTOR):
        raise ValueError('wrong self snapshot')
    samples = {row['time']:row['value'] for row in self_data['samples']}
    wanted = {(c['chunk'], c[k][0]) for c in CASES for k in ('reward','entity_packet')}
    anchors = {}
    for p in packets(raw):
        key = p['chunk'],p['offset']
        if p['stream'] == 1 and key in wanted:
            anchors[key] = p
            if len(anchors) == len(wanted):
                break
    record = dict(schema='personal-camp-hud/v1', source_sha256=SHA, actor=ACTOR, team_id=200, build=BUILD,
                  observations=[])
    historical = []
    monster_vitals = {}
    for c in CASES:
        folder, frames = reviewed_frames(root,c)
        times = list(frames)
        reward = anchors[c['chunk'],c['reward'][0]]
        dead = anchors[c['chunk'],c['entity_packet'][0]]
        death = reward['time']
        if (reward['opcode'] != 0x267 or reward['payload'].hex()!=c['reward'][1] or dead['opcode']!=0x2e7
                or dead['time']!=death or dead['param']!=c['entity_packet'][1] or not times[-2]<death<=times[-1]):
            raise ValueError('death window does not contain the reviewed reward/entity packets')
        # Every intermediate time below was separately read on the native video.
        # Do not send prior full HP, future reward or a duration with an engagement sample.
        for t in times[1:-1]:
            record['observations'].append(dict(camp=c['camp'], locator=c['locator'], state='engaged',
                available_at_seconds=t, evidence=frames[t]))
        for t, hp in zip(times[:-1], c['hp'], strict=True):
            monster_vitals[frames[t]['sha256']] = dict(camp=c['camp'], time=t, monster_hp=hp,
                full_hp=c['hp'][0], last_full_at=times[0], last_full_frame_sha256=frames[times[0]]['sha256'])
        duration = [round(death-times[1],4),round(death-times[0],4)]
        refs = dict(onset=[frames[times[0]], frames[times[1]]], death=[frames[times[-2]],frames[times[-1]]],
                    reward_packet=dict(stream=1,chunk=c['chunk'],offset=reward['offset'],opcode='0x267'),
                    entity_packet=dict(stream=1,chunk=c['chunk'],offset=dead['offset'],opcode='0x2e7',entity_id=hex(dead['param'])))
        record['observations'].append(dict(camp=c['camp'], locator=c['locator'], state='cleared',
            available_at_seconds=times[-1], observed_clear_seconds=duration, reward_time_seconds=death,
            reward_gold=c['gold'], evidence=refs))
        before = max(t for t in samples if t<=times[0])
        after = min(t for t in samples if t>=times[-1])
        historical.append(dict(schema='observed-jungle-clear/v1', champion='Pantheon', build=BUILD,
            camp=c['camp'], level=c['level'], mode='classic', solo=True, leash=False,
            monster_hp_before_first_damage=c['monster_start_hp'], start_game_time_bounds=times[:2],
            end_game_time_bounds=times[-2:], observed_elapsed_seconds=duration, observed_gold_reward=c['gold'],
            reward_time=death, before=dict(time=before,level=samples[before]['level'],inventory=samples[before]['inventory']),
            after=dict(time=after,level=samples[after]['level'],inventory=samples[after]['inventory']),
            start_player_bars=hud_bars(folder/frames[times[0]]['file']),
            end_player_bars=hud_bars(folder/frames[times[-1]]['file']),
            selected_runepage=[int(footer[f'PERK{i}']) for i in range(6)],
            stat_shards=[int(footer[f'STAT_PERK_{i}']) for i in range(3)],
            smite='ready then on cooldown at Blue death' if c['camp']=='blue' else 'already recharging at onset; exact charges unknown',
            skill_ranks=None, evidence=refs, source_replay_sha256=SHA, decision_input_eligible=False))
    record['record_sha256'] = digest(record)
    output.mkdir(parents=True,exist_ok=True)
    path = output/f'{ACTOR}.json'
    save_verified(path,record)
    vitals = dict(schema='personal-camp-hp/v1',actor=ACTOR, source_sha256=SHA,build=BUILD, frames=monster_vitals)
    save_verified(output/f'{ACTOR}.hud-hp.json',dict(vitals,record_sha256=digest(vitals)))
    save_verified(root/'ranked-clears.json',historical)
    print(json.dumps([(c['camp'],c['observed_elapsed_seconds'],c['end_player_bars']) for c in historical]))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('replay',type=Path)
    parser.add_argument('--capture-root',type=Path,default=Path('data/private/jungle-clear-20261116'))
    parser.add_argument('--player-state',type=Path,default=Path('data/private/player_state')/SHA/ACTOR/'native_replay_liveclient_allplayers_self.json')
    parser.add_argument('--output',type=Path,default=DEFAULT_CAMP_ROOT/SHA)
    args=parser.parse_args()
    measure(args.replay,args.capture_root,args.player_state,args.output)
