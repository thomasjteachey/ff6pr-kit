"""SNES FF6 maps -> Pixel Remaster maps, with each map's tile offset: one table for every tool.

The PR remade each SNES map (0-415) as one or more Tiled maps (vanilla/map_*/.../Map_<group>_<n>/
tilemap.json, 16 px tiles like the SNES's), often padded or trimmed by a few tiles. Anything placed
by SNES coordinates (chests, NPCs, exits, event tiles, a mod's new merchant or room) needs the PR
map and the offset: PR (x, y) = SNES (x + dx, y + dy). Before this table each port worked that out
for itself (port_chests' per-map offsets from paired chests, wc_npcs' pairs, map names in
wc_events' comments, profile_bnw's "laid out 3 tiles lower").

How it's built (`build`, needs numpy; any Python that has it): each SNES map's BG1 layout (map
properties at ED/8F00: layout = bytes 13-16 & 0x3FF, size = byte 23; LZSS layouts through the
pointers at D9/CD90) against every PR map of a compatible size, at every offset that keeps them
overlapping: the score is the mutual information between the SNES tile in each cell and the PR's
tile stack there (Bottom/Ground/Upper layers), in bits. The same map at the right offset explains
nearly all of the SNES layout (`share` ~0.9: Doma Castle 126 -> Map_20451_2 at (0, +3)); any other
pairing explains little. SNES maps that share one layout (World of Balance / Ruin versions of a
town) match several PR maps equally: all are kept, best first.

    python tools/snes_maps.py build              (writes data/snes_pr_maps.json from the US ROM)
    python tools/snes_maps.py show 126           (a SNES map's PR maps)
    python tools/snes_maps.py pr Map_20451_2     (a PR map's SNES maps)

In code (no numpy needed):

    import snes_maps
    snes_maps.pr_maps(126)        # [Match(pr='Map_20451_2', pr_id=..., dx=0, dy=3, share=0.91, ...), ...]
    snes_maps.to_pr(126, 55, 9)   # ('Map_20451_2', 55, 12): the best PR map
    snes_maps.snes_maps('Map_20451_2')

The same decoder reads a mod's own maps (`layout(rom, m)`, `properties(rom, m)`) when the mod keeps
the US tables (a Japanese-ROM mod after tools/jp_layout.py, or with its own table offsets).
"""
import json
import os
import sys
from collections import namedtuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import kitpath  # noqa: E402,F401  (the modding kit's tools, when it's this repository's kit/ submodule)
except ImportError:   # the kit repository alone has none (its tools are already on the path)
    pass
import prdata as P  # noqa: E402

MAPS = 416
PROPS = 0x2D8F00          # ED/8F00: 33 bytes per map
LAYOUT_PTRS = 0x19CD90    # D9/CD90: 3-byte offsets into LAYOUT_DATA
LAYOUT_DATA = 0x19D1B0    # D9/D1B0: LZSS layouts
DATA_FILE = os.path.join(HERE, "..", "data", "snes_pr_maps.json")
OVERRIDES_FILE = os.path.join(HERE, "..", "data", "snes_pr_maps_overrides.json")
SIZES = (16, 32, 64, 128)

Match = namedtuple("Match", "pr pr_id dx dy how share share_pr coverage bits entities size walk world cross lookalike",
                   defaults=(None, None, False, False))


# --- SNES map data ------------------------------------------------------------------------------
def lzss(d):
    """FF6's LZSS: 2-byte size, then per 8 items a control byte (bit set = literal), a reference
    being 11 bits of a 2 KB window position (starting at 0x7DE) and 5 bits of length - 3."""
    n = d[0] | d[1] << 8
    win, wi, out, i = bytearray(0x800), 0x7DE, bytearray(), 2
    while i < n:
        c = d[i]
        i += 1
        for bit in range(8):
            if i >= n:
                break
            if c >> bit & 1:
                v = d[i]
                i += 1
                out.append(v)
                win[wi] = v
                wi = (wi + 1) & 0x7FF
            else:
                w = d[i] | d[i + 1] << 8
                i += 2
                for k in range((w >> 11) + 3):
                    v = win[((w & 0x7FF) + k) & 0x7FF]
                    out.append(v)
                    win[wi] = v
                    wi = (wi + 1) & 0x7FF
    return bytes(out)


def properties(rom, m, base=PROPS):
    """A map's properties (Beyond Chaos's locationrandomizer field names)."""
    p = rom[base + 33 * m:base + 33 * m + 33]
    mapdata = int.from_bytes(p[13:17], "little")
    return {"name": p[0], "tile_properties": p[4], "random_battles": bool(p[5] & 0x80),
            "graphic_sets": list(p[7:11]), "tilesets": p[11] << 8 | p[12],
            "layouts": [mapdata & 0x3FF, mapdata >> 10 & 0x3FF, mapdata >> 20 & 0x3FF],
            "bg1_size": (SIZES[p[23] >> 6 & 3], SIZES[p[23] >> 4 & 3]),
            "bg2_size": (SIZES[p[23] >> 2 & 3], SIZES[p[23] & 3]),
            "palette": p[25], "music": p[28], "raw": bytes(p)}


def layout(rom, m, layer=0, props=PROPS, ptrs=LAYOUT_PTRS, data=LAYOUT_DATA, t=None):
    """A map's layout as rows of tile numbers (BG1: layer 0, BG2: 1, BG3: 2), or None (no layout /
    undecodable). `t`: a Tables (a mod's own addresses), else the props/ptrs/data offsets."""
    if t is not None:
        props, ptrs = t.props, t.layout_ptrs
    pr = properties(rom, m, props)
    idx = pr["layouts"][layer]
    w, h = (pr["bg1_size"], pr["bg2_size"], pr["bg2_size"])[layer]
    if idx == 0:
        return None
    return layout_rows(rom, idx, w, h, ptrs, data if t is None else None, t)


def layout_rows(rom, idx, w, h, ptrs=LAYOUT_PTRS, data=LAYOUT_DATA, t=None):
    """Layout `idx` (the number in map properties) as h rows of w tiles, or None."""
    a = int.from_bytes(rom[ptrs + 3 * idx:ptrs + 3 * idx + 3], "little")
    if data is None:   # 24-bit SNES address = base + pointer (bank wraps), as the field code adds it
        snes = (t.layout_base if t else 0xD9D1B0) + a
        at = _file_offset(((snes >> 16) & 0xFF) << 16 | (snes & 0xFFFF))
    else:
        at = data + a
    raw = lzss(rom[at:at + 0x10000])
    if len(raw) < w * h:
        return None
    return [list(raw[r * w:(r + 1) * w]) for r in range(h)]


def _file_offset(snes):
    """HiROM / ExHiROM SNES address -> file offset (C0-FF: the first 4 MB; 40-7D: the 4-8 MB)."""
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


EXITS, LONG_EXITS = 0x1FBB00, 0x2DF480   # 2-byte offsets per map from the table's own start
NPCS, EVENTS, CHESTS = 0x041A10, 0x040000, (0x2D82F4, 0x2D8634)
EVENT_CODE = 0xCA0000   # NPC and event-tile event addresses are offsets from CA/0000


