"""Art for the Pixel Remaster from a mod's own sources, made on the player's machine and served live by the
kit's ArtSwap (plugin/PrKit/ArtSwap.cs): character sprites and portraits, monster images under keys of their
own, bestiary thumbnails, UI sprites. Kit tool (FF6 addresses; any mod: Beyond Chaos' seeds, T-Edition's
costumes and new monsters, Worlds Collide's custom sprites). MODDING.md "SNES sprites -> PR art".

    import pr_art, snes_charsprites as C
    game = pr_art.GameArt()                          # the player's game: its textures, read once, cached
    out = pr_art.ArtWriter(folder)                   # folder/art.json + PNG sheets (merged with what's there)
    frames = C.group_frames(sheet, palette, C.frame_names("bc_ff6_p001"))
    out.character("bc_ff6_p001", frames, field="mo_ff6_p001")   # battle addresses + the field atlas
    out.face("fa_ff6_p001", C.portrait(raw, pal))
    m = out.monster(0, w, h, rgba, pivot=pr_art.pivot(box, w, h, 0, 0))   # monster 0 on its own image key
    out.save()                                       # art.json for ArtSwap.Load(folder)
    pr_art.write_monster_tables(master_dir, out.monster_rows)   # monster.csv / monster_asset.csv rows

What the PR draws (2026-11-20): characters SNES-sized in 32x32 frames (snes_charsprites.py); portraits 40x40;
monsters as images the size of the SNES sprite's opaque box, pivot bottom-centre, 1 px per unit, a bestiary
thumbnail 226x226 per image (group mt_<group>_<asset>, key Thumbnail); UI sprites 100 px per unit, 9-sliced.
A new monster image is a monster_asset row 2000+monster in the group of the monster's own image (its shadow
and bestiary place) with key {GROUP}_B{monster:03} (tools/port_sprites.py's convention), the key added to the
game's asset list by ArtSwap. Nothing here ships game data: the game's own art is read from the player's game.
"""
import csv
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ADDR_BATTLE = "Assets/GameAssets/Serial/Res/Chara/Battle/{G}/{f}"
ADDR_FACE = "Assets/GameAssets/Serial/Res/Chara/Face/{G}/Default_00"
ADDR_MONSTER = "Assets/GameAssets/Serial/Res/Battle/Monster/{G}/{K}"
ADDR_THUMB = "Assets/GameAssets/Serial/Res/UI/Common/Library/Thumbnail/{G}/Thumbnail"
ADDR_UI = "Assets/GameAssets/Common/UI/Common/Sprites/{n}"
ASSET_BASE = 2000          # monster_asset ids of a mod's own images (the PR's go to ~365)
THUMB = 226                # the bestiary's thumbnail
SHEET = 1024               # monster pictures are packed on pages this wide
MASTER = "master/Assets/GameAssets/Serial/Data/Master"


def game_dir():
    """The player's FINAL FANTASY VI folder: FF6_GAME_DIR, else a parent of this script (a generator living under
    the game's BepInEx), else the kit's game registry (the dev PC)."""
    d = os.environ.get("FF6_GAME_DIR")
    if d and os.path.isdir(d):
        return d
    p = HERE
    for _ in range(8):
        if os.path.isdir(os.path.join(p, "FINAL FANTASY VI_Data")):
            return p
        p = os.path.dirname(p)
    from prkit import games
    return games.get("ff6").install


