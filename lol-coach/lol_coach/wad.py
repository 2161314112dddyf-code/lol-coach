"""Small read-only WAD 3.4 reader for bounded raw/Zstandard map entries.

Format references and their licenses are recorded in docs/MAP_FORMAT_NOTES.md.
This is not a general archive extractor: subchunks and redirects are rejected.
"""
import hashlib
import struct
from dataclasses import dataclass, asdict
from pathlib import Path

import xxhash
import zstandard


@dataclass(frozen=True)
class Entry:
    path_hash: int
    offset: int
    compressed_size: int
    size: int
    storage_type: int
    checksum: int


class WadReader:
    def __init__(self, path):
        self.path = Path(path)
        self.file_size = self.path.stat().st_size
        with self.path.open("rb") as f:
            head = f.read(272)
            if len(head) != 272 or head[:4] != b"RW\x03\x04":
                raise ValueError("Only WAD 3.4 is supported")
            count = struct.unpack_from("<I", head, 268)[0]
            if not 0 < count <= 1_000_000 or 272 + count * 32 > self.file_size:
                raise ValueError("Invalid WAD index size")
            self.index_bytes = head + f.read(count * 32)
        self.entries = {}
        for values in struct.iter_unpack("<QIIIBBHQ", self.index_bytes[272:]):
            key, offset, compressed, size, kind, _, _, checksum = values
            if key in self.entries or offset < len(self.index_bytes) or offset + compressed > self.file_size:
                raise ValueError("Duplicate hash or out-of-bounds WAD entry")
            self.entries[key] = Entry(key, offset, compressed, size, kind, checksum)

    def extract_bytes(self, internal_path, max_bytes=16_000_000):
        key = xxhash.xxh64_intdigest(internal_path.lower().encode("utf-8"))
        if key not in self.entries:
            raise ValueError(f"WAD path not found: {internal_path}")
        entry = self.entries[key]
        if not 0 < entry.size <= max_bytes or not 0 < entry.compressed_size <= max_bytes:
            raise ValueError("WAD entry exceeds extraction size limit")
        if entry.storage_type not in (0, 3):
            raise ValueError(f"Unsupported WAD storage type: {entry.storage_type}")
        with self.path.open("rb") as f:
            f.seek(entry.offset)
            packed = f.read(entry.compressed_size)
        if len(packed) != entry.compressed_size or xxhash.xxh3_64_intdigest(packed) != entry.checksum:
            raise ValueError("WAD compressed-entry checksum mismatch")
        if entry.storage_type == 0:
            data = packed
        else:
            if zstandard.frame_content_size(packed) != entry.size:
                raise ValueError("Zstandard frame size differs from WAD index")
            data = zstandard.ZstdDecompressor().decompress(packed, max_output_size=max_bytes, allow_extra_data=False)
        if len(data) != entry.size:
            raise ValueError("WAD decompressed size mismatch")
        evidence = asdict(entry)
        evidence.update(internal_path=internal_path, path_hash=f"{key:016x}",
                        compressed_sha256=hashlib.sha256(packed).hexdigest(),
                        sha256=hashlib.sha256(data).hexdigest(), checksum_status="xxh3_64_verified")
        return data, evidence
