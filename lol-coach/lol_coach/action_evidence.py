"""Retrospective movement timeline and explicitly conditional travel arithmetic."""
import copy
import math


def conditional_travel(points, speed):
    if isinstance(speed,bool) or not isinstance(speed,(int,float)) or not math.isfinite(speed) or speed<=0:
        raise ValueError('Speed must be positive finite game units per second')
    if not isinstance(points,list) or len(points)<2:raise ValueError('At least two route points required')
    if any(not isinstance(p,(list,tuple)) or len(p)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in p) for p in points):
        raise ValueError('Expected finite 2D route coordinates')
    length=sum(math.dist(a,b) for a,b in zip(points,points[1:]))
    return dict(kind='conditional_arithmetic_not_actual_arrival',route_length_game_units=length,
        constant_speed_game_units_per_second=speed,duration_seconds=length/speed,
        assumptions=['Route is actually traversable and followed exactly','Speed remains constant',
                     'No command interruption, cast time, collision, turn delay or other movement modifier'],
        actual_duration_seconds=None,actual_end_position=None,decision_input_eligible=False)


def movement_timeline(report):
    if report.get('version')!='16.20.824.8524' or report.get('source_integrity')!='verified':
        raise ValueError('Expected verified existing movement evidence report')
    timing=report['timing_sample']
    if timing['replay_sha256']!=report['replay']['sha256'] or timing['video_sha256']!=report['video']['sha256']:
        raise ValueError('Movement/video identity mismatch')
    rows=[];active=None
    for i,row in enumerate(report['track']):
        if rows and row['time']<rows[-1]['packet_time_seconds']:raise ValueError('Unordered movement evidence')
        points=row['points'];multiple=len(points)>1
        entry=dict(id=f'm{i+1}',packet_time_seconds=row['time'],kind='movement_plan' if multiple else 'single_point_candidate',
            decoded_relative_points=copy.deepcopy(points),speed_candidate=row['speed'],
            actual_arrival=None,source_report_pointer=f'/track/{i}',supersedes_plan_id=active if multiple else None)
        if multiple:
            entry['conditional_duration']=conditional_travel(points,row['speed']) if row['speed']>0 else None
            active=entry['id']
        else:
            entry['preceding_plan_id']=active
            entry['meaning']='A single point does not establish arrival, manual stop or plan completion'
            active=None
        rows.append(entry)
    return dict(schema='movement-action-timeline/v1',version=report['version'],
        replay_sha256=report['replay']['sha256'],video_sha256=report['video']['sha256'],
        events=rows,video_duration_observations=[copy.deepcopy(timing)],
        time_basis='Packet clock and video clock remain separate; no global offset applied',
        interpretation='Retrospective evidence, not a continuous actual trajectory',decision_input_eligible=False)


def render_timeline(timeline):
    lines=['# 现有素材行动时间线','','计划与单点候选保留原包时间；视频实测使用视频时间，不把单点自动认作到达。','',
           '| 包时间（秒） | 类型 | 计划长度/条件耗时 | 替换的计划 |','| --- | --- | --- | --- |']
    for r in timeline['events']:
        c=r.get('conditional_duration');v='未知' if c is None else f"{c['route_length_game_units']:.2f} 单位 / {c['duration_seconds']:.3f} 秒"
        lines.append(f"| {r['packet_time_seconds']:.3f} | {r['kind']} | {v} | {r.get('supersedes_plan_id') or '无'} |")
    for r in timeline['video_duration_observations']:
        lo,hi=r['duration_seconds_interval'];lines+=['',f'已有视频观察：末段移动 {lo:.1f}–{hi:.1f} 秒；只用于该片段回顾，不是其他路线耗时模型。']
    return '\n'.join(lines)+'\n'
