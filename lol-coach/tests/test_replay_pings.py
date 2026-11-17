import pytest

from lol_coach.hero_sight import reviewed_heroes
from lol_coach.movement_1622 import TEN_PLAYER
from lol_coach.replay_pings import OPCODE, build_ping_index, decode_ping_fields, decode_ping_packet
from scripts.audit_replay_pings import FOOTER_KINDS, footer_counts


def packet(hex_body, **fields):
    return dict(dict(stream=1, channel=1, opcode=OPCODE, param=0, chunk=3, offset=108587,
                     time=17.785788700103787, payload=bytes.fromhex(hex_body)), **fields)


HEROES = reviewed_heroes(TEN_PLAYER)
# Actual bytes of the first accepted signal, emitted before 18 seconds.
COMMAND = "55a22a885d93f701a54ac693"


def test_command_uses_presence_bits_and_sender_slot():
    event = decode_ping_packet(packet(COMMAND), HEROES)
    assert event["time_seconds"] == 17.785788700103787
    assert (event["sender_champion"], event["sender_entity_id"], event["team_id"]) == ("MasterYi", "0x400000b4", 200)
    assert event["kind"] == "command" and event["source"]["offset"] == 108587
    assert event["marker_xz"] is None and "channel" not in event
    assert "delivery" not in event and "attention" not in event


@pytest.mark.parametrize(("body", "slot"), [
    ("6da3f74d44d72af51c62e3eb72c393", 3),
    ("5da3f770bd162a34e46b0f3672c293", 2),
])
def test_second_real_match_long_command_keeps_wire_sender(body, slot):
    event = decode_ping_fields(packet(body))
    assert (event["kind"], event["sender_slot"]) == ("command", slot)
    assert event["marker_xz"] is None and "channel" not in event


@pytest.mark.parametrize("body", [
    "55a3f74d44d72af51c62e3eb72c393",  # unobserved header for three extra bytes
    "6da3f74d44d72af51c62e3eb00c393",  # different ending
    "6da3f74d44d72af51c62e3eb0072c393",  # unobserved command length
])
def test_other_long_command_shapes_remain_unknown(body):
    with pytest.raises(ValueError, match="unreviewed_player_ping_kind"):
        decode_ping_fields(packet(body))


@pytest.mark.parametrize(("kind_byte", "kind"), [(0x64, "get_back"), (0x65, "on_my_way"),
                         (0x66, "enemy_vision"), (0x67, "assist_me"), (0x69, "all_in"),
                         (0x6B, "retreat"), (0x7A, "enemy_missing"), (0x7E, "push"), (0x7F, "need_vision")])
def test_wire_type_values_and_channel_scope(kind_byte, kind):
    event = decode_ping_packet(packet("d562f79e14692a60553c" + f"{kind_byte:02x}" + "c493"), HEROES)
    assert (event["kind"], event["team_id"], event["sender_champion"]) == (kind, 100, "Pantheon")
    assert (event.get("channel") == "team") == (kind != "get_back")
    assert "delivery" not in event


@pytest.mark.parametrize("fields", [dict(stream=2), dict(channel=2), dict(opcode=0x40)])
def test_other_channels_and_checkpoints_do_not_emit(fields):
    assert decode_ping_packet(packet(COMMAND, **fields), HEROES) is None


def test_uncounted_same_opcode_packet_does_not_emit_even_when_sender_and_type_look_valid():
    assert decode_ping_packet(packet("1562f79e14692a60553c65c493"), HEROES) is None


@pytest.mark.parametrize("body", ["", COMMAND[:-2], COMMAND[:-4] + "ff93",
                                   "d562f79e14692a60553cffc493", "55a22a885d93f701a54ac69300"])
def test_unreviewed_shape_rejected(body):
    with pytest.raises(ValueError):
        decode_ping_packet(packet(body), HEROES)


def test_no_sender_guess_and_no_exposing_unreviewed_replay():
    with pytest.raises(ValueError, match="sender"):
        decode_ping_packet(packet(COMMAND), {})
    unknown = build_ping_index(b"unreviewed")
    assert unknown["events"] == [] and unknown["status"] == "unsupported_replay"


def test_missing_zero_counter_does_not_pass_an_audit():
    row = {kind.upper() + "_PINGS": "0" for kind in FOOTER_KINDS}
    row["PING"] = "42"
    assert footer_counts(row) == dict.fromkeys(FOOTER_KINDS, 0)
    del row["BASIC_PINGS"]
    with pytest.raises(ValueError, match="counters"):
        footer_counts(row)
