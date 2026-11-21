"""FF6 SNES monster sprites at any table addresses (kit tool): tools/snes_sprites.py's decoder for a mod that moved
the monster graphics tables. To be folded into snes_sprites.py as a layout option after the WC 0.6.9 release
(snes_sprites is frozen until then).

    import snes_sprites_at as SA
    s = SA.Sprites(rom_bytes, SA.TEDITION)          # T-Edition 3.0.7 / EX 2.0.6
    sp = s.sprite(400)                              # snes_sprites.Sprite: .px (index rows), .pal, .bbox(), .rgba()
    w, h, rgba, x0, y0 = SA.cropped(sp)             # the opaque box as RGBA, and where it sits in the tile grid

A Layout says where each table is (file offsets in the headerless image): `entries` (5 bytes a monster: the
tile pointer & 0x7FFF in 8-byte units, bit 15 = 3bpp; byte 2 bit 7 = a big 16x16 stencil, bits 0-1 + byte 3 = the
palette index; byte 4 = the stencil index), `count`, `palettes` (16 bytes = 8 colors each, a 4bpp sprite reads
two), `tiles(i)` (the tile base for monster i: vanilla E9/7000 for all; T-Edition picks the bank by monster id),
and the stencil pointers (`comp8`, `comp16`: two bytes each, into bank D2).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import snes_sprites as SS  # noqa: E402


class Layout:
    def __init__(self, name, entries, count, palettes, tiles, comp8=0x12A820, comp16=0x12A822):
        self.name, self.entries, self.count, self.palettes = name, entries, count, palettes
        self.tiles, self.comp8, self.comp16 = tiles, comp8, comp16


VANILLA = Layout("vanilla", SS.INFO, SS.N, SS.PAL, lambda i: SS.GFX)


def _tedition_tiles(i):
    """T-Edition's hook (C1/2040 stores the monster id, C0/D978 picks the bank): F0/0000 for 0-416 and
    432-479, F4/0000 for 417-431, F5/0000 for 480-511 (and EX's 512+, read from EX's own ROM by its slot)."""
    return 0x350000 if i >= 0x1E0 else 0x340000 if 0x1A1 <= i < 0x1B0 else 0x300000


# entries CF/1A00 (512, vanilla's format), palettes 41/6200, stencils as vanilla (MEDIA_INVENTORY.md 2.1)
TEDITION = Layout("tedition", 0x0F1A00, 512, 0x416200, _tedition_tiles)


class Sprites(SS.Sprites):
    """snes_sprites.Sprites over a Layout (rom: the image's bytes)."""

    def __init__(self, rom, layout=VANILLA):
        self.layout = layout

        class _Rom:
            data = rom

            def b(self, a, n):
                return rom[a:a + n]
        self.rom = _Rom()
        d = rom
        self.comp8 = 0x120000 + (d[layout.comp8] | d[layout.comp8 + 1] << 8)
        self.comp16 = 0x120000 + (d[layout.comp16] | d[layout.comp16 + 1] << 8)
        self._base = SS.GFX

    def entry(self, i):
        e = self.rom.b(self.layout.entries + 5 * i, 5)
        return e[0] | e[1] << 8, bool(e[2] & 0x80), (e[2] & 3) << 8 | e[3], e[4]

    def palette(self, pal_index, bpp3):
        n = 8 if bpp3 else 16
        raw = self.rom.b(self.layout.palettes + 16 * pal_index, 2 * n)
        return [SS.snes_rgb(raw[2 * k] | raw[2 * k + 1] << 8) for k in range(n)]

    def sprite(self, i):
        self._base = self.layout.tiles(i)
        return super().sprite(i)

    def tile(self, at, bpp3):          # snes_sprites asks for GFX + 8 x pointer + n: rebased on this monster's bank
        return super().tile(self._base + at - SS.GFX, bpp3)


def cropped(sp):
    """A Sprite's opaque box: (w, h, rgba top-down, x0, y0), x0/y0 its place in the tile grid; None if empty."""
    bb = sp.bbox()
    if not bb:
        return None
    x0, y0, x1, y1 = bb
    out = bytearray()
    for y in range(y0, y1):
        for x in range(x0, x1):
            v = sp.px[y][x]
            out += (bytes(sp.pal[v]) + b"\xff") if v else b"\0\0\0\0"
    return x1 - x0, y1 - y0, bytes(out), x0, y0
