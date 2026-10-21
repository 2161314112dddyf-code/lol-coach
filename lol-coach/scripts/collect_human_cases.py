"""Cache two readable human sources and preserve conditional historical claims."""
import argparse
import hashlib
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lol_coach.http import EvidenceClient,save_json

CASES=[
 dict(id='human-farm-santorin-2023',decision='continue_development',
    url='https://dignitas.gg/articles/the-big-three-jungle-concepts-with-santorin',
    title='The Big Three Jungle Concepts with Santorin',author='Teatones',speaker='Santorin',published_date='2023-11-27',
    section='Playing Towards Your Win Condition',marker='If your team has more scaling focused',
    source_claim_summary='当己方坦克打野配合偏发育、暂时伤害不足的线上英雄时，Santorin 建议把计划更多转向反蹲与有效发育，等待队友成型；若当前尝试风险不必要，可换行动或返回清野。',
    source_conditions=['己方打野承担坦克职责','线上队友偏发育且当前伤害不足'],
    project_required_inputs=['己方英雄当前角色与装备','队友当前伤害/控制能力','对手施压方式','当地兵线与可到场队友','可清营地和行动耗时'],
    project_application_limit='不能把坦克标签单独当成继续刷野的理由；当前风险和替代行动仍需本局证据。'),
 dict(id='human-turn-to-gank-fordola-2021',decision='turn_to_assist',
    url='https://dignitas.gg/articles/how-to-set-up-effective-jungle-ganks',
    title='How to Set Up Effective Jungle Ganks',author='Fordola',speaker='Fordola',published_date='2021-11-17',
    section='Understanding When to Clear vs. When to Gank',marker='enemy Wukong is trying to slow push',
    source_claim_summary='作者描述自己回城后仍有营地可刷，但看到敌方悟空正在慢推、准备回城，选择先抓该路，争取击杀或迫使对手在兵线不利时回城。作者强调清野途中观察兵线，计算能否在对手推线进塔前到场。',
    source_conditions=['营地可刷','对手正在慢推并试图获得回城窗口','能利用兵线形成抓人或压迫机会'],
    project_required_inputs=['兵线方向、数量和进塔时间','双方英雄位置/血量/关键技能','队友配合能力','到场耗时','敌方打野已知信息与视野'],
    project_application_limit='来源是作者叙述案例，未取得对应回放；不能视为本项目实测，也不能用旧路线和数值直接预测 16.20。')]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--offline',action='store_true');args=parser.parse_args()
    root=ROOT/'data/research/human_sources';client=EvidenceClient(root,timeout=15,retries=0)
    cards=[];failures=[]
    for case in CASES:
        source,_=client.fetch(case['id'],case['url'],offline=args.offline)
        if source.get('sha256') is None or source['http_status']!=200:
            failures.append(dict(id=case['id'],source=source));continue
        body=(root/source['evidence_path']).read_bytes()
        if hashlib.sha256(body).hexdigest()!=source['sha256']:raise ValueError('Source changed')
        if case['marker'] not in body.decode('utf8'):raise ValueError('Reviewed passage absent')
        cards.append(dict(**case,source=source,kind='historical_human_claim',source_patch=None,
            patch_status='publication_date_known; exact_play_patch_unknown',
            current_patch_applicability='requires_conditions_and_mechanics_review',
            duration_seconds=None,independently_observed_outcome=None,
            unconditional_recommendation=False,decision_input_eligible=False,
            provenance_note='source_claim_summary/source_conditions paraphrase the author; project_* fields are project analysis'))
    output=dict(schema='conditional-human-experience/v1',cards=cards,failures=failures,
        limitation='Historical conditional evidence, not a fitted strategy or measured clear-time dataset')
    save_json(ROOT/'data/knowledge/human_decision_cases.json',output)
    save_json(ROOT/'reports/human_case_collection.json',dict(cards=len(cards),failures=failures,offline=args.offline,
        source_passages_present=len(cards),source_hashes_verified=len(cards),measured_clear_records=0))
    print(dict(cards=len(cards),failures=len(failures),offline=args.offline))
    if failures:raise SystemExit(1)


if __name__=='__main__':main()
