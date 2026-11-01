"""Synthetic checks of the validity CLI's immutable forecast/label join."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf8")


@pytest.fixture
def audit_case(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "synthetic_travel_validity_audit", ROOT / "scripts/audit_travel_validity.py")
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    for relative in audit.CODE:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    monkeypatch.setattr(audit, "ROOT", tmp_path)

    private = tmp_path / "data/private"
    frozen, labels = private / "frozen", private / "labels"
    frozen.mkdir(parents=True)
    labels.mkdir()
    source = private / "synthetic_input.bin"
    source.write_bytes(b"synthetic causal input; not a game recording")
    forecast_path = private / "prior_forecast.json"
    forecast = dict(replay_id="synthetic-replay", entity_kind="hero",
                    records=[dict(prediction_id="endpoint"), dict(prediction_id="replaced")])
    write_json(forecast_path, forecast)
    query = dict(replay_id="synthetic-replay", entity_kind="hero",
                 source_forecast_file=str(forecast_path.resolve()),
                 source_forecast_sha256=audit.sha(forecast_path),
                 invalidations=[dict(reason="speed_changed_requires_new_path")],
                 rows=[dict(forecast_id="endpoint", horizon_seconds=0,
                            original_plan_current=True, status="conditional_active"),
                       dict(forecast_id="replaced", horizon_seconds=0,
                            original_plan_current=True, status="conditional_active"),
                       dict(forecast_id="endpoint", horizon_seconds=1,
                            original_plan_current=True, status="observation_stale")])
    query_path = frozen / "hero-synthetic-replay.json"
    write_json(query_path, query)
    manifest_path = frozen / "manifest.json"
    write_json(manifest_path, dict(inputs={"data/private/synthetic_input.bin": audit.sha(source)},
               jobs=[dict(file=query_path.name, sha256=audit.sha(query_path))]))
    label_path = labels / "hero-synthetic-replay.json"
    label = dict(replay_id="synthetic-replay", entity_kind="hero",
                 frozen_prediction_sha256=audit.digest(forecast),
                 rows=[dict(prediction_id="endpoint", outcome="endpoint_position_report",
                            observation_source=dict(stream=1), predicted_duration_seconds=0.5,
                            report_time_absolute_error_seconds=0.02, arrival_bracket_width_seconds=0.1),
                       dict(prediction_id="replaced", outcome="new_path_before_expected")])
    write_json(label_path, label)
    return SimpleNamespace(audit=audit, root=tmp_path, frozen=frozen, labels=labels,
        output=private / "evaluation", forecast_path=forecast_path, query_path=query_path,
        manifest_path=manifest_path, label_path=label_path, label=label, source=source)


def evaluate(case):
    case.audit.evaluate_queries(case.frozen, case.labels, case.output)


def test_correct_join_retains_old_outcomes_without_granting_timing_qualification(audit_case):
    case = audit_case
    paths = [case.forecast_path, case.query_path, case.manifest_path, case.label_path, case.source]
    before = {path: path.read_bytes() for path in paths}
    evaluate(case)
    report = case.audit.read(case.output / "summary.json")
    assert report["timing_qualification"] == "INSUFFICIENT_EVIDENCE"
    assert report["model_integration_permitted"] is False
    assert report["human_signoff"] is None
    group = report["groups"]["hero"]
    assert group["timing_qualification"] == "INSUFFICIENT_EVIDENCE"
    assert group["active_zero_old_outcomes"] == {
        "endpoint_position_report": 1, "new_path_before_expected": 1}
    assert group["query_counts"] == {"conditional_active": 2, "observation_stale": 1}
    assert group["invalidations"] == {"speed_changed_requires_new_path": 1}
    assert group["old_live_endpoint_reports"] == [dict(
        replay_id="synthetic-replay", forecast_id="endpoint", report_error_seconds=0.02,
        bracket_width_seconds=0.1)]
    assert {path: path.read_bytes() for path in paths} == before


@pytest.mark.parametrize("field,value", [("replay_id", "different-replay"),
                                        ("entity_kind", "minion"),
                                        ("frozen_prediction_sha256", "0" * 64)])
def test_rejects_labels_bound_to_another_source(audit_case, field, value):
    case = audit_case
    case.label[field] = value
    write_json(case.label_path, case.label)
    with pytest.raises(ValueError, match="do not match"):
        evaluate(case)
    assert not (case.output / "summary.json").exists()


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unrelated"])
def test_rejects_missing_duplicate_and_unrelated_prediction_ids(audit_case, mutation):
    case = audit_case
    if mutation == "missing":
        case.label["rows"].pop()
    elif mutation == "duplicate":
        case.label["rows"].append(dict(case.label["rows"][0]))
    else:
        case.label["rows"][0]["prediction_id"] = "unrelated"
    write_json(case.label_path, case.label)
    with pytest.raises(ValueError, match="missing, duplicated or unrelated"):
        evaluate(case)
    assert not (case.output / "summary.json").exists()


def test_original_forecast_byte_change_is_rejected_even_if_json_value_is_equal(audit_case):
    case = audit_case
    before = case.forecast_path.read_bytes()
    case.forecast_path.write_bytes(before + b"\n")
    with pytest.raises(ValueError, match="Original forecasts changed"):
        evaluate(case)
    assert case.forecast_path.read_bytes() == before + b"\n"
    assert not (case.output / "summary.json").exists()


def test_frozen_query_bytes_cannot_change_before_join(audit_case):
    case = audit_case
    query = case.audit.read(case.query_path)
    query["rows"][0]["status"] = "observation_stale"
    write_json(case.query_path, query)
    with pytest.raises(ValueError, match="Causal queries changed"):
        evaluate(case)
    assert not (case.output / "summary.json").exists()


def test_changed_causal_input_is_rejected_before_writing_output(audit_case):
    case = audit_case
    case.source.write_bytes(b"changed synthetic evidence")
    with pytest.raises(ValueError, match="Causal inputs changed"):
        evaluate(case)
    assert not case.output.exists()


def test_join_cannot_overwrite_a_previous_evaluation(audit_case):
    case = audit_case
    evaluate(case)
    before = (case.output / "summary.json").read_bytes()
    with pytest.raises(FileExistsError):
        evaluate(case)
    assert (case.output / "summary.json").read_bytes() == before


def test_output_must_be_below_private_directory(audit_case):
    case = audit_case
    with pytest.raises(ValueError, match="new child of data/private"):
        case.audit.evaluate_queries(case.frozen, case.labels, case.root / "public")
    assert not (case.root / "public").exists()
