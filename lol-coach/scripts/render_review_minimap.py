"""Render one verified early-game Map11 snapshot from a personal-review bundle."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageFont

from lol_coach.round_chain import _check_bundle, _source


RECENT_SECONDS = 1.0
LANES = ('top', 'mid', 'bot')
BLUE, RED = '#64c9ff', '#ff827d'
INK, MUTED, GOLD = '#f0f4f4', '#afc0c1', '#ffe28b'


def project(xz, extent, size):
    x0, z0, x1, z1 = extent
    x, z = xz
    if not (x0 <= x <= x1 and z0 <= z <= z1):
        return None
    return round((size-1)*(x-x0)/(x1-x0)), round((size-1)*(z1-z)/(z1-z0))


def snapshot(bundle, assets, *, terrain=None):
    frame = _check_bundle(bundle)
    task, d = frame['task'], frame['decision']
    origin = task.get('review_origin') or {}
    if origin.get('perspective') != 'personal' or not origin.get('match_id') or origin.get('replay_sha256') != _source(bundle):
        raise ValueError('requires_source_bound_personal_review')
    if d['build'] != assets['build']:
        raise ValueError('map_and_replay_build_mismatch')
    if terrain is not None and (terrain.get('schema')!='native-minimap-variant/v1'
            or terrain.get('source_sha256')!=_source(bundle) or terrain.get('frame_id')!=frame['frame_id']
            or terrain.get('build')!=d['build'] or terrain.get('at')!=d['at_seconds']):
        raise ValueError('terrain_evidence_mismatch')
    if d['at_seconds'] > 320 and terrain is None:
        raise ValueError('later terrain requires native evidence at the same replay tick')
    hero_lookup = {h['entity_id']: h for h in frame['lineup']}
    at, team = d['at_seconds'], d['observer_team_id']
    result = dict(origin=origin, frame_id=frame['frame_id'], at=at, team=team,
                  player=hero_lookup[d['player_entity_id']]['champion'], lanes={}, heroes=[], minions=[], personal_pings=[])
    for fid, fact in frame['facts'].items():
        value, field = fact['value'], fact['field']
        if field=='map_ping_sent' and fid in frame.get('recent_team_pings',{}).get('fact_ids',[]):
            area=value.get('marker_region') or {}
            if (fact['entity_id']==d['player_entity_id'] and value.get('known_as')=='own_sent'
                    and value.get('observer_team_id')==team and area.get('basis')=='native_hud_ring_estimate'
                    and area.get('map_id')==11 and fact['observed_at_seconds']<=area['observed_through_seconds']<=at
                    and 'xz_rounded_to_100' in area):
                result['personal_pings'].append(dict(kind=value['kind'],xz=area['xz_rounded_to_100'],
                    at=fact['observed_at_seconds'],available_at=area['observed_through_seconds'],
                    description=area['description'],fact_id=fid,exact_packet_xz=None))
        if field == 'lane_current_units_and_groups':
            if value.get('observer_team_id') != team or value.get('count_scope') != 'own_team_observed_live_only':
                raise ValueError('inconsistent_lane_scope')
            lane = value['lane']
            counts = Counter()
            for unit in value['units']:
                counts['registered'] += 1
                pos, when = unit['last_xz'], unit['sampled_at']
                if pos is not None and when is not None and 0 <= at-when <= RECENT_SECONDS:
                    counts['recent'] += 1
                    result['minions'].append(dict(lane=lane, kind=unit['kind'], xz=pos, sampled_at=when, fact_id=fid))
            result['lanes'][lane] = dict(registered=counts['registered'], recent=counts['recent'])
        elif field in ('observer_visibility', 'allied_path_start_sample'):
            entity = fact['entity_id'].removeprefix('entity:')
            hero = hero_lookup.get(entity)
            if not hero:
                continue
            if field == 'observer_visibility':
                if hero['relation'] != 'enemy' or value.get('team_id') != team or value.get('visible') is not True:
                    continue
                sample = value.get('last_observed_position') or {}
                pos, when = sample.get('xz'), sample.get('sampled_at')
            else:
                if hero['relation'] != 'ally' or value.get('observer_team_id') != team:
                    continue
                pos, when = value.get('xz'), fact['observed_at_seconds']
            if pos is not None and when is not None and 0 <= at-when <= RECENT_SECONDS:
                result['heroes'].append(dict(champion=hero['champion'], ally=hero['relation']=='ally',
                    player=entity==d['player_entity_id'], xz=pos, sampled_at=when, fact_id=fid))
    if set(result['lanes']) != set(LANES):
        raise ValueError('missing_three_lane_evidence_use_lane_replay')
    return result


def render(data, assets, texture, icons, font_path, out):
    fonts = {n: ImageFont.truetype(str(font_path), n) for n in (11, 14, 16, 18, 20, 26)}
    canvas = Image.new('RGB', (820, 592), '#121c20')
    draw = ImageDraw.Draw(canvas)
    def label(x, y, s, n=16, fill=INK):
        draw.text((x, y), s, font=fonts[n], fill=fill, anchor='lt')
    def circle(p, r, fill, outline):
        x,y=p
        draw.ellipse((x-r,y-r,x+r,y+r),fill=fill,outline=outline,width=2)
    def marker(xz):
        pt = project(xz, assets['world_extent'], 512)
        return (pt[0]+16, pt[1]+64) if pt is not None else None
    side = '蓝方' if data['team']==100 else '红方'
    t = int(data['at'])
    label(16, 18, '召唤师峡谷', 26)
    player_name = {'Pantheon':'潘森'}.get(data['player'],data['player'])
    label(178, 25, f'{t//60:02}:{t%60:02}   /   {side} · {player_name}', 20)
    background = Image.open(texture).convert('RGBA').resize((512,512),Image.Resampling.LANCZOS)
    canvas.paste(background, (16,64), background)
    draw.rectangle((15,63,528,576),outline='#455958')
    tower_file = Path(__file__).resolve().parents[1]/'lol_coach/profiles/turret_map11_16_22.json'
    towers = json.loads(tower_file.read_bytes())
    if towers['version'] != assets['build']:
        raise ValueError('tower_build_mismatch')
    for tower in towers['towers']:
        if tower['role']=='Root':
            continue
        x,y=marker(tower['xz'])
        color='#80caeb' if tower['team']==100 else '#eb9090'
        draw.polygon([(x-4,y-4),(x+4,y-4),(x+3,y+2),(x,y+5),(x-3,y+2)],fill='#172a30',outline=color)
    labels = dict(blue='蓝',red='红',wolves='狼',raptors='锋喙鸟',krugs='石甲虫',gromp='魔沼蛙',
                  scuttle='河蟹',dragon='龙坑',baron='上河坑')
    for camp in assets['camps']:
        position = marker(camp['xz'])
        if position:
            x,y = position
            kind=camp['kind']
            color={'blue':'#80baff','red':'#ea8f78','scuttle':'#abcfbc'}.get(kind,'#dcc7a0')
            r=5 if kind in ('dragon','baron','blue','red') else 3
            draw.polygon([(x,y-r),(x+r,y),(x,y+r),(x-r,y)], fill='#18211c',outline=color,width=2)
            draw.text((x+r+1,y-2),labels[kind],font=fonts[11],anchor='lm',fill='#e3e1cc',
                      stroke_width=1,stroke_fill='#1b2526')
    for unit in data['minions']:
        pt = marker(unit['xz'])
        if pt:
            x,y=pt
            draw.rectangle((x-2,y-2,x+2,y+2), fill=BLUE if data['team']==100 else RED, outline='#1b2d39')
    icon_sources = json.loads((icons/'.sources.json').read_bytes()) if icons and (icons/'.sources.json').is_file() else {}
    for hero in sorted(data['heroes'],key=lambda h:h['player']):
        pt = marker(hero['xz'])
        if pt is None: continue
        x,y=pt
        r = 12 if hero['player'] else 9
        border = GOLD if hero['player'] else (BLUE if hero['ally']==(data['team']==100) else RED)
        circle(pt,r+2,'#152027',border)
        name = hero['champion']
        if name in icon_sources:
            file = icons / (name+'.png')
            if file_sha(file) != icon_sources[name]['sha256']:
                raise ValueError('champion_portrait_hash_mismatch')
            portrait = Image.open(file).convert('RGB').resize((2*r,2*r),Image.Resampling.LANCZOS)
            mask=Image.new('L',(2*r,2*r)); ImageDraw.Draw(mask).ellipse((0,0,2*r-1,2*r-1),fill=255)
            canvas.paste(portrait,(x-r,y-r),mask)
        else:
            draw.text(pt,name[:1],font=fonts[14],fill=INK,anchor='mm')
    left=551
    label(left,73,'兵线',26)
    label(left,117,'分路',16,MUTED);label(left+82,117,'登记数',16,MUTED);label(left+163,117,'有新坐标',16,MUTED)
    for i,(lane,cn) in enumerate(zip(LANES,('上路','中路','下路'))):
        y=157+i*40; row=data['lanes'][lane]
        label(left,y,cn);label(left+92,y,str(row['registered']),18);label(left+182,y,str(row['recent']),18)
    label(left,284,'小方点为己方小兵最近位置。',16,MUTED)
    label(left,310,'敌兵数量未知。',16,MUTED)
    draw.line((left,350,796,350),fill='#3e4e50')
    label(left,369,'野区',26)
    label(left,414,'空心菱形为营地或资源坑位置。',16,MUTED)
    label(left,440,'图中营地存活与刷新时间未知。',16,MUTED)
    label(left,467,'盾形标注防御塔的固定位置。',16,MUTED)
    label(left,504,'英雄与兵只画最近 1 秒采样。',16,MUTED)
    label(left,529,'金圈为本人，敌人须本队可见。',16,MUTED)
    label(left,557,f'对局 {data["origin"]["match_id"]}',14,MUTED)
    if data['personal_pings']:
        canvas = with_ping_detail(canvas, background, data, assets, fonts)
    canvas.save(out,format='PNG')


def with_ping_detail(base, texture, data, assets, fonts):
    """Zoom the same clean client texture and redraw only the perspective-filtered samples."""
    canvas=Image.new('RGB',(1000,682),'#121c20')
    canvas.paste(base.crop((0,0,540,592)),(0,0))
    draw=ImageDraw.Draw(canvas)
    def txt(pt,s,size=16,color=INK):
        draw.text(pt,s,font=fonts[size],fill=color,anchor='lt')
    def ring(pt,r):
        x,y=pt
        for shift,col in ((0,'#172229'),(2,'#ffce56'),(5,'#432f07')):
            rr=r-shift
            draw.ellipse((x-rr,y-rr,x+rr,y+rr),outline=col,width=2)
    extent=assets['world_extent']
    event=data['personal_pings'][-1]
    center=project(event['xz'],extent,512)
    if center is None:
        raise ValueError('ping_outside_map')
    for e in data['personal_pings']:
        px,py=project(e['xz'],extent,512)
        ring((px+16,py+64),18)
    draw.rounded_rectangle((548,64,981,547),12,fill='#1d2a2e')
    txt((568,83),'标点附近',26)
    kind={'assist_me':'请求协助','on_my_way':'正在路上','enemy_missing':'敌人消失'}.get(event['kind'],event['kind'])
    t=event['at']
    txt((568,127),f'{int(t)//60:02}:{t%60:04.1f}  你发出「{kind}」',18,'#ffde88')
    txt((568,157),event['description'],16,MUTED)
    crop=148
    x0=max(0,min(512-crop,center[0]-crop//2))
    y0=max(0,min(512-crop,center[1]-crop//2))
    size=300; ox,oy=568,195
    tile=texture.crop((x0,y0,x0+crop,y0+crop)).resize((size,size),Image.Resampling.LANCZOS)
    canvas.paste(tile,(ox,oy),tile)
    draw.rectangle((ox-1,oy-1,ox+size,oy+size),outline='#52655d')
    def zoom(xz):
        p=project(xz,extent,512)
        if p and x0<=p[0]<x0+crop and y0<=p[1]<y0+crop:
            return (round(ox+(p[0]-x0)*size/crop),round(oy+(p[1]-y0)*size/crop))
    camp_names={'dragon':'龙坑','baron':'上河坑','scuttle':'河蟹','gromp':'魔沼蛙','blue':'蓝',
                'red':'红','krugs':'石甲虫','wolves':'狼','raptors':'锋喙鸟'}
    for camp in assets['camps']:
        p=zoom(camp['xz'])
        if p and ox+5<=p[0]<=ox+size-36 and oy+5<=p[1]<=oy+size-8:
            x,y=p
            draw.polygon([(x,y-4),(x+4,y),(x,y+4),(x-4,y)],fill='#1c2723',outline='#d4bc82')
            draw.text((x+6,y+4),camp_names[camp['kind']],font=fonts[11],anchor='lt',fill='#e9dcad',
                      stroke_width=1,stroke_fill='#1e2924')
    for m in data['minions']:
        p=zoom(m['xz'])
        if p:
            x,y=p
            draw.rectangle((x-2,y-2,x+2,y+2),fill=RED if data['team']==200 else BLUE)
    names={'Pantheon':'潘森','Jayce':'杰斯','Ahri':'阿狸','Ezreal':'伊泽瑞尔','Nautilus':'泰坦',
           'Darius':'诺手','Amumu':'阿木木','TwistedFate':'卡牌','Jhin':'烬','Karma':'卡尔玛'}
    for i,h in enumerate(sorted((h for h in data['heroes'] if zoom(h['xz'])),key=lambda h:-h['xz'][1])):
        x,y=zoom(h['xz'])
        col=GOLD if h['player'] else (RED if h['ally']==(data['team']==200) else BLUE)
        # The small disk is the location; names occupy a separate column when two heroes overlap.
        draw.ellipse((x-3,y-3,x+3,y+3),fill=col,outline='#0e1619')
        ey=oy+16+i*29
        draw.line((x+4,y,865,ey+4,878,ey+4),fill=col)
        txt((883,ey-3),names.get(h['champion'],h['champion']),14,col)
    ring(zoom(event['xz']),16)
    txt((568,515),'金色双圈为信号估计区域，游戏坐标取整到 100。',14,MUTED)
    txt((550,561),'头像金边为本人，红边为红方，蓝边为蓝方。',14,MUTED)
    draw.line((16,586,980,586),fill='#40505a')
    txt((18,607),'己方兵线',18)
    txt((124,609),'近一秒有坐标 / 仍登记',14,MUTED)
    for i,(lane,name) in enumerate(zip(LANES,('上','中','下'))):
        row=data['lanes'][lane]
        txt((18+i*105,644),f"{name}   {row['recent']}/{row['registered']}",16)
    txt((354,607),'小方点是己方兵。菱形是营地位置，盾形是塔址。',14,MUTED)
    txt((354,641),'仅画最近一秒的位置样本；敌方英雄还须该时刻本队可见。',14,MUTED)
    if not any(h['player'] for h in data['heroes']):
        txt((702,607),'本人最近一秒缺少位置样本。',14,'#ffde88')
    return canvas


def file_sha(path):
    return sha256(path.read_bytes()).hexdigest()


def verify_source(bundle_path, game_log, assets):
    directory = bundle_path.parent
    manifest = json.loads((directory.parent/'manifest.json').read_bytes())
    steps = [s for s in manifest['steps'] if s['input_sha256'] == file_sha(bundle_path)]
    subject = manifest.get('verified_subject') or {}
    raw = game_log.read_bytes()
    if (manifest.get('perspective') != 'personal' or len(steps) != 1
            or subject.get('replay_sha256') != steps[0]['source_sha256']
            or subject.get('local_champion') != steps[0]['champion']
            or sha256(raw).hexdigest() != subject.get('log_sha256')):
        raise ValueError('game log and personal-review manifest do not match the frame')
    skins = set(re.findall(rb'\bmapskin\s*=\s*([A-Za-z0-9_]+)',raw))
    if skins != {assets['skin'].encode('ascii')}:
        raise ValueError('game log and minimap terrain skin do not match')
    return subject


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle',type=Path,required=True)
    p.add_argument('--assets',type=Path,required=True)
    p.add_argument('--game-log',type=Path,required=True)
    p.add_argument('--icons',type=Path)
    p.add_argument('--hud-clip',type=Path,help='Source-bound native frames for matching late terrain')
    p.add_argument('--game-dir',type=Path,help='Matching game installation with Map11 WAD')
    p.add_argument('--font',type=Path,default=Path('C:/Windows/Fonts/msyh.ttc'))
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    assets=json.loads(a.assets.read_bytes())
    texture=a.assets.parent/assets['texture_file']
    if file_sha(texture)!=assets['texture_sha256']:
        p.error('minimap texture checksum mismatch')
    subject=verify_source(a.bundle,a.game_log,assets)
    bundle=json.loads(a.bundle.read_bytes())
    terrain=None
    if (a.hud_clip is None)!=(a.game_dir is None):
        p.error('supply native HUD clip and game directory together')
    if a.hud_clip is not None:
        from lol_coach.minimap_terrain import verify_terrain
        selected,terrain=verify_terrain(bundle,assets,a.game_dir,a.hud_clip)
    data=snapshot(bundle,assets,terrain=terrain)
    if data['origin']['match_id'] != subject['match_id'] or data['team'] != subject['local_team_id']:
        p.error('bundle and verified subject mismatch')
    a.output.mkdir(parents=True,exist_ok=False)
    if terrain:
        texture=a.output/'terrain.png'
        selected.save(texture)
        terrain['texture_png_sha256']=file_sha(texture)
        (a.output/'terrain-proof.json').write_text(json.dumps(terrain,indent=2),encoding='utf8')
    render(data,assets,texture,a.icons,a.font,a.output/'minimap.png')
    data.update(asset_profile_sha256=file_sha(a.assets), texture_sha256=file_sha(texture),
                world_extent=assets['world_extent'], camps=assets['camps'], camp_status='unknown')
    (a.output/'observations.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    print(a.output/'minimap.png')

if __name__=='__main__':
    main()
