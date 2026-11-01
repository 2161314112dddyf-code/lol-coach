import pytest
from lol_coach.review_evaluation import evaluate_scan_labels


def sequence():return dict(schema='review-sequence/v1',scan_decisions=[dict(frame_id='a',selected=True),dict(frame_id='b',selected=False)])
def label(fid,value):return dict(source_frame_id=fid,author='synthetic fixture',needs_reconsideration=value)


def test_no_labels_is_no_score():
    r=evaluate_scan_labels(sequence(),[])
    assert r['confusion_matrix'] is None and r['precision'] is None and r['recall'] is None


def test_unselected_positive_is_a_false_negative():
    r=evaluate_scan_labels(sequence(),[label('a',False),label('b',True)])
    assert r['confusion_matrix']['false_negative']==1 and r['confusion_matrix']['false_positive']==1
    assert r['recall']==0 and r['label_coverage']==1 and r['tactical_accuracy'] is None


def test_unknown_is_excluded_and_duplicates_or_other_frames_rejected():
    r=evaluate_scan_labels(sequence(),[label('a',None),label('b',True)])
    assert r['decisive_labels']==1 and r['label_coverage']==.5
    for labels in ([label('missing',True)],[label('a',True),label('a',False)]):
        with pytest.raises(ValueError):evaluate_scan_labels(sequence(),labels)
