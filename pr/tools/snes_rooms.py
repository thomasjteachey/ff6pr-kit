"""SNES rooms -> new Pixel Remaster maps: the PR's tiles for an SNES layout, and the files of a new map.

The PR redrew FF6's maps on 16 px atlases (one or more per map group: package.json "texture", e.g.
map353 for the Veldt cave), keeping the SNES's grid: each SNES cell became a stack of up to four PR
tiles (BottomLayer, GroundLayer, UpperLayer, CeilLayer) plus a collision value (the map's one
collision layer, GroundCollision or UpperCollision: 0 = walkable, 1 = blocked, 2-11 = the PR's
special cells). The PR draws the whole SNES layout on each of its room maps but makes only that
room walkable. So an SNES room the PR never had (a mod's new room, drawn with a vanilla tileset)
can be redrawn from what the PR did with the same SNES tiles elsewhere:

    import snes_rooms as R
    model = R.model(rom, m)                         # learned from the vanilla rooms that look like map m
    room = model.convert(bg1_rows, bg2_rows, R.tile_props(rom, m))
    R.write_map(out, model.group, "Map_30761_6", map_id=806, script_id=629, like="Map_30761_1",
                room=room, objects=[...])           # a Magicite folder with the new map
    R.clone_map(out, "Map_20071_10", "Map_20071_28", ...)   # a copy of a PR map, new objects
    R.render(room, "room.png")                      # a picture of it (the game's atlases, read only)

How a stack is chosen (`Model`): tiers of vanilla rooms, closest look first: the same SNES graphics
(map properties bytes 7-12), the same tilesets and graphics sets, the same two tilesets (a mod that
swapped a graphics set keeps the vanilla tileset's structure), the same BG1 tileset. Within a tier,
the BG1 tile with its four neighbours (the PR draws a wall's top row, a corner, a shadow
differently), then (BG1, BG2), then BG1 alone. Stacks are kept as atlas-local references (atlas
name, tile number) so rooms from several PR maps teach one model; a model writes into one map group
and keeps to the atlases that group has. Collision: (BG1, BG2, the tile's SNES properties), then
(BG1, properties), then the SNES properties alone over every vanilla room (`tile_props`: the
passability bytes the SNES field code uses; they alone decide 92% of the PR's collision).

Measured (`python tools/snes_rooms.py eval`): see `evaluate`.
New map ids and script ids must not be the game's (map.csv, map_script.csv): the caller picks them.
"""
import collections
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import kitpath  # noqa: E402,F401
except ImportError:   # the kit repository alone has none (its tools are already on the path)
    pass
import prdata as P  # noqa: E402
import snes_maps as SM  # noqa: E402

LAYERS = ("BottomLayer", "GroundLayer", "UpperLayer", "CeilLayer")
RES = "Assets/GameAssets/Serial/Res/Map"
MASTER = "Assets/GameAssets/Serial/Data/Master"
FLIPS = 0xE0000000   # Tiled's flip bits on a gid


# --- SNES side -------------------------------------------------------------------------------------
def graphics(rom, m, base=SM.PROPS):
    """The bytes that decide how a map's SNES tiles look (graphics sets + tilesets)."""
    return bytes(rom[base + 33 * m + 7:base + 33 * m + 13])


def look(g):
    """Map properties bytes 7-12 unpacked as the field code does (C0/2690, C0/27D8): four 7-bit
    graphics sets, BG3 graphics, the BG1 tileset ((word 11) >> 2 & 0x7F), the BG2 tileset (byte
    12 >> 1)."""
    v = int.from_bytes(g[:4], "little")
    return {"sets": tuple(v >> 7 * k & 0x7F for k in range(4)), "bg3": v >> 28 | (g[4] & 3) << 4,
            "ts1": (g[4] | g[5] << 8) >> 2 & 0x7F, "ts2": g[5] >> 1}


def tiers(g):
    """The keys of a look, closest first (see the module notes)."""
    lk = look(g)
    return [("graphics", bytes(g)), ("sets", (lk["ts1"], lk["ts2"], lk["sets"])), ("tilesets", (lk["ts1"], lk["ts2"])),
            ("bg1", lk["ts1"])]


def tile_props(rom, m, props=SM.PROPS):
    """A map's SNES tile properties (snes_maps.tile_props): per BG1 tile (low, high) bytes."""
    return SM.tile_props(rom, m, props)


def _shape(rows, props, x, y):
    """Which of the 4 cells N, S, W, E of (x, y) are SNES walls (1), not (0), off the layout (2)."""
    if props is None:
        return None
    h, w = len(rows), len(rows[0])
    get = lambda xx, yy: (props[rows[yy][xx]][0] == SM.WALL) if 0 <= yy < h and 0 <= xx < w else 2
    return (int(get(x, y - 1)), int(get(x, y + 1)), int(get(x - 1, y)), int(get(x + 1, y)))


def _around(rows, x, y):
    """The BG1 tiles N, S, W, E of (x, y) (-1 off the layout)."""
    h, w = len(rows), len(rows[0])
    get = lambda xx, yy: rows[yy][xx] if 0 <= yy < h and 0 <= xx < w else -1
    return (get(x, y - 1), get(x, y + 1), get(x - 1, y), get(x + 1, y))


# --- PR side ---------------------------------------------------------------------------------------
def group_of(pr_map):
    """The asset group (Magicite folder, e.g. map_20071) a vanilla PR map is in."""
    rel = os.path.relpath(SM.pr_tilemaps()[pr_map], P.VANILLA)
    return rel.replace("\\", "/").split("/")[0]


_textures = {}


def group_textures(group):
    """The atlases a map group's package.json lists."""
    if group not in _textures:
        import glob
        names = set()
        for p in glob.glob(os.path.join(P.VANILLA, group, *RES.split("/"), "*", "package.json")):
            with open(p, encoding="utf-8") as f:
                names |= {t["name"] for t in json.load(f).get("texture", [])}
        _textures[group] = names
    return _textures[group]


def _tsets(tm):
    return sorted(((ts["firstgid"], ts["name"]) for ts in tm["tilesets"]), reverse=True)


def _ref(gid, tsets):
    """A gid -> (atlas name, tile number | flip bits), or 0."""
    if not gid:
        return 0
    raw = gid & ~FLIPS
    for first, name in tsets:
        if raw >= first:
            return (name, (raw - first) | (gid & FLIPS))
    return 0


_tileset_entries = {}


