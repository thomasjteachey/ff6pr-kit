"""Enemy sprites a mod changed: point each PR monster at art that looks like the mod's.

The PR draws each monster from a pre-drawn image (monster.monster_asset_id -> monster_asset ->
Assets/GameAssets/Serial/Res/Battle/Monster/MN_FF6_<group>/MN_FF6_<group>_<asset>, an RGBA32 sprite
the size of the SNES sprite's opaque box, redrawn in the SNES sprite's 16 colors; tools/pr_images.py).

Two modes:

- shapes only (the default; Beyond Chaos): a monster the mod draws with ANOTHER vanilla monster's
  shape gets that monster's PR asset (right shape, vanilla colors); the shape is its sprite's first tiles,
  or with profile.sprite_identity "pointer" its graphics pointer (no pixels read: Beyond Chaos's ROM-free
  generator, whose input has no graphics). profile.sprite_keep: monsters
  whose own PR art is kept; profile.sprite_standins {monster: monster}: a stand-in for new art on a
  slot that shows the placeholder.

- images (profile.sprite_images, BNW): every monster is compared with vanilla's as the SNES draws it
  (tools/snes_sprites.py: cropped to its opaque box, palette slots matched by content, so a mod that
  renumbers palettes or touches up a few pixels still matches):
    same      looks like vanilla (or a pixel touch-up in the same colors): nothing to do
    swap      looks exactly like another vanilla monster: that monster's PR asset
    recolor   a vanilla shape in new colors: a new image, the PR's art of the closest-colored
              vanilla monster of that shape with each color moved by the mod's palette change
              (Lab shift: the PR's shading kept). The PR's art has <= 16 colors, so the change is
              a color table (old RGB -> new RGB); no art ships, only colors
    new       the mod's own art (profile.sprite_new_art {monster: stand-in}): the mod's SNES sprite,
              shipped as palette + pixels (BNW's art, from BNW's patch), in the stand-in's group
              (its shadow); the rest are listed in the log
  profile.sprite_final_tiers: the final battle's tower picture (MN_FF6_147_C00, where the PR paints
  the statue tiers' parts) with the mod's changed pixels and part sprites over the PR's own
  (tools/final_tiers.py; an "overlay" entry)
  New images get monster_asset rows of their own (IMAGE_ASSET_BASE + monster) in the group of
  their source art, key <GROUP>_B<monster>, and port.images holds their recipe for the plugin
  (bnw_data.json "monster_images"): BnwPlugin builds the PNGs from the player's own game at first
  start (plugin/Rules/MonsterImages.cs), into the mod's Magicite folder.
"""
import base64
import collections
import hashlib
import json
import math
import os
import zlib

import ff6snes as S
import prdata as P

INFO, GFX = 0x127000, 0x297000  # D2/7000 graphics entries (5 bytes), E9/7000 tiles
N = 384
IMAGE_ASSET_BASE = 2000          # monster_asset ids of the mod's images (the PR's go to ~365)


def shape(rom, i, by_pointer=False):
    e = rom.b(INFO + 5 * i, 5)
    ptr = e[0] | e[1] << 8
    if by_pointer:
        # (profile.sprite_identity "pointer") the sprite by its graphics entry's pointer (and colour depth),
        # not its pixels: a ROM-free generator (Beyond Chaos's, tools/bc_romfree.py) has no sprite graphics
        return ptr
    return bytes(rom.b(GFX + (ptr & 0x7FFF) * 8, 96))


def port(van, mod, tables, log, profile=None):
    if getattr(profile, "sprite_images", False):
        return port_images(van, mod, tables, log, profile)
    mon = tables.setdefault("monster", P.Table("monster"))
    vmon = P.Table("monster")
    keep = set(getattr(profile, "sprite_keep", None) or ())
    standins = getattr(profile, "sprite_standins", None) or {}
    changed = set()
    by_ptr = getattr(profile, "sprite_identity", "") == "pointer"
    vshape = [shape(van, i, by_ptr) for i in range(N)]
    first = {}
    for j, sh in enumerate(vshape):
        first.setdefault(sh, j)
    names = {e.id: e.name.strip() for e in S.enemies(mod)}
    notes = []

    def asset(i):
        r = vmon.rows.get(i + 1)
        return r["monster_asset_id"] if r else None

    def set_asset(i, a, why):
        row = mon.rows.get(i + 1)
        if row is None or a is None or row["monster_asset_id"] == a:
            return
        row["monster_asset_id"] = a
        changed.add(i + 1)
        notes.append(f"{i} {names.get(i) or '?'} -> {why}")

    for i in range(N):
        if i in keep:
            continue
        sh = shape(mod, i, by_ptr)
        if sh == vshape[i]:
            continue
        j = first.get(sh)
        if j is None or asset(j) == asset(i):
            continue
        set_asset(i, asset(j), f"{j}'s shape")
    placeholder = asset(0)  # empty vanilla slots show the Guard (asset of monster 0)
    for i, j in standins.items():
        if asset(i) == placeholder:
            set_asset(i, asset(j), f"{j}'s art (stand-in)")
    log(f"sprites: {len(changed)} monsters on another asset ({'; '.join(notes) or 'none'})")
    return {"monster": changed}


