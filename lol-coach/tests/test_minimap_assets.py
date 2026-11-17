"""Exercise the BC3 mip order and checked Map11 subchunk extraction."""
import struct
from types import SimpleNamespace

import pytest

pytest.importorskip("PIL.Image")
import xxhash
import zstandard

from lol_coach.minimap_assets import TEXTURE, TOC, _texture_bytes, decode_base_minimap


def test_primary_tex_mip_is_at_end_and_alpha_is_preserved():
    header = struct.pack("<4sHH4B", b"TEX\0", 512, 512, 1, 12, 0, 1)
    # Transparent black for the small mips; opaque red in the primary level.
    top_block = struct.pack("<2B6x2HI", 255, 0, 0xf800, 0, 0)
    raw = header + bytes(349564 - len(header) - 262144) + top_block * (128 * 128)
    image = decode_base_minimap(raw)
    assert image.size == (512, 512)
    assert image.getpixel((510, 507)) == (255, 0, 0, 255)
    with pytest.raises(ValueError, match="mip chain"):
        decode_base_minimap(raw[:-16])


def test_packed_mips_use_their_own_checked_sizes_and_hashes(tmp_path):
    chunks = [b"d" * 64, b"e" * 128]
    packed = [zstandard.ZstdCompressor().compress(block) for block in chunks]
    source = b"".join(packed)
    path = tmp_path/"texture.wad"
    path.write_bytes(source)
    key = xxhash.xxh64_intdigest(TEXTURE.encode())
    checksum = xxhash.xxh3_64_intdigest(source)
    entry = SimpleNamespace(storage_type=0x24, compressed_size=len(source), size=192,
                            offset=0, checksum=checksum)
    index = bytes(272) + struct.pack("<QIIIBBHQ", key, 0, len(source), 192, 0x24, 0, 1, checksum)
    table = bytearray(16)
    for raw, block in zip(chunks, packed):
        table.extend(struct.pack("<IIQ", len(block), len(raw), xxhash.xxh3_64_intdigest(block)))
    def extract_toc(name):
        assert name == TOC
        return bytes(table), {}
    wad = SimpleNamespace(path=path, entries={key:entry}, index_bytes=index, extract_bytes=extract_toc)
    assert _texture_bytes(wad) == b"".join(chunks)
    table[-1] ^= 1
    with pytest.raises(ValueError, match="Invalid minimap subchunk"):
        _texture_bytes(wad)
