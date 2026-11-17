"""Project manually reviewed personal camp samples into a decision prefix."""
from copy import deepcopy
import json
from pathlib import Path

from .reasoning_frame import canonical, digest, number
from .round_chain import _check_bundle, _source


DEFAULT_CAMP_ROOT = Path(__file__).resolve().parents[1] / 'data/private/jungle_observations'


def attach_personal_camps(bundle, root=DEFAULT_CAMP_ROOT):
    frame = _check_bundle(bundle)
    d = frame['decision']
    source, actor = _source(bundle), d['player_entity_id']
    if not actor.startswith('0x') or not actor[2:] or any(c not in '0123456789abcdef' for c in actor[2:]):
        return bundle
    path = root / source / f'{actor}.json'
    if not path.is_file():
        return bundle
    record = json.loads(path.read_bytes())
    checksum = record.pop('record_sha256', None)
    if (digest(record) != checksum or record.get('schema') != 'personal-camp-hud/v1'
            or (record['source_sha256'], record['actor'], record['team_id'], record['build'])
            != (source, actor, d['observer_team_id'], d['build'])):
        raise ValueError('personal_camp_source_mismatch')
    # Keep only the latest engagement sample and latest completion per observed camp.
    # A later screenshot can never establish camp presence or the outcome at an earlier time.
    latest = {}
    for row in record['observations']:
        t = row['available_at_seconds']
        if not number(t) or t < 0 or row['state'] not in ('engaged', 'cleared'):
            raise ValueError('invalid_personal_camp_observation')
        if t <= d['at_seconds']:
            key = row['camp']
            if key not in latest or t > latest[key]['available_at_seconds']:
                latest[key] = row
    if not latest:
        return bundle
    result = deepcopy(bundle)
    frame = result['frame']
    ids = []
    for fid in frame.get('personal_camp_fact_ids', []):
        if frame['facts'][fid]['field'] != 'personal_jungle_camp_observation':
            raise ValueError('invalid_personal_camp_index')
        del frame['facts'][fid]
        result['audit']['fact_sources'].pop(fid, None)
    hp_path = path.with_suffix('.hud-hp.json')
    hp_frames = {}
    if hp_path.is_file():
        hp_record = json.loads(hp_path.read_bytes())
        hp_hash = hp_record.pop('record_sha256', None)
        if (hp_hash != digest(hp_record) or hp_record['schema'] != 'personal-camp-hp/v1'
                or (hp_record['actor'],hp_record['source_sha256'],hp_record['build']) != (actor,source,d['build'])):
            raise ValueError('personal_camp_hp_source_mismatch')
        hp_frames = hp_record['frames']
    for row in sorted(latest.values(), key=lambda r:r['available_at_seconds']):
        t = row['available_at_seconds']
        fields = ('camp', 'locator', 'state')
        if row['state'] == 'cleared':
            fields += ('observed_clear_seconds', 'reward_gold', 'reward_time_seconds')
            if not number(row['reward_time_seconds']) or not 0 <= row['reward_time_seconds'] <= t:
                raise ValueError('invalid_personal_camp_reward_time')
        value = {key:row[key] for key in fields}
        evidence = dict(row['evidence'])
        if row['state'] == 'engaged' and row['evidence'].get('sha256') in hp_frames:
            sample = hp_frames[row['evidence']['sha256']]
            full = hp_frames[sample['last_full_frame_sha256']]
            if ((sample['time'],sample['camp']) != (t,row['camp']) or full['camp'] != sample['camp']
                    or full['time'] != sample['last_full_at'] or not 0 <= full['time'] <= t
                    or not 0 < sample['monster_hp'] <= sample['full_hp'] == full['monster_hp']):
                raise ValueError('invalid_personal_camp_hp_sample')
            value.update(monster_hp=sample['monster_hp'], full_hp=sample['full_hp'], last_full_at=full['time'])
            evidence.update(hp_record_sha256=hp_hash, last_full_frame_sha256=sample['last_full_frame_sha256'])
        value['observer_team_id'] = d['observer_team_id']
        fact = dict(entity_id=actor, field='personal_jungle_camp_observation', value=value,
                    temporal_scope='historical_personal_camp_hud', observed_at_seconds=t,
                    age_seconds=d['at_seconds']-t)
        fid = 'f_' + digest(fact)[:20]
        frame['facts'][fid] = fact
        result['audit']['fact_sources'][fid] = dict(source_sha256=source, record_sha256=checksum,
                                                   evidence=evidence)
        ids.append(fid)
    frame['personal_camp_fact_ids'] = ids
    frame.pop('frame_id')
    frame['frame_id'] = 'frame_' + digest(frame)[:24]
    result['audit']['frame_chars'] = len(canonical(frame))
    return result