class Look:
    """What an SNES map's tiles look like: its graphics sets in VRAM as the field code loads them
    (C0/2690: set 0 at chars 0-255, 1 at 256-383, 2 at 384-511, 3 at 512-767; data DF/DB00 + the
    3-byte pointers at the ROM's gfx_ptrs), its palette (props byte 25: 128 colours at `palettes`)
    and its two tilesets' 16x16 formations (DF/BA00). `cell(a, b)`: the 16x16 picture of a cell (BG2
    tile b under BG1 tile a) as RGB bytes, black where both are clear; `key(a, b)` a short hash of
    it: two cells with one key look the same on the SNES, whatever their tile numbers."""

    def __init__(self, rom, m, t=None):
        t = t or SM.US
        p = SM.properties(rom, m, t.props)
        lk = look(graphics(rom, m, t.props))
        self.vram = bytearray(0x6000)
        for k, (at, size) in enumerate(((0, 0x2000), (0x2000, 0x1000), (0x3000, 0x1000), (0x4000, 0x2000))):
            ptr = int.from_bytes(rom[t.gfx_ptrs + 3 * lk["sets"][k]:t.gfx_ptrs + 3 * lk["sets"][k] + 3], "little")
            snes = 0xDFDB00 + ptr
            src = SM._file_offset((snes >> 16 & 0xFF) << 16 | snes & 0xFFFF)
            self.vram[at:at + size] = bytes(rom[src:src + size]).ljust(size, bytes(1))
        raw = rom[t.palettes + 256 * p["palette"]:t.palettes + 256 * p["palette"] + 256]
        self.pal = []
        for i in range(128):
            c = raw[2 * i] | raw[2 * i + 1] << 8
            self.pal.append(None if i % 16 == 0 else bytes(((c & 31) << 3, (c >> 5 & 31) << 3, (c >> 10 & 31) << 3)))
        self.forms = (SM.tileset(rom, lk["ts1"]), SM.tileset(rom, lk["ts2"]))
        self._chars, self._cells, self._keys = {}, {}, {}

    def _char(self, n):
        if n not in self._chars:
            b = self.vram[32 * n:32 * n + 32] if 32 * n + 32 <= len(self.vram) else bytes(32)
            px = []
            for y in range(8):
                p0, p1, p2, p3 = b[2 * y], b[2 * y + 1], b[16 + 2 * y], b[17 + 2 * y]
                px.append([(p0 >> 7 - x & 1) | (p1 >> 7 - x & 1) << 1 | (p2 >> 7 - x & 1) << 2 | (p3 >> 7 - x & 1) << 3
                           for x in range(8)])
            self._chars[n] = px
        return self._chars[n]

    def cell(self, a, b):
        k = (a, b)
        if k not in self._cells:
            img = [bytes(3)] * 256
            for tile, form in ((b, self.forms[1]), (a, self.forms[0])):
                if tile is None or not 0 <= tile < 256:
                    continue
                f = form[tile]
                for q in range(4):
                    w = f[q] | f[q + 4] << 8
                    px = self._char(w & 0x3FF)
                    pal = (w >> 10 & 7) * 16
                    for y in range(8):
                        row = px[7 - y if w & 0x8000 else y]
                        for x in range(8):
                            c = self.pal[pal + row[7 - x if w & 0x4000 else x]]
                            if c is not None:
                                img[(8 * (q // 2) + y) * 16 + 8 * (q % 2) + x] = c
            self._cells[k] = b"".join(img)
        return self._cells[k]

    def key(self, a, b):
        k = (a, b)
        if k not in self._keys:
            import hashlib
            self._keys[k] = hashlib.blake2b(self.cell(a, b), digest_size=8).digest()
        return self._keys[k]

    def signature(self, a, b):
        """A coarse picture: the mean colour of each 4x4 block (48 numbers), for the nearest look."""
        c = self.cell(a, b)
        out = []
        for by in range(4):
            for bx in range(4):
                tot = [0, 0, 0]
                for y in range(4):
                    for x in range(4):
                        i = ((by * 4 + y) * 16 + bx * 4 + x) * 3
                        tot[0] += c[i]
                        tot[1] += c[i + 1]
                        tot[2] += c[i + 2]
                out += [v // 16 for v in tot]
        return tuple(out)


_looks = {}


def look_of(rom, m, t=None):
    """The Look of map m (shared by every map with the same graphics and palette)."""
    t = t or SM.US
    key = (id(rom), graphics(rom, m, t.props), SM.properties(rom, m, t.props)["palette"], t.gfx_ptrs, t.palettes)
    if key not in _looks:
        _looks[key] = Look(rom, m, t)
    return _looks[key]


def pr_cells(pr_map):
    """A PR map's per-cell ((Bottom, Ground, Upper, Ceil refs), collision) rows and its tilemap JSON.
    A ref is (atlas, tile | flips) or 0. The collision is the map's collision layer (a few maps have
    two: a cell walkable on either is walkable)."""
    path = SM.pr_tilemaps()[pr_map]
    lay = SM.pr_layers(path)
    with open(os.path.join(os.path.dirname(path), "collision.json"), encoding="utf-8") as f:
        c = json.load(f)
    colls = []

    def walk(ls):
        for layer in ls:
            if layer.get("type") == "tilelayer":
                colls.append([layer["data"][r * layer["width"]:(r + 1) * layer["width"]] for r in range(layer["height"])])
            walk(layer.get("layers", []))
    walk(c.get("layers", []))
    with open(path, encoding="utf-8") as f:
        tm = json.load(f)
    for ts in tm["tilesets"]:
        _tileset_entries.setdefault(ts["name"], ts)
    H, W = tm["height"], tm["width"]
    ts = _tsets(tm)
    z = [[0] * W for _ in range(H)]

    def coll_at(x, y):
        vals = [cl[y][x] for cl in colls if y < len(cl) and x < len(cl[0])]
        if not vals:
            return 1
        return 0 if 0 in vals else vals[0]
    rows = [[(tuple(_ref(lay.get(n, z)[y][x], ts) for n in LAYERS), coll_at(x, y)) for x in range(W)] for y in range(H)]
    return rows, tm


_cells_cache = {}


def _cells(pr):
    if pr not in _cells_cache:
        _cells_cache[pr] = pr_cells(pr)
    return _cells_cache[pr]


def active(cells, border=2):
    """The cells a PR room shows: its walkable cells and what borders them (`border` tiles)."""
    H, W = len(cells), len(cells[0])
    walk = {(x, y) for y in range(H) for x in range(W) if cells[y][x][1] == 0 and any(cells[y][x][0])}
    return {(x + a, y + b) for x, y in walk for a in range(-border, border + 1) for b in range(-border, border + 1)
            if 0 <= x + a < W and 0 <= y + b < H}


# --- learning --------------------------------------------------------------------------------------
class Room:
    """A converted room: layers {name: rows of refs (atlas, tile) or 0}, collision rows."""

    def __init__(self, width, height, layers, collision, unknown, guessed=0):
        self.width, self.height = width, height
        self.layers, self.collision, self.unknown = layers, collision, unknown
        self.guessed = guessed   # cells drawn from a looser rule (a tile seen without its neighbourhood)

    def atlases(self):
        return sorted({r[0] for rows in self.layers.values() for row in rows for r in row if r})


_best_cache = {}


def _best_for(tiles, key, counter, group, ok):
    """_most(counter, ok) for a picture, kept per (Tiles, picture, group)."""
    k = (id(tiles), key, group)
    if k not in _best_cache:
        _best_cache[k] = _most(counter, ok)
    return _best_cache[k]


def _most(counter, ok=None):
    for v, _ in counter.most_common():
        if ok is None or ok(v):
            return v
    return None


class Tiles:
    """Counts from vanilla cells: the PR stack by (BG1, BG2, neighbours), (BG1, BG2), BG1; the
    collision by (BG1, BG2, SNES properties), (BG1, properties), properties."""
    TABLES = ("ctx", "shape", "pair", "single", "vis", "vis_shape", "coll_pair", "coll_tile", "coll_props")

    def __init__(self):
        for n in self.TABLES:
            setattr(self, n, collections.defaultdict(collections.Counter))
        self.cells = 0
        self.groups = collections.Counter()
        self.signatures = {}      # vis key -> coarse picture (Look.signature)

    def add(self, a, b, around, prop, stack, coll, group=None, shape=None, vis=None):
        self.ctx[(a, b) + around][stack] += 1
        if shape is not None:
            self.shape[(a, b) + shape][stack] += 1
        if vis is not None:
            self.vis[vis[0]][stack] += 1
            self.signatures[vis[0]] = vis[1]
            if shape is not None:
                self.vis_shape[(vis[0],) + shape][stack] += 1
        self.pair[(a, b)][stack] += 1
        self.single[a][stack] += 1
        if coll is not None:      # None: a cell the PR blocks only because its room ends there
            self.coll_pair[(a, b, prop)][coll] += 1
            self.coll_tile[(a, prop)][coll] += 1
            self.coll_props[prop][coll] += 1
        self.cells += 1
        if group:
            self.groups[group] += 1

    def merge(self, other):
        for n in self.TABLES:
            mine = getattr(self, n)
            for k, c in getattr(other, n).items():
                mine[k].update(c)
        self.cells += other.cells
        self.groups.update(other.groups)
        self.signatures.update(other.signatures)
        return self

    def _get(self, table, key, exclude):
        c = getattr(self, table).get(key)
        if c and exclude is not None:
            e = getattr(exclude, table).get(key)
            if e:
                c = c - e
        return c or None

    def stack(self, a, b, around=None, ok=None, exclude=None, shape=None):
        """(PR stack or None, how: 0 neighbourhood (the 4 tiles around), 1 BG1+BG2 with which neighbours
        are walls (the PR draws a room's edge into the SNES void beside it), 1 BG1+BG2, 2 BG1 alone,
        3 none)."""
        for how, (table, key) in ((0, ("ctx", (a, b) + around if around else None)),
                                  (1, ("shape", (a, b) + shape if shape else None)), (1, ("pair", (a, b))),
                                  (2, ("single", a))):
            if key is None:
                continue
            c = self._get(table, key, exclude)
            s = _most(c, ok) if c else None
            if s is not None:
                return s, how
        return None, 3

    def collision(self, a, b, prop, exclude=None, props_only=False):
        keys = (("coll_props", prop),) if props_only else \
            (("coll_pair", (a, b, prop)), ("coll_tile", (a, prop)), ("coll_props", prop))
        for table, key in keys:
            c = self._get(table, key, exclude)
            if c:
                return _most(c)
        return None


_samples = {}


def samples(rom, m, pr, dx, dy, t=None):
    """A vanilla pair's learning cells: Tiles over the PR room's shown cells (cached)."""
    key = (id(rom), m, pr, dx, dy)
    if key in _samples:
        return _samples[key]
    tiles = Tiles()
    _samples[key] = tiles
    if pr not in SM.pr_tilemaps():
        return tiles
    bg1, bg2 = SM.layout(rom, m, 0, t=t), SM.layout(rom, m, 1, t=t)
    if bg1 is None:
        return tiles
    tp = tile_props(rom, m, t.props if t else SM.PROPS)
    cells, _ = _cells(pr)
    group = group_of(pr)
    wk = SM.pr_walkable(pr)
    lk = look_of(rom, m, t)
    for (x, y) in active(cells):
        refs, coll = cells[y][x]
        sx, sy = x - dx, y - dy
        if not (0 <= sy < len(bg1) and 0 <= sx < len(bg1[0])) or not any(refs):
            continue
        b = bg2[sy][sx] if bg2 and sy < len(bg2) and sx < len(bg2[0]) else None
        a = bg1[sy][sx]
        if coll != 0 and cut(bg1, tp, wk, sx, sy, dx, dy):
            coll = None
        tiles.add(a, b, _around(bg1, sx, sy), tp[a], refs, coll, group, _shape(bg1, tp, sx, sy),
                  (lk.key(a, b), lk.signature(a, b)))
    return tiles


def cut(bg1, tp, wk, sx, sy, dx, dy):
    """Whether a cell the PR blocks is one the SNES walks on that leads on past the PR room (the PR
    split the SNES map into rooms there): passable itself, with a passable neighbour outside the
    room's walkable cells. Such cells teach nothing about collision and aren't judged on it."""
    if tp[bg1[sy][sx]][0] == SM.WALL:
        return False
    for nx, ny in ((sx + 1, sy), (sx - 1, sy), (sx, sy + 1), (sx, sy - 1)):
        if 0 <= ny < len(bg1) and 0 <= nx < len(bg1[0]) and tp[bg1[ny][nx]][0] != SM.WALL and                 (nx + dx, ny + dy) not in wk:
            return True
    return False


def learn(rom, pairs, t=None, into=None):
    """Tiles from (SNES map, PR map, dx, dy) pairs (snes_maps.pr_maps gives them)."""
    tiles = into or Tiles()
    for m, pr, dx, dy in pairs:
        tiles.merge(samples(rom, m, pr, dx, dy, t))
    return tiles


TRAIN_WALK = 0.85   # pairs learned from: the PR walks where the SNES walks on 85%+ of its walkable cells


class Vanilla:
    """The vanilla rooms to learn from (snes_maps pairs found by chests, exits or tiles, walking
    where the SNES walks: not the 'layout' copies), grouped by every look tier; Tiles per tier key
    built on demand."""

    def __init__(self, us=None):
        import ff6snes as S
        self.us = us if us is not None else S.rom_bytes(P.VANILLA_ROM)
        self.pairs = collections.defaultdict(list)
        self.by_key = collections.defaultdict(list)
        for m, ms in SM.table().items():
            if m < 3:
                continue
            for mt in ms:
                walk = mt.walk or [None, 0]
                if mt.how != "layout" and mt.pr in SM.pr_tilemaps() and                         (walk[0] is None or walk[1] < 8 or walk[0] >= TRAIN_WALK):
                    self.pairs[m].append((m, mt.pr, mt.dx, mt.dy))
            if self.pairs[m]:
                for key in tiers(graphics(self.us, m)):
                    self.by_key[key].append(m)
        self._tiles = {}
        self._all = None
        self._disk = None     # the learned Tiles kept on disk (_load), and whether this process added any
        self._dirty = False

    # The learned Tiles depend only on the vanilla ROM, the vanilla folder, the snes_maps pairs and this code, and
    # learning them took most of a minute in every process that converts a room (BNW's port: the Kaiser room;
    # T-Edition's maps). They're kept beside vcache's files (pr/cache/snes_rooms_tiles.pickle), keyed by all of
    # those inputs (any change: learned again), written once at exit (aside, then moved in). SNES_ROOMS_NOCACHE=1
    # skips the file (architecture roadmap item 6, 2026-11-20).
    def _fingerprint(self):
        import hashlib
        import vcache
        h = hashlib.sha1(b"snes_rooms tiles 1;")
        h.update(hashlib.sha1(bytes(self.us)).digest())
        h.update(vcache.stamp().encode())
        srcs = [os.path.join(HERE, n) for n in ("snes_rooms.py", "snes_maps.py", "ff6snes.py", "prdata.py")]
        for f in srcs + [SM.DATA_FILE, SM.OVERRIDES_FILE]:
            try:
                with open(f, "rb") as fh:
                    h.update(fh.read())
            except OSError:
                h.update(b"-")
        h.update(repr(TRAIN_WALK).encode())
        return h.hexdigest()

    @staticmethod
    def _disk_path():
        import vcache
        return os.path.join(vcache.folder(), "snes_rooms_tiles.pickle")

    def _load(self):
        if self._disk is not None:
            return
        self._disk = {"fp": None, "tiles": {}, "every": None}
        if os.environ.get("SNES_ROOMS_NOCACHE"):
            return
        import pickle
        self._disk["fp"] = fp = self._fingerprint()
        try:
            with open(self._disk_path(), "rb") as f:
                doc = pickle.load(f)
            if isinstance(doc, dict) and doc.get("fp") == fp:
                self._disk = doc
        except Exception:   # missing, half-written by a crash, or from older code: learn again
            pass

    def _changed(self):
        if not self._dirty and not os.environ.get("SNES_ROOMS_NOCACHE"):
            import atexit
            atexit.register(self._save)
        self._dirty = True

    def _save(self):
        import pickle
        path = self._disk_path()
        tmp = f"{path}.{os.getpid()}.tmp"
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(tmp, "wb") as f:
                pickle.dump(self._disk, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, path)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass

    # each learned Tiles is kept as its pickle, taken as it's learned (nothing done with it later reaches the file),
    # and read back only when a process asks for that key
    def tiles(self, key):
        if key not in self._tiles:
            import pickle
            self._load()
            b = self._disk["tiles"].get(key)
            if b is not None:
                t = pickle.loads(b)
            else:
                t = Tiles()
                for m in self.by_key.get(key, []):
                    learn(self.us, self.pairs[m], into=t)
                self._disk["tiles"][key] = pickle.dumps(t, protocol=pickle.HIGHEST_PROTOCOL)
                self._changed()
            self._tiles[key] = t
        return self._tiles[key]

    def own(self, m, key=None):
        """What a held-out evaluation of map m must not learn from: its pairs and every other map's on
        the same PR rooms (its story-state twins), among the maps of tier `key` (all maps: None)."""
        prs = {pr for _, pr, _, _ in self.pairs.get(m, [])}
        maps = self.by_key.get(key, []) if key is not None else list(self.pairs)
        return learn(self.us, [p for v in maps for p in self.pairs[v] if p[1] in prs])

    def every(self):
        """Every vanilla room (for the collision by SNES properties alone)."""
        if self._all is None:
            import pickle
            self._load()
            b = self._disk.get("every")
            if b is not None:
                t = pickle.loads(b)
            else:
                t = Tiles()
                for m in self.pairs:
                    learn(self.us, self.pairs[m], into=t)
                self._disk["every"] = pickle.dumps(t, protocol=pickle.HIGHEST_PROTOCOL)
                self._changed()
            self._all = t
        return self._all


_vanilla = None


def vanilla():
    global _vanilla
    if _vanilla is None:
        _vanilla = Vanilla()
    return _vanilla


class Model:
    """A room's converter: tiers of Tiles (closest look first) writing into one map group. A tile
    no tier shows is drawn as the most alike tile that one does (`formation`: the room's SNES
    tileset; most 8x8 parts in common, at least 2 of 4)."""

    def __init__(self, tier_tiles, every, group, exclude=None, formation=None, look=None):
        self.tiers, self.every, self.group = tier_tiles, every, group
        self.textures = group_textures(group) if group else None
        self.exclude = exclude or {}   # a held-out map's own counts per tier key (None: every room)
        self.cells = sum(t.cells for _, t in tier_tiles)
        self.formation = formation
        self.look = look               # the room's own Look: cells matched by their SNES picture
        self._alike, self._near = {}, {}

    def ok(self, stack):
        return self.textures is None or all(not r or r[0] in self.textures for r in stack)

    def _stack(self, a, b, around, shape=None):
        """Each rule over every tier before the next, looser rule: an exact (BG1, BG2) pair from a
        room with the same tilesets beats BG1 alone from one with the same graphics (BG2 can carry
        the wall). Rules that read BG2 only from tiers that share the BG2 tileset."""
        levels = (("ctx", (a, b) + around if around else None, 0), ("shape", (a, b) + shape if shape else None, 1),
                  ("pair", (a, b), 1), ("single", a, 2))
        for table, k, how in levels:
            if k is None:
                continue
            for i, (key, t) in enumerate(self.tiers):
                if table != "single" and key[0] == "bg1":
                    continue
                c = t._get(table, k, self.exclude.get(key))
                st = _most(c, self.ok) if c else None
                if st is not None:
                    return st, how + 3 * i
        return None, 99

    def alike(self, a):
        """The known tiles most like tile a (by SNES tile parts), best first."""
        if a not in self._alike:
            out = []
            if self.formation:
                f = self.formation[a]
                known = {k for key, t in self.tiers for k in t.single if t._get("single", k, self.exclude.get(key))}
                scored = sorted(((SM.tile_likeness(f, self.formation[k]), k) for k in known if k != a and 0 <= k < 256),
                                reverse=True)
                out = [k for sc, k in scored if sc >= 2][:4]
            self._alike[a] = out
        return self._alike[a]

    def _visual(self, vis, shape):
        """A stack for a cell by its SNES picture (with which neighbours are walls, then alone): in
        the rooms that look like this one first (tier by tier), then in every vanilla room."""
        sources = [(key, t) for key, t in self.tiers] + [(None, self.every)]
        for table, k, how in (("vis_shape", (vis,) + shape if shape else None, 30), ("vis", vis, 31)):
            if k is None:
                continue
            for i, (key, t) in enumerate(sources):
                c = t._get(table, k, self.exclude.get(key))
                st = _most(c, self.ok) if c else None
                if st is not None:
                    return st, how + (2 if key is None else 0)
        return None, 99

    def _pictures(self):
        """[(coarse picture, stack)] of every vanilla picture this group's atlases can draw (once)."""
        if not hasattr(self, "_pics"):
            ex = self.exclude.get(None)
            exv = ex.vis if ex is not None else {}
            self._pics = []
            for k, c in self.every.vis.items():
                if k in exv:
                    c = c - exv[k]
                    if not c:
                        continue
                st = _best_for(self.every, k, c, self.group, self.ok) if k not in exv else _most(c, self.ok)
                if st is not None:
                    self._pics.append((self.every.signatures[k], st))
        return self._pics

    def nearest(self, vis, sig):
        """The stack of the vanilla picture nearest to `sig` (coarse colours) among those this
        group's atlases can draw."""
        if vis not in self._near:
            best = None
            for ksig, st in self._pictures():
                d = sum((x - y) * (x - y) for x, y in zip(sig, ksig))
                if best is None or d < best[0]:
                    best = (d, st)
            # no room of this look to learn from: the nearest picture whatever its distance
            cap = 48 * 24 * 24 if self.tiers else None
            self._near[vis] = best[1] if best and (cap is None or best[0] <= cap) else None
        return self._near[vis]

    def stack(self, a, b, around, shape=None):
        """The rules in order: the BG1 tile with its 4 neighbours (same look); the cell's SNES picture
        (with which neighbours are walls, then alone: any vanilla room); the tile rules (`_stack`);
        the nearest picture; the most alike tile."""
        s, how = self._stack(a, b, around, None) if around else (None, 99)
        if s is not None and how % 3 == 0:
            return s, how
        vis = self.look.key(a, b) if self.look else None
        if vis is not None:
            s, how = self._visual(vis, shape)
            if s is not None:
                return s, how
        s, how = self._stack(a, b, None, shape)
        if s is None and vis is not None:
            s = self.nearest(vis, self.look.signature(a, b))
            if s is not None:
                return s, 40
        if s is None:
            for k in self.alike(a):
                s, how = self._stack(k, b, None)
                if s is not None:
                    return s, 50 + how
        return s, how

    def collision(self, a, b, prop):
        for key, t in self.tiers:
            c = t.collision(a, b, prop, self.exclude.get(key))
            if c is not None:
                return c
        c = self.every.collision(a, b, prop, self.exclude.get(None), props_only=True)
        return 1 if c is None else c

    def convert(self, bg1, bg2=None, props=None, trim=3):
        """A room's PR layers (refs) and collision from its BG1 (and BG2) rows; `props`: its
        tile_props. Cells more than `trim` tiles from anywhere walkable are left empty (the void
        around a room: the map's backdrop colour, as the PR leaves it; None keeps them)."""
        h, w = len(bg1), len(bg1[0])
        layers = {n: [[0] * w for _ in range(h)] for n in LAYERS}
        coll = [[self.collision(bg1[y][x], bg2[y][x] if bg2 and y < len(bg2) and x < len(bg2[0]) else None,
                                props[bg1[y][x]] if props else None) for x in range(w)] for y in range(h)]
        shown = None
        if trim is not None:
            walk = [(x, y) for y in range(h) for x in range(w) if coll[y][x] == 0]
            shown = {(x + a, y + b) for x, y in walk for a in range(-trim, trim + 1) for b in range(-trim, trim + 1)}
        unknown = guessed = 0
        for y in range(h):
            for x in range(w):
                if shown is not None and (x, y) not in shown:
                    coll[y][x] = 1
                    continue
                b = bg2[y][x] if bg2 and y < len(bg2) and x < len(bg2[0]) else None
                s, how = self.stack(bg1[y][x], b, _around(bg1, x, y), _shape(bg1, props, x, y))
                if s is None:
                    unknown += 1
                    continue
                guessed += how in (2, 5, 8, 11, 32, 33, 40) or how >= 50
                for n, v in zip(LAYERS, s):
                    layers[n][y][x] = v
        room = Room(w, h, layers, coll, unknown, guessed)
        room.shown = len(shown & {(x, y) for y in range(h) for x in range(w)}) if shown is not None else w * h
        return room

    def coverage(self, rows, group):
        """How many of the cells in `rows` (BG1) some tier can draw with `group`'s atlases."""
        tex = group_textures(group)
        ok = lambda st: all(not r or r[0] in tex for r in st)
        counts = collections.Counter(v for row in rows for v in row)
        return sum(n for a, n in counts.items()
                   if any(c and any(ok(st) for st in c)
                          for c in (t._get("single", a, self.exclude.get(key)) for key, t in self.tiers)))


def model(rom, m, props=SM.PROPS, group=None, exclude_map=None, min_cells=200, rows=None, t=None, rows2=None):
    """The converter for map m of `rom` (a mod's map, read at its own properties table `props`):
    the vanilla tiers that share its look; the map group (or `group`) is the one whose atlases
    draw most of `rows` (the room's BG1, when given), else the one most of the closest tier's
    cells come from. A look no vanilla room the PR drew has (a mod's own graphics) is drawn from
    the nearest SNES pictures, in the group whose pictures are nearest (`group_by_pictures`; needs
    `rows`, and `rows2` = its BG2)."""
    v = vanilla()
    g = graphics(rom, m, props)
    tier_tiles = [(key, v.tiles(key)) for key in tiers(g) if v.by_key.get(key)]
    exclude = None
    if exclude_map is not None:
        exclude = {key: v.own(exclude_map, key) for key, _ in tier_tiles}
        exclude[None] = v.own(exclude_map)
    if group is None:
        for key, tt in tier_tiles:   # not `t`: that's the Tables argument, used below
            counts = tt.groups.copy()
            if exclude is not None:
                counts.subtract(exclude[key].groups)
            counts = +counts
            if sum(counts.values()) >= min_cells:
                group = counts.most_common(1)[0][0]
                break
        else:
            group = next((t.groups.most_common(1)[0][0] for _, t in tier_tiles if t.groups), None)
    lk = look(g)
    try:
        formation = SM.tileset(rom, lk["ts1"])
    except (IndexError, ValueError):
        formation = None
    try:
        lk_obj = look_of(rom, m, t or (SM.US if props == SM.PROPS else SM.Tables(props=props)))
    except (IndexError, ValueError):
        lk_obj = None
    if not tier_tiles and group is None and rows is not None and lk_obj is not None:
        group = group_by_pictures(lk_obj, rows, rows2, v.every())
    mdl = Model(tier_tiles, v.every(), group, exclude, formation, lk_obj)
    if rows is not None and tier_tiles:
        cands = []
        for _, tt in tier_tiles:
            cands += [gr for gr, _ in tt.groups.most_common() if gr not in cands]
        best = max(cands, key=lambda gr: (mdl.coverage(rows, gr), -cands.index(gr)), default=None)
        if best and best != mdl.group:
            mdl = Model(tier_tiles, v.every(), best, exclude, formation, lk_obj)
    return mdl


def group_by_pictures(lk, rows, rows2, every, k=12):
    """The map group whose vanilla cells look most like a room's: each of the room's distinct cell
    pictures votes (all alike: a floor counts as much as the void around it) for the atlases of its
    k nearest vanilla pictures (by coarse colours), nearer ones more."""
    cells = collections.Counter((rows[y][x], rows2[y][x] if rows2 and y < len(rows2) and x < len(rows2[0]) else None)
                                for y in range(len(rows)) for x in range(len(rows[0])))
    pics = [(sig, key) for key, sig in every.signatures.items()]
    groups_of = {}
    votes = collections.Counter()
    for (a, b), n in cells.most_common(64):
        sig = lk.signature(a, b)
        near = sorted(pics, key=lambda p: sum((x - y) * (x - y) for x, y in zip(sig, p[0])))[:k]
        for rank, (_, key) in enumerate(near):
            if key not in groups_of:
                groups_of[key] = {r[0] for st in every.vis[key] for r in st if r}
            for atlas in groups_of[key]:
                votes[atlas] += k - rank
    if not votes:
        return None
    # the atlas most voted for, and the group that has it
    for atlas, _ in votes.most_common():
        for gr in sorted(every.groups):
            if atlas in group_textures(gr):
                return gr
    return None


def evaluate(maps=None, border=1):
    """Held-out accuracy: each vanilla SNES map with PR pairs, converted by a model that leaves its
    own rooms out, against the PR's drawing of it (its first PR map; cells the PR shows: walkable
    and `border` around). Returns ({map: [cells, collision right, stack right, bottom+ground right,
    no tile, tier counts]}, totals)."""
    v = vanilla()
    out = {}
    for m in sorted(maps or v.pairs):
        if not v.pairs.get(m):
            continue
        _, pr, dx, dy = v.pairs[m][0]
        mdl = model(v.us, m, exclude_map=m, group=group_of(pr))   # redrawn in the room's own atlases
        if not mdl.cells:
            continue
        bg1, bg2, tp = SM.layout(v.us, m, 0), SM.layout(v.us, m, 1), tile_props(v.us, m)
        if bg1 is None:
            continue
        cells, _ = _cells(pr)
        wk = SM.pr_walkable(pr)
        r = [0, 0, 0, 0, 0, collections.Counter(), 0]
        # the stacks the room itself draws each SNES tile with (the PR scatters variants of a wall
        # or floor): a prediction among them looks right even when it isn't the variant at that cell
        variants = collections.defaultdict(set)
        for (x, y) in active(cells, border):
            sx, sy = x - dx, y - dy
            if 0 <= sy < len(bg1) and 0 <= sx < len(bg1[0]):
                variants[(bg1[sy][sx], bg2[sy][sx] if bg2 and sy < len(bg2) and sx < len(bg2[0]) else None)].add(
                    cells[y][x][0])
        for (x, y) in active(cells, border):
            refs, coll = cells[y][x]
            sx, sy = x - dx, y - dy
            if not (0 <= sy < len(bg1) and 0 <= sx < len(bg1[0])) or not any(refs):
                continue
            a = bg1[sy][sx]
            b = bg2[sy][sx] if bg2 and sy < len(bg2) and sx < len(bg2[0]) else None
            pred, how = mdl.stack(a, b, _around(bg1, sx, sy), _shape(bg1, tp, sx, sy))
            c = mdl.collision(a, b, tp[a])
            r[0] += 1
            if coll != 0 and cut(bg1, tp, wk, sx, sy, dx, dy):
                r[5]["cut"] += 1
                r[1] += 1          # blocked only where the PR's room ends: not a collision question
            else:
                r[1] += (c == 0) == (coll == 0)
            r[2] += pred == refs
            r[3] += pred is not None and pred[:2] == refs[:2]
            r[4] += pred is None
            r[5][how] += 1
            r[6] += pred is not None and pred in variants[(a, b)]
        if r[0]:
            out[m] = r
    tot = [sum(v[i] for v in out.values()) for i in range(5)]
    tot.append(sum((v[5] for v in out.values()), collections.Counter()))
    tot.append(sum(v[6] for v in out.values()))
    return out, tot


# --- writing ---------------------------------------------------------------------------------------
def _tileset_entry(name):
    """The PR's tilemap "tilesets" entry of atlas `name`. pr_cells fills the table as it reads PR maps, but
    with the learned Tiles read from disk (Vanilla._load) no PR map may have been read: then the PR's tilemaps
    are read for their entries until `name` turns up."""
    if name not in _tileset_entries:
        for path in SM.pr_tilemaps().values():
            with open(path, encoding="utf-8") as f:
                for ts in json.load(f).get("tilesets", []):
                    _tileset_entries.setdefault(ts["name"], ts)
            if name in _tileset_entries:
                break
    return _tileset_entries[name]


def room_tilesets(room):
    """The tilemap "tilesets" for a room's atlases (the PR's own entries, firstgids renumbered)
    and its layers as gids."""
    out, first, gid_of = [], 1, {}
    for name in room.atlases():
        e = copy.deepcopy(_tileset_entry(name))
        e["firstgid"] = first
        gid_of[name] = first
        first += e["tilecount"]
        out.append(e)
    layers = {n: [[(gid_of[r[0]] + (r[1] & ~FLIPS)) | (r[1] & FLIPS) if r else 0 for r in row] for row in rows]
              for n, rows in room.layers.items()}
    return out, layers


def _tilelayer(src, rows):
    out = copy.deepcopy(src)
    out["data"] = [v for r in rows for v in r]
    out["width"], out["height"] = len(rows[0]), len(rows)
    return out


def object_layer(map_dir):
    """The entity layer a PR map keeps its doors and arrivals on (GroundObject, UpperObject or
    BottomObject: the level its rooms are walked on), else the one matching its collision layer."""
    counts = collections.Counter()
    path = os.path.join(map_dir, "entity_default.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)

        def walk(ls):
            for lay in ls:
                if lay.get("type") == "objectgroup":
                    for o in lay.get("objects") or []:
                        if o.get("name") in ("GotoMap", "PointIn"):
                            counts[lay.get("name")] += 1
                walk(lay.get("layers", []))
        walk(d.get("layers", []))
    if counts:
        return counts.most_common(1)[0][0]
    cpath = os.path.join(map_dir, "collision.json")
    if os.path.exists(cpath):
        with open(cpath, encoding="utf-8") as f:
            c = json.load(f)
        names = []

        def walk2(ls):
            for lay in ls:
                if lay.get("type") == "tilelayer":
                    names.append(lay["name"])
                walk2(lay.get("layers", []))
        walk2(c.get("layers", []))
        for n in names:
            if n.endswith("Collision"):
                return n.replace("Collision", "Object")
    return "GroundObject"


def put_objects(ent, layer_name, objects):
    """Append Tiled objects (already built) to the entity file's layer `layer_name`, making the layer
    (like the file's other object layers) when it has none."""
    found = []

    def walk(ls, parent):
        for lay in ls:
            if lay.get("type") == "objectgroup":
                if lay.get("name") == layer_name:
                    found.append(lay)
                elif not found and parent is not None:
                    found_parent.append(parent)
            walk(lay.get("layers", []), lay)
    found_parent = []
    walk(ent.get("layers", []), None)
    if found:
        found[0]["objects"] = (found[0].get("objects") or []) + objects
        return
    proto = None

    def first(ls, parent):
        nonlocal proto
        for lay in ls:
            if lay.get("type") == "objectgroup" and proto is None:
                proto = (lay, parent)
            first(lay.get("layers", []), lay)
    first(ent.get("layers", []), ent)
    if proto is None:
        ent.setdefault("layers", []).append({"draworder": "topdown", "id": 900, "name": layer_name, "objects": objects,
                                             "opacity": 1, "type": "objectgroup", "visible": True, "x": 0, "y": 0})
        return
    lay, parent = proto
    new = {k: v for k, v in lay.items() if k not in ("objects", "id", "name")}
    new.update({"id": 900 + len(parent.get("layers", [])), "name": layer_name, "objects": objects})
    parent["layers"].append(new)


def _objects(objects, first_id=1):
    out = []
    for i, o in enumerate(objects):
        obj = {"height": 16, "id": first_id + i, "name": o["name"], "rotation": 0, "type": "", "visible": True,
               "width": 16, "x": 16 * o["x"], "y": 16 * (o["y"] + (1 if "gid" in o else 0)),
               "properties": [{"name": k, "type": "string" if isinstance(v, str) else "bool" if isinstance(v, bool)
                               else "int", "value": v} for k, v in sorted(o["properties"].items())]}
        if "gid" in o:
            obj["gid"] = o["gid"]
        out.append(obj)
    return out


def _map_script(src, like, name):
    """An empty map script (`like`'s format): the map script runs when the map loads; `like`'s sets
    its story flags and entity layers, a new map's caller adds its own."""
    import glob
    path = os.path.join(src, f"sc_map_{like[4:].lower()}.json")
    if not os.path.exists(path):    # a map without a map script: any map script is the format
        path = (glob.glob(os.path.join(os.path.dirname(src), "*", "sc_map_*.json")) or
                glob.glob(os.path.join(P.VANILLA, "map_*", *RES.split("/"), "*", "*", "sc_map_*.json")))[0]
    with open(path, encoding="utf-8") as f:
        sc = json.load(f)
    keep = [x for x in sc["Mnemonics"] if x["mnemonic"] in ("Nop", "Exit")]
    sc["Mnemonics"] = [keep[0], keep[-1]] if len(keep) >= 2 else keep
    sc["Mnemonics"][0]["label"] = "Main"
    sc["Segments"] = [{"Label": "Main", "EntryPoint": 0, "Count": len(sc["Mnemonics"])}]
    sc["ScriptLocal"], sc["ScriptLocalValue"] = [], []
    sc["Name"] = f"sc_{name}"
    return sc


def _register(out, group, name, map_id, script_id, like, sc, map_row):
    """A new map's package.json entry, keys and master rows."""
    sc_name = f"sc_map_{name[4:].lower()}"
    folder_name = name.rsplit("_", 1)[0]
    dest = os.path.join(out, group, *RES.split("/"), folder_name, name)
    with open(os.path.join(dest, sc_name + ".json"), "w", encoding="utf-8") as f:
        json.dump(sc, f, ensure_ascii=False)
    pkg_out = os.path.join(out, group, *RES.split("/"), folder_name, "package.json")
    pkg_src = pkg_out if os.path.exists(pkg_out) else os.path.join(P.VANILLA, group, *RES.split("/"), folder_name,
                                                                    "package.json")
    with open(pkg_src, encoding="utf-8") as f:
        pkg = json.load(f)
    pkg["map"] = [e for e in pkg["map"] if e["name"] != name] + [{
        "name": name, "tilemap": f"{name}/tilemap", "collision": f"{name}/collision",
        "entity_default": f"{name}/entity_default", "entity": [],
        "script": [{"name": sc_name, "asset": f"{name}/{sc_name}"}], "route_instruction": []}]
    with open(pkg_out, "w", encoding="utf-8") as f:
        json.dump(pkg, f, ensure_ascii=False)
    folder = f"{RES}/{folder_name}"
    assets = [(f"{name}/tilemap", f"{folder}/{name}/tilemap"), (f"{name}/collision", f"{folder}/{name}/collision"),
              (f"{name}/entity_default", f"{folder}/{name}/entity_default"),
              (f"{name}/{sc_name}", f"{folder}/{name}/{sc_name}"), ("package", f"{folder}/package")]
    add_keys(out, group, "new_maps", assets)
    maps = P.Table("map")
    row = dict(maps[int(next(r["id"] for r in maps if r["map_name"] == like))])
    row.update({"id": str(map_id), "map_name": name, "script_id": str(script_id)})
    row.update({k: str(v) for k, v in (map_row or {}).items()})
    add_rows(out, "map", [row])
    add_rows(out, "map_script", [{"id": str(script_id), "script_name": sc_name}])
    return assets


def write_map(out, group, name, map_id, script_id, like, room, objects, tilesets=None, map_row=None):
    """A new map `name` (Map_<group number>_<n>) in `group`, made like the PR map `like` (its layer
    setup, map script, map.csv row): files under out/<group>/, its package.json entry, keys, and the
    map.csv / map_script.csv rows under out/master/. `room`: a converted Room (refs: its tilesets
    are made from the atlases it uses) or one with gid layers and `tilesets`. `objects`: Tiled
    objects (in tile units: dicts with name, x, y, gid, properties) for the entity layer `like`
    keeps its doors on (`object_layer`).
    Returns the assets written."""
    src = os.path.dirname(SM.pr_tilemaps()[like])
    with open(os.path.join(src, "tilemap.json"), encoding="utf-8") as f:
        tm = json.load(f)
    tm["width"], tm["height"] = room.width, room.height
    layers = room.layers
    if any(r for rows in room.layers.values() for row in rows for r in row if isinstance(r, tuple)):
        tilesets, layers = room_tilesets(room)
    if tilesets:
        tm["tilesets"] = tilesets

    def redo(ls):
        for lay in ls:
            if lay.get("type") == "tilelayer":
                lay.update(_tilelayer(lay, layers.get(lay["name"]) or [[0] * room.width for _ in range(room.height)]))
            redo(lay.get("layers", []))
    redo(tm["layers"])
    # every layer the room draws, even where `like` has none (a cave without a CeilLayer...)
    have = set()

    def names(ls):
        for lay in ls:
            if lay.get("type") == "tilelayer":
                have.add(lay["name"])
            names(lay.get("layers", []))
    names(tm["layers"])
    group_layer = next((lay for lay in tm["layers"] if lay.get("type") == "group" and lay.get("layers")), None)
    for n in LAYERS:
        if n not in have and any(any(r) for r in layers.get(n, [])) and group_layer:
            proto = next(lay for lay in group_layer["layers"] if lay.get("type") == "tilelayer")
            new = _tilelayer(proto, layers[n])
            new["name"], new["id"] = n, tm.get("nextlayerid", 100)
            tm["nextlayerid"] = new["id"] + 1
            group_layer["layers"].append(new)
            group_layer["layers"].sort(key=lambda lay: LAYERS.index(lay["name"]) if lay["name"] in LAYERS else 9)
    with open(os.path.join(src, "collision.json"), encoding="utf-8") as f:
        coll = json.load(f)

    def redo_coll(ls):
        for lay in ls:
            if lay.get("type") == "tilelayer":
                lay.update(_tilelayer(lay, room.collision))
            redo_coll(lay.get("layers", []))
    redo_coll(coll["layers"])
    with open(os.path.join(src, "entity_default.json"), encoding="utf-8") as f:
        ent = json.load(f)
    ent["width"], ent["height"] = room.width, room.height

    def redo_ent(ls):
        for lay in ls:
            if lay.get("type") == "objectgroup":
                lay["objects"] = []
            redo_ent(lay.get("layers", []))
    redo_ent(ent["layers"])
    put_objects(ent, object_layer(src), _objects(objects))
    dest = os.path.join(out, group, *RES.split("/"), name.rsplit("_", 1)[0], name)
    os.makedirs(dest, exist_ok=True)
    for fname, doc in (("tilemap.json", tm), ("collision.json", coll), ("entity_default.json", ent)):
        with open(os.path.join(dest, fname), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
    return _register(out, group, name, map_id, script_id, like, _map_script(src, like, name), map_row)


# the PR objects a copy of a map keeps: its geometry and decoration (z-level changes, animated
# tiles, door-opening triggers, minimap marks, fires...), not its doors, arrivals, chests, people or
# events (a copy gets the mod's own)
DROP_PROPS = ("map_id", "point_id", "content_id", "message_key", "product_group_id", "title_id", "goto_entity_id")
DROP_NAMES = ("GotoMap", "PointIn", "EventGotoMap", "SavePoint", "savepoint", "TelepoPoint")


def keep_object(o):
    p = {x["name"]: x["value"] for x in o.get("properties", [])}
    if o.get("name") in DROP_NAMES or any(k in p for k in DROP_PROPS):
        return False
    if p.get("script_id"):      # runs an event of the original map
        return False
    return True


def clone_map(out, src_pr, name, map_id, script_id, objects, map_row=None, patch=None, keep=keep_object):
    """A copy of the vanilla PR map `src_pr` as a new map `name` in the same group: its tiles and
    collision as the PR drew them (`patch`: {(x, y): (refs stack, collision)} cells to redraw), the
    objects `keep` accepts, plus `objects` (tile units, as write_map) on its GroundObject layer.
    Returns the assets written."""
    group = group_of(src_pr)
    src = os.path.dirname(SM.pr_tilemaps()[src_pr])
    with open(os.path.join(src, "tilemap.json"), encoding="utf-8") as f:
        tm = json.load(f)
    with open(os.path.join(src, "collision.json"), encoding="utf-8") as f:
        coll = json.load(f)
    if patch:
        first = {ts["name"]: ts["firstgid"] for ts in tm["tilesets"]}
        W = tm["width"]

        def put(ls):
            for lay in ls:
                if lay.get("type") == "tilelayer" and lay["name"] in LAYERS:
                    i = LAYERS.index(lay["name"])
                    for (x, y), (refs, _) in patch.items():
                        r = refs[i]
                        if r and r[0] not in first:
                            continue
                        lay["data"][y * W + x] = ((first[r[0]] + (r[1] & ~FLIPS)) | (r[1] & FLIPS)) if r else 0
                put(lay.get("layers", []))
        put(tm["layers"])

        def put_coll(ls):
            for lay in ls:
                if lay.get("type") == "tilelayer":
                    for (x, y), (_, c) in patch.items():
                        lay["data"][y * lay["width"] + x] = c
                put_coll(lay.get("layers", []))
        put_coll(coll["layers"])
    with open(os.path.join(src, "entity_default.json"), encoding="utf-8") as f:
        ent = json.load(f)
    ids = []

    def all_ids(ls):
        for lay in ls:
            ids.extend(o["id"] for o in lay.get("objects") or [])
            all_ids(lay.get("layers", []))
    all_ids(ent["layers"])
    next_id = [1 + max(ids or [0])]

    def redo_ent(ls):
        for lay in ls:
            if lay.get("type") == "objectgroup":
                lay["objects"] = [o for o in lay.get("objects") or [] if keep(o)]
            redo_ent(lay.get("layers", []))
    redo_ent(ent["layers"])
    put_objects(ent, object_layer(src), _objects(objects, next_id[0]))
    dest = os.path.join(out, group, *RES.split("/"), name.rsplit("_", 1)[0], name)
    os.makedirs(dest, exist_ok=True)
    for fname, doc in (("tilemap.json", tm), ("collision.json", coll), ("entity_default.json", ent)):
        with open(os.path.join(dest, fname), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
    return _register(out, group, name, map_id, script_id, src_pr, _map_script(src, src_pr, name), map_row)


def add_keys(out, group, keys_name, assets):
    """Name assets in out/<group>/keys/<keys_name>.json (Magicite: key -> address), merged."""
    path = os.path.join(out, group, "keys", keys_name + ".json")
    doc = {"keys": [], "values": []}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    for k, v in assets:
        if k not in doc["keys"]:
            doc["keys"].append(k)
            doc["values"].append(v)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)


def add_rows(out, table, rows):
    """New rows for a master table in out/master/ (header + rows; merged with rows written before)."""
    t = P.Table(table)
    cols = list(next(iter(t.rows.values())).keys())
    path = os.path.join(out, "master", *MASTER.split("/"), table + ".csv")
    have = {}
    if os.path.exists(path):
        import csv
        with open(path, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                have[r["id"]] = r
    for r in rows:
        have[r["id"]] = {c: r.get(c, "0") for c in cols}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(",".join(cols) + "\n")
        for r in sorted(have.values(), key=lambda r: int(r["id"])):
            f.write(",".join(str(r[c]) for c in cols) + "\n")
    add_keys(out, "master", "new_rows", [(table, f"{MASTER}/{table}")])


# --- pictures --------------------------------------------------------------------------------------
GAME = os.environ.get("FF6_PR_DIR") or r"D:/SteamLibrary/steamapps/common/FINAL FANTASY VI PR"
_atlas = {}


def atlas(name, game=GAME):
    """An atlas texture (w, h, rgba) from the game's map bundles (read only)."""
    if name not in _atlas:
        import glob
        import pr_images
        groups = [os.path.relpath(p, P.VANILLA).replace("\\", "/").split("/")[0]
                  for p in glob.glob(os.path.join(P.VANILLA, "map_*", *RES.split("/"), "*", "package.json"))
                  if f'"{name}"' in open(p, encoding="utf-8").read()]
        for g in groups:
            try:
                tex = pr_images.textures(pr_images.bundle_for(game, g))
            except FileNotFoundError:
                continue
            for k, v in tex.items():
                _atlas.setdefault(k, v)
            if name in _atlas:
                break
    return _atlas.get(name)


def render(cells, path, coll=None, scale=1, tint=False, box=None):
    """A PNG of map cells: `cells` rows of ref stacks (or a Room, or a PR map name), drawn Bottom to
    Ceil; with `tint`, blocked cells (`coll` rows) tinted red; `box` (x0, y0, x1, y1): only those
    cells. Needs numpy (any Python that has it)."""
    import numpy as np
    import pr_images
    if isinstance(cells, str):
        rows, _ = pr_cells(cells)
        cells, coll = [[r[0] for r in row] for row in rows], [[r[1] for r in row] for row in rows]
    elif isinstance(cells, Room):
        coll = coll or cells.collision
        cells = [[tuple(cells.layers[n][y][x] for n in LAYERS) for x in range(cells.width)] for y in range(cells.height)]
    if box:
        x0, y0, x1, y1 = box
        cells = [row[x0:x1] for row in cells[y0:y1]]
        coll = [row[x0:x1] for row in coll[y0:y1]] if coll else None
    h, w = len(cells), len(cells[0])
    img = np.zeros((h * 16, w * 16, 4), dtype=np.float32)
    img[..., 3] = 255
    tiles = {}

    def tile(ref):
        if ref not in tiles:
            a = atlas(ref[0])
            if a is None:
                tiles[ref] = None
            else:
                aw, ah, rgba = a
                arr = np.frombuffer(rgba, dtype=np.uint8).reshape(ah, aw, 4)[::-1]   # Tiled counts tiles from the top
                n = ref[1] & ~FLIPS
                cols = aw // 16
                t = arr[(n // cols) * 16:(n // cols) * 16 + 16, (n % cols) * 16:(n % cols) * 16 + 16].astype(np.float32)
                if ref[1] & 0x80000000:
                    t = t[:, ::-1]
                if ref[1] & 0x40000000:
                    t = t[::-1]
                tiles[ref] = t
        return tiles[ref]
    for y in range(h):
        for x in range(w):
            for ref in cells[y][x]:
                if not ref:
                    continue
                t = tile(ref)
                if t is None:
                    continue
                al = t[..., 3:4] / 255
                dst = img[y * 16:y * 16 + 16, x * 16:x * 16 + 16]
                dst[..., :3] = dst[..., :3] * (1 - al) + t[..., :3] * al
            if tint and coll and coll[y][x] != 0:
                dst = img[y * 16:y * 16 + 16, x * 16:x * 16 + 16]
                dst[..., 0] = dst[..., 0] * 0.6 + 255 * 0.4
    out = img.clip(0, 255).astype(np.uint8)
    if scale != 1:
        out = out[::int(1 / scale), ::int(1 / scale)] if scale < 1 else out.repeat(scale, 0).repeat(scale, 1)
    with open(path, "wb") as f:
        f.write(pr_images.png(out.shape[1], out.shape[0], out.tobytes()))
    return path


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "eval":
        per, tot = evaluate()
        n, cr, sr, gr, unk, how, var = tot
        got = n - unk
        print(f"{len(per)} held-out SNES maps, {n} cells (walkable and 1 around): collision {cr / n:.1%}; "
              f"a PR tile for {got / n:.1%}, of those: exact stack {sr / got:.1%}, one the room itself uses for "
              f"that SNES tile {var / got:.1%}, bottom+ground {gr / got:.1%}; rule used "
              f"(tier*3 + 0 neighbourhood / 1 pair / 2 BG1; 50+: an alike tile's): {dict(sorted(how.items(), key=str))}")
        worst = sorted(per.items(), key=lambda kv: kv[1][1] / kv[1][0])[:10]
        print("lowest collision:", ", ".join(f"{m} {r[1] / r[0]:.0%} of {r[0]}" for m, r in worst))
    else:
        sys.exit(__doc__)


# --- the SNES side's picture ------------------------------------------------------------------------
def snes_picture(rom, m, path, bg1=None, bg2=None, t=None, box=None, scale=1):
    """A PNG of SNES map m as the SNES draws it (BG2 under BG1, no sprites, no animation) straight
    from the ROM: its four graphics sets in VRAM as the field code loads them (C0/2690: set 0 at
    chars 0-255, 1 at 256-383, 2 at 384-511, 3 at 512-767; data DF/DB00 + the 3-byte pointers at
    `gfx_ptrs`), the tilesets' 16x16 formations (DF/BA00), the map palette (props byte 25, 256 bytes
    at `palettes`). `bg1`/`bg2`: rows to draw instead of the map's layouts (an entrance event's
    tiles applied). Needs numpy. For checking a conversion against the original."""
    import numpy as np
    import pr_images
    t = t or SM.US
    p = SM.properties(rom, m, t.props)
    lk = look(graphics(rom, m, t.props))
    vram = bytearray(0x6000)
    for k, (at, size) in enumerate(((0, 0x2000), (0x2000, 0x1000), (0x3000, 0x1000), (0x4000, 0x2000))):
        ptr = int.from_bytes(rom[t.gfx_ptrs + 3 * lk["sets"][k]:t.gfx_ptrs + 3 * lk["sets"][k] + 3], "little")
        src = SM._file_offset(((0xDFDB00 + ptr) >> 16 & 0xFF) << 16 | (0xDFDB00 + ptr) & 0xFFFF)
        vram[at:at + size] = rom[src:src + size].ljust(size, b"\0")
    pal_raw = rom[t.palettes + 256 * p["palette"]:t.palettes + 256 * p["palette"] + 256]
    pal = np.zeros((128, 4), dtype=np.uint8)
    for i in range(128):
        c = pal_raw[2 * i] | pal_raw[2 * i + 1] << 8
        pal[i] = ((c & 31) << 3, (c >> 5 & 31) << 3, (c >> 10 & 31) << 3, 0 if i % 16 == 0 else 255)
    chars = {}

    def char(n):
        if n not in chars:
            b = vram[32 * n:32 * n + 32] if 32 * n + 32 <= len(vram) else bytes(32)
            px = np.zeros((8, 8), dtype=np.uint8)
            for y in range(8):
                p0, p1, p2, p3 = b[2 * y], b[2 * y + 1], b[16 + 2 * y], b[16 + 2 * y + 1]
                for x in range(8):
                    s = 7 - x
                    px[y, x] = (p0 >> s & 1) | (p1 >> s & 1) << 1 | (p2 >> s & 1) << 2 | (p3 >> s & 1) << 3
            chars[n] = px
        return chars[n]
    layers = []
    for rows, ts in ((bg2 if bg2 is not None else SM.layout(rom, m, 1, t=t), lk["ts2"]),
                     (bg1 if bg1 is not None else SM.layout(rom, m, 0, t=t), lk["ts1"])):
        if rows:
            layers.append((rows, SM.tileset(rom, ts)))
    if not layers:
        return None
    rows0 = layers[-1][0]
    if box:
        x0, y0, x1, y1 = box
    else:
        x0, y0, x1, y1 = 0, 0, len(rows0[0]), len(rows0)
    img = np.zeros(((y1 - y0) * 16, (x1 - x0) * 16, 4), dtype=np.uint8)
    img[..., 3] = 255
    for rows, form in layers:
        for y in range(y0, min(y1, len(rows))):
            for x in range(x0, min(x1, len(rows[0]))):
                f = form[rows[y][x]]
                for q in range(4):
                    w = f[q] | f[q + 4] << 8
                    px = char(w & 0x3FF)
                    if w & 0x4000:
                        px = px[:, ::-1]
                    if w & 0x8000:
                        px = px[::-1]
                    rgba = pal[(w >> 10 & 7) * 16 + px]
                    oy, ox = (y - y0) * 16 + 8 * (q // 2), (x - x0) * 16 + 8 * (q % 2)
                    dst = img[oy:oy + 8, ox:ox + 8]
                    mask = rgba[..., 3] > 0
                    dst[mask] = rgba[mask]
    if scale != 1:
        img = img.repeat(scale, 0).repeat(scale, 1)
    with open(path, "wb") as fh:
        fh.write(pr_images.png(img.shape[1], img.shape[0], img.tobytes()))
    return path
