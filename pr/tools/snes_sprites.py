"""FF6 SNES monster sprites: decode a ROM's monster graphics into palette-index images.

    from snes_sprites import Sprites
    s = Sprites(rom)            # ff6snes.Rom (vanilla or a mod) or the image's bytes
    sp = s.sprite(i)            # monster i (0..383): .w, .h, .px (index rows, 0 = clear), .pal (RGB list)
    s = Sprites(data, TEDITION) # a mod that moved the tables (a Layout: T-Edition 3.0.7 / EX 2.0.6, monsters 0-511)
    w, h, rgba, x0, y0 = cropped(sp)   # the opaque box as RGBA, and where it sits in the tile grid

Layout (vanilla US 1.0, the same in BNW): graphics entries D2/7000 (5 bytes: tile pointer
& 0x7FFF in 8-byte units at E9/7000, bit 15 = 3bpp; byte 2 bit 7 = big 16x16 stencil, bits 0-1 +
byte 3 = palette index; byte 4 = stencil index), palettes D2/7820 (16 bytes = 8 colors each, a
4bpp sprite reads two), stencils at the D2 offsets in D2/A820 (8x8 tiles, 8 bytes) and D2/A822
(16x16 tiles, 32 bytes, big-endian words). Beyond Chaos' remonsterate.py decodes them the same way.
A Layout says where each table is for a mod that moved them (`entries`, `count`, `palettes`, `tiles(i)`: the tile
base for monster i, and the stencil pointers `comp8`/`comp16`); VANILLA (the default) is the above.

Dev-PC only (reads an SNES ROM): what ships is derived data (palettes, BNW's own art), see
port_sprites.py.
"""
import ff6snes as S  # noqa: F401  (Rom)

INFO, PAL, GFX = 0x127000, 0x127820, 0x297000
N = 384


class Layout:
    def __init__(self, name, entries, count, palettes, tiles, comp8=0x12A820, comp16=0x12A822):
        self.name, self.entries, self.count, self.palettes = name, entries, count, palettes
        self.tiles, self.comp8, self.comp16 = tiles, comp8, comp16


VANILLA = Layout("vanilla", INFO, N, PAL, lambda i: GFX)


def _tedition_tiles(i):
    """T-Edition's hook (C1/2040 stores the monster id, C0/D978 picks the bank): F0/0000 for 0-416 and
    432-479, F4/0000 for 417-431, F5/0000 for 480-511 (and EX's 512+, read from EX's own ROM by its slot)."""
    return 0x350000 if i >= 0x1E0 else 0x340000 if 0x1A1 <= i < 0x1B0 else 0x300000


# T-Edition 3.0.7 / EX 2.0.6: entries CF/1A00 (512, vanilla's format), palettes 41/6200, stencils as vanilla
TEDITION = Layout("tedition", 0x0F1A00, 512, 0x416200, _tedition_tiles)


def snes_rgb(w):
    r, g, b = w & 31, (w >> 5) & 31, (w >> 10) & 31
    return ((r << 3) | (r >> 2), (g << 3) | (g >> 2), (b << 3) | (b >> 2))


class Sprite:
    def __init__(self, idx, px, pal, bpp3, big, palette_index, ptr, stencil_index):
        self.idx = idx
        self.px = px                  # rows of palette indexes, 0 = clear
        self.pal = pal                # 8 or 16 RGB tuples
        self.bpp3 = bpp3
        self.big = big
        self.palette_index = palette_index
        self.ptr = ptr
        self.stencil_index = stencil_index
        self.h = len(px)
        self.w = len(px[0]) if px else 0

    def bbox(self):
        """(x0, y0, x1, y1) of the opaque pixels (exclusive), or None."""
        xs = [x for row in self.px for x, v in enumerate(row) if v]
        ys = [y for y, row in enumerate(self.px) if any(row)]
        if not xs:
            return None
        return min(xs), min(ys), max(xs) + 1, max(ys) + 1

    def rgba(self):
        """Flat RGBA bytes (w*h*4)."""
        out = bytearray()
        for row in self.px:
            for v in row:
                if v:
                    out += bytes(self.pal[v]) + b"\xff"
                else:
                    out += b"\0\0\0\0"
        return bytes(out)


