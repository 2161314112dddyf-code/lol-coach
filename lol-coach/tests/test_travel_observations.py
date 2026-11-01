"""Synthetic visual-interval checks; never evidence of gameplay accuracy."""
from copy import deepcopy
import math

import pytest

from lol_coach.travel_observations import compare_duration, compare_samples


def fixture_pair():
    frozen = dict(schema="frozen-travel-predictions/v1", version="16.20.824.8524",
        replay_id="synthetic-replay", source_sha256="a" * 64,
        records=[dict(prediction_id="route-a", predicted_duration_seconds=2.4),
                 dict(prediction_id="route-b", predicted_duration_seconds=1.2)])
    bundle = dict(schema="travel-visual-observations/v1", version=frozen["version"],
        replay_id=frozen["replay_id"], source_sha256=frozen["source_sha256"],
        video_sha256="b" * 64, review_order="synthetic; no real frame annotation",
        samples=[dict(sample_id="synthetic-a", prediction_id="route-a",
            start_video_interval_seconds=[10, 10.1], end_video_interval_seconds=[12.4, 12.5],
            association_status="supported",
            endpoint_correspondence="visual_stop_with_replay_endpoint_correspondence",
            evidence=["synthetic fixture only"], limitations=["No real video or physical observation"])])
    return frozen, bundle


@pytest.mark.parametrize("prediction,minimum,maximum,inside", [
    (2.4, 0, .1, True), (1.0, 1.3, 1.5, False), (4.0, 1.5, 1.7, False)])
def test_interval_error_preserves_entire_departure_and_stop_uncertainty(prediction, minimum, maximum, inside):
    result = compare_duration(prediction, [10, 10.1], [12.4, 12.5])
    assert result["observed_duration_interval_seconds"] == pytest.approx([2.3, 2.5])
    assert result["duration_interval_width_seconds"] == pytest.approx(.2)
    assert result["minimum_absolute_error_seconds"] == pytest.approx(minimum)
    assert result["maximum_absolute_error_within_interval_seconds"] == pytest.approx(maximum)
    assert result["prediction_within_observed_interval"] is inside
    assert result["exact_duration_seconds"] is None


def test_point_observations_do_not_assert_physical_exactness():
    result = compare_duration(2, [10, 10], [12, 12])
    assert result["observed_duration_interval_seconds"] == [2, 2]
    assert result["minimum_absolute_error_seconds"] == 0
    assert result["maximum_absolute_error_within_interval_seconds"] == 0
    assert result["exact_duration_seconds"] is None


@pytest.mark.parametrize("prediction", [True, False, 0, -1, math.nan, math.inf, "2.4", None])
def test_rejects_nonphysical_or_nonfinite_prediction(prediction):
    with pytest.raises(ValueError):
        compare_duration(prediction, [10, 10.1], [12.4, 12.5])


@pytest.mark.parametrize("interval", [None, [], [1], [1, 2, 3], [2, 1], [-1, 1],
    [False, 1], [1, True], [1, math.nan], [1, math.inf], ["1", 2]])
def test_rejects_malformed_intervals(interval):
    with pytest.raises(ValueError):
        compare_duration(2.4, interval, [12.4, 12.5])
    with pytest.raises(ValueError):
        compare_duration(2.4, [1, 2], interval)


@pytest.mark.parametrize("start,end", [([10, 11], [11, 12]), ([10, 12], [11, 13]), ([12, 13], [10, 11])])
def test_overlapping_touching_or_reversed_windows_cannot_define_positive_motion(start, end):
    with pytest.raises(ValueError):
        compare_duration(2.4, start, end)