class GameArt:
    """The player's game's art: textures per asset group (tools/pr_images.py, standard library only), the
    bundle folder listed once, every group read once."""

    def __init__(self, root=None):
        self.root = root or game_dir()
        self.cache = {}
        self.index = None

    def bundle(self, group):
        if self.index is None:
            import pr_images
            folder = os.path.join(self.root, pr_images.BUNDLES)
            self.index = {fn.split("_assets_all_")[0]: os.path.join(folder, fn)
                          for fn in os.listdir(folder) if "_assets_all_" in fn and fn.endswith(".bundle")}
        return self.index.get(group)

    def textures(self, group):
        """{name: (w, h, rgba top-down)} of a group's RGBA32/RGB24 textures ({} when the game has no such group)."""
        if group not in self.cache:
            import pr_images
            path = self.bundle(group)
            self.cache[group] = pr_images.textures(path) if path else {}
        return self.cache[group]

    def textures_named(self, group, names):
        """Only the named textures (a 10 MB group like `common` reads in ~0.3 s this way; all of it ~25 s)."""
        import struct
        import pr_bundle
        import pr_images
        path = self.bundle(group)
        out = {}
        if not path:
            return out
        b = pr_bundle.Bundle(path)
        for node in b.serialized_files():
            sf = pr_bundle.SerializedFile(b.file(node))
            for _, (cid, start, size) in sf.objects.items():
                if cid != 28:
                    continue
                (n,) = struct.unpack_from("<i", sf.data, start)
                name = bytes(sf.data[start + 4:start + 4 + n]).decode("utf-8", "replace")
                if name in names:
                    t = pr_images.texture(sf, b, start, start + size)
                    if t:
                        out[t[0]] = t[1:]
        return out

    def frames(self, group):
        """A character group's 32x32 frames {name: rgba} (field mo_ and battle bc_ groups are the same pixels)."""
        g = group.replace("mo_ff6_", "bc_ff6_")
        key = "frames:" + g
        if key not in self.cache:
            self.cache[key] = {n: rgba for n, (w, h, rgba) in self.textures(g).items() if (w, h) == (32, 32)}
        return self.cache[key]

    def maps(self, group):
        """The group's colors on their SNES palette slots (snes_charsprites.ColorMaps), from these frames."""
        import snes_charsprites as C
        g = group.replace("mo_ff6_", "bc_ff6_")
        key = "maps:" + g
        if key not in self.cache:
            fr = self.frames(g)
            self.cache[key] = C.ColorMaps(g, [fr[n] for n in C.data()["groups"].get(g, fr) if n in fr])
        return self.cache[key]

    def face(self, group):
        """A portrait (40x40 rgba), from its fa_ group."""
        return self.textures(group)["Default_00"][2]


# --- images ---------------------------------------------------------------------------------------------

def apply_table(rgba, table):
    """{rgb: rgb} on RGBA bytes (opaque pixels; alpha kept): tools/port_sprites.apply_table's result, ~10x
    faster (whole pixels looked up as 32-bit words)."""
    import array
    px = array.array("I", rgba)
    little = sys.byteorder == "little"

    def word(c, a=255):
        return (a << 24 | c[2] << 16 | c[1] << 8 | c[0]) if little else (c[0] << 24 | c[1] << 16 | c[2] << 8 | a)
    tw = {word(c): word(n) for c, n in table.items()}
    get = tw.get
    return array.array("I", (get(p, p) for p in px)).tobytes()


def pivot(box, w, h, x0, y0):
    """A monster picture's pivot so the PR draws it where the SNES draws it: the SNES draws a sprite's tiles
    from the formation position's top-left, the PR draws the monster's old image by its bottom-centre at the
    bottom-centre of the old SNES box. box: the monster's vanilla opaque box (x0, y0, x1, y1) in its tile grid;
    (x0, y0): the picture's place in the grid; w x h its size."""
    if not box:
        return [0.5, 0.0]
    bx0, _, bx1, by1 = box
    return [round(((bx0 + bx1) / 2 - x0) / w, 4), round((y0 + h - by1) / h, 4)]


def thumbnail(w, h, rgba):
    """A new image's bestiary thumbnail: 3x, centred, or its top-right when too big (the head: monsters face
    right), on a clear 226x226 (tools/port_sprites.py's art_thumb placement)."""
    import port_sprites as PS
    x = (THUMB - 3 * w) // 2 if 3 * w <= THUMB else THUMB - 10 - 3 * w
    y = (THUMB - 3 * h) // 2 if 3 * h <= THUMB else 10
    return PS.scaled(w, h, rgba, x, y, 3)


def pack_shelves(images, width=SHEET):
    """{key: (w, h, rgba)} -> [(png bytes, {key: [x, y, w, h]})]: shelves on pages `width` wide, tallest first."""
    import pr_images
    pages, placed = [], []
    x = y = shelf = 0
    for k in sorted(images, key=lambda k: -images[k][1]):
        w, h, _ = images[k]
        if x + w > width:
            x, y, shelf = 0, y + shelf, 0
        if y + h > width:
            pages.append(placed)
            placed, x, y, shelf = [], 0, 0, 0
        placed.append((k, x, y))
        x += w + 1
        shelf = max(shelf, h + 1)
    if placed:
        pages.append(placed)
    out = []
    for page in pages:
        H = max(y + images[k][1] for k, _, y in page)
        buf = bytearray(width * H * 4)
        rects = {}
        for k, x, y in page:
            w, h, px = images[k]
            for r in range(h):
                buf[((y + r) * width + x) * 4:((y + r) * width + x + w) * 4] = px[r * w * 4:(r + 1) * w * 4]
            rects[k] = [x, y, w, h]
        out.append((pr_images.png(width, H, bytes(buf)), rects))
    return out


