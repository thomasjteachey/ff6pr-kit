"""Japanese FF6 (Super Famicom v1.0) layout -> the US v1.0 layout the shared porter reads.

The shared porter (tools/port.py) diffs a modded ROM in the US v1.0 layout against the US ROM. A mod
built on the Japanese ROM (T-Edition) has three differences:

  * a few tables sit elsewhere in the Japanese ROM (JP_ADDRESS: the espers' learning/bonus data is
    at E6/F567, where the US ROM keeps its longer spell names; magic points per formation at
    D0/FE00), and the name tables are shorter kana fields at other addresses. Every other data table
    the porter reads is at the same address in both ROMs (checked 2026-11-20: characters, items,
    spells, monsters, formations, packs, zones, map properties, chests, shops, AI, sketches, rages,
    dances, natural magic, sprite entries);
  * the mod may have moved tables into the 4-6 MB expansion (ExHiROM) and grown them;
  * its text is the mod's own encoding (Mato's T-Edition translation: English in the JP ROM).

`build_us_image` turns such a mod into the porter's input: the US ROM's bytes, with every record the
mod changed (against the Japanese ROM) written over the US record at the US address, so that a
record the mod left alone reads as the US ROM's (its US names, its US data where the two versions
differ). The image lives in memory (ff6snes.MEMORY), never on disk. A mod's profile lists its tables
(`Table`) and fixes what doesn't fit a fixed-size record (chests, AI, grown tables) in its own code.
"""
import os

import ff6snes as S

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.normpath(os.path.join(HERE, "..", ".."))
JP_ROM_NAME = "Final Fantasy VI (Japan).sfc"
JP_CRC = 0x45EF5AC8   # FF6 JP v1.0 (no header); T-Edition's base ROM

# Tables the Japanese ROM keeps somewhere else than the US ROM: US file offset -> JP file offset
JP_ADDRESS = {
    0x186E00: 0x26F567,   # espers (11 bytes x 27): JP E6/F567 (the US ROM moved them to D8/6E00)
    0x1FB400: 0x10FE00,   # magic points per formation (1 byte x 512): JP D0/FE00
}


def jp_rom_path():
    for p in (os.environ.get("FF6_JP_ROM"), os.path.join(PROJECT, "rom", "vanilla", JP_ROM_NAME)):
        if p and os.path.exists(p):
            return p
    raise SystemExit(f"no Japanese ROM ({JP_ROM_NAME} in rom/vanilla): set FF6_JP_ROM")


def file_offset(snes):
    """A SNES address (HiROM / ExHiROM) -> file offset. Banks C0-FF: the first 4 MB; banks 40-7D: the
    ExHiROM second half (file 0x400000 + ...); 80-BF / 00-3F upper halves mirror them."""
    bank, low = snes >> 16, snes & 0xFFFF
    if bank >= 0xC0:
        return snes - 0xC00000
    if 0x40 <= bank < 0x7E:
        return snes
    if 0x80 <= bank < 0xC0 and low >= 0x8000:
        return snes - 0x800000
    if bank < 0x40 and low >= 0x8000:
        return 0x400000 + snes
    raise ValueError(f"${snes:06X} is not ROM")


def jp_address(us):
    return JP_ADDRESS.get(us, us)


class Table:
    """One fixed-size table: `count` records of `size` bytes at US file offset `us`; in the mod at
    file offset `mod` (records `mod_size` bytes; `convert(raw) -> size bytes` when the mod's record
    is another shape); in the Japanese ROM at `jp` (default: JP_ADDRESS or the US offset)."""

    def __init__(self, name, us, size, count, mod=None, mod_size=None, convert=None, jp=None, jp_convert=None):
        self.name, self.us, self.size, self.count = name, us, size, count
        self.mod = us if mod is None else mod
        self.mod_size = mod_size or size
        self.convert = convert
        self.jp = jp_address(us) if jp is None else jp
        self.jp_convert = jp_convert

    def mod_record(self, mod, i):
        raw = bytes(mod[self.mod + i * self.mod_size:self.mod + (i + 1) * self.mod_size])
        return self.convert(raw) if self.convert else raw

    def jp_record(self, jp, i):
        raw = bytes(jp[self.jp + i * self.size:self.jp + (i + 1) * self.size])
        return self.jp_convert(raw) if self.jp_convert else raw


def build_us_image(mod, jp, us, tables, size=None):
    """The US ROM's bytes with each record the mod changed (vs the Japanese ROM) written in.
    Returns (bytearray image, {table: (changed, count)})."""
    img = bytearray(us)
    if size and len(img) < size:
        img += bytes(size - len(img))
    stats = {}
    for t in tables:
        changed = 0
        for i in range(t.count):
            rec = t.mod_record(mod, i)
            if rec != t.jp_record(jp, i):
                img[t.us + i * t.size:t.us + (i + 1) * t.size] = rec[:t.size]
                changed += 1
        stats[t.name] = (changed, t.count)
    return img, stats


# --- US menu text (the porter reads names in it) --------------------------------------------------
_US_CODE = {v: k for k, v in S._NAME.items()}


def encode_us_name(text, width, icon=None):
    """A name in the US menu font, padded with 0xFF to `width` (an icon byte first if given)."""
    out = [icon] if icon is not None else []
    for ch in text:
        if ch in _US_CODE:
            out.append(_US_CODE[ch])
        elif ch == " ":
            out.append(0xFF)
    out = out[:width]
    return bytes(out + [0xFF] * (width - len(out)))
