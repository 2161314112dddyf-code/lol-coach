"""Create two private, labelled derivatives of one reviewed ROFL for a causal experiment."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import struct
import sys

import zstandard

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.movement_1622 import PANTHEON
from lol_coach.replay_container import chunks, container_info, packets
from lol_coach.vision_regions_1622 import OPCODE, WIRE_TO_FLOAT_BYTE, decode_spatial_record


def make_pair(source, destination):
    original = source.read_bytes()
    digest = lambda data: hashlib.sha256(data).hexdigest()
    if digest(original) != PANTHEON:
        raise ValueError("This intervention belongs to the reviewed Pantheon original only")
    destination.mkdir(parents=True, exist_ok=False)
    edits = defaultdict(list)
    old, new = [2104, 8310], [6280, 9860]
    encode = bytes(WIRE_TO_FLOAT_BYTE.index(i) for i in range(256))
    replacement = struct.pack(">ff", new[1], new[0]).translate(encode)
    for p in packets(original):
        if p["opcode"] != OPCODE:
            continue
        row = decode_spatial_record(p["payload"])
        if (row and row["center_xz"] == old and row["team_id"] == 100
                and row["family"] == "ordinary_or_control_ward_associated"):
            edits[p["stream"], p["chunk"]].append((p, row["payload_offset_zx"]))
    if set(edits) != {(1, 50), (2, 4), (2, 5)} or sum(map(len, edits.values())) != 3:
        raise ValueError("Ward source count or chunk registration changed")
    info = container_info(original)
    report = dict(original_sha256=PANTHEON, old_xz=old, new_xz=new, receipt={})
    for kind in ("repacked_control", "shifted_region"):
        output = bytearray(original[:info["start"]])
        expected_hashes, changes = [], []
        for chunk in chunks(original):
            start = chunk["container_offset"]
            size = chunk["header_size"]
            header = bytearray(original[start:start + size])
            compressed_size, = struct.unpack_from("<I", header, 13)
            raw = bytearray(chunk["raw"])
            modified = edits.get((chunk["stream"], chunk["chunk"]))
            stored_size = compressed_size or len(raw)
            if modified:
                for p, word in modified:
                    layout = bytes(raw).find(p["payload"], p["offset"], p["offset"] + len(p["payload"]) + 20)
                    if layout < 0:
                        raise ValueError("Cannot resolve original payload at its packet boundary")
                    pos = layout + word
                    if kind == "shifted_region":
                        changes.append(dict(stream=p["stream"], chunk=p["chunk"], at=p["time"],
                                            packet_offset=p["offset"], coordinate_offset_in_chunk=pos,
                                            old=raw[pos:pos+8].hex(), new=replacement.hex()))
                        raw[pos:pos + 8] = replacement
                stored = zstandard.ZstdCompressor(level=3).compress(raw) if compressed_size else raw
                if compressed_size:
                    struct.pack_into("<I", header, 13, len(stored))
            else:
                stored = original[start + size:start + size + stored_size]
            output.extend(header)
            output.extend(stored)
            expected_hashes.append(digest(raw))
        # Preserve the original footer/signature and metadata bytes in both forms.
        output.extend(original[info["end"]:])
        if [digest(c["raw"]) for c in chunks(output)] != expected_hashes:
            raise ValueError("Decompressed chunks differ from intended content")
        count = 0
        for a, b in zip(packets(original), packets(output), strict=True):
            if a == b:
                continue
            delta = [k for k in a if a[k] != b[k]]
            before = decode_spatial_record(a["payload"])
            after = decode_spatial_record(b["payload"])
            if (delta != ["payload"] or not before or not after or before["center_xz"] != old
                    or after["center_xz"] != new or (a["stream"], a["chunk"]) not in edits):
                raise ValueError("Unexpected packet difference")
            count += 1
        if count != len(changes):
            raise ValueError("Unverified number of packet changes")
        path = destination / kind / source.name
        path.parent.mkdir()
        path.write_bytes(output)
        report["receipt"][kind] = dict(file=str(path.resolve()), sha256=digest(output),
                                       modified_packets=count, changes=changes, size=len(output))
    if digest(source.read_bytes()) != PANTHEON:
        raise ValueError("Original file changed")
    (destination / "receipt.json").write_text(json.dumps(report, indent=2), encoding="utf8")
    return report


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("source", type=Path)
    cli.add_argument("new_output_directory", type=Path)
    args = cli.parse_args()
    print(json.dumps(make_pair(args.source, args.new_output_directory), indent=2))
