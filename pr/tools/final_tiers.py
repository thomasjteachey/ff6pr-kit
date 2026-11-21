"""BNW's final battle tower for the PR: what to paint over the PR's own tower image.

The PR draws the final battle's three statue tiers as one picture, MN_FF6_147_C00 (240x456, RGB24): the
SNES's tier backgrounds ($33, $34, $35) stacked, redrawn, with vanilla's statue parts painted in (the PR's
part monsters are 1x1 empty images). BNW's final battle hack (bnw 3.0/asm/final_battle.asm, art by Khaos
and Ryo_Hazuki) cut those parts out of the tier backgrounds and draws its own parts as monster sprites
(Limbo, Lust, Gluttony / Wrath, Greed, Heresy, Violence / Fraud, Treachery). The overlay here is only what
BNW changed: its background pixels that differ from vanilla's (in the PR's colors, through a per-tier map
learned where the two agree) and its part sprites (BNW's palettes), at the PR picture's coordinates. The
plugin paints it over the player's own picture (PrKit/MonsterImages.cs "overlay"), and each part is a layer of
its own ("parts") that BnwPlugin erases from the picture when that monster dies, as BNW's sprites vanish.

BNW also swaps a few background tiles in when tiers 2 and 3 begin (final_battle.asm TransferDeadGFX: the
Tier2_* / Tier3_* pieces, copied to VRAM as the screen finishes scrolling to the tier, for formation $200 /
$201): those are part of BNW's look of those tiers, so the captures apply them too (`pieces`, the
profile's final_tier_pieces: BNW's files and VRAM places, from its source; written to the SNES's VRAM and
the core's state saved and reloaded so its tile cache sees them).

Measured (2026-11-20, tools/snes_final_tiers.py captures against the PR's picture): each SNES tier sits
at x 0 and rows OFF[t] of the PR picture (luma correlation 0.93 / 0.96 / 0.79). Dev PC only (SNES ROMs
and the windowless SNES); captures cached under build/sprites/tiers_cache by the ROMs' sha1.
"""
import collections
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import prdata as P  # noqa: E402

W, H = 240, 456
OFF = {1: 305, 2: 153, 3: 1}
ROWS = 150                                   # the battle field above the menu windows
PARTS = {1: [343, 344, 345], 2: [346, 347, 348, 349], 3: [350, 351]}
TIER_FB = {1: (471, 0x33), 2: (512, 0x34), 3: (513, 0x35)}
CACHE = os.path.join(os.path.dirname(HERE), "build", "sprites", "tiers_cache")


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()[:12]


def _apply_pieces(s, pieces):
    """Tile pieces [(file, VRAM word address, words per row, rows)] into the SNES's VRAM, then the core's
    state saved and reloaded (Snes9x caches decoded tiles; a direct VRAM write alone isn't drawn)."""
    import ctypes
    L = s.lib
    L.retro_get_memory_data.restype = ctypes.c_void_p
    L.retro_serialize_size.restype = ctypes.c_size_t
    L.retro_serialize.restype = ctypes.c_bool
    L.retro_unserialize.restype = ctypes.c_bool
    vram = (ctypes.c_uint8 * 65536).from_address(L.retro_get_memory_data(3))
    for path, addr, words, rows in pieces:
        with open(path, "rb") as f:
            data = f.read()
        i = 0
        for r in range(rows):
            a = (addr + r * 0x100) * 2
            vram[a:a + 2 * words] = data[i:i + 2 * words]
            i += 2 * words
    n = L.retro_serialize_size()
    buf = ctypes.create_string_buffer(n)
    if not (L.retro_serialize(buf, n) and L.retro_unserialize(buf, n)):
        raise RuntimeError("the SNES core couldn't save/reload its state")