# --- the folder ArtSwap serves ------------------------------------------------------------------------------

class ArtWriter:
    """A folder of PNG sheets + art.json in ArtSwap's format ({"sprites", "atlases", "keys"}), merged with an
    art.json already there (several steps can write one folder)."""

    def __init__(self, folder, standalone_battle=False):
        self.folder = folder
        self.standalone_battle = standalone_battle
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "art.json")
        self.art = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {"sprites": {}, "atlases": {}}
        self.monster_rows = {}          # PR monster id -> (monster_asset id, row), for write_monster_tables
        self._monsters = {}

    def png(self, name, data):
        with open(os.path.join(self.folder, name), "wb") as f:
            f.write(data)

    def sprite(self, address, png, rect, pivot=(0.5, 0), ppu=None, border=None, preload=False):
        e = {"png": png, "rect": list(rect), "pivot": list(pivot)}
        if ppu is not None:
            e["ppu"] = ppu
        if border is not None:
            e["border"] = list(border)
        if preload:
            e["preload"] = True
        self.art["sprites"][address] = e

    def key(self, group, key, address):
        """A key the game lacks (group + key -> address): ArtSwap adds it to the game's asset list."""
        self.art.setdefault("keys", {}).setdefault(group, {})[key] = address

    def character(self, group, frames, field=None):
        """A character group's frames ({name: 32x32 rgba}) as one sheet: its battle addresses and, given its field
        group (mo_ff6_...), that SpriteAtlas's frames."""
        import pr_images
        import snes_charsprites as C
        png, rects = C.pack(frames)
        fn = group + ".png"
        self.png(fn, png)
        G = group.upper()
        for n, r in rects.items():
            if self.standalone_battle:
                # PR's battle renderer expects a frame's UVs to span its whole
                # texture. A Sprite subrect from the field sheet looks scattered.
                battle_fn = f"{group}_battle_{n.lower()}.png"
                self.png(battle_fn, pr_images.png(32, 32, frames[n]))
                self.sprite(ADDR_BATTLE.format(G=G, f=n), battle_fn, [0, 0, 32, 32])
            else:
                self.sprite(ADDR_BATTLE.format(G=G, f=n), fn, r)
        if field:
            self.art["atlases"][field.upper()] = {n: {"png": fn, "rect": r, "pivot": [0.5, 0]} for n, r in rects.items()}

    def face(self, group, rgba):
        """A 40x40 portrait for a face group (fa_ff6_...)."""
        import snes_charsprites as C
        fn = group + ".png"
        self.png(fn, C.pack({"Default_00": rgba}, size=C.FACE, cols=1)[0])
        self.sprite(ADDR_FACE.format(G=group.upper()), fn, [0, 0, C.FACE, C.FACE], pivot=(0.5, 0.5))

    def ui(self, name, w, h, rgba, border=(0, 0, 0, 0)):
        """A UI sprite of the `common` group (100 px per unit, pivot centre, 9-slice border l, b, r, t)."""
        import pr_images
        fn = f"ui_{name.lower()}.png"
        self.png(fn, pr_images.png(w, h, rgba))
        self.sprite(ADDR_UI.format(n=name), fn, [0, 0, w, h], pivot=(0.5, 0.5), ppu=100, border=border, preload=True)

    def monster(self, m, group, asset_row, w, h, rgba, pivot=(0.5, 0.0), thumb=None, pr_id=None, asset_id=None):
        """SNES monster m on an image of its own: key {GROUP}_B{m:03} in `group` (an image group whose shadow and
        bestiary place it takes: its own image's, or a stand-in's for a new monster), monster_asset row
        `asset_id` (default 2000+m; a copy of `asset_row` with the new id and asset name b{m:03}) for the PR
        monster row `pr_id` (default m+1; a mod's new monster: its own id, e.g. T-Edition's 1000+e). thumb: its
        bestiary thumbnail (226x226 rgba; None: made from the image, see thumbnail(); False: none). Written at
        save(); the table rows in monster_rows {pr_id: (asset id, row)}."""
        key = f"{group.upper()}_B{m:03d}"
        aid = ASSET_BASE + m if asset_id is None else asset_id
        self._monsters[key] = (group, w, h, rgba, list(pivot), thumb)
        self.monster_rows[m + 1 if pr_id is None else pr_id] = (aid, dict(asset_row, id=str(aid), asset_name=f"b{m:03d}"))
        return key

    def _write_monsters(self):
        import port_sprites as PS
        import pr_images
        images = {k: (w, h, rgba) for k, (g, w, h, rgba, pv, th) in self._monsters.items()}
        if self.standalone_battle:
            for key, (g, w, h, rgba, pv, _) in self._monsters.items():
                fn = f"monster_{key.lower()}.png"
                self.png(fn, pr_images.png(w, h, rgba))
                addr = ADDR_MONSTER.format(G=g.upper(), K=key)
                self.sprite(addr, fn, [0, 0, w, h], pivot=pv, preload=True)
                self.key(g, key, addr)
        else:
            for n, (png, rects) in enumerate(pack_shelves(images)):
                fn = f"monsters_{n}.png"
                self.png(fn, png)
                for key, r in rects.items():
                    g, _, _, _, pv, _ = self._monsters[key]
                    addr = ADDR_MONSTER.format(G=g.upper(), K=key)
                    self.sprite(addr, fn, r, pivot=pv, preload=True)     # in battle: there before the game asks
                    self.key(g, key, addr)
        for key, (g, w, h, rgba, pv, th) in self._monsters.items():
            if th is False:
                continue
            tg = PS.thumb_group(key)
            fn = f"thumb_{key.lower()}.png"
            self.png(fn, pr_images.png(THUMB, THUMB, th if th is not None else thumbnail(w, h, rgba)))
            addr = ADDR_THUMB.format(G=tg.upper())
            self.sprite(addr, fn, [0, 0, THUMB, THUMB], pivot=(0.5, 0.5), ppu=100)
            self.key(tg, "Thumbnail", addr)
        self._monsters = {}

    def save(self):
        if self._monsters:
            self._write_monsters()
        with open(os.path.join(self.folder, "art.json"), "w", encoding="utf-8") as f:
            json.dump(self.art, f, indent=0)