# --- images mode -------------------------------------------------------------------------------

class Crop:
    """A SNES sprite cropped to its opaque box: palette slots per pixel (0 = clear) and its colors."""

    def __init__(self, sp):
        bb = sp.bbox()
        self.empty = bb is None
        self.pal = sp.pal
        if self.empty:
            self.w = self.h = 0
            self.idx = []
            return
        x0, y0, x1, y1 = bb
        self.w, self.h = x1 - x0, y1 - y0
        self.idx = [sp.px[y][x] for y in range(y0, y1) for x in range(x0, x1)]
        self.mask = bytes(1 if v else 0 for v in self.idx)

    def at(self, x, y):
        return self.idx[y * self.w + x] if 0 <= x < self.w and 0 <= y < self.h else 0


def pairing(a, b):
    """a's palette slots -> b's, by the most pixels in common (a one-to-one match)."""
    m = collections.Counter((x, y) for x, y in zip(a.idx, b.idx) if x and y)
    best = {}
    for (x, y), _ in m.most_common():
        if x not in best and y not in best.values():
            best[x] = y
    return best


def shape_diff(a, b):
    """Share of pixels whose palette-slot structure disagrees (0 = the same shape)."""
    pair = pairing(a, b)
    bad = sum(1 for x, y in zip(a.idx, b.idx) if (x or y) and pair.get(x, -1) != y)
    tot = sum(1 for x, y in zip(a.idx, b.idx) if x or y)
    return bad / max(1, tot)


def color_diff(a, b):
    """Largest-channel RGB distance, averaged over the pixels both draw."""
    s = n = 0
    for x, y in zip(a.idx, b.idx):
        if x and y:
            p, q = a.pal[x], b.pal[y]
            s += max(abs(p[0] - q[0]), abs(p[1] - q[1]), abs(p[2] - q[2]))
            n += 1
    return s / max(1, n)


def classify(van_sprites, mod_sprites, n=N):
    """[(monster, kind, vanilla monster, shape diff)]: kind same/swap/recolor/new/empty."""
    V = [Crop(van_sprites.sprite(i)) for i in range(n)]
    B = [Crop(mod_sprites.sprite(i)) for i in range(n)]
    by_size = collections.defaultdict(list)
    for j, c in enumerate(V):
        if not c.empty:
            by_size[(c.w, c.h)].append(j)
    out = []
    for i, b in enumerate(B):
        if b.empty:
            out.append((i, "empty", None, 1.0))
            continue
        scored = []
        for j in by_size.get((b.w, b.h), ()):
            if sum(x != y for x, y in zip(V[j].mask, b.mask)) > 0.2 * len(b.mask):
                continue
            scored.append((shape_diff(V[j], b), j != i, j))
        scored.sort()
        if not scored or scored[0][0] > 0.2:
            out.append((i, "new", None, scored[0][0] if scored else 1.0))
            continue
        d = scored[0][0]
        family = [j for s, _, j in scored if s <= 0.2]
        c, _, j = min((color_diff(V[j], b), j != i, j) for j in family)
        if c <= 4:
            kind = "same" if j == i or color_diff(V[i], b) <= 4 else "swap"
        else:
            kind = "recolor"
        out.append((i, kind, j, d))
    return out, V, B


_LAB = {}


def lab(c):
    c = tuple(c[:3])
    if c in _LAB:
        return _LAB[c]

    def lin(u):
        u /= 255
        return u / 12.92 if u <= 0.04045 else ((u + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(v) for v in c)
    X = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    Y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    Z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    fx, fy, fz = f(X), f(Y), f(Z)
    _LAB[c] = v = (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))
    return v