def captures(rom, settle=300, frames=6, every=7, pieces=None):
    """{tier: ([background-only RGB images, `frames` of them `every` frames apart], sprites-only RGB
    image)} of a ROM's tiers (cached). Several background frames: the tiers' clouds move. pieces:
    {tier: [(file, VRAM word address, words per row, rows)]}, the mod's tiles written over the tier's
    background (BNW: profile final_tier_pieces)."""
    from PIL import Image
    import snes_final_tiers as F
    d = os.path.join(CACHE, _sha(rom) + ("_pieces" if pieces else ""))
    os.makedirs(d, exist_ok=True)
    out = {}
    for t, (f, bg) in TIER_FB.items():
        bgps = [os.path.join(d, f"bg{t}_{k}.png") for k in range(frames)]
        spp = os.path.join(d, f"spr{t}.png")
        for paths, hidden in ((bgps, ("snes9x_layer_1", "snes9x_layer_3", "snes9x_layer_5")), ([spp], ("snes9x_layer_1", "snes9x_layer_2", "snes9x_layer_3"))):
            if all(os.path.exists(p) for p in paths):
                continue
            s = F.LayerSnes(rom, hidden)
            try:
                while s.rd(0x1503) != 0xC1:
                    s.wr(0x11E0, f & 0xFF)
                    s.wr(0x11E1, f >> 8)
                    s.wr(0x11E2, bg)
                    k = s.frame % 40
                    if k < 2:
                        s.press("a")
                    elif 10 <= k < 30 and (s.frame // 2000) % 2:
                        s.press("up")
                    else:
                        s.release()
                    s.run(1)
                    if s.frame > 200000:
                        raise RuntimeError("no battle by frame 200000")
                s.release()
                s.run(settle)
                if pieces and pieces.get(t) and paths is bgps:
                    _apply_pieces(s, pieces[t])
                    s.run(1)
                for p in paths:
                    s.screenshot(p, scale=1)
                    s.run(every)
            finally:
                s.close()
        out[t] = ([Image.open(p).convert("RGB") for p in bgps], Image.open(spp).convert("RGB"))
    return out


def _close(a, b, tol):
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol and abs(a[2] - b[2]) <= tol


def find_sprite(cap, sp, tol=24):
    """(x, y) of the sprite's cropped top left on the sprites-only capture, the share of its pixels
    that match there, and its pixels as placed (mirrored if it's drawn mirrored)."""
    a = _find(cap, sp, tol, False)
    if a[1] >= 0.9:
        return a
    b = _find(cap, sp, tol, True)
    a = b if b[1] > a[1] else a
    if a[1] >= 0.6:
        return a
    # partly covered (a forced battle's party can stand in front of a part): every position, exact
    # colors, at least a fifth of the sprite and 80 pixels showing
    for flip in (False, True):
        c = _find(cap, sp, 8, flip, anchored=False)
        if c[1] > a[1] and c[1] * len(c[2]) >= 80:
            a = c
    return a if a[1] >= 0.2 else (None, a[1], a[2])


def _find(cap, sp, tol, flip, anchored=True):
    bb = sp.bbox()
    x0, y0, x1, y1 = bb
    pix = [((x1 - 1 - x) if flip else (x - x0), y - y0, sp.pal[sp.px[y][x]])
           for y in range(y0, y1) for x in range(x0, x1) if sp.px[y][x]]
    step = max(1, len(pix) // 24)
    anchors = pix[::step][:24]
    c = cap.load()
    cw, ch = cap.size
    best = (0, None)
    for y in range(0, ch - (y1 - y0) + 1):
        for x in range(0, cw - (x1 - x0) + 1):
            if not anchored:
                n = sum(1 for ax, ay, col in pix if _close(c[x + ax, y + ay], col, tol))
                if n > best[0]:
                    best = (n, (x, y))
                continue
            ok = 0
            for ax, ay, col in anchors:
                if _close(c[x + ax, y + ay], col, tol):
                    ok += 1
                elif ok + (len(anchors) - anchors.index((ax, ay, col))) < len(anchors) * 0.8:
                    break
            if ok < len(anchors) * 0.8:
                continue
            n = sum(1 for ax, ay, col in pix if _close(c[x + ax, y + ay], col, tol))
            if n > best[0]:
                best = (n, (x, y))
    return best[1], best[0] / max(1, len(pix)), pix


def layers(van_rom, mod_rom, composite_rgba, log=print, diff_tol=24, pieces=None):
    """(background layer, [(SNES monster, its layer)], notes): RGBA bytes W x H each, clear where the PR's
    picture stays; the background layer is BNW's changed background pixels, each part's its sprite."""
    from snes_sprites import Sprites
    import ff6snes as S
    from PIL import Image
    comp = Image.frombytes("RGBA", (W, H), composite_rgba).convert("RGB")
    cp = comp.load()
    van, mod = captures(van_rom), captures(mod_rom, pieces=pieces)
    ms = Sprites(S.Rom(mod_rom))
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    op = out.load()
    parts = []
    notes = []
    for t in (1, 2, 3):
        vbgs = [im.load() for im in van[t][0]]
        mbgs = [im.load() for im in mod[t][0]]
        vbg, mbg, mspr = vbgs[0], mbgs[0], mod[t][1]
        # the tier's SNES color -> the PR picture's color, where vanilla's background and the PR agree
        votes = collections.defaultdict(collections.Counter)
        for y in range(ROWS):
            for x in range(W):
                for v in vbgs:
                    votes[v[x, y]][cp[x, y + OFF[t]]] += 1
        cmap = {k: v.most_common(1)[0][0] for k, v in votes.items()}
        keys = list(cmap)

        def to_pr(c):
            if c in cmap:
                return cmap[c]
            k = min(keys, key=lambda q: sum((q[i] - c[i]) ** 2 for i in range(3)))
            return cmap[k]
        changed = 0
        for y in range(ROWS):
            for x in range(W):
                # changed: no frame of BNW's matches any frame of vanilla's here (moving clouds match
                # in some frame); BNW's color from its first frame
                if all(not _close(v[x, y], m[x, y], diff_tol) for v in vbgs for m in mbgs):
                    op[x, y + OFF[t]] = to_pr(mbg[x, y]) + (255,)
                    changed += 1
        placed = []
        for m in PARTS[t]:
            sp = ms.sprite(m)
            if sp.bbox() is None:
                continue
            pos, share, pix = find_sprite(mspr, sp)
            if pos is None:
                notes.append(f"tier {t}: monster {m} not found on the SNES ({share:.2f})")
                continue
            layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            lp = layer.load()
            for ax, ay, col in pix:
                X, Y = pos[0] + ax, pos[1] + ay + OFF[t]
                if 0 <= X < W and 0 <= Y < H and pos[1] + ay < ROWS:
                    lp[X, Y] = tuple(col) + (255,)
            parts.append((m, layer.tobytes()))
            placed.append(f"{m}@{pos} {share:.2f}")
        notes.append(f"tier {t}: {changed} background pixels, parts {', '.join(placed)}")
    for n in notes:
        log("final tiers: " + n)
    return out.tobytes(), parts, notes


def overlay(van_rom, mod_rom, composite_rgba, log=print, diff_tol=24, pieces=None):
    """(RGBA bytes W x H: the background layer with every part over it; notes)."""
    bg, parts, notes = layers(van_rom, mod_rom, composite_rgba, log, diff_tol, pieces)
    out = bytearray(bg)
    for _, layer in parts:
        for k in range(0, len(out), 4):
            if layer[k + 3]:
                out[k:k + 4] = layer[k:k + 4]
    return bytes(out), notes


if __name__ == "__main__":
    import port_sprites
    import profiles
    prof = profiles.PROFILES["bnw"]
    tex = port_sprites.pr_textures("mn_ff6_147")["MN_FF6_147_C00"]
    ov, notes = overlay(P.VANILLA_ROM, prof.rom, tex[2], pieces=getattr(prof, "final_tier_pieces", None))
    from PIL import Image
    base = Image.frombytes("RGBA", (W, H), tex[2])
    o = Image.frombytes("RGBA", (W, H), ov)
    res = base.copy()
    res.alpha_composite(o)
    sheet = Image.new("RGBA", (W * 3 + 20, H), (255, 0, 255, 255))
    sheet.paste(base, (0, 0))
    sheet.paste(res, (W + 10, 0))
    sheet.alpha_composite(o, (2 * W + 20, 0))
    out = os.path.join(os.path.dirname(HERE), "build", "sprites", "final_tiers.png")
    sheet.resize((sheet.width * 2, sheet.height * 2), Image.NEAREST).save(out)
    print(out)
