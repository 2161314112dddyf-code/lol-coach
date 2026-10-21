"""Synthetic contract tests; real replay checks are reported separately."""
import json
import pytest

from lol_coach.replay_fields import VERSION, analyze, decode_level_payload, read_metadata


def container(version=VERSION, stats=None):
    version = version.encode("ascii")
    header = b"RIOT\x02" + b"\x00" * 9 + bytes([len(version)]) + version
    meta = json.dumps({"gameLength": 1000, "statsJson": json.dumps(stats or [])}).encode()
    return header + b"\x00" * 256 + meta + len(meta).to_bytes(4, "little")


def packet(payload, owner=0x400000AE, time=1, opcode=0x229, stream=1):
    return dict(payload=payload, param=owner, time=time, opcode=opcode,
                stream=stream, chunk=1, offset=int(time * 100), channel=1)


def directory():
    return packet(b"synthetic directory", opcode=0x445, stream=2, time=0)


@pytest.mark.parametrize("payload,level", [(b"\x19", 2), (bytes.fromhex("3d37be"), 3),
                                          (bytes.fromhex("30e4"), 4), (bytes.fromhex("3722e4"), 4)])
def test_observed_shapes(payload, level):
    assert decode_level_payload(payload, VERSION) == level


@pytest.mark.parametrize("payload", [b"", b"\xbe", b"\x30", b"\x30\x00",
                                     b"\xff\xe4", b"\x30\x19", b"\x30\x01\x02\xe4"])
def test_unknown_or_truncated_does_not_invent_level(payload):
    with pytest.raises(ValueError):
        decode_level_payload(payload, VERSION)


def test_wrong_version_rejected():
    with pytest.raises(ValueError, match="build"):
        read_metadata(container("16.19.1"))
    with pytest.raises(ValueError, match="build"):
        decode_level_payload(b"\x19", "16.19.1")


def test_metadata_boundary_rejected():
    with pytest.raises(ValueError, match="boundary"):
        read_metadata(container()[:-4] + b"\xff" * 4)


def test_no_updates_does_not_mean_level_one_or_footer_level():
    result = analyze(container(stats=[{"SKIN": "Pantheon", "LEVEL": "13"}]), [directory()])
    assert result["level_checks"][0]["initial_level"] is None
    assert result["level_checks"][0]["last_observed_candidate"] is None
    assert result["identity_directory"]["owners"][0]["champion"] is None
    assert result["final_statistics"]["not_a_timeline"] is True
    assert result["decision_input_eligible"] is False


def test_non_champion_level_packet_excluded():
    result = analyze(container(), [directory(), packet(b"\x19", owner=0x4000021C)])
    assert not result["level_events"]
    assert result["excluded_level_packet_counts"] == {"non_directory_owner": 1}


def test_gap_and_unknown_preserved_instead_of_interpolated():
    result = analyze(container(), [directory(), packet(b"\x19"),
                                  packet(b"\x30\x00", time=2), packet(b"\x30\xe4", time=3)])
    assert [e["level_candidate"] for e in result["level_events"]] == [2, 4]
    assert result["rejected_level_packets"][0]["level_candidate"] is None
    assert result["level_checks"][0]["status"] == "FAIL"


def test_keyframe_events_not_counted_again():
    result = analyze(container(), [directory(), packet(b"\x19"), packet(b"\x19", stream=2)])
    assert len(result["level_events"]) == 1


def test_duplicate_directory_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        analyze(container(), [directory(), directory()])


def test_nonfinite_time_rejected():
    with pytest.raises(ValueError, match="timestamp"):
        analyze(container(), [directory(), packet(b"\x19", time=1) | {"time": float("nan")}])
