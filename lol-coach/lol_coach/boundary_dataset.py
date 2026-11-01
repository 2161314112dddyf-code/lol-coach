"""Validate isolated review inputs and score only supplied boundary labels."""
import math
from .reasoning_frame import digest


def audit_cases(cases, labels=()):
    ids=set();groups={};by_id={}
    for case in cases:
        if case.get('schema')!='round-boundary-review-case/v1':raise ValueError('Unknown case schema')
        frame=case['frame'];candidate=case['candidate'];cid=candidate['candidate_id']
        if cid in ids:raise ValueError('Duplicate candidate')
        ids.add(cid);by_id[cid]=case
        if frame['frame_id']!='frame_'+digest({k:v for k,v in frame.items() if k!='frame_id'})[:24]:raise ValueError('Changed frame')
        if candidate['frame_id']!=frame['frame_id'] or candidate['at_seconds']!=frame['decision']['at_seconds']:raise ValueError('Candidate/frame mismatch')
        if case.get('future_outcome_included') is not False or case.get('label') is not None:raise ValueError('Review input contains a label/outcome')
        if candidate.get('actual_round_boundary') is not None or candidate.get('tactical_correctness') is not None:raise ValueError('Candidate was promoted to verdict')
        for fact in frame['facts'].values():
            for name in ('observed_at_seconds','available_at_seconds'):
                time=fact.get(name)
                if time is not None and (type(time) not in (int,float) or not math.isfinite(time) or not 0<=time<=candidate['at_seconds']):raise ValueError('Future or invalid fact')
        for reason in candidate['reasons']:
            if reason['current_fact_id'] not in frame['facts']:raise ValueError('Missing fact reference')
        group=case.get('split_group');split=case.get('split')
        if not isinstance(group,str) or len(group)!=64 or any(c not in '0123456789abcdef' for c in group):raise ValueError('Missing replay group')
        if split not in ('unassigned','train','validation','test'):raise ValueError('Unknown split')
        if group in groups and groups[group]!=split:raise ValueError('Same replay crosses splits')
        groups[group]=split
    reviewed={};useful=0
    for label in labels:
        cid=label.get('candidate_id')
        if cid not in by_id or cid in reviewed:raise ValueError('Unknown or duplicate label')
        if label.get('frame_id')!=by_id[cid]['frame']['frame_id']:raise ValueError('Label refers to another frame')
        if not isinstance(label.get('author'),str) or not label['author'].strip():raise ValueError('Missing label author')
        value=label.get('useful_reconsideration')
        if value is not None and type(value) is not bool:raise ValueError('Invalid usefulness label')
        reviewed[cid]=value
        useful+=value is True
    decisive=sum(type(v) is bool for v in reviewed.values())
    return dict(schema='round-boundary-dataset-audit/v1',cases=len(cases),replay_groups=len(groups),
        group_assignments=groups,labels_supplied=len(reviewed),decisive_labels=decisive,
        candidate_usefulness_rate=useful/decisive if decisive else None,
        recall=None,tactical_accuracy=None,training_ready=False,
        evaluation_status='LABELED_CANDIDATE_SUBSET_ONLY' if decisive else 'INSUFFICIENT_EVIDENCE',
        limitation='No negative-time ground truth, so no recall; labels are supplied judgments, not verified authority')