class Tables:
    """Where a ROM keeps its map tables (file offsets). The field code reads each per-map list as
    2-byte offsets at `*_ptrs` (map m's records run from offset m to offset m + 1), the records at
    `*_data` + offset. US v1.0 (and the Japanese ROM) by default; a mod that moved them (T-Edition:
    tools/ted_maps.py) gives its own. `maps`: map slots the tables cover (the last offset ends the
    data); `layout_base`: the SNES address a layout pointer is added to (24-bit, as C0/2892 does)."""

    def __init__(self, name="US", maps=416, props=PROPS, layout_ptrs=LAYOUT_PTRS, layout_base=0xD9D1B0,
                 exit_ptrs=EXITS, exit_data=EXITS, long_exit_ptrs=LONG_EXITS, long_exit_data=LONG_EXITS,
                 npc_ptrs=NPCS, npc_data=NPCS, event_ptrs=EVENTS, event_data=EVENTS,
                 chest_ptrs=CHESTS[0], chest_data=CHESTS[1], palettes=0x2DC480, gfx_ptrs=0x1FDA00,
                 offsets=None, chest_item_bank=None):
        self.name, self.maps, self.props = name, maps, props
        # how many offsets each list has (default maps + 1); the US chest list has 416 (maps 0-414)
        self.offsets = offsets or {}
        self.layout_ptrs, self.layout_base = layout_ptrs, layout_base
        self.exit_ptrs, self.exit_data = exit_ptrs, exit_data
        self.long_exit_ptrs, self.long_exit_data = long_exit_ptrs, long_exit_data
        self.npc_ptrs, self.npc_data = npc_ptrs, npc_data
        self.event_ptrs, self.event_data = event_ptrs, event_data
        self.chest_ptrs, self.chest_data = chest_ptrs, chest_data
        # a mod's chest flag for items past 255: (type bit, first item); T-Edition's 0x10 = item 256 + contents
        self.chest_item_bank = chest_item_bank
        self.palettes, self.gfx_ptrs = palettes, gfx_ptrs
        self._ranges = {}

    def ranges(self, rom, ptrs, n=None):
        """[(start, end)] offsets of each map's records in the list whose offsets are at `ptrs`.
        Offsets normally rise map by map; a mod that gave one map more records may put them after
        the table (T-Edition's map 130 exits): an offset off the rising run is such a map, its
        records running to the next offset above it, and the map before it ends at the next offset
        on the run (the longest non-decreasing run of the maps + 1 offsets)."""
        key = (id(rom), ptrs)
        if key in self._ranges:
            return self._ranges[key]
        n = n or self.offsets.get(ptrs, self.maps + 1)
        p = [rom[ptrs + 2 * i] | rom[ptrs + 2 * i + 1] << 8 for i in range(n)]
        on = _rising(p)
        out = []
        for m in range(n - 1):
            if m in on:
                end = next((p[k] for k in range(m + 1, len(p)) if k in on), p[m])
            else:
                end = min([q for q in p if q > p[m]] or [p[m]])
            out.append((p[m], max(end, p[m])))
        self._ranges[key] = out
        return out


def _rising(p):
    """The indices of a longest non-decreasing subsequence of p (patience sorting)."""
    import bisect
    tails, tail_i, prev = [], [], [-1] * len(p)
    for i, v in enumerate(p):
        k = bisect.bisect_right(tails, v)
        if k == len(tails):
            tails.append(v)
            tail_i.append(i)
        else:
            tails[k], tail_i[k] = v, i
        prev[i] = tail_i[k - 1] if k else -1
    out, i = set(), tail_i[-1] if tail_i else -1
    while i >= 0:
        out.add(i)
        i = prev[i]
    return out


US = Tables(offsets={CHESTS[0]: 416})


def _records(rom, m, ptrs, data, size, t):
    rs = t.ranges(rom, ptrs)
    if m >= len(rs):
        return []
    a, b = rs[m]
    return [bytes(rom[data + o:data + o + size]) for o in range(a, b - size + 1, size)]


def npcs(rom, m, t=US):
    """A map's NPCs (9-byte records; field names as Worlds Collide's data/npc.py): x, y, sprite,
    palette, movement, speed, direction, the event bit that shows it (event_byte * 8 + event_bit,
    $1EE0 bits) and its event (SNES address: CA/0000 + 18 bits)."""
    out = []
    for i, r in enumerate(_records(rom, m, t.npc_ptrs, t.npc_data, 9, t)):
        ev = r[0] | r[1] << 8 | (r[2] & 3) << 16
        out.append({"index": i, "x": r[4] & 0x7F, "y": r[5] & 0x3F, "event": EVENT_CODE + ev,
                    "palette": r[2] >> 2 & 7, "bg_scrolls": r[2] >> 5 & 1,
                    "show_bit": (r[3] >> 1) * 8 + (r[2] >> 6 | (r[3] & 1) << 2),
                    "no_face": r[4] >> 7, "speed": r[5] >> 6, "sprite": r[6], "movement": r[7] & 15,
                    "layer": r[7] >> 4 & 3, "vehicle": r[7] >> 6, "direction": r[8] & 3,
                    "const_sprite": r[8] >> 2 & 1, "bg_layer": r[8] >> 3 & 3, "split_sprite": r[8] >> 6 & 1,
                    "raw": r.hex()})
    return out


def event_tiles(rom, m, t=US):
    """A map's event tiles (5 bytes: x, y, 24-bit offset from CA/0000): stepping on one runs it."""
    return [{"index": i, "x": r[0], "y": r[1], "event": EVENT_CODE + (r[2] | r[3] << 8 | r[4] << 16)}
            for i, r in enumerate(_records(rom, m, t.event_ptrs, t.event_data, 5, t))]


def exits(rom, m, t=US):
    """A map's exits, short (6 bytes) then long (7 bytes: a row, or a column when bit 7 of byte 2
    is set, of byte 2 & 0x7F + 1 tiles): tiles, dest map (9 bits; 0x1FF = back to the parent map,
    0-2 world maps), dest x, y, and the flag bits beside the map number (facing, map title...)."""
    out = []
    for i, r in enumerate(_records(rom, m, t.exit_ptrs, t.exit_data, 6, t)):
        out.append({"kind": "short", "index": i, "tiles": [(r[0], r[1])], "dest": r[2] | (r[3] & 1) << 8,
                    "dest_x": r[4], "dest_y": r[5], "flags": r[3] >> 1})
    for i, r in enumerate(_records(rom, m, t.long_exit_ptrs, t.long_exit_data, 7, t)):
        n = (r[2] & 0x7F) + 1
        tiles = [(r[0], r[1] + k) for k in range(n)] if r[2] & 0x80 else [(r[0] + k, r[1]) for k in range(n)]
        out.append({"kind": "long", "index": i, "tiles": tiles, "dest": r[3] | (r[4] & 1) << 8,
                    "dest_x": r[5], "dest_y": r[6], "flags": r[4] >> 1})
    return out


CHEST_ITEM, CHEST_GIL, CHEST_EMPTY, CHEST_MONSTER = 0x40, 0x80, 0x08, 0x20


def chests(rom, m, t=US):
    """A map's chests (5 bytes: x, y, the event bit it clears (9 bits), type, contents): type
    "item" (contents = item id), "gil" (contents x 100), "monster" (contents = event pack),
    "empty"; ordered as the game keeps them."""
    out = []
    for i, r in enumerate(_records(rom, m, t.chest_ptrs, t.chest_data, 5, t)):
        kind = next((n for b, n in ((CHEST_ITEM, "item"), (CHEST_GIL, "gil"), (CHEST_MONSTER, "monster"),
                                    (CHEST_EMPTY, "empty")) if r[3] & b), "empty")
        contents, bank = r[4], getattr(t, "chest_item_bank", None)
        if bank and r[3] & bank[0] and not r[3] & (CHEST_GIL | CHEST_MONSTER):
            kind, contents = "item", bank[1] + r[4]
        out.append({"index": i, "x": r[0], "y": r[1], "bit": r[2] | (r[3] & 1) << 8, "type": kind,
                    "contents": contents, "raw": r.hex()})
    return out


def map_data(rom, m, t=US):
    """Everything placed on a map: properties, NPCs, event tiles, exits, chests."""
    return {"map": m, "properties": properties(rom, m, t.props), "npcs": npcs(rom, m, t),
            "events": event_tiles(rom, m, t), "exits": exits(rom, m, t), "chests": chests(rom, m, t)}


def snes_entities(rom, m, t=US):
    """A SNES map's placed things as (kind, x, y): exits (6-byte, and 7-byte long ones), NPCs
    (9-byte), event tiles (5-byte), chests (5-byte)."""
    out = [("exit" if e["kind"] == "short" else "long exit",) + e["tiles"][0] for e in exits(rom, m, t)]
    out += [("npc", n["x"], n["y"]) for n in npcs(rom, m, t)]
    out += [("event", e["x"], e["y"]) for e in event_tiles(rom, m, t)]
    out += [("chest", c["x"], c["y"]) for c in chests(rom, m, t)]
    return out


