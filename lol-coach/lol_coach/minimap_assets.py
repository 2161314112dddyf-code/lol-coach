"""Extract the installed Map11 minimap and static camp locators, offline."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from PIL import Image
import xxhash
import zstandard

from .prop_reader import Reader, fnv
from .wad import WadReader


MAP_CONFIG = "data/maps/shipping/map11/map11.bin"
TEXTURE = "assets/maps/info/map11/2dlevelminimap_base_baron1.tex"
TOC = "data/final/maps/shipping/map11.wad.subchunktoc"
# Named world transforms in the Map11 PROP's locator table on 16.22.
LOCATOR_ENTRY = 0xA250382E
LOCATOR_LIST = "{b471dc2a}"
LOCATORS = {"Dragon": "dragon", "Baron1": "baron", "DragonEelCamp": "scuttle",
            "BaronEelCamp": "scuttle"}
for side in ("Order", "Chaos"):
    for suffix, kind in (("BlueBuff1", "blue"), ("RedBuff1", "red"), ("Wolves1", "wolves"),
                         ("Golems1", "krugs"), ("Vultures1", "raptors"), ("OwlBear", "gromp")):
        LOCATORS[side + suffix] = kind


def _read_config(raw, skin, *, variant_hashes=False):
    labels = ("name", "transform", "mMinimapBackgroundConfig", "mDefaultTextureName",
              "mCustomMinimapBackgrounds", "mTextureName", "mSize", "mOrigin")
    reader = Reader(raw, {fnv(s): s for s in labels})
    if reader.read(4) != b"PROP" or reader.number("I") != 3:
        raise ValueError("Expected a Map11 PROP v3 config")
    for _ in range(reader.count("I")):
        reader.string()
    types = [reader.number("I") for _ in range(reader.count("I"))]
    backgrounds, camps = {}, {}
    for entry_type in types:
        length = reader.number("I")
        end = reader.pos + length
        key, count = reader.fmt("IH")
        if end > len(raw) or end < reader.pos:
            raise ValueError("Bad PROP entry boundary")
        if key == LOCATOR_ENTRY or entry_type == fnv("MapSkin"):
            fields = reader.fields(count)
            if reader.pos != end:
                raise ValueError("Unexpected end of Map11 entry")
            if key == LOCATOR_ENTRY:
                for row in fields[LOCATOR_LIST]:
                    name = row["name"]
                    if name in LOCATORS:
                        if name in camps:
                            raise ValueError("Duplicate camp locator")
                        transform = row["transform"]
                        camps[name] = dict(kind=LOCATORS[name], locator=name,
                                           xz=[transform[12], transform[14]])
            else:
                backgrounds[fields["name"]] = fields["mMinimapBackgroundConfig"]
        reader.pos = end
    if reader.pos != len(raw) or camps.keys() != LOCATORS.keys():
        raise ValueError("Incomplete Map11 camp locator configuration")
    bg = backgrounds[skin]
    if variant_hashes:
        return sorted({int(v["mTextureName"]) for _, v in bg["mCustomMinimapBackgrounds"]
                       if tuple(v.get("mOrigin",(0,0))) == (0,0) and tuple(v["mSize"]) == (14850,14850)})
    texture_hash = xxhash.xxh64_intdigest(TEXTURE.encode())
    if bg["mDefaultTextureName"] != texture_hash:
        raise ValueError("Selected skin has a different minimap texture")
    rectangles = set()
    for _, variant in bg.get("mCustomMinimapBackgrounds", []):
        if variant["mTextureName"] == texture_hash:
            x, z = variant.get("mOrigin", [0, 0])
            width, height = variant["mSize"]
            rectangles.add((x, z, x + width, z + height))
    if len(rectangles) != 1:
        raise ValueError("No unique configured world extent for this texture")
    matching = sorted(n for n, b in backgrounds.items() if b["mDefaultTextureName"] == texture_hash)
    return list(rectangles.pop()), list(camps.values()), matching


def _texture_bytes(wad, key=None):
    key = xxhash.xxh64_intdigest(TEXTURE.encode()) if key is None else key
    entry = wad.entries[key]
    if entry.storage_type in (0, 3):
        return wad.extract_hash(key)[0]
    parts = entry.storage_type >> 4
    if (entry.storage_type & 15 != 4 or not parts or
            max(entry.size, entry.compressed_size) > 16000000):
        raise ValueError("Unexpected minimap storage type or size")
    # WAD 3.4 index bytes 21..23 store the 24-bit subchunk index (high byte first).
    for identifier, _, _, _, _, high, low, _ in struct.iter_unpack("<QIIIBBHQ", wad.index_bytes[272:]):
        if identifier == key:
            start = high * 65536 + low
            break
    toc, _ = wad.extract_bytes(TOC)
    if (start + parts) * 16 > len(toc):
        raise ValueError("Invalid minimap subchunk table range")
    with wad.path.open("rb") as f:
        f.seek(entry.offset)
        packed = f.read(entry.compressed_size)
    if xxhash.xxh3_64_intdigest(packed) != entry.checksum:
        raise ValueError("Invalid minimap WAD checksum")
    raw, offset = bytearray(), 0
    for compressed, size, checksum in struct.iter_unpack("<IIQ", toc[start*16:(start+parts)*16]):
        block = packed[offset:offset+compressed]
        if (len(block) != compressed or xxhash.xxh3_64_intdigest(block) != checksum
                or len(raw) + size > entry.size):
            raise ValueError("Invalid minimap subchunk")
        if block.startswith(b"\x28\xb5\x2f\xfd"):
            if zstandard.frame_content_size(block) != size:
                raise ValueError("Invalid minimap subchunk frame size")
            block = zstandard.ZstdDecompressor().decompress(block, max_output_size=size, allow_extra_data=False)
        if len(block) != size:
            raise ValueError("Invalid minimap subchunk length")
        raw.extend(block)
        offset += compressed
    if len(raw) != entry.size or offset != len(packed):
        raise ValueError("Incomplete minimap subchunks")
    return bytes(raw)


def decode_base_minimap(raw):
    """Return row-zero-at-top RGBA from the verified square BC3 TEX mip chain."""
    if len(raw) < 12 or raw[:4] != b"TEX\0":
        raise ValueError("Expected a TEX texture")
    w, h, extension, fmt, unused, mips = struct.unpack_from("<HHBBBB", raw, 4)
    if (w, h, extension, fmt, unused, mips) != (512, 512, 1, 12, 0, 1):
        raise ValueError("Expected the 512x512 BC3 minimap")
    level_sizes = [max(1, w >> (n+2)) ** 2 * 16 for n in range(w.bit_length())]
    if len(raw) != 12 + sum(level_sizes):
        raise ValueError("Invalid TEX mip chain length")
    return Image.frombytes("RGBA", (w, h), raw[-level_sizes[0]:], "bcn", (3, "DXT5"))


def extract_assets(game_dir, output, *, build="16.22.836.1077", skin="Default"):
    game, out = Path(game_dir), Path(output)
    ver = build.split(".")
    expected = ".".join(ver[:2] + ["".join(ver[2:])])
    if len(ver) != 4 or any(json.loads((game / f).read_bytes())["version"].split("+")[0] != expected
                            for f in ("content-metadata.json", "code-metadata.json")):
        raise ValueError("Installed asset version differs from the requested replay build")
    wad = WadReader(game / "DATA/FINAL/Maps/Shipping/Map11.wad.client")
    config, ref = wad.extract_bytes(MAP_CONFIG)
    extent, camps, matching = _read_config(config, skin)
    raw = _texture_bytes(wad)
    image = decode_base_minimap(raw)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / "minimap.png"
    image.save(dest)
    report = dict(build=build, map_id=11, skin=skin, texture_file=dest.name,
                  texture_sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),
                  world_extent=extent, camps=camps, image_size=list(image.size),
                  archive=wad.path.name, wad_index_sha256=hashlib.sha256(wad.index_bytes).hexdigest(),
                  texture_path=TEXTURE, tex_sha256=hashlib.sha256(raw).hexdigest(),
                  config_path=MAP_CONFIG, config_sha256=ref["sha256"], locator_entry=hex(LOCATOR_ENTRY),
                  other_skins_with_same_default=sorted(set(matching) - {skin}),
                  background_scope="Installed default skin texture; active in-game overlays and elemental variants are not selected.",
                  camp_scope="Static named world locators; monster presence, position and timers require replay evidence.")
    (out/"assets.json").write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n", encoding="utf8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    extract_assets(args.game_dir, args.output)