def test_comparable_sample_has_no_model_or_corpus_permission_and_does_not_mutate_inputs():
    frozen, bundle = fixture_pair()
    before = deepcopy((frozen, bundle))
    result = compare_samples(frozen, bundle)
    assert result["new_comparable_samples"] == 1
    assert result["total_comparable_samples"] == 1
    assert result["gate_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["decision_input_eligible"] is False
    row = result["rows"][0]
    assert row["status"] == "PASS"
    assert row["exact_arrival_seconds"] is None
    assert row["decision_input_eligible"] is False
    assert (frozen, bundle) == before
    row["evidence"].append("result-side mutation")
    row["start_video_interval_seconds"][0] = 0
    assert (frozen, bundle) == before


def test_prior_sample_is_retained_but_never_counted_as_new():
    frozen, bundle = fixture_pair()
    result = compare_samples(frozen, bundle, prior_prediction_ids=["route-a"])
    assert result["total_comparable_samples"] == 1
    assert result["new_comparable_samples"] == 0
    assert result["rows"][0]["previously_counted"] is True


@pytest.mark.parametrize("missing", ["start_video_interval_seconds", "end_video_interval_seconds", "both"])
def test_missing_departure_or_stop_is_preserved_as_insufficient(missing):
    frozen, bundle = fixture_pair()
    sample = bundle["samples"][0]
    if missing == "both":
        sample["start_video_interval_seconds"] = sample["end_video_interval_seconds"] = None
    else:
        sample.pop(missing)
    result = compare_samples(frozen, bundle)
    assert len(result["rows"]) == 1
    assert result["total_comparable_samples"] == result["new_comparable_samples"] == 0
    assert result["rows"][0]["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["rows"][0]["comparison"] is None


@pytest.mark.parametrize("field,value", [
    ("association_status", "unknown"), ("association_status", None),
    ("endpoint_correspondence", "unknown"), ("endpoint_correspondence", "stopped_somewhere"),
    ("endpoint_correspondence", None)])
def test_measurable_duration_does_not_establish_unproven_source_or_destination(field, value):
    frozen, bundle = fixture_pair()
    bundle["samples"][0][field] = value
    result = compare_samples(frozen, bundle)
    assert result["rows"][0]["comparison"] is not None
    assert result["rows"][0]["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["new_comparable_samples"] == result["total_comparable_samples"] == 0


@pytest.mark.parametrize("field", ["sample_id", "prediction_id", "visual_interval"])
def test_duplicate_observation_forecast_or_exact_visual_interval_is_rejected(field):
    frozen, bundle = fixture_pair()
    duplicate = deepcopy(bundle["samples"][0])
    if field != "sample_id":
        duplicate["sample_id"] = "synthetic-b"
    if field != "prediction_id":
        duplicate["prediction_id"] = "route-b"
    if field != "visual_interval":
        duplicate["start_video_interval_seconds"] = [20, 20.1]
        duplicate["end_video_interval_seconds"] = [21.3, 21.4]
    bundle["samples"].append(duplicate)
    with pytest.raises(ValueError):
        compare_samples(frozen, bundle)


def test_unknown_sample_prediction_does_not_match_by_position_or_similarity():
    frozen, bundle = fixture_pair()
    bundle["samples"][0]["prediction_id"] = "not-in-frozen-bundle"
    with pytest.raises(ValueError):
        compare_samples(frozen, bundle)


def test_missing_all_frozen_records_rejects_observed_sample():
    frozen, bundle = fixture_pair()
    frozen["records"] = []
    with pytest.raises(ValueError):
        compare_samples(frozen, bundle)


def test_duplicate_frozen_prediction_is_rejected():
    frozen, bundle = fixture_pair()
    frozen["records"].append(deepcopy(frozen["records"][0]))
    with pytest.raises(ValueError):
        compare_samples(frozen, bundle)


def test_prior_sample_must_be_an_existing_frozen_prediction():
    frozen, bundle = fixture_pair()
    with pytest.raises(ValueError):
        compare_samples(frozen, bundle, prior_prediction_ids=["missing"])


@pytest.mark.parametrize("field", ["version", "replay_id", "source_sha256"])
def test_source_binding_mismatch_rejected(field):
    frozen, bundle = fixture_pair()
    bundle[field] = "another-source"
    with pytest.raises(ValueError):
        compare_samples(frozen, bundle)


@pytest.mark.parametrize("field", ["version", "replay_id", "source_sha256"])
def test_missing_binding_on_both_sides_not_a_match(field):
    frozen, bundle = fixture_pair()
    frozen.pop(field); bundle.pop(field)
    with pytest.raises(ValueError):
        compare_samples(frozen, bundle)


@pytest.mark.parametrize("field,value", [("schema", "wrong/v1"), ("video_sha256", None),
    ("video_sha256", "a" * 63), ("video_sha256", "G" * 64), ("review_order", ""), ("review_order", None)])
def test_observation_provenance_requirements(field, value):
    frozen, bundle = fixture_pair()
    bundle[field] = value
    with pytest.raises(ValueError):
        compare_samples(frozen, bundle)


@pytest.mark.parametrize("field,value", [("sample_id", ""), ("sample_id", None),
    ("evidence", []), ("evidence", None), ("limitations", None), ("limitations", "none")])
def test_sample_evidence_requirements(field, value):
    frozen, bundle = fixture_pair()
    bundle["samples"][0][field] = value
    with pytest.raises(ValueError):
        compare_samples(frozen, bundle)


@pytest.mark.parametrize("prediction", [math.nan, math.inf, True, -1])
def test_missing_visual_window_does_not_allow_invalid_frozen_prediction(prediction):
    frozen, bundle = fixture_pair()
    frozen["records"][0]["predicted_duration_seconds"] = prediction
    bundle["samples"][0]["start_video_interval_seconds"] = None
    with pytest.raises(ValueError):
        compare_samples(frozen, bundle)


def test_missing_departure_does_not_silently_retain_nan_in_other_window():
    frozen, bundle = fixture_pair()
    bundle["samples"][0]["start_video_interval_seconds"] = None
    bundle["samples"][0]["end_video_interval_seconds"] = [12, math.nan]
    with pytest.raises(ValueError):
        compare_samples(frozen, bundle)
