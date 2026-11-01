"""Causal review scheduling, not inferred player intention or accepted rounds."""
from copy import deepcopy
from .round_boundaries import BoundaryTracker
from .reasoning_frame import digest,number


class CheckpointScheduler:
    def __init__(self, interval_seconds=30):
        if not number(interval_seconds) or interval_seconds<=0:raise ValueError('Invalid review interval')
        self.interval=interval_seconds;self.tracker=BoundaryTracker();self.last=None;self.pending=[]

    def feed(self,bundle):
        candidate=self.tracker.feed(bundle);frame=bundle['frame'];at=frame['decision']['at_seconds']
        if candidate:self.pending.append(candidate)
        initial=self.last is None
        urgent=bool(candidate and any(r['reason']=='observed_zero_tower_health' or
            (r['reason']=='observed_zero_hero_health' and r['entity_id']==frame['decision']['player_entity_id']) for r in candidate['reasons']))
        emit=initial or urgent or bool(self.pending and at-self.last>=self.interval)
        result=dict(at_seconds=at,frame_id=frame['frame_id'],raw_candidate=candidate,
            selected=emit,selection_kind='initial' if initial else 'urgent_observation' if urgent else 'coalesced_changes' if emit else 'not_selected',
            true_round_boundary=None,review_label=None)
        if emit:
            result['covered_candidates']=deepcopy(self.pending)
            result['checkpoint_id']='checkpoint_'+digest(dict(frame=frame['frame_id'],pending=self.pending,interval=self.interval))[:24]
            self.pending=[];self.last=at
        return result

    def tail(self):
        """Pending tail is audit evidence, never retroactively changes a checkpoint."""
        return deepcopy(self.pending)

    def flush(self,bundle):
        """Emit pending observations at an explicit scan cutoff, not a game-end claim."""
        if self.tracker.previous is None or bundle['frame']!=self.tracker.previous:raise ValueError('Flush requires the last scanned frame')
        if not self.pending:return None
        frame=bundle['frame'];at=frame['decision']['at_seconds']
        result=dict(at_seconds=at,frame_id=frame['frame_id'],raw_candidate=None,selected=True,
            selection_kind='scan_cutoff_pending_changes',true_round_boundary=None,review_label=None,
            covered_candidates=deepcopy(self.pending))
        result['checkpoint_id']='checkpoint_'+digest(dict(frame=frame['frame_id'],pending=self.pending,interval=self.interval,flush=True))[:24]
        self.pending=[];self.last=at
        return result


def prepare_checkpoint(bundle,selection):
    if not selection.get('selected') or selection['frame_id']!=bundle['frame']['frame_id']:raise ValueError('Selection/frame mismatch')
    result=deepcopy(bundle);frame=result['frame']
    ids=list(dict.fromkeys(r['current_fact_id'] for c in selection['covered_candidates'] for r in c['reasons'] if r['current_fact_id'] in frame['facts']))
    frame['task']['review_checkpoint']=dict(checkpoint_id=selection['checkpoint_id'],selection_kind=selection['selection_kind'],
        current_trigger_fact_ids=ids,true_round_boundary=None,
        instruction='这是工程调度的复盘检查点，不代表玩家意图或真实回合边界。仅按当前事实比较行动，旧建议不证明执行，未知耗时/冷却/区域视野不得补值。')
    frame['frame_id']='frame_'+digest({k:v for k,v in frame.items() if k!='frame_id'})[:24]
    result['audit']['checkpoint_selection']=deepcopy(selection)
    return result
