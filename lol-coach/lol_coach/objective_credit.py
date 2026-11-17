"""Player-visible dragon announcements and the scope of their kill credit."""
from .reasoning_frame import number


DRAGON_DISPLAY_NAMES = {'Cloud Drake': '云霄亚龙', 'Infernal Drake': '炼狱亚龙'}
_OBSERVED_ALLIED_HUD = {f'玩家画面出现“我方队伍已经击杀了{zh}！”公告。': en
                        for en, zh in DRAGON_DISPLAY_NAMES.items()}


def dragon_kill_events(frame):
    """Index current facts that announce a kill. Never use the observation owner as killer."""
    at = frame['decision']['at_seconds']
    team = frame['decision']['observer_team_id']
    roster = {hero['entity_id']: hero.get('relation') for hero in frame['lineup']}
    events = {}
    for fid, fact in frame['facts'].items():
        field = fact.get('field')
        if field not in ('allied_dragon_kill', 'public_objective_kill_feed', 'dragon_pit_observation'):
            continue
        observed = fact.get('observed_at_seconds')
        available = fact.get('available_at_seconds', observed)
        if not (number(observed) and number(available) and 0 <= observed <= available <= at):
            continue
        value = fact.get('value')
        if field == 'dragon_pit_observation':
            # Only the two labelled HUD captures carry this old free-text encoding.
            if fact.get('temporal_scope') != 'player_view_at_video_frame' or not isinstance(value, str):
                continue
            name = _OBSERVED_ALLIED_HUD.get(value)
        else:
            if (fact.get('temporal_scope') not in ('public_event', 'historical_replay_event_cross_checked_by_player_HUD')
                    or not isinstance(value, dict)):
                continue
            name = value.get('name_from_announcement')
        if not isinstance(name, str) or not name.strip():
            continue
        if field != 'public_objective_kill_feed':
            # Legacy packets are indexed on the observer and only name the objective.
            credited_team, killer = team, None
        else:
            # A named public feed must identify the killer and agree with this roster.
            credited_team = value.get('killer_team_id')
            killer = value.get('killer_entity_id')
            if (value.get('objective_kind') != 'dragon' or type(credited_team) is not int
                    or credited_team not in (100, 200) or not isinstance(killer, str)
                    or roster.get(killer) != ('ally' if credited_team == team else 'enemy')):
                continue
        events[fid] = dict(objective_kind='dragon', objective_name=name, credited_team_id=credited_team,
                           killer_entity_id=killer, observed_at_seconds=observed, available_at_seconds=available)
    return events