def snes_exits(rom, m, t=US):
    """A SNES map's exits: [(tiles the exit covers, dest map, dest x, dest y)]; long exits cover a
    row (bit 7 of byte 2 clear) or a column of byte 2 & 0x7F + 1 tiles."""
    return [(e["tiles"], e["dest"], e["dest_x"], e["dest_y"]) for e in exits(rom, m, t)]


TILE_PROPS_PTRS, TILE_PROPS_DATA = 0x19CD10, 0x19A800   # D9/CD10: offsets from D9/A800 (C0/1CD5), LZSS
WALL = 0xF7    # a tile properties low byte: impassable


def tile_props(rom, m, props=PROPS, ptrs=TILE_PROPS_PTRS, data=TILE_PROPS_DATA):
    """A map's SNES tile properties (map properties byte 4 picks the set; the field code unpacks it
    to 7E/7600): per BG1 tile (low, high) bytes, the 256 low bytes first (low 0xF7 = a wall; else
    z-level, bridge and stair bits, the high byte the directions it can be left by)."""
    idx = rom[props + 33 * m + 4]
    a = rom[ptrs + 2 * idx] | rom[ptrs + 2 * idx + 1] << 8
    try:
        raw = lzss(rom[data + a:data + a + 0x1000])
    except IndexError:          # an unused map's garbage index
        raw = b""
    raw = raw + bytes(512 - len(raw)) if len(raw) < 512 else raw
    return [(raw[i], raw[256 + i]) for i in range(256)]