class _Bytes:
    """An image's bytes where an ff6snes.Rom is expected (.data, .b(at, n))."""

    def __init__(self, data):
        self.data = data

    def b(self, a, n):
        return self.data[a:a + n]


class Sprites:
    def __init__(self, rom, layout=VANILLA):
        self.rom = _Bytes(rom) if isinstance(rom, (bytes, bytearray)) else rom
        self.layout = layout
        d = self.rom.data
        self.comp8 = 0x120000 + (d[layout.comp8] | d[layout.comp8 + 1] << 8)
        self.comp16 = 0x120000 + (d[layout.comp16] | d[layout.comp16 + 1] << 8)

    def entry(self, i):
        e = self.rom.b(self.layout.entries + 5 * i, 5)
        ptr = e[0] | e[1] << 8
        return ptr, bool(e[2] & 0x80), (e[2] & 3) << 8 | e[3], e[4]

    def palette(self, pal_index, bpp3):
        n = 8 if bpp3 else 16
        raw = self.rom.b(self.layout.palettes + 16 * pal_index, 2 * n)
        return [snes_rgb(raw[2 * k] | raw[2 * k + 1] << 8) for k in range(n)]

    def stencil(self, big, k):
        if big:
            raw = self.rom.b(self.comp16 + 32 * k, 32)
            return [raw[2 * y] << 8 | raw[2 * y + 1] for y in range(16)], 16
        raw = self.rom.b(self.comp8 + 8 * k, 8)
        return list(raw), 8

    def sprite(self, i):
        ptr, big, pal_index, sk = self.entry(i)
        bpp3 = bool(ptr & 0x8000)
        tsize = 24 if bpp3 else 32
        base = self.layout.tiles(i) + (ptr & 0x7FFF) * 8
        rows, width = self.stencil(big, sk)
        blank = [[0] * 8 for _ in range(8)]
        grid, t = [], 0
        for y in range(width):
            line = []
            for x in range(width):
                if rows[y] & (1 << (width - 1 - x)):
                    line.append(self.tile(base + tsize * t, bpp3))
                    t += 1
                else:
                    line.append(blank)
            grid.append(line)
        px = []
        for line in grid:
            for r in range(8):
                px.append([v for tile in line for v in tile[r]])
        return Sprite(i, px, self.palette(pal_index, bpp3), bpp3, big, pal_index, ptr, sk)

    def tile(self, at, bpp3):
        # each byte's 8 bits from a table, the planes summed by weight: the same pixels as bit by bit, several
        # times faster (every port decodes ~25,000 tiles; roadmap item 6)
        raw = self.rom.b(at, 24 if bpp3 else 32)
        out = []
        for r in range(8):
            if bpp3:
                a, b, c = _BITS[raw[2 * r]], _BITS[raw[2 * r + 1]], _BITS[raw[16 + r]]
                out.append([a[x] | b[x] << 1 | c[x] << 2 for x in range(8)])
            else:
                a, b, c, d = _BITS[raw[2 * r]], _BITS[raw[2 * r + 1]], _BITS[raw[16 + 2 * r]], _BITS[raw[17 + 2 * r]]
                out.append([a[x] | b[x] << 1 | c[x] << 2 | d[x] << 3 for x in range(8)])
        return out

    def tile_bitwise(self, at, bpp3):
        """tile() the old way, bit by bit (the offline check compares the two)."""
        raw = self.rom.b(at, 24 if bpp3 else 32)
        out = []
        for r in range(8):
            planes = (raw[2 * r], raw[2 * r + 1], raw[16 + r]) if bpp3 else \
                (raw[2 * r], raw[2 * r + 1], raw[16 + 2 * r], raw[17 + 2 * r])
            out.append([sum(((p >> (7 - x)) & 1) << k for k, p in enumerate(planes)) for x in range(8)])
        return out


_BITS = [tuple((v >> (7 - x)) & 1 for x in range(8)) for v in range(256)]   # a byte's bits, left pixel first


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
