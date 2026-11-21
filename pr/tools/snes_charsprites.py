"""FF6 SNES character sprites and portraits -> the Pixel Remaster's frames (kit tool, any FF6 mod).

    import snes_charsprites as C
    frames = C.group_frames(sheet, palette, C.frame_names("bc_ff6_p001"))   # {PR frame name: 32x32 RGBA}
    face = C.portrait(portrait_bytes, portrait_palette)                     # 40x40 RGBA
    png, rects = C.pack(frames)                                             # one PNG + {name: [x, y, w, h]}

What the PR draws (2026-11-20, measured from the game's bundles):
- A character's field frames (`mo_ff6_pNNN`, one SpriteAtlas) and battle frames (`bc_ff6_pNNN`, one
  32x32 RGBA32 Texture2D each) are the same pixels: 50-62 named frames (Default_00..02, WalkB/L/R_00..02,
  Idle_00, Ready_00, Win_00, Down_00, ...), pivot (0.5, 0), 1 pixel per unit, point filtered.
- The art is SNES-sized: a standing character is 16 px wide (x 8..23) and 24-26 tall with its feet on
  the bottom row (y 31). So an SNES pose (16x24, 2x3 tiles of 8x8 4bpp) sits 1:1 at x 8, y 8: no scaling,
  no filtering, no outline added (SNES sprites carry their own, as the PR's redraws do).
- Portraits (`fa_ff6_pNNN/Default_00`) are 40x40, pivot (0.5, 0.5): the SNES portrait (5x5 tiles,
  0x320 bytes, layout PORTRAIT) at the same size; the PR's are lightly retouched copies of them.

The pose map (data/ff6_charsprites.json "frames"): each PR frame name -> an SNES pose of the ROM's table
at C0/CE3A (6 tile offsets per pose; 0-39 the character poses) or the dead-lying (40, 3x2 tiles) and
riding (46, 47) poses, mirrored for the R frames. Found by matching all 14 characters' PR frames
against their SNES poses (the best pose per frame by vote), with the walk cycles taken from the PR's own
field animations (anim_info: Default_01, WalkB_00 and WalkL_01 are the standing frames). "slots" maps
the SNES sprite slots (0-21) to the PR's art groups; "color_slots" gives, per PR group, the SNES palette
index each of its distinct colors (sorted) sits on (learned by `build` from aligned frames, for
recolouring the PR's own art with an SNES palette: Beyond Chaos' `c`). The data file holds no game
data: no pixels, no colors, no palettes; ColorMaps pairs the slot numbers with the colors of the player's
own frames, and the vanilla palettes come from the caller's ROM or base data (vanilla_palettes(rom)).

Nothing here reads a ROM at run time: SNES sheets come from the caller (a mod's own files, e.g. Beyond
Chaos' custom/sprites/*.bin, or a generator's output). `build` (dev PC: the ROM + the game) remakes
the data file.

    python tools/snes_charsprites.py sheet FILE.bin [--pal FILE.pal|--slot N] [--portrait P.bin] OUT.png
    python tools/snes_charsprites.py build [--rc BC/data/sprites]   # data/ff6_charsprites.json's slots + frame names
"""
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
DATA = os.path.join(os.path.dirname(HERE), "data", "ff6_charsprites.json")

FRAME = 32          # the PR's frame (field and battle)
PALETTES = 0x268000  # SNES character palettes (16 colors each)
FACE = 40           # the PR's portrait
SHEET_SIZE = 0x16A0  # an SNES character sheet with riding poses (181 tiles); 0x1560 without
PORTRAIT_SIZE = 0x320
PORTRAIT = [[0, 1, 2, 3, 8], [16, 17, 18, 19, 9], [4, 5, 6, 7, 10], [20, 21, 22, 23, 11], [13, 14, 15, 24, 12]]

_data = None


def data():
    global _data
    if _data is None:
        with open(DATA, encoding="utf-8") as f:
            _data = json.load(f)
    return _data


# --- SNES graphics -------------------------------------------------------------------------------