# --- PR maps --------------------------------------------------------------------------------------
def pr_links(map_dir, detail=False):
    """A PR map's exits and arrival points: ([(x, y, dest PR map id, dest point id)], {point id: (x, y)}),
    from its default entities and its story-state layers (ev_*.json: doors a scene opens, the world
    map's moving Figaro Castle). An exit is any object with a map_id (the PR names many after the
    place: the world map's town entrances, "...からのGotoMap"), an arrival point a PointIn.
    `detail`: ([door dicts], {point id: point dict}) instead, each with what a tool needs to edit it in
    place: x, y, map_id, point_id (doors) / direction (points), the object's "id" and "name", its "layer"
    (the object group's name) and "file" (relative to the PR extract, P.VANILLA), objects in nested
    groups included; a door on several layers (the default and a story layer's copy) is listed per copy."""
    import glob
    if detail:
        return _pr_links_detail(map_dir)
    gotos, points = [], {}
    files = [os.path.join(map_dir, "entity_default.json")] + sorted(glob.glob(os.path.join(map_dir, "ev_*.json")))
    for path in files:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        for lay in d.get("layers", []):
            for o in lay.get("objects", []) or []:
                p = {x["name"]: x["value"] for x in o.get("properties", [])}
                x, y = int(o["x"] // 16), int(o["y"] // 16) - (1 if "gid" in o else 0)
                if p.get("map_id"):
                    g = (x, y, p["map_id"], p.get("point_id", 0))
                    if g not in gotos:
                        gotos.append(g)
                elif o.get("name") == "PointIn":
                    points.setdefault(p.get("object_id"), (x, y))
    return gotos, points


def _pr_objects_nested(doc):
    """[(object group name, object)] of an entity file, groups inside groups included."""
    out = []

    def walk(ls):
        for lay in ls:
            for o in lay.get("objects") or []:
                out.append((lay.get("name"), o))
            walk(lay.get("layers", []))
    walk(doc.get("layers", []))
    return out


def _pr_links_detail(map_dir):
    import glob
    doors, points = [], {}
    files = [os.path.join(map_dir, "entity_default.json")] + sorted(glob.glob(os.path.join(map_dir, "ev_*.json")))
    for path in files:
        if not os.path.exists(path):
            continue
        rel = os.path.relpath(path, P.VANILLA).replace(os.sep, "/")
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        for lay, o in _pr_objects_nested(doc):
            p = {x["name"]: x["value"] for x in o.get("properties", [])}
            x, y = int(o["x"] // 16), int(o["y"] // 16) - (1 if "gid" in o else 0)
            if p.get("map_id"):
                doors.append({"x": x, "y": y, "map_id": p["map_id"], "point_id": p.get("point_id", 0),
                              "id": o.get("id"), "name": o.get("name", ""), "layer": lay, "file": rel})
            elif o.get("name") == "PointIn" and p.get("object_id") is not None:
                points.setdefault(p["object_id"], {"x": x, "y": y, "direction": p.get("direction"), "id": o.get("id"),
                                                   "layer": lay, "file": rel})
    return doors, points


# --- rooms found by following doors (lifted from Beyond Chaos's entrance index, tools/bc_entrances.py) -----
DOOR_WALK_MIN = 0.8              # a room found by its doors: share of its walkable cells on SNES floor,
DOORS_MIN, DOORS_EXACT = 3, 0.3  # and its door tiles on the SNES map's exit tiles: 3+ and 30%+,
DOORS_SHARE = 0.6                # or 60%+ on or a tile from them (at least one on)
WORLD_SOURCES = {0: "WoB", 1: "WoR"}                        # the SNES world maps
PR_WORLD_SOURCES = {"Map_10010": "WoB", "Map_10020": "WoR"}  # the PR's
# SNES maps whose doors mislead the nearest-world-map rule: Figaro Castle's basement (0x3D-0x42) is reached
# from the castle in both worlds, but its only door path to a world map runs through the cave, which reads
# as World of Ruin; both worlds use it (BC lead, 2026-11-21)
SNES_WORLD_OVERRIDES = {m: {"WoB", "WoR"} for m in range(0x3D, 0x43)}
STRUCTURAL = ("manual", "chests", "exits", "door", "door-in")   # pairs found by more than tiles (lookalikes are judged against them)


class PrDoors:
    """Every vanilla PR map's doors and arrival points (pr_links(detail=True)) by map name: `doors`,
    `points`, `spots` (door tiles), `into` (doors leading to a map), `target(door)`, `graph()`."""

    def __init__(self):
        import collections
        self.ids = {r["map_name"]: int(r["id"]) for r in P.Table("map")}
        self.names = {v: k for k, v in self.ids.items()}
        self.dirs = pr_map_dirs()
        self.doors, self.points = {}, {}
        for name, d in sorted(self.dirs.items()):
            ds, ps = pr_links(d, detail=True)
            self.doors[name] = [dict(door, pr=name) for door in ds]
            self.points[name] = ps
        self.spots = {n: {(d["x"], d["y"]) for d in ds} for n, ds in self.doors.items()}
        self.into = collections.defaultdict(list)
        for ds in self.doors.values():
            for d in ds:
                if d["map_id"] in self.names:
                    self.into[self.names[d["map_id"]]].append(d)

    def target(self, door):
        """(PR map name, its PointIn dict or None) a door leads to."""
        name = self.names.get(door["map_id"])
        return name, (self.points.get(name, {}).get(door["point_id"]) if name else None)

    def graph(self):
        """{PR map: {PR maps its doors lead to or come from}}."""
        import collections
        g = collections.defaultdict(set)
        for name, ds in self.doors.items():
            for d in ds:
                t = self.names.get(d["map_id"])
                if t:
                    g[name].add(t)
                    g[t].add(name)
        return g


def grow_doors(rom, pairs, doors=None, rounds=6, log=None, unblock=()):
    """Rooms the other passes missed, found by following vanilla's doors both ways from known pairs
    (`pairs`: {SNES map: {PR map: (dx, dy)}}, left as it is): "door" = a door of a known room of map m on an
    SNES exit's tile leads into a PR map the exit's destination lacks (offset: its PointIn against the
    SNES landing spot, or a tile around it); "door-in" = a door into a known room's landing spot comes
    from a PR map the exit's own map lacks (offset: the door against the SNES exit tile). A found room
    must walk where the SNES walks (walk_agreement >= DOOR_WALK_MIN) and have its door tiles on the SNES
    map's exit tiles (DOORS_MIN and DOORS_EXACT of them, or DOORS_SHARE on or beside them). Returns
    [{snes, pr, dx, dy, how, walk, cells, doors_on_exits}]. Beyond Chaos's tools/bc_entrances.py Rooms.
    `unblock`: {(SNES map, PR map)} pairs that seed the search but may be found again by doors (lookalike
    rows: a door-found room replaces them)."""
    import collections
    doors = doors or PrDoors()
    of = collections.defaultdict(dict)
    for m, prs in pairs.items():
        for name, (dx, dy) in prs.items():
            if name in doors.dirs:
                of[m].setdefault(name, (dx, dy))
    exits_of = {m: [{"tiles": list(t), "dest": d, "dest_x": x, "dest_y": y} for t, d, x, y in snes_exits(rom, m)]
                for m in range(MAPS)}
    lay, tiles_of, found = {}, {}, []
    refound = set()

    def free(m, name):
        """PR map `name` not yet a room of SNES map m, or only as an unblocked (lookalike) row not yet re-found."""
        return name not in of[m] or ((m, name) in unblock and (m, name) not in refound)

    def walk(m, name, dx, dy):
        if m not in lay:
            rows = layout(rom, m)
            lay[m] = (rows, tile_props(rom, m) if rows else None)
        rows, props = lay[m]
        return walk_agreement(rom, m, name, dx, dy, rows, props) if rows else (None, 0)

    def evidence(m, name, dx, dy):
        if m not in tiles_of:
            on = {tuple(t) for e in exits_of.get(m, []) for t in e["tiles"]}
            tiles_of[m] = on, {(x + a, y + b) for x, y in on for a in (-1, 0, 1) for b in (-1, 0, 1)}
        on, near = tiles_of[m]
        spots = [(x - dx, y - dy) for x, y in doors.spots.get(name, ())]
        return sum(1 for t in spots if t in on), sum(1 for t in spots if t in near), len(spots)

    def enough(on, near, n):
        return bool(n) and ((on >= DOORS_MIN and on >= DOORS_EXACT * n) or (on and near >= DOORS_SHARE * n))

    def add(m, name, dx, dy, how, around=False):
        if m < 3 or m >= MAPS or name.startswith("Map_1") or name not in doors.dirs:
            return
        if not free(m, name):
            return
        best = None
        for ox, oy in ([(dx + a, dy + b) for a in (-1, 0, 1) for b in (-1, 0, 1)] if around else [(dx, dy)]):
            on, near, n = evidence(m, name, ox, oy)
            if not enough(on, near, n):
                continue
            share, cells = walk(m, name, ox, oy)
            if share is None or share < DOOR_WALK_MIN:
                continue
            key = (on / n, near / n, (ox, oy) == (dx, dy), share)
            if best is None or key > best[0]:
                best = (key, ox, oy, share, cells, f"{on}/{near}/{n}")
        if best:
            _, ox, oy, share, cells, ev = best
            of[m][name] = (ox, oy)
            refound.add((m, name))
            found.append({"snes": m, "pr": name, "dx": ox, "dy": oy, "how": how, "walk": round(share, 3),
                          "cells": cells, "doors_on_exits": ev})

    for _ in range(rounds):
        n0 = len(found)
        for m in range(MAPS):
            for e in exits_of.get(m, []):
                b, bx, by = e["dest"], e["dest_x"], e["dest_y"]
                if b >= MAPS or b < 2:
                    continue
                tiles = {tuple(t) for t in e["tiles"]}
                for name, (dx, dy) in list(of[m].items()):
                    for door in doors.doors.get(name, []):
                        if (door["x"] - dx, door["y"] - dy) not in tiles:
                            continue
                        t, pt = doors.target(door)
                        if t and pt and free(b, t):
                            add(b, t, pt["x"] - bx, pt["y"] - by, "door", around=True)
                if len(e["tiles"]) != 1:
                    continue
                x, y = e["tiles"][0]
                for t, (dx, dy) in list(of[b].items()):
                    for door in doors.into.get(t, []):
                        _, pt = doors.target(door)
                        if pt and max(abs(pt["x"] - bx - dx), abs(pt["y"] - by - dy)) <= 1 and free(m, door["pr"]):
                            add(m, door["pr"], door["x"] - x, door["y"] - y, "door-in")
        if log:
            log(f"door pass, round: {len(found) - n0} rooms")
        if len(found) == n0:
            break
    return found


def world_labels(graph, sources):
    """{node: {labels}}: the source(s) nearest each node by doors (`sources`: {world map: label}): a
    town's World of Balance version is nearest the World of Balance map, an interior both versions enter
    is as near both. Doors the game makes by event (the airship) aren't edges: a label is a hint."""
    dists = {}
    for src, lab in sources.items():
        dist, frontier = {src: 0}, [src]
        while frontier:
            nxt = []
            for n in frontier:
                for t in graph.get(n, ()):
                    if t not in dist:
                        dist[t] = dist[n] + 1
                        nxt.append(t)
            frontier = nxt
        dists[lab] = dist
    out = {}
    for n in set(graph) | set(sources):
        got = {lab: d[n] for lab, d in dists.items() if n in d}
        if got:
            low = min(got.values())
            out[n] = {lab for lab, v in got.items() if v == low}
    return out


def pair_worlds(rom, doors=None):
    """(SNES map -> world labels, PR map -> world labels): each side's nearest world map by its own doors
    (SNES exits both ways, parent exits left out; the PR's GotoMaps both ways)."""
    import collections
    g = collections.defaultdict(set)
    for m in range(MAPS):
        for _, dest, _, _ in snes_exits(rom, m):
            if dest < MAPS and dest != m:
                g[m].add(dest)
                g[dest].add(m)
    doors = doors or PrDoors()
    snes = world_labels(g, WORLD_SOURCES)
    snes.update({m: set(v) for m, v in SNES_WORLD_OVERRIDES.items()})
    return snes, world_labels(doors.graph(), PR_WORLD_SOURCES)


def lookalikes(rom, maps):
    """{(SNES map, PR map)} of tile/layout pairs that are another place's room: the PR room is structurally
    paired (STRUCTURAL: chests, exits, doors, by hand) to another SNES map of another place: its graphics or
    name differ, or its exits lead to none of the maps this map's exits lead to (FF6's interiors share
    graphics and an empty name across towns: Mobliz's inn 0xA0 and Thamasa's rooms). Same-place story-state
    copies (same look, exits into the same place) aren't lookalikes. `maps`: {str(SNES map): [(how, scores,
    pr, dx, dy)]}."""
    import collections
    owners = collections.defaultdict(set)
    for m, rows in maps.items():
        for how, _, pr, _, _ in rows:
            if how in STRUCTURAL:
                owners[pr].add(int(m))
    look, dests = {}, {}

    def place(m):
        if m not in look:
            q = properties(rom, m)
            look[m] = (tuple(q["graphic_sets"]), q["tilesets"], q["name"])
            dests[m] = {d for _, d, _, _ in snes_exits(rom, m) if 2 <= d < MAPS and d != m}
        return look[m]

    def other_place(a, b):
        if place(a) != place(b):
            return True
        return bool(dests[a] and dests[b] and not (dests[a] & dests[b]) and a not in dests[b] and b not in dests[a])
    out = set()
    for m, rows in maps.items():
        for how, _, pr, _, _ in rows:
            if how in ("tiles", "layout"):
                others = owners.get(pr, set()) - {int(m)}
                if any(other_place(o, int(m)) for o in others):
                    out.add((int(m), pr))
    return out


def world_tag(snes_lab, pr_lab):
    """(world, cross) of a pair: world = "WoB" / "WoR" / "both" / None from the two sides' labels; cross =
    the SNES map is one world's alone and the PR map the other's alone (157 <-> Map_20340: a World of Ruin
    scene on a World of Balance room)."""
    labs = set(snes_lab or ()) | set(pr_lab or ())
    world = None if not labs else ("both" if len(labs) > 1 else next(iter(labs)))
    cross = bool(snes_lab and pr_lab and len(snes_lab) == 1 and len(pr_lab) == 1 and set(snes_lab) != set(pr_lab))
    return world, cross


TILESET_PTRS, TILESET_BASE = 0x1FBA00, 0xDE0000   # DF/BA00: 3-byte offsets from DE/0000 (C0/27EF), LZSS


def tileset(rom, idx, ptrs=TILESET_PTRS):
    """SNES tileset (tile formation) `idx`: per 16x16 tile its four 8x8 parts as 8 bytes (the 2 KB
    the field code unpacks hold eight 256-byte planes: parts' character bytes, then their
    attributes). Two tiles sharing parts look alike (`tile_likeness`)."""
    a = int.from_bytes(rom[ptrs + 3 * idx:ptrs + 3 * idx + 3], "little")
    at = _file_offset(TILESET_BASE + a)
    raw = lzss(rom[at:at + 0x2000])
    raw = raw + bytes(2048 - len(raw)) if len(raw) < 2048 else raw
    return [tuple(raw[k * 256 + t] for k in range(8)) for t in range(256)]


def tile_likeness(f1, f2):
    """How many of two tiles' four 8x8 parts are the same (character and attributes)."""
    return sum(f1[k] == f2[k] and f1[k + 4] == f2[k + 4] for k in range(4))


_walkable = {}


def pr_walkable(pr_map):
    """The cells of a PR map one can walk on: collision 0 (any collision layer) where a tile is drawn."""
    if pr_map not in _walkable:
        out = set()
        path = pr_tilemaps().get(pr_map)
        if path:
            with open(os.path.join(os.path.dirname(path), "collision.json"), encoding="utf-8") as f:
                c = json.load(f)
            layers = list(pr_layers(path).values())
            colls = []

            def walk(ls):
                for lay in ls:
                    if lay.get("type") == "tilelayer":
                        colls.append(lay)
                    walk(lay.get("layers", []))
            walk(c.get("layers", []))
            for lay in colls:
                W = lay["width"]
                for i, v in enumerate(lay["data"]):
                    x, y = i % W, i // W
                    if v == 0 and any(y < len(L) and x < len(L[0]) and L[y][x] for L in layers):
                        out.add((x, y))
        _walkable[pr_map] = out
    return _walkable[pr_map]


def walk_agreement(rom, m, pr_map, dx, dy, rows=None, props=None):
    """(share, cells): of the PR map's walkable cells on the SNES layout at PR = SNES + (dx, dy), the
    share whose SNES BG1 tile isn't a wall by the SNES tile properties. A right pair is ~0.9+ (the
    PR walks where the SNES did); a wrong offset or a wrong map is far lower."""
    rows = rows if rows is not None else layout(rom, m)
    props = props if props is not None else tile_props(rom, m)
    if rows is None:
        return None, 0
    n = ok = 0
    for x, y in pr_walkable(pr_map):
        sx, sy = x - dx, y - dy
        if 0 <= sy < len(rows) and 0 <= sx < len(rows[0]):
            n += 1
            ok += props[rows[sy][sx]][0] != WALL
    return (ok / n if n else None), n


def pr_map_dirs():
    """{PR map name: folder} for every vanilla PR map with entities (world maps included: they have
    no tilemap.json, their tiles are chunked)."""
    import glob
    out = {}
    for p in glob.glob(os.path.join(P.VANILLA, "map_*", "Assets", "GameAssets", "Serial", "Res", "Map", "*", "*",
                                    "entity_default.json")):
        out[os.path.basename(os.path.dirname(p))] = os.path.dirname(p)
    return out


def chest_seeds(rom_path=None):
    """(SNES map, PR map, dx, dy) from the chests port_chests pairs by contents (vanilla against
    vanilla): each PR map with 2+ chests at one offset, or a map's only chest."""
    import collections
    import ff6snes as S
    import port_chests as C
    rom = S.Rom(rom_path or P.VANILLA_ROM)
    chests = C.snes_chests(rom)
    votes = collections.defaultdict(collections.Counter)
    for key, e in C.match(chests).items():
        c = chests.get(key)
        if c:
            votes[c["map"]][(os.path.basename(os.path.dirname(e["file"])),
                              round(e["x"] / 16) - c["x"], round(e["y"] / 16) - 1 - c["y"])] += 1
    out = []
    for m, cnt in votes.items():
        top = cnt.most_common()
        out += [(m,) + k for k, n in top if n >= 2] or [(m,) + top[0][0]]
    return out


def propagate(rom, seeds, tilemaps, verify=None):
    """Follow exits from known (SNES map, PR map, dx, dy): a SNES exit's tile, moved by the offset,
    holds a PR GotoMap; its PR destination and arrival point, against the SNES exit's destination
    and arrival tile, give the next pair and its offset (the arrival point may sit a tile off: the
    offset most exits agree on wins). `verify(m, pr, dx, dy)` can veto a pair. {(m, pr): (dx, dy, how)}."""
    import collections
    by_id = {int(r["id"]): r["map_name"] for r in P.Table("map")}
    links = {n: pr_links(d) for n, d in pr_map_dirs().items()}
    known = {(s[0], s[1]): (s[2], s[3], s[4] if len(s) > 4 else "chests") for s in seeds}
    queue = list(known)
    votes = collections.defaultdict(collections.Counter)
    # the other way round: exits INTO a known pair's maps (SNES: from any map; PR: GotoMaps naming it)
    into_snes = collections.defaultdict(list)
    for x in range(MAPS):
        for tiles, dest, tx, ty in snes_exits(rom, x):
            if dest < MAPS:
                into_snes[dest].append((x, tiles, tx, ty))
    into_pr = collections.defaultdict(list)
    for n, (gotos, _) in links.items():
        for gx, gy, mid, point in gotos:
            if mid in by_id:
                into_pr[by_id[mid]].append((n, gx, gy, point))

    def add(m2, pr2, offset, how):
        votes[(m2, pr2)][offset] += 1
        if m2 < 3 or pr2.startswith("Map_1"):   # world maps (PR group 1xxxx): seeded by hand only
            return
        if (m2, pr2) not in known:
            checked = verify(m2, pr2, *offset) if verify else offset
            if checked:
                known[(m2, pr2)] = tuple(checked) + (how,)
                queue.append((m2, pr2))

    while queue:
        m, pr = queue.pop()
        dx, dy, _ = known[(m, pr)]
        if pr not in links:
            continue
        points = links[pr][1]
        for x, tiles, tx, ty in into_snes.get(m, []):
            if len(tiles) != 1:   # one-tile exits only: a long exit's PR door could be any of its tiles
                continue
            for n, gx, gy, point in into_pr.get(pr, []):
                p = points.get(point)
                if p and abs(p[0] - tx - dx) <= 1 and abs(p[1] - ty - dy) <= 1:
                    add(x, n, (gx - tiles[0][0], gy - tiles[0][1]), "exits")
        gotos, _ = links[pr]
        for tiles, dest, tx, ty in snes_exits(rom, m):
            if dest >= MAPS or dest < 3:   # 0x1FF "back", world maps (the PR's are other maps)
                continue
            hit = next((g for g in gotos for (x, y) in tiles if abs(g[0] - x - dx) <= 1 and abs(g[1] - y - dy) <= 1), None)
            if not hit:
                continue
            npr = by_id.get(hit[2])
            if not npr or npr not in links:
                continue
            pt = links[npr][1].get(hit[3])
            if pt:
                add(dest, npr, (pt[0] - tx, pt[1] - ty), "exits")
    return known


def pr_objects(map_dir):
    """A PR map's objects (entity_default.json) as (name, tile x, tile y): a tile object's y is its
    bottom edge in Tiled (tile = y / 16 - 1), a plain rectangle's its top."""
    path = os.path.join(map_dir, "entity_default.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    out = []
    for lay in d.get("layers", []):
        for o in lay.get("objects", []) or []:
            out.append((o.get("name", ""), int(o["x"] // 16), int(o["y"] // 16) - (1 if "gid" in o else 0)))
    return out


_tilemaps = None


def pr_tilemaps():
    """{PR map name: tilemap.json path} for every vanilla PR map (read once)."""
    global _tilemaps
    if _tilemaps is not None:
        return _tilemaps
    import glob
    out = _tilemaps = {}
    for p in glob.glob(os.path.join(P.VANILLA, "map_*", "Assets", "GameAssets", "Serial", "Res", "Map", "*", "*",
                                    "tilemap.json")):
        out[os.path.basename(os.path.dirname(p))] = p
    return out


def pr_layers(path):
    """{layer name: rows of gids} of a PR tilemap (layers inside groups included)."""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    out = {}

    def walk(ls):
        for lay in ls:
            if lay.get("type") == "tilelayer":
                out[lay["name"]] = [lay["data"][r * d["width"]:(r + 1) * d["width"]] for r in range(d["height"])]
            walk(lay.get("layers", []))
    walk(d["layers"])
    return out


# --- matching -----------------------------------------------------------------------------------
def _pr_key(path):
    import numpy as np
    layers = pr_layers(path)
    if not layers:
        return None   # a map without tile layers (chunked world maps)
    first = next(iter(layers.values()))
    shape = (len(first), len(first[0]))
    z = np.zeros(shape, dtype=np.int64)
    get = lambda n: np.array(layers[n], dtype=np.int64) if n in layers else z
    return (get("BottomLayer") << 40) | (get("GroundLayer") << 20) | get("UpperLayer")


def _mi(a, b):
    """Mutual information (bits per cell) between two equal-length int arrays, and the SNES side's entropy."""
    import numpy as np
    n = len(a)
    _, ia = np.unique(a, return_inverse=True)
    _, ib = np.unique(b, return_inverse=True)
    joint = np.bincount(ia * (int(ib.max()) + 1) + ib)
    joint = joint[joint > 0] / n
    pa, pb = np.bincount(ia) / n, np.bincount(ib) / n
    ent = lambda p: float(-(p * np.log2(p)).sum())
    ha = ent(pa)
    return ha + ent(pb) - ent(joint), ha


def score(snes, prk, dx, dy):
    """At PR = SNES + (dx, dy): (bits explained, share of the SNES side's information, share of
    the PR side's, coverage = the part of the PR map's drawn cells that fall on the SNES layout)."""
    import numpy as np
    h, w = snes.shape
    H, W = prk.shape
    x0, y0, x1, y1 = max(0, -dx), max(0, -dy), min(w, W - dx), min(h, H - dy)
    drawn = int(np.count_nonzero(prk))
    if x1 - x0 < 4 or y1 - y0 < 4 or not drawn:
        return 0.0, 0.0, 0.0, 0.0
    a = snes[y0:y1, x0:x1].ravel()
    b = prk[y0 + dy:y1 + dy, x0 + dx:x1 + dx].ravel()
    keep = b != 0
    a, b = a[keep], b[keep]
    if len(a) < 30:
        return 0.0, 0.0, 0.0, 0.0
    mi, ha = _mi(a, b)
    _, hb = _mi(b, a)
    return mi * len(a), (mi / ha if ha > 0 else 0.0), (mi / hb if hb > 0 else 0.0), len(a) / drawn


def _edges(t):
    """Where the tile changes to the right and downward (1.0), any tile numbering."""
    import numpy as np
    eh = np.zeros(t.shape)
    ev = np.zeros(t.shape)
    eh[:, :-1] = t[:, 1:] != t[:, :-1]
    ev[:-1, :] = t[1:, :] != t[:-1, :]
    return eh, ev


def _peaks(snes_e, pr_e, k=4):
    """The k offsets (dx, dy) where the two maps' tile edges line up best (FFT cross-correlation)."""
    import numpy as np
    (sh_, sv), (ph, pv) = snes_e, pr_e
    h, w = sh_.shape
    H, W = ph.shape
    shape = (h + H, w + W)
    f = lambda a: np.fft.rfft2(a, shape)
    corr = np.fft.irfft2(np.conj(f(sh_)) * f(ph) + np.conj(f(sv)) * f(pv), shape)
    flat = np.argsort(corr.ravel())[::-1][:k]
    out = []
    for i in flat:
        dy, dx = divmod(int(i), shape[1])
        out.append((dx - shape[1] if dx > W else dx, dy - shape[0] if dy > H else dy))
    return out


_PR = {}


def _pr_cached(path):
    if path not in _PR:
        key = _pr_key(path)
        objs = {(x, y) for _, x, y in pr_objects(os.path.dirname(path))}
        _PR[path] = (key, _edges(key), objs) if key is not None else (None, None, None)
    return _PR[path]


def _hits(ents, objs, prk, dx, dy):
    """(SNES things landing on a PR object, SNES things on the PR map's drawn cells)."""
    H, W = prk.shape
    inside = [(x + dx, y + dy) for _, x, y in ents if 0 <= x + dx < W and 0 <= y + dy < H and prk[y + dy, x + dx]]
    return sum(p in objs for p in inside), len(inside)


def _match_one(args):
    """One SNES map against each candidate PR map, at the offsets where their edges line up.
    A match needs the tiles to agree both ways (mutual information) and, where the SNES map has
    exits/NPCs/chests/event tiles on the PR map's cells, at least 40% of them on a PR object at the
    same offset (with none to check: near-perfect tiles). Returns [(bits, share_snes, share_pr,
    coverage, hits, inside, pr, dx, dy)], most bits first."""
    m, snes_rows, ents, cands = args[:4]
    props = args[4] if len(args) > 4 else None
    import numpy as np
    snes = np.array(snes_rows, dtype=np.int64)
    se = _edges(snes)
    out = []
    for name, path in cands:
        prk, pe, objs = _pr_cached(path)
        if prk is None:
            continue
        best = None
        for dx, dy in _peaks(se, pe):
            for ddx in (-1, 0, 1):
                for ddy in (-1, 0, 1):
                    s = score(snes, prk, dx + ddx, dy + ddy)
                    if s[1] < 0.5 or s[2] < 0.5 or s[3] < 0.6:
                        continue
                    h = _hits(ents, objs, prk, dx + ddx, dy + ddy)
                    key = (h[0], s[1] * s[2])
                    if best is None or key > best[0]:
                        best = (key, s + h + (dx + ddx, dy + ddy))
        if best is None:
            continue
        bits, s1, s2, cov, hits, inside, dx, dy = best[1]
        if inside >= 2:
            ok = hits >= 2 and hits >= 0.4 * inside
        else:
            ok = s1 >= 0.85 and s2 >= 0.85 and cov >= 0.9 and bits >= 500
        walk, n = walk_agreement(None, m, name, dx, dy, snes_rows, props) if props else (None, 0)
        # or the PR walks where the SNES walks (an independent check: a room the PR redrew more
        # than the tiles show, its people not where the PR has objects)
        if ok or (walk is not None and walk >= 0.9 and n >= 30 and s1 >= 0.7 and s2 >= 0.5 and cov >= 0.8):
            out.append((bits, s1, s2, cov, hits, inside, name, dx, dy, walk, n))
    out.sort(key=lambda t: -t[0])
    return m, out


def _compatible(sw, sh, W, H):
    """A PR map no bigger than the SNES layout plus padding (it may be one room of it)."""
    return W <= sw + 16 and H <= sh + 16


def build(rom_path=None, processes=None):
    """Match every SNES map of the US ROM to the PR's maps and write data/snes_pr_maps.json."""
    import collections
    import multiprocessing
    import ff6snes as S
    rom = S.rom_bytes(rom_path or P.VANILLA_ROM)
    tilemaps = pr_tilemaps()
    sizes = {}
    for name, path in tilemaps.items():
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        sizes[name] = (d["width"], d["height"])
    jobs = []
    for m in range(MAPS):
        rows = layout(rom, m)
        if rows is None:
            continue
        sw, sh = len(rows[0]), len(rows)
        cands = [(n, tilemaps[n]) for n, (W, H) in sizes.items() if _compatible(sw, sh, W, H)]
        jobs.append((m, rows, snes_entities(rom, m), cands, tile_props(rom, m)))
    ids = {r["map_name"]: int(r["id"]) for r in P.Table("map")}
    import numpy as np
    arrays = {m: np.array(rows, dtype=np.int64) for m, rows, _, _, _ in jobs}
    ents = {m: e for m, _, e, _, _ in jobs}

    def measure(m, pr, dx, dy):
        if pr not in tilemaps or m not in arrays:
            return None
        prk, _, objs = _pr_cached(tilemaps[pr])
        if prk is None:
            return None
        return score(arrays[m], prk, dx, dy) + _hits(ents[m], objs, prk, dx, dy)

    def verify(m, pr, dx, dy):
        """An exit-found pair: the offset (or a neighbour: arrival points sit a tile off) where the
        tiles agree; no layout to check: taken as found."""
        if m not in arrays:
            return dx, dy
        if pr not in tilemaps:
            return None   # a SNES room against a PR map with no tiles (a world map): not the same place
        best = max(((measure(m, pr, dx + a, dy + b) or (0, 0, 0, 0, 0, 0)), dx + a, dy + b)
                   for a in (-1, 0, 1) for b in (-1, 0, 1))
        (bits, s1, s2, cov, hits, inside), bx, by = best
        return (bx, by) if s1 >= 0.4 and s2 >= 0.4 else None

    # 1. chests (content-paired), 2. exits followed from them, 3. tiles alone for what neither reached
    raw = chest_seeds(rom_path)   # contents can pair a chest with another map's: the tiles must agree too
    seeds = [(m, pr) + tuple(c) for m, pr, dx, dy in raw for c in [verify(m, pr, dx, dy)] if c and pr in tilemaps]
    print(f"chest pairs: {len(raw)}, {len(seeds)} with agreeing tiles", flush=True)
    dirs = pr_map_dirs()
    manual = [(m, pr, dx, dy, "manual") for m, pr, dx, dy, _ in overrides() if pr in dirs]
    known = propagate(rom, manual + [s for s in seeds if (s[0], s[1]) not in {(t[0], t[1]) for t in manual}],
                      tilemaps, verify)
    print(f"chests: {len(seeds)} pairs on {len({s[0] for s in seeds})} SNES maps; with exits: {len(known)} pairs "
          f"on {len({k[0] for k in known})} SNES maps", flush=True)
    reached = {k[0] for k in known}
    # tiles for every map: a map the exits reached may also be other PR maps (its World of Ruin
    # version, a scene's copy) that only its tiles name
    rest = jobs
    found, loose = {}, {}
    cache = os.path.join(P.ROOT, "build", "snes_maps_tiles.json")   # the tiles pass (minutes): --reuse reads it

    def tile_results():
        if "--reuse" in sys.argv and os.path.exists(cache):
            with open(cache, encoding="utf-8") as f:
                yield from ((int(m), [tuple(o) for o in out]) for m, out in json.load(f).items())
            return
        done = {}
        with multiprocessing.Pool(processes or max(1, (os.cpu_count() or 2) - 2)) as pool:
            for m, out in pool.imap_unordered(_match_one, rest, chunksize=4):
                done[m] = out
                yield m, out
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "w", encoding="utf-8") as f:
            json.dump({str(m): out for m, out in done.items()}, f)
    if True:
        for m, out in tile_results():
            # tiles alone: only near-certain pairs (both sides explained, the PR map on the layout)
            # _match_one's own rule (its entities on PR objects, or near-perfect tiles), then tighter
            hit_ok = lambda o: (o[4] >= 2 and o[4] >= 0.4 * o[5]) if o[5] >= 2 else                 (o[1] >= 0.85 and o[2] >= 0.85 and o[3] >= 0.9 and o[0] >= 500)
            strict = [o for o in out if hit_ok(o) and o[1] >= 0.85 and o[2] >= 0.75 and o[3] >= 0.85 and
                      (o[5] < 2 or o[4] >= 0.5 * o[5])]
            found[m] = [o for o in strict if not o[6].startswith("Map_1") and (m, o[6]) not in known]
            loose[m] = [o for o in out if o not in strict and o[9] is not None and o[9] >= 0.9 and o[10] >= 30
                        and not o[6].startswith("Map_1") and (m, o[6]) not in known]
    # looser tile matches the PR's walking confirms: only where they are the PR map's best SNES match
    # (by tiles x walking; a map with the same layout ties) and the PR map isn't another layout's
    # by chests or exits; at most 3 per SNES map
    lay_of = {m: tuple(properties(rom, m)["layouts"][:2]) for m in range(MAPS)}
    firm = collections.defaultdict(set)
    for (m, pr) in known:
        firm[pr].add(lay_of.get(m))
    best = {}
    for m, os_ in loose.items():
        for o in os_:
            sc = o[1] * o[2] * o[9]
            if sc > best.get(o[6], (0,))[0]:
                best[o[6]] = (sc, lay_of[m])
    took = 0
    for m, os_ in loose.items():
        keep = [o for o in os_ if o[1] * o[2] * o[9] >= 0.97 * best[o[6]][0] and
                (lay_of[m] == best[o[6]][1] or o[1] * o[2] * o[9] >= best[o[6]][0]) and
                (not firm.get(o[6]) or lay_of[m] in firm[o[6]])]
        keep = sorted(keep, key=lambda o: -o[1] * o[2] * o[9])[:3]
        found.setdefault(m, []).extend(keep)
        took += len(keep)
    print(f"tile matches: {sum(len(v) for v in found.values()) - took} near-certain, {took} confirmed by walking",
          flush=True)
    maps = {}
    for (m, pr), (dx, dy, how) in known.items():
        s = measure(m, pr, dx, dy) or (0, 0, 0, 0, 0, 0)
        maps.setdefault(str(m), []).append((how, s, pr, dx, dy))
    for m, out in found.items():
        for o in out:
            maps.setdefault(str(m), []).append(("tiles", o[:6], o[6], o[7], o[8]))
    # 4. event copies: a map still without a pair that has a placed map's BG1 and BG2 layouts (the
    #    same room in another story state, its Ruin version) takes that map's PR maps, the ones
    #    drawn with the same SNES graphics first
    layouts = {m: tuple(properties(rom, m)["layouts"][:2]) + (properties(rom, m)["bg1_size"],) for m in range(MAPS)}
    looks = {m: bytes(rom[PROPS + 33 * m + 7:PROPS + 33 * m + 13]) for m in range(MAPS)}
    copies = {}
    for m in range(MAPS):
        if str(m) in maps or not layouts[m][0]:
            continue
        sibs = sorted((v for v in range(MAPS) if v != m and str(v) in maps and layouts[v] == layouts[m]),
                      key=lambda v: looks[v] != looks[m])
        rows, seen = [], set()
        for v in sibs:
            for how, s, pr, dx, dy in maps[str(v)]:
                if pr not in seen:
                    seen.add(pr)
                    rows.append(("layout", measure(m, pr, dx, dy) or s, pr, dx, dy))
        if rows:
            copies[str(m)] = rows
    maps.update(copies)
    print(f"event copies (a placed map's layouts): {len(copies)} SNES maps", flush=True)
    # 4b. rooms by doors (Beyond Chaos's entrance index, tools/bc_entrances.py): vanilla's doors followed both
    #     ways from every pair so far; a room counts when it walks where the SNES walks and its doors sit on the
    #     SNES map's exits (grow_doors)
    #     lookalike rows (another place's room by tiles alone) seed it but don't block it: a room found by doors
    #     replaces the lookalike row of the same PR map
    doors = PrDoors()
    la0 = lookalikes(rom, maps)
    pairs = {int(m): {pr: (dx, dy) for how, s, pr, dx, dy in rows} for m, rows in maps.items()}
    grown = grow_doors(rom, pairs, doors, unblock=la0)
    for g in grown:
        s = measure(g["snes"], g["pr"], g["dx"], g["dy"]) or (0, 0, 0, 0, 0, 0)
        rows = [r for r in maps.get(str(g["snes"]), []) if r[2] != g["pr"]]
        maps[str(g["snes"])] = rows + [(g["how"], s, g["pr"], g["dx"], g["dy"])]
    print(f"door pass: {len(grown)} rooms on {len({g['snes'] for g in grown})} SNES maps", flush=True)
    # 5. every pair against the SNES passability: the PR's walkable cells on SNES walls means a
    #    wrong pair (a generic room or scene backdrop matched by tiles, a wrong offset)
    walks, dropped = {}, collections.Counter()
    for m in list(maps):
        rows, props = layout(rom, int(m)), tile_props(rom, int(m))
        keep = []
        for row in maps[m]:
            how, s, pr, dx, dy = row
            share, n = walk_agreement(rom, int(m), pr, dx, dy, rows, props) if rows else (None, 0)
            walks[(m, pr)] = (round(share, 3) if share is not None else None, n)
            floor = 0.4 if how in ("chests", "exits") else 0.8
            if how == "manual" or (share is None and how != "tiles") or (n < 8 and how != "tiles") or                     (share is not None and share >= floor):
                keep.append(row)
            else:
                dropped[how] += 1
        if keep:
            maps[m] = keep
        else:
            del maps[m]
    print(f"dropped by SNES passability: {dict(dropped)}", flush=True)
    snes_w, pr_w = pair_worlds(rom, doors)
    la = lookalikes(rom, maps)
    print(f"lookalike pairs (another place's room by tiles alone): {len(la)}", flush=True)
    doc_maps = {}
    for m in sorted(maps, key=int):
        # pairs found by chests / exits / by hand first, then rooms by doors, then tiles / layout alone (each
        # by how much the tiles explain): to_pr and pr_maps()[0] take the first that fits
        rows = sorted(maps[m], key=lambda t: ({"door": 1, "door-in": 1, "tiles": 2, "layout": 2}.get(t[0], 0), -t[1][0]))
        doc_maps[m] = [{"pr": pr, "pr_id": ids.get(pr), "dx": dx, "dy": dy, "how": how, "share": round(s[1], 3),
                        "share_pr": round(s[2], 3), "coverage": round(s[3], 3), "bits": round(s[0]),
                        "entities": [s[4], s[5]], "size": list(sizes.get(pr, (0, 0))),
                        "walk": list(walks.get((m, pr), (None, 0))),
                        "world": world_tag(snes_w.get(int(m)), pr_w.get(pr))[0],
                        "cross": world_tag(snes_w.get(int(m)), pr_w.get(pr))[1],
                        "lookalike": (int(m), pr) in la}
                       for how, s, pr, dx, dy in rows]
    missing = [m for m in range(MAPS) if str(m) not in doc_maps]
    print(f"no PR map for SNES maps: {missing}")
    doc = {"_source": "tools/snes_maps.py build (US v1.0 ROM + the PR's vanilla maps). PR (x, y) = SNES (x + dx, "
                      "y + dy). how: 'chests' = the map's chests pair by contents (port_chests); 'exits' = reached "
                      "by following exits from such a pair (SNES exit -> the PR GotoMap at the same spot -> its "
                      "destination and arrival point; the world maps 0 and 1 are seeded as Map_10010 / Map_10020 "
                      "at (0, 0), so world-map towns are reached through the PR's entrance objects); 'tiles' = "
                      "only the layouts agree (mutual information between the SNES tile and the PR's tile stack "
                      "per cell; near-certain, or looser when the PR walks where the SNES walks: walk >= 0.9); 'layout' = an event copy: the SNES map has another placed map's BG1 and BG2 "
                      "layouts and takes its PR maps; 'door' / 'door-in' = a room reached by vanilla's doors from a pair (its doors on the "
                      "SNES map's exits, walk >= 0.8: grow_doors). world: the pair's world by each side's nearest world map "
                      "(WoB / WoR / both / null); cross: the SNES map is one world's and the PR map the other's (a porter "
                      "following exits should skip it); lookalike: a tiles/layout pair whose PR room is another "
                      "place's (structurally paired to an SNES map of other graphics or name): tools reading every "
                      "pair should skip it (lookups list it after the map's own pairs). One SNES map is often several PR "
                      "maps (its rooms, each its own offset) and one layout several SNES maps (World of Balance "
                      "/ Ruin). share / share_pr: the part of each side's tile information the other explains; "
                      "coverage: the part of the PR map's drawn cells on the SNES layout; entities: SNES exits/"
                      "NPCs/chests/event tiles on a PR object / on the PR map's cells; walk: [share, cells] of "
                      "the PR map's walkable cells that are on SNES tiles the SNES tile properties don't make "
                      "walls (pairs under 0.4 for chests/exits, 0.8 for tiles/layout are dropped)",
           "maps": doc_maps}
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
    hows = __import__("collections").Counter(e["how"] for v in doc_maps.values() for e in v)
    print(f"{len(doc_maps)} of {MAPS} SNES maps placed ({dict(hows)} pairs) -> {os.path.normpath(DATA_FILE)}")
    return doc


# --- lookups --------------------------------------------------------------------------------------
_table = None


def overrides():
    """Hand-confirmed pairs (data/snes_pr_maps_overrides.json): [(SNES map, PR map, dx, dy, note)].
    The build follows exits from them too; lookups list them first."""
    if not os.path.exists(OVERRIDES_FILE):
        return []
    with open(OVERRIDES_FILE, encoding="utf-8") as f:
        return [(int(m), e["pr"], e["dx"], e["dy"], e.get("note", "")) for m, es in json.load(f)["maps"].items()
                for e in es]


def table():
    global _table
    if _table is None:
        with open(DATA_FILE, encoding="utf-8") as f:
            _table = {int(k): [Match(**v) for v in vs] for k, vs in json.load(f)["maps"].items()}
        ids = None
        for m, pr, dx, dy, _ in reversed(overrides()):
            if ids is None:
                ids = {r["map_name"]: int(r["id"]) for r in P.Table("map")}
            rest = [t for t in _table.get(m, []) if t.pr != pr]
            _table[m] = [Match(pr, ids.get(pr), dx, dy, "manual", 1.0, 1.0, 1.0, 0, [0, 0], [0, 0])] + rest
    return _table


def pr_maps(snes_map):
    """The PR maps of a SNES map, best first ([] when unknown)."""
    return table().get(snes_map, [])


_drawn, _paths = {}, None


def drawn(pr_map, x, y):
    """Whether the PR map has a tile at (x, y) (its vanilla tilemap; True when it isn't at hand)."""
    global _paths
    if pr_map not in _drawn:
        if _paths is None:
            _paths = pr_tilemaps()
        rows = None
        if pr_map in _paths:
            layers = list(pr_layers(_paths[pr_map]).values())
            rows = [[any(lay[r][c] for lay in layers) for c in range(len(layers[0][0]))] for r in range(len(layers[0]))]
        _drawn[pr_map] = rows
    rows = _drawn[pr_map]
    if rows is None:
        return True
    return 0 <= y < len(rows) and 0 <= x < len(rows[0]) and rows[y][x]


def to_pr(snes_map, x, y, pr=None):
    """SNES (map, x, y) -> (PR map name, x, y): the best PR map (or `pr`) whose room is there (a
    SNES map's rooms are separate PR maps, each drawing the whole SNES layout but walkable only in
    its own room): the first whose walkable cells are at or next to the spot, else the first that
    has a tile there. None when no PR map of it covers the spot."""
    ms = [mt for mt in pr_maps(snes_map) if pr is None or mt.pr == pr]
    for mt in ms:
        wk = pr_walkable(mt.pr)
        px, py = x + mt.dx, y + mt.dy
        if any((px + a, py + b) in wk for a in (-1, 0, 1) for b in (-1, 0, 1)):
            return mt.pr, px, py
    for mt in ms:
        if drawn(mt.pr, x + mt.dx, y + mt.dy):
            return mt.pr, x + mt.dx, y + mt.dy
    return None


def snes_maps(pr_map):
    """[(SNES map, Match)] whose PR map is `pr_map`."""
    return [(m, mt) for m, ms in table().items() for mt in ms if mt.pr == pr_map]


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "build":
        build()
    elif cmd == "show":
        for m in ([int(sys.argv[2], 0)] if len(sys.argv) > 2 else sorted(table())):
            print(m, ", ".join(f"{t.pr} ({t.dx:+d},{t.dy:+d}) {t.share:.2f}" for t in pr_maps(m)) or "-")
    elif cmd == "pr":
        for m, t in snes_maps(sys.argv[2]):
            print(m, f"({t.dx:+d},{t.dy:+d}) {t.share:.2f}")
    else:
        sys.exit(__doc__)