def from_lab(L):
    l, a, b = L
    fy = (l + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200

    def inv(t):
        return t ** 3 if t ** 3 > 0.008856 else (t - 16 / 116) / 7.787
    X, Y, Z = inv(fx) * 0.95047, inv(fy), inv(fz) * 1.08883
    r = 3.2406 * X - 1.5372 * Y - 0.4986 * Z
    g = -0.9689 * X + 1.8758 * Y + 0.0415 * Z
    bb = 0.0557 * X - 0.2040 * Y + 1.0570 * Z

    def enc(u):
        u = max(0.0, min(1.0, u))
        u = 12.92 * u if u <= 0.0031308 else 1.055 * u ** (1 / 2.4) - 0.055
        return int(round(u * 255))
    return (enc(r), enc(g), enc(bb))


def dE(p, q):
    return math.dist(lab(p), lab(q))


def align(w, h, rgba, crop):
    """(dx, dy): PR pixel (x, y) sits on the SNES crop's (x + dx, y + dy) (masks agree best)."""
    opaque = [rgba[4 * k + 3] > 0 for k in range(w * h)]
    best = None
    for dy in range(-4, 5):
        for dx in range(-4, 5):
            s = 0
            for y in range(h):
                for x in range(w):
                    s += 1 if opaque[y * w + x] == (crop.at(x + dx, y + dy) > 0) else -1
            if best is None or s > best[0]:
                best = (s, dx, dy)
    return best[1], best[2]


def color_table(w, h, rgba, van, mod):
    """{PR rgb: new rgb}: the PR art of vanilla crop `van` in the colors of the mod's crop `mod`.

    Each PR pixel takes the palette slot of the SNES pixel under it (the nearest slot within 3
    pixels whose vanilla color is closest to the PR's), then moves by that slot's change in Lab;
    a PR color gets the change most of its pixels get."""
    pair = pairing(van, mod)
    dx, dy = align(w, h, rgba, van)
    used = sorted(set(van.idx) - {0})
    per = collections.defaultdict(list)
    for y in range(h):
        for x in range(w):
            k = 4 * (y * w + x)
            if rgba[k + 3] == 0:
                continue
            c = tuple(rgba[k:k + 3])
            best = None
            for r in (1, 2, 3):
                for yy in range(y + dy - r, y + dy + r + 1):
                    for xx in range(x + dx - r, x + dx + r + 1):
                        v = van.at(xx, yy)
                        if v:
                            cost = dE(c, van.pal[v]) + 6 * math.hypot(xx - x - dx, yy - y - dy)
                            if best is None or cost < best[0]:
                                best = (cost, v)
                if best:
                    break
            v = best[1] if best else min(used, key=lambda u: dE(c, van.pal[u]))
            t = pair.get(v)
            if t is None or van.pal[v] == mod.pal[t]:
                n = c
            else:
                A, B, X = lab(van.pal[v]), lab(mod.pal[t]), lab(c)
                n = from_lab(tuple(X[q] + B[q] - A[q] for q in range(3)))
            per[c].append(n)
    return {c: collections.Counter(ns).most_common(1)[0][0] for c, ns in per.items()}


def apply_table(rgba, table):
    out = bytearray(rgba)
    for k in range(0, len(out), 4):
        if out[k + 3]:
            out[k:k + 3] = bytes(table.get(tuple(out[k:k + 3]), tuple(out[k:k + 3])))
    return bytes(out)


def hexrgb(c):
    return "%02x%02x%02x" % tuple(c[:3])


def sha1(b):
    return hashlib.sha1(b).hexdigest()


def pr_textures(group, game=None):
    """{texture name: (w, h, rgba)} of one asset group (mn_/mt_), from this PC's game (cached)."""
    import pr_images
    cache = pr_textures.__dict__.setdefault("cache", {})
    if group not in cache:
        if game is None:
            from prkit import games
            game = games.get("ff6").install
        cache[group] = pr_images.textures(pr_images.bundle_for(game, group))
    return cache[group]


# --- bestiary thumbnails ------------------------------------------------------------------------
# The bestiary's habitat map shows each monster as a 226x226 Thumbnail in a group of its own,
# mt_<group>_<asset> (LibraryResourceLoader: the monster's "{group}_{asset}" with "mn_" -> "mt_"):
# the monster's art at 3x, centered (big ones on a crop of the PR's choosing), in the art's colors.
THUMB = 226


def thumb_group(key):
    return "mt_" + key.lower()[3:]


def recolor_thumb(src, key, table):
    """A recolor's thumbnail: the base art's own thumbnail with the same color table."""
    tex = pr_textures(thumb_group(src)).get("Thumbnail")
    if tex is None:
        return None
    return {"group": thumb_group(key), "from_group": thumb_group(src), "sha1": sha1(apply_table(tex[2], table))}


def art_thumb(key, w, h, rgba, top=10, right=10):
    """New art's thumbnail: 3x, centered if it fits, else its top-right (the head: monsters face right)."""
    x = (THUMB - 3 * w) // 2 if 3 * w <= THUMB else THUMB - right - 3 * w
    y = (THUMB - 3 * h) // 2 if 3 * h <= THUMB else top
    return {"group": thumb_group(key), "x": x, "y": y, "scale": 3, "sha1": sha1(scaled(w, h, rgba, x, y, 3))}


def scaled(w, h, rgba, x0, y0, k, size=THUMB):
    """rgba (w x h) at k times its size with its top left at (x0, y0) on a clear size x size image."""
    out = bytearray(size * size * 4)
    for y in range(size):
        sy = (y - y0) // k
        if not 0 <= sy < h or y - y0 < 0:
            continue
        for x in range(size):
            sx = (x - x0) // k
            if 0 <= sx < w and x - x0 >= 0:
                a = 4 * (sy * w + sx)
                out[4 * (y * size + x):4 * (y * size + x) + 4] = rgba[a:a + 4]
    return bytes(out)


def final_tiers_image(profile, log):
    """The final battle's tower picture (MN_FF6_147_C00) with the mod's changes painted over the PR's
    own (tools/final_tiers.py: SNES captures of both ROMs' tiers, cached), or None without them."""
    try:
        import final_tiers as FT
        tex = pr_textures("mn_ff6_147").get("MN_FF6_147_C00")
        if tex is None:
            return None
        w, h, rgba = tex
        bg, parts, _ = FT.layers(P.VANILLA_ROM, profile.rom, rgba, log=log,
                                 pieces=getattr(profile, "final_tier_pieces", None))
    except Exception as e:      # no SNES core on this PC, ...: the PR's own tower stays
        log(f"sprites: final battle tower not made ({e})")
        return None
    out = bytearray(rgba)
    for layer in [bg] + [lay for _, lay in parts]:
        for k in range(0, len(out), 4):
            if layer[k + 3]:
                out[k:k + 4] = layer[k:k + 4]

    def z(b):
        return base64.b64encode(zlib.compress(b, 9)).decode("ascii")
    # each part a layer of its own: the plugin erases it from the picture when that monster (PR id = SNES + 1) dies
    return {"name": "final battle tower", "key": "MN_FF6_147_C00", "group": "mn_ff6_147", "w": w, "h": h,
            "from": "MN_FF6_147_C00", "from_sha1": sha1(rgba), "overlay": z(bg),
            "parts": [{"monster": m + 1, "overlay": z(lay)} for m, lay in parts], "sha1": sha1(bytes(out))}


def port_images(van, mod, tables, log, profile):
    from snes_sprites import Sprites
    mon = tables.setdefault("monster", P.Table("monster"))
    masset = tables.setdefault("monster_asset", P.Table("monster_asset"))
    vmon, vasset = P.Table("monster"), P.Table("monster_asset")
    vnames = {e.id: e.name.strip() for e in S.enemies(van)}
    names = {e.id: e.name.strip() for e in S.enemies(mod)}
    new_art = dict(getattr(profile, "sprite_new_art", None) or {})
    vs, ms = Sprites(van), Sprites(mod)
    rows, V, B = classify(vs, ms)
    changed = {"monster": set(), "monster_asset": set()}
    images, notes, left = [], collections.defaultdict(list), []

    def asset_id(i):
        r = vmon.rows.get(i + 1)
        return int(r["monster_asset_id"]) if r else None

    def key_of(aid):
        a = vasset.rows.get(aid)
        return (a["group_name"], f"{a['group_name'].upper()}_{a['asset_name'].upper()}") if a else (None, None)

    def set_asset(i, aid):
        row = mon.rows.get(i + 1)
        if row is not None and str(row["monster_asset_id"]) != str(aid):
            row["monster_asset_id"] = str(aid)
            changed["monster"].add(i + 1)

    def new_asset(i, group):
        aid = IMAGE_ASSET_BASE + i
        tmpl = dict(vasset.rows[asset_id(i)] if asset_id(i) in vasset.rows else next(iter(vasset)))
        tmpl.update(id=str(aid), group_name=group, asset_name=f"b{i:03d}")
        masset.rows[aid] = tmpl
        changed["monster_asset"].add(aid)
        set_asset(i, aid)
        return f"{group.upper()}_B{i:03d}"

    placeholder = asset_id(0)
    for i, kind, j, d in rows:
        if kind == "swap":
            if asset_id(j) != asset_id(i):
                set_asset(i, asset_id(j))
                notes["swap"].append(f"{i} {names[i]} = {vnames[j]}")
        elif kind == "recolor":
            # the shape's vanilla monsters with PR art: the one whose colors are closest
            fam = [k for k in range(N) if not V[k].empty and (V[k].w, V[k].h) == (V[j].w, V[j].h)
                   and shape_diff(V[k], V[j]) <= 0.2 and asset_id(k) and asset_id(k) != placeholder]
            best = None
            for k in fam:
                p = pairing(V[k], B[i])
                dist = sum(dE(V[k].pal[v], B[i].pal[t]) for v, t in p.items()) / max(1, len(p))
                if best is None or dist < best[0]:
                    best = (dist, k)
            if best is None:
                left.append(f"{i} {names[i]} (no PR art of its shape)")
                continue
            k = best[1]
            group, src = key_of(asset_id(k))
            tex = pr_textures(group).get(src)
            if tex is None:
                left.append(f"{i} {names[i]} ({src} isn't RGBA32)")
                continue
            w, h, rgba = tex
            table = color_table(w, h, rgba, V[k], B[i])
            table = {c: n for c, n in table.items() if c != n}
            if not table:           # a pixel touch-up in vanilla's colors: the PR's art is it
                notes["touch-up"].append(f"{i} {names[i]}")
                continue
            key = new_asset(i, group)
            out = apply_table(rgba, table)
            images.append({"monster": i, "name": names[i], "key": key, "group": group, "w": w, "h": h,
                           "from": src, "from_sha1": sha1(rgba),
                           "map": sorted(f"{hexrgb(c)}:{hexrgb(n)}" for c, n in table.items()),
                           "sha1": sha1(out), "thumb": recolor_thumb(src, key, table)})
            notes["recolor"].append(f"{i} {names[i]} <- {src}")
        elif kind == "new":
            if i in new_art:
                stand = new_art[i]
                group, _ = key_of(asset_id(stand))
                c = B[i]
                pal = sorted(set(c.idx) - {0})
                rgba = b"".join(bytes(c.pal[v]) + b"\xff" if v else b"\0\0\0\0" for v in c.idx)
                key = new_asset(i, group)
                images.append({"monster": i, "name": names[i], "key": key, "group": group, "w": c.w, "h": c.h,
                               "palette": [hexrgb(c.pal[v]) if v in pal else "000000" for v in range(len(c.pal))],
                               "pixels": base64.b64encode(zlib.compress(bytes(c.idx), 9)).decode("ascii"),
                               "sha1": sha1(rgba), "thumb": art_thumb(key, c.w, c.h, rgba)})
                notes["new"].append(f"{i} {names[i]}")
            else:
                left.append(f"{i} {names[i] or '(unnamed)'} (new art)")
    for i, j in (getattr(profile, "sprite_standins", None) or {}).items():
        if i not in new_art and str(mon.rows[i + 1]["monster_asset_id"]) == str(placeholder):
            set_asset(i, asset_id(j))
            notes["stand-in"].append(f"{i} {names[i]} = {vnames[j]}")
    if getattr(profile, "sprite_final_tiers", False):
        tower = final_tiers_image(profile, log)
        if tower:
            images.append(tower)
            notes["final battle tower"].append(f"{tower['key']} repainted")
    recipe = {"version": 1, "images": images}
    recipe["id"] = sha1(json.dumps(recipe, sort_keys=True).encode())[:16]
    port.images = recipe
    port.classes = rows
    counts = collections.Counter(k for _, k, _, _ in rows)
    log(f"sprites: {dict(counts)}; " + "; ".join(f"{k} ({len(v)}): {', '.join(v)}" for k, v in notes.items())
        + (f"; not ported: {', '.join(left)}" if left else ""))
    return changed


port.images = None
port.classes = None


if __name__ == "__main__":
    # dev check: the classification and recipe for BNW, without running the whole porter
    import sys
    import profiles
    prof = profiles.PROFILES["bnw"]
    tables = {}
    ch = port(S.Rom(P.VANILLA_ROM), S.Rom(prof.rom), tables, print, prof)
    print({k: len(v) for k, v in ch.items()})
    json.dump(port.images, sys.stdout if len(sys.argv) < 2 else open(sys.argv[1], "w"), indent=1)
