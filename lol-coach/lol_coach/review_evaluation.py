"""Score externally labeled scan times, including unselected times, without fake gold."""


def evaluate_scan_labels(sequence,labels):
    if sequence.get('schema')!='review-sequence/v1':raise ValueError('Unsupported review sequence')
    rows=sequence['scan_decisions'];by_id={r['frame_id']:r for r in rows}
    if len(by_id)!=len(rows):raise ValueError('Duplicate scan frame')
    seen=set();counts=dict(true_positive=0,false_positive=0,false_negative=0,true_negative=0);unknown=0
    for row in labels:
        fid=row.get('source_frame_id')
        if fid not in by_id or fid in seen:raise ValueError('Duplicate or unknown labeled frame')
        seen.add(fid)
        if not isinstance(row.get('author'),str) or not row['author'].strip():raise ValueError('Label author required')
        value=row.get('needs_reconsideration')
        if value is None:unknown+=1;continue
        if type(value) is not bool:raise ValueError('Invalid review label')
        prediction=by_id[fid]['selected']
        if type(prediction) is not bool:raise ValueError('Invalid selection')
        key=('true_positive' if value else 'false_positive') if prediction else ('false_negative' if value else 'true_negative')
        counts[key]+=1
    n=sum(counts.values());tp=counts['true_positive'];fp=counts['false_positive'];fn=counts['false_negative']
    return dict(status='LABELED_SUBSET_ONLY' if n else 'INSUFFICIENT_EVIDENCE',scan_frames=len(rows),
        labels_received=len(labels),decisive_labels=n,unknown_labels=unknown,label_coverage=n/len(rows) if rows else 0,
        confusion_matrix=counts if n else None,precision=tp/(tp+fp) if tp+fp else None,recall=tp/(tp+fn) if tp+fn else None,
        tactical_accuracy=None,semantic_round_accuracy=None,
        limitation='Metrics describe supplied labels only; they do not validate tactical answers or genuine player rounds. Authors are declared, not authenticated.')
