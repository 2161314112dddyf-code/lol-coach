"""Publish readable individual casebooks after checking each card against its own frozen evidence."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re

from lol_coach.file_model_bridge import atomic_json
from lol_coach.round_chain import _check_bundle


NAMES = {'Aatrox': '剑魔', 'Jayce': '杰斯', 'TwistedFate': '卡牌', 'Caitlyn': '女警', 'Pantheon': '潘森',
         'Yone': '永恩', 'MasterYi': '剑圣', 'Katarina': '卡特', 'KogMaw': '大嘴', 'TahmKench': '塔姆'}
ROLES = {'TOP': '上路', 'JUNGLE': '打野', 'MIDDLE': '中路', 'BOTTOM': '射手', 'UTILITY': '辅助'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    root = parser.parse_args().root
    run = json.loads((root / 'run.json').read_bytes())
    outcomes = {row['SKIN']: row for row in json.loads((root/'outcome-only.json').read_bytes())['rows']}
    publications, audits = {}, []
    for player in run['roster']:
        champ = player['champion']
        side = '蓝' if player['team_id'] == 100 else '红'
        title = f"{side}方{ROLES[player['assigned_role']]} · {NAMES.get(champ, champ)}"
        lines = ['# ' + title, '', f"对局 {run['match_id']}。按游戏时间阅读；建议所依据的是当时本队可知的信息。", '']
        previous_write = 0
        for sec in run['times']:
            card = root/'cards'/champ/f'{sec}.md'
            text = card.read_text(encoding='utf-8')
            mtime = card.stat().st_mtime_ns
            tool = root/'tools'/champ/f'{sec}.json'
            raw = tool.read_bytes()
            result = json.loads(raw)
            identity = result['identity']
            assert (identity['champion'], identity['observer_team_id'], identity['at_seconds']) == (champ, player['team_id'], sec)
            refs = set(re.findall(r'\bf_[0-9a-f]{20}\b', text))
            bundle_raw = (root/'frames'/champ/str(sec)/'bundle.json').read_bytes()
            frame = _check_bundle(json.loads(bundle_raw))
            assert sha256(bundle_raw).hexdigest() == identity['bundle_sha256'] and frame['frame_id'] == identity['frame_id']
            assert refs and refs <= frame['facts'].keys() and all(fid.encode() in raw for fid in refs)
            assert mtime > previous_write and len([ln for ln in text.splitlines() if ln.startswith('**')]) >= 5
            previous_write = mtime
            errata = card.with_name(f'{sec}_errata.md')
            body = text.splitlines()[1:]
            # In the casebook apply explicit author corrections; keep the timestamped original intact.
            if errata.is_file():
                if champ == 'TahmKench' and sec == 740:
                    body = [line.replace('大嘴回城窗口', '大嘴在基地、暂时不在线上的窗口') for line in body]
                body += ['', f'[该卡原文的用词更正](../cards/{champ}/{sec}_errata.md)']
            lines += [f'## {sec//60:02}:{sec%60:02}', '']
            lines.extend(line.replace('../../tools/', '../tools/') for line in body)
            lines += ['', f'[原始卡](../cards/{champ}/{sec}.md) · [原始工具查询](../tools/{champ}/{sec}.json)', '']
            audits.append(dict(champion=champ, seconds=sec, frame_id=identity['frame_id'], cited_fact_ids=sorted(refs),
                               card_sha256=sha256(card.read_bytes()).hexdigest(), evidence_sha256=sha256(raw).hexdigest(),
                               written_ns=mtime))
        o = outcomes[champ]
        lines += ['## 赛后核对', '',
                  f"结算记击杀／死亡／助攻 {o['CHAMPIONS_KILLED']}/{o['NUM_DEATHS']}/{o['ASSISTS']}，"
                  f"放眼 {o['WARD_PLACED']}，个人小龙 {o['DRAGON_KILLS']}。",
                  '', f'[本人全局移动查点](../timeline/{champ}.json) · [终局来源](../outcome-only.json)', '']
        publications[champ] = '\n'.join(lines)
    for side in (100, 200):
        players = {r['champion'] for r in run['roster'] if r['team_id'] == side}
        batches = [[r['written_ns'] for r in audits if r['champion'] in players and r['seconds'] == t] for t in run['times']]
        assert all(max(a) < min(b) for a, b in zip(batches, batches[1:]))
    out = root / 'players'
    out.mkdir(exist_ok=False)
    for name, body in publications.items():
        (out / f'{name}.md').write_text(body, encoding='utf-8')
    atomic_json(root/'card-checks.json', dict(players=len(publications), cards=len(audits), rows=audits,
                scope='frame, roster, evidence references and file write order; tactical conclusions require review'))
    print(len(publications), 'casebooks;', len(audits), 'cards checked')


if __name__ == '__main__':
    main()
