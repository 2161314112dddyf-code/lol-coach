import json
import pytest

from lol_coach.region_vision import channel_intervals, checked_indexes, frame_queries, visibility_query
from lol_coach.reasoning_frame import compile_frame, model_messages


SHA = "a" * 64
GROUND = "ground:camp"


def row(at, visible, *, team=100, mode="transition", subject=GROUND, **extra):
    return dict(time_seconds=at, visible=visible, team_id=team, mode=mode, subject=subject,
                source={"kind": "test", "private": "AUDIT_ONLY"}, **extra)


def index(*events, sha=SHA):
    return dict(schema="vision-evidence/v1", version="build", source_sha256=sha,
                end_seconds=120, observations=list(events))


def test_observer_subject_and_time_are_independent():
    rows = [index(row(1, False), row(10, True), row(11, True, team=200, subject="entity:hero"))]
    for team, subject, t, expected in [
            (100, GROUND, 0, None), (100, GROUND, 2, False), (100, GROUND, 10, True),
            (200, GROUND, 11, None), (200, "entity:hero", 11, True), (100, "entity:hero", 11, None)]:
        assert visibility_query(rows, team, subject, t)["visible"] is expected


def test_hud_does_not_carry_and_native_barrier_clears_state():
    rows = [index(row(4, True), row(8, None), row(9, True, mode="sample"))]
    assert [visibility_query(rows, 100, GROUND, t)["visible"] for t in (7, 8, 9, 9.01)] == [True, None, True, None]


def test_disagreement_and_delayed_updates_are_not_certainty():
    rows = [index(row(2, True), row(3, False, mode="sample"), row(5, False, available_at_seconds=6))]
    assert visibility_query(rows, 100, GROUND, 3)["basis"] == "conflicting_evidence"
    assert visibility_query(rows, 100, GROUND, 5.5)["visible"] is None
    assert visibility_query(rows, 100, GROUND, 6)["visible"] is False


def test_durations_use_transitions_not_interpolated_frames():
    inputs = [index(row(2, False, mode="sample"), row(3, True), row(7.5, False), row(9, None))]
    result = channel_intervals(inputs, 100, GROUND, 1, 11)
    assert result["seconds"] == {"visible": 4.5, "hidden": 1.5, "unknown": 4}


def test_scope_end_time_and_mismatched_files():
    with pytest.raises(ValueError): checked_indexes([index(), index(sha="b"*64)])
    with pytest.raises(ValueError): frame_queries([index()], "different", SHA, 100, 3)
    with pytest.raises(ValueError): frame_queries([index()], "build", SHA, 100, 121)
    with pytest.raises(ValueError): checked_indexes([index(row(2, 1))])


@pytest.mark.parametrize("kind", ["player_hud", "calibrated_player_minimap_shading"])
def test_hud_bucket_requires_same_recording_and_decision_image_time(kind):
    hud = row(5, True, mode="sample")
    hud["source"] = dict(kind=kind, video_sha256=SHA, pts_first=8.2, pts_last=8.6)
    inputs = ([index(hud)], "build", SHA, 100, 5, [GROUND])
    for bad in (None, {"video_sha256": "b" * 64, "pts": 8.3}, {"video_sha256": SHA, "pts": 8.1}):
        assert frame_queries(*inputs, hud_frame=bad)[0]["visible"] is None
    assert frame_queries(*inputs, hud_frame={"video_sha256": SHA, "pts": 8.3})[0]["visible"] is True


def test_prefix_and_visibility_audit_do_not_leak_into_prompt():
    s = {"schema":"macro-snapshot/v1", "context":{"at_seconds":5, "observer_team_id":100,
         "player_entity_id":"self"}, "source_sha256":SHA, "version":"build", "evidence":{},
         "heroes":[{"entity_id":"self", "team_id":100, "champion":"Pantheon", "inventory":{}, "visibility":{"value":True}}],
         "recent_public_combat":[]}
    rows = [index(row(2, True), row(6, False, subject="ground:FUTURE"), row(2, False, team=200, subject="ground:ENEMY"))]
    bundle = compile_frame(s, vision_indexes=rows, max_principles=0)
    frame = bundle["frame"]; [fact_id] = frame["vision_fact_ids"]
    assert frame["facts"][fact_id]["value"]["visible"] is True
    assert "AUDIT_ONLY" in str(bundle["audit"]["fact_sources"][fact_id])
    prompt = json.dumps(model_messages(bundle, {}))
    for private in ("FUTURE", "ENEMY", "AUDIT_ONLY"):
        assert private not in prompt