def snes_rgb(w):
    r, g, b = w & 31, (w >> 5) & 31, (w >> 10) & 31
    return ((r << 3) | (r >> 2), (g << 3) | (g >> 2), (b << 3) | (b >> 2))


def palette(raw):
    """16 SNES colors (32 bytes, BGR555) -> 16 RGB tuples (index 0 is drawn clear)."""
    return [snes_rgb(struct.unpack_from("<H", raw, 2 * k)[0]) for k in range(len(raw) // 2)]


def tiles(raw):
    """4bpp tiles (32 bytes each) -> list of 8 rows of 8 palette indexes."""
    out = []
    for t in range(len(raw) // 32):
        b = raw[t * 32:(t + 1) * 32]
        rows = []
        for y in range(8):
            p0, p1, p2, p3 = b[2 * y], b[2 * y + 1], b[16 + 2 * y], b[16 + 2 * y + 1]
            rows.append([((p0 >> s) & 1) | (((p1 >> s) & 1) << 1) | (((p2 >> s) & 1) << 2) | (((p3 >> s) & 1) << 3)
                         for s in range(7, -1, -1)])
        out.append(rows)
    return out


def pose(tl, spec):
    """An SNES pose ({"tiles": [...], "w": tiles across}) -> rows of palette indexes."""
    w = spec.get("w", 2)
    ids = spec["tiles"]
    h = len(ids) // w
    rows = [[0] * (8 * w) for _ in range(8 * h)]
    for k, t in enumerate(ids):
        if t >= len(tl):
            continue
        tx, ty = k % w, k // w
        for y in range(8):
            rows[ty * 8 + y][tx * 8:tx * 8 + 8] = tl[t][y]
    return rows


def frame(tl, spec, poses=None):
    """A PR frame (32x32 palette indexes) from its pose-map entry:
    {"pose": n, "mirror": bool, "dy": raise in px, "shadow": [x0, x1] a line of index 1 on the bottom row}."""
    poses = poses or data()["poses"]
    px = pose(tl, poses[str(spec["pose"])])
    if spec.get("mirror"):
        px = [list(reversed(r)) for r in px]
    h, w = len(px), len(px[0])
    out = [[0] * FRAME for _ in range(FRAME)]
    x0 = (FRAME - w) // 2
    y0 = FRAME - h - spec.get("dy", 0)
    for y in range(h):
        for x in range(w):
            if px[y][x] and 0 <= y0 + y < FRAME:
                out[y0 + y][x0 + x] = px[y][x]
    if spec.get("shadow"):
        a, b = spec["shadow"]
        for x in range(a, b):
            if not out[FRAME - 1][x]:
                out[FRAME - 1][x] = 1
    return out


def rgba(index_rows, pal):
    """Rows of palette indexes -> RGBA bytes (index 0 clear)."""
    out = bytearray()
    for row in index_rows:
        for v in row:
            out += (bytes(pal[v]) + b"\xff") if v else b"\0\0\0\0"
    return bytes(out)


def mirror(rgba_bytes, size=FRAME):
    """A square RGBA frame flipped left-right."""
    out = bytearray(len(rgba_bytes))
    for y in range(size):
        for x in range(size):
            o, m = (y * size + x) * 4, (y * size + size - 1 - x) * 4
            out[o:o + 4] = rgba_bytes[m:m + 4]
    return bytes(out)


def portrait_indexes(raw):
    tl = tiles(raw[:PORTRAIT_SIZE])
    rows = [[0] * FACE for _ in range(FACE)]
    for ty, line in enumerate(PORTRAIT):
        for tx, t in enumerate(line):
            for y in range(8):
                rows[ty * 8 + y][tx * 8:tx * 8 + 8] = tl[t][y]
    return rows


def portrait(raw, pal_raw):
    """An SNES portrait (0x320 bytes) + its palette (32 bytes) -> 40x40 RGBA (index 0 clear)."""
    return rgba(portrait_indexes(raw), palette(pal_raw))


# --- the PR's frames ---------------------------------------------------------------------------

def vanilla_palettes(rom):
    """The SNES character palettes by index (0-7; 6 = Esper Terra's, kept as the field set's 8) in `rom`: the
    vanilla ROM or a generator's base data holding the same table (C6/8000): what the PR's own art was drawn
    from (recolor's `old`). Not shipped by the kit: it's the ROM's."""
    return [palette(rom[PALETTES + (8 if i == 6 else i) * 0x20:PALETTES + (8 if i == 6 else i) * 0x20 + 0x20])
            for i in range(8)]


def frame_names(group):
    """The frame names a PR art group has (field and battle groups have the same ones)."""
    g = group.replace("mo_ff6_", "bc_ff6_")
    return data()["groups"][g]


def spec_for(name):
    """The pose-map entry for a PR frame name (Locke's and Celes' Red* disguise frames and Gogo's
    misspelt WalkR00 fall back to the plain frame)."""
    frames = data()["frames"]
    if name in frames:
        return frames[name]
    if name.startswith("Red") and name[3:] in frames:
        return frames[name[3:]]
    if name == "WalkR00":
        return frames["WalkR_00"]
    import re
    m = re.match(r"(\w+?)_(\d\d)$", name)
    if m:   # an extra numbered frame (RedDefault_03): the same animation's first frame
        for k in (f"{m.group(1)}_00", f"{m.group(1).replace('Red', '')}_00"):
            if k in frames:
                return frames[k]
    return frames["Idle_00"]


def group_frames(sheet, pal, names):
    """An SNES character sheet (bytes) + its 16-color palette (RGB list or 32 raw bytes) -> {name: RGBA}."""
    if isinstance(pal, (bytes, bytearray)):
        pal = palette(pal)
    tl = tiles(sheet)
    poses = data()["poses"]
    return {n: rgba(frame(tl, spec_for(n), poses), pal) for n in names}


def group_indexes(sheet, names):
    """As group_frames, as palette indexes (for recolouring later)."""
    tl = tiles(sheet)
    poses = data()["poses"]
    return {n: frame(tl, spec_for(n), poses) for n in names}


def pack(frames, size=FRAME, cols=8):
    """Frames (name -> size x size RGBA) -> (PNG bytes of one sheet, {name: [x, y, w, h]} top-down).
    The plugin cuts its sprites from the sheet (PrKit/Ff6/CharacterArt.cs)."""
    import pr_images
    names = sorted(frames)
    rows = (len(names) + cols - 1) // cols
    W, H = cols * size, rows * size
    buf = bytearray(W * H * 4)
    rects = {}
    for i, n in enumerate(names):
        x, y = (i % cols) * size, (i // cols) * size
        px = frames[n]
        for r in range(size):
            buf[((y + r) * W + x) * 4:((y + r) * W + x + size) * 4] = px[r * size * 4:(r + 1) * size * 4]
        rects[n] = [x, y, size, size]
    return pr_images.png(W, H, bytes(buf)), rects


# --- recolouring the PR's own art with an SNES palette (Beyond Chaos' `c`) -----------------------

class ColorMaps:
    """A PR group's colors on their SNES palette slots, made from the player's own frames of the group:
    the data file holds only the slot numbers ("color_slots": the group's distinct colors sorted, each
    one's slot; "color_slots_rc": on Beyond Chaos' re-indexed Cyan/Mog/Umaro sheets), never the colors.
    centre: the PR's average shade (Lab, pixel-weighted) of each slot."""

    def __init__(self, group, frames):
        g = group.replace("mo_ff6_", "bc_ff6_")
        count, colors = {}, set()
        for px in frames:
            for i in range(0, len(px), 4):
                if px[i + 3]:
                    c = (px[i], px[i + 1], px[i + 2])
                    count[c] = count.get(c, 0) + 1
        colors = sorted(count)

        def slots(key):
            e = data().get(key, {}).get(g)
            # another number of colors: the player's game isn't the one the slots were learned on
            return dict(zip(colors, e["slots"])) if e and e["n"] == len(colors) else None
        self.cmap, self.rmap = slots("color_slots"), slots("color_slots_rc")
        self.matched = self.cmap is not None
        self.centre = {}
        if self.cmap:
            acc = {}
            for c, n in count.items():
                a = acc.setdefault(self.cmap[c], [0.0, 0.0, 0.0, 0])
                L = lab(c)
                a[0] += L[0] * n; a[1] += L[1] * n; a[2] += L[2] * n; a[3] += n
            self.centre = {k: (v[0] / v[3], v[1] / v[3], v[2] / v[3]) for k, v in acc.items()}

    def slot(self, c, old_pal):
        if self.cmap is not None and c in self.cmap:
            return self.cmap[c]
        L = lab(c)          # unknown art: the nearest vanilla color
        return min(range(1, len(old_pal)), key=lambda s: sum((L[k] - q) ** 2 for k, q in enumerate(lab(old_pal[s]))))


def recolor(rgba_bytes, maps, old_pal, new_pal, reindexed=False):
    """The PR's art of a group (RGBA bytes) as the SNES would draw it with palette `new_pal` where it had
    `old_pal` (16 RGB each); maps: the group's ColorMaps. `reindexed`: the slots of Beyond Chaos' re-indexed
    sheets (its new palette mode). A slot whose color didn't change keeps its PR colors exactly."""
    rmap = (maps.rmap or {}) if reindexed else {}
    cache = {}
    out = bytearray(rgba_bytes)
    for i in range(0, len(out), 4):
        if not out[i + 3]:
            continue
        c = (out[i], out[i + 1], out[i + 2])
        if c not in cache:
            slot = maps.slot(c, old_pal)
            nslot = rmap.get(c, slot)
            if nslot == slot and old_pal[slot] == new_pal[slot]:
                cache[c] = c
            else:
                cache[c] = shift(c, maps.centre.get(slot) or lab(old_pal[slot]), new_pal[nslot])
        out[i:i + 3] = bytes(cache[c])
    return bytes(out)


def shift(c, centre, new, keep=0.5):
    """Color c (a PR shade of an SNES palette slot whose shades average `centre`, Lab) as it would be
    with the slot's new color `new` (RGB): the new color with c's lightness offset from the average and
    half its tint offset (CIE Lab). Centred on the PR's own shades, not the SNES color: the PR retouched
    hues and brightness (its Relm's hair is golden where the SNES palette is tan, Strago's whiter)."""
    L0, a0, b0 = centre
    L1, a1, b1 = lab(new)
    Lc, ac, bc = lab(c)
    return rgb_from_lab((L1 + (Lc - L0), a1 + keep * (ac - a0), b1 + keep * (bc - b0)))


def _lin(v):
    v /= 255
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _gam(v):
    v = 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055
    return max(0, min(255, round(v * 255)))


def lab(c):
    r, g, b = (_lin(x) for x in c)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def rgb_from_lab(c):
    L, a, b = c
    fy = (L + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200

    def fi(t):
        return t ** 3 if t ** 3 > 0.008856 else (t - 16 / 116) / 7.787
    x, y, z = fi(fx) * 0.95047, fi(fy), fi(fz) * 1.08883
    r = 3.2406 * x - 1.5372 * y - 0.4986 * z
    g = -0.9689 * x + 1.8758 * y + 0.0415 * z
    bb = 0.0557 * x - 0.2040 * y + 1.0570 * z
    return (_gam(max(0.0, r)), _gam(max(0.0, g)), _gam(max(0.0, bb)))


# --- dev PC: build the data file ---------------------------------------------------------------

def _rom():
    import prdata as P
    import ff6snes as S
    return S.rom_bytes(P.VANILLA_ROM)


SHEET_SIZES = [0x16A0] * 0x10 + [0x1560] * 6


def rom_sheet(rom, slot):
    start = 0x150000 + sum(SHEET_SIZES[:slot])
    return rom[start:start + SHEET_SIZES[slot]]


def rom_palette(rom, slot):
    i = rom[0x2CE2B + slot]
    return rom[0x268000 + i * 0x20:0x268000 + i * 0x20 + 0x20]


RC_SHEETS = {2: "RCcyan.bin", 10: "RCmog.bin", 13: "RCumaro.bin"}   # Beyond Chaos' data/sprites


def _votes(tex, names, tl):
    """(PR color -> Counter of SNES palette indexes) over the frames, each aligned to the SNES pose
    (the redraw sits a pixel or two off now and then: the shift with most overlap)."""
    import collections
    votes = collections.defaultdict(collections.Counter)
    for n in names:
        idx = frame(tl, spec_for(n))
        _, _, px = tex[n]
        best = None
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                k = sum(1 for y in range(FRAME) for x in range(FRAME)
                        if 0 <= y + dy < FRAME and 0 <= x + dx < FRAME and idx[y][x]
                        and px[((y + dy) * FRAME + x + dx) * 4 + 3])
                if best is None or k > best[0]:
                    best = (k, dx, dy)
        _, dx, dy = best
        for y in range(FRAME):
            for x in range(FRAME):
                v = idx[y][x]
                if not v or not (0 <= y + dy < FRAME and 0 <= x + dx < FRAME):
                    continue
                o = ((y + dy) * FRAME + x + dx) * 4
                if not px[o + 3]:
                    continue
                c = tuple(px[o:o + 3])
                if v == 1 and sum(c) > 270:      # the redraw's detail over an SNES outline pixel
                    continue
                votes[c][v] += 1
    return votes


def build(game_dir=None, rc_dir=None):
    """Remake data/ff6_charsprites.json's "groups" (frame names per PR group, from the game) and
    "color_slots" (each group's distinct colors, sorted, on their SNES palette slots, from aligned frames:
    the PR art is at the SNES resolution and position, so most pixels line up; only the slot numbers are
    written, the colors are the player's game's). rc_dir: Beyond Chaos' data/sprites, for "color_slots_rc"
    (its re-indexed Cyan/Mog/Umaro sheets, RC*.bin)."""
    import collections
    import pr_images
    rom = _rom()
    d = data()
    if game_dir is None:
        from prkit import games
        game_dir = games.get("ff6").install
    groups, colors, palettes, colors_rc = {}, {}, {}, {}
    snes_pals = [palette(rom[0x268000 + (8 if i == 6 else i) * 0x20:0x268000 + (8 if i == 6 else i) * 0x20 + 0x20]) for i in range(8)]

    def dist(a, b):
        return sum(abs(a[k] - b[k]) for k in range(3))

    for slot, g in d["slots"].items():
        g["palette"] = rom[0x2CE2B + int(slot)]
        pal = snes_pals[g["palette"]]
        for grp in [g["battle"]] + g.get("also", []):
            try:
                tex = pr_images.textures(pr_images.bundle_for(game_dir, grp))
            except FileNotFoundError:
                continue
            groups[grp] = sorted(n for n, (w, h, _) in tex.items() if w == FRAME and h == FRAME)
            votes = _votes(tex, groups[grp], tiles(rom_sheet(rom, int(slot))))
            rc = RC_SHEETS.get(int(slot))
            rvotes = None
            if rc and grp == g["battle"] and rc_dir and os.path.exists(os.path.join(rc_dir, rc)):
                # Beyond Chaos' re-indexed sheet of this character (its new palette mode): the slot each
                # PR color has there
                with open(os.path.join(rc_dir, rc), "rb") as f:
                    rvotes = _votes(tex, groups[grp], tiles(f.read()))
            allc = set(votes)
            for n in groups[grp]:
                _, _, px = tex[n]
                allc.update(tuple(px[i:i + 3]) for i in range(0, len(px), 4) if px[i + 3])
            cm = {}
            for c in sorted(allc):
                v = votes.get(c)
                if v and sum(v.values()) >= 4:
                    s = max(v, key=lambda s: (v[s], -dist(c, pal[s])))     # the SNES pixel it sits on, most often
                else:
                    s = min(range(1, 16), key=lambda s: dist(c, pal[s]))
                cm[c] = s
            order = sorted(cm)
            colors[grp] = {"n": len(order), "slots": [cm[c] for c in order]}
            if rvotes is not None:
                colors_rc[grp] = {"n": len(order), "slots": [rvotes[c].most_common(1)[0][0] if c in rvotes else cm[c]
                                                             for c in order]}
            # the SNES palette (0-7) the group's colors fit best (a palette variant: the green soldiers)
            if grp == g["battle"]:
                palettes[grp] = g["palette"]
            else:
                w = {c: sum(votes.get(c, {}).values()) + 1 for c in cm}
                palettes[grp] = min(range(8), key=lambda i: sum(w[c] * dist(c, snes_pals[i][s]) for c, s in cm.items()))
    # SNES portrait ids -> the PR face group drawn from them (the vanilla slots' own portraits)
    portraits = {}
    for slot, g in d["slots"].items():
        pid = struct.unpack_from("<H", rom, 0x36F1B + 2 * int(slot))[0] // PORTRAIT_SIZE
        if g.get("face") and str(pid) not in portraits:
            portraits[str(pid)] = g["face"]
        g["portrait"] = pid
    d["groups"], d["color_slots"], d["palettes"], d["portraits"] = groups, colors, palettes, portraits
    d["color_slots_rc"] = colors_rc
    for k in ("colors", "colors_rc", "slot_lab", "snes_palettes"):   # the old format's game data: gone
        d.pop(k, None)
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1, sort_keys=False)
    print(f"{len(groups)} groups, {sum(v['n'] for v in colors.values())} colors' slots -> {DATA}")


def contact(sheet, pal, out, portrait_raw=None, portrait_pal=None, names=None, scale=3):
    """A contact sheet PNG of every PR frame made from one SNES sheet (+ the portrait)."""
    from PIL import Image, ImageDraw
    names = names or frame_names("bc_ff6_p001")
    fr = group_frames(sheet, pal, names)
    cols = 10
    rows = (len(names) + cols - 1) // cols
    im = Image.new("RGBA", (cols * 36 * scale, rows * 44 * scale + (FACE + 8) * scale), (60, 60, 90, 255))
    dr = ImageDraw.Draw(im)
    for i, n in enumerate(names):
        a = Image.frombytes("RGBA", (FRAME, FRAME), fr[n]).resize((FRAME * scale, FRAME * scale), Image.NEAREST)
        x, y = (i % cols) * 36 * scale, (i // cols) * 44 * scale
        im.paste(a, (x, y), a)
        dr.text((x + 2, y + FRAME * scale + 2), n, fill=(255, 255, 0, 255))
    if portrait_raw:
        a = Image.frombytes("RGBA", (FACE, FACE), portrait(portrait_raw, portrait_pal)).resize((FACE * scale,) * 2, Image.NEAREST)
        im.paste(a, (0, rows * 44 * scale), a)
    im.save(out)


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--game", default=None)
    b.add_argument("--rc", default=None, help="Beyond Chaos' data/sprites folder (its re-indexed RC*.bin sheets)")
    s = sub.add_parser("sheet")
    s.add_argument("bin")
    s.add_argument("out")
    s.add_argument("--pal", default=None, help="a 32-byte palette file")
    s.add_argument("--slot", type=int, default=0, help="else the vanilla palette of this SNES slot (dev PC)")
    s.add_argument("--portrait", default=None)
    a = ap.parse_args()
    if a.cmd == "build":
        build(a.game, a.rc)
    else:
        sheet = open(a.bin, "rb").read()
        pal = open(a.pal, "rb").read() if a.pal else rom_palette(_rom(), a.slot)
        pr = pp = None
        if a.portrait:
            pr = open(a.portrait, "rb").read()
            pp = open(os.path.splitext(a.portrait)[0] + ".pal", "rb").read()
        contact(sheet, pal, a.out, pr, pp)


if __name__ == "__main__":
    main()