# --- monster tables ----------------------------------------------------------------------------------------

def monster_asset(m, vmon=None, vasset=None):
    """SNES monster m's own PR image: (group, its monster_asset row), or (None, None)."""
    import prdata as P
    vmon = vmon or P.Table("monster")
    vasset = vasset or P.Table("monster_asset")
    r = vmon.rows.get(m + 1)
    a = vasset.rows.get(int(r["monster_asset_id"])) if r else None
    return (a["group_name"], a) if a else (None, None)


def _read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    return rows[0], rows[1:]


def _write_csv(path, head, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(head)
    w.writerows(rows)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(buf.getvalue())


def write_monster_tables(master_dir, rows):
    """Each monster in `rows` ({PR monster id: (monster_asset id, row)}, ArtWriter.monster_rows) on its own image:
    the folder's full monster table (or the game's) with those rows' monster_asset_id, and the full monster_asset
    table with the new rows."""
    import prdata as P
    vmon, vasset = P.Table("monster"), P.Table("monster_asset")
    os.makedirs(master_dir, exist_ok=True)
    mpath = os.path.join(master_dir, "monster.csv")
    head, mrows = _read_csv(mpath) if os.path.exists(mpath) else (list(vmon.columns), [[r[c] for c in vmon.columns] for r in vmon])
    col = head.index("monster_asset_id")
    for r in mrows:
        if int(r[0]) in rows:
            r[col] = str(rows[int(r[0])][0])
    _write_csv(mpath, head, mrows)
    ahead = list(vasset.columns)
    arows = [[r[c] for c in ahead] for r in vasset] + [[row[c] for c in ahead] for _, row in sorted(rows.values())]
    _write_csv(os.path.join(master_dir, "monster_asset.csv"), ahead, arows)
