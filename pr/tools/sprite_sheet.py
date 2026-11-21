"""Contact sheet of a monster-image recipe (bnw_data.json "monster_images", port_sprites): for each
image, the PR's art it starts from, the result, and the mod's SNES sprite. Dev PC only (reads the
game's bundles and the mod's ROM); the picture stays on this PC.

    .venv/Scripts/python tools/sprite_sheet.py [recipe.json|bnw_data.json] [out.png] [--rom <mod.sfc>]
"""
import argparse
import base64
import json
import os
import sys
import zlib

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ff6snes as S  # noqa: E402
import port_sprites  # noqa: E402
from snes_sprites import Sprites  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PR = os.path.dirname(HERE)


def build(img):
    """(w, h, rgba) the plugin makes for one recipe entry (Python twin of MonsterImages.cs)."""
    w, h = img["w"], img["h"]
    if "from" in img:
        group = img["group"]
        tw, th, rgba = port_sprites.pr_textures(group)[img["from"]]
        table = {}
        for pair in img.get("map", []):
            a, b = pair.split(":")
            table[tuple(bytes.fromhex(a))] = tuple(bytes.fromhex(b))
        out = bytearray(port_sprites.apply_table(rgba, table))
        for ov64 in ([img["overlay"]] if "overlay" in img else []) + [p["overlay"] for p in img.get("parts", [])]:
            ov = zlib.decompress(base64.b64decode(ov64))
            for k in range(0, len(out), 4):
                if ov[k + 3]:
                    out[k:k + 4] = ov[k:k + 4]
        return tw, th, bytes(out), rgba
    pal = [tuple(bytes.fromhex(c)) for c in img["palette"]]
    idx = zlib.decompress(base64.b64decode(img["pixels"]))
    rgba = b"".join(bytes(pal[v]) + b"\xff" if v else b"\0\0\0\0" for v in idx)
    return w, h, rgba, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("recipe", nargs="?", default=os.path.join(PR, "mods", "BraveNewWorld", "bnw_data.json"))
    ap.add_argument("out", nargs="?", default=os.path.join(PR, "build", "sprites", "monster_images.png"))
    ap.add_argument("--rom", default=os.path.join(os.path.dirname(PR), "build", "brave-new-world", "Brave New World 3.0 FRC.sfc"))
    ap.add_argument("--zoom", type=int, default=2)
    a = ap.parse_args()
    data = json.load(open(a.recipe, encoding="utf-8"))
    recipe = data.get("monster_images", data)
    mod = Sprites(S.Rom(a.rom))
    Z = a.zoom
    cells = []
    bad = 0
    for img in recipe["images"]:
        w, h, out, src = build(img)
        ok = port_sprites.sha1(out) == img["sha1"]
        bad += not ok
        if img.get("monster", -1) < 0:       # the tower: the PR's picture | the result
            cells.append((f"{img['name']}  {img['key']}" + ("" if ok else "  SHA1 MISMATCH"),
                          [Image.frombytes("RGBA", (w, h), src), Image.frombytes("RGBA", (w, h), out)]))
            continue
        sp = mod.sprite(img["monster"])
        snes = Image.frombytes("RGBA", (sp.w, sp.h), sp.rgba()).crop(sp.bbox())
        ims = [Image.frombytes("RGBA", (w, h), src) if src else None, Image.frombytes("RGBA", (w, h), out), snes]
        cells.append((f"{img['monster']} {img['name']}  {img['key']}" + ("" if ok else "  SHA1 MISMATCH"), ims))
    # monsters the porter pointed at another PR asset (shape swaps): the PR art | the SNES sprite
    import prdata as P
    master = os.path.join(os.path.dirname(os.path.abspath(a.recipe)), "master", "Assets", "GameAssets", "Serial", "Data", "Master")
    if os.path.exists(os.path.join(master, "monster.csv")):
        with open(os.path.join(master, "monster.csv"), encoding="utf-8") as f:
            mon = P.Table("monster", f.read())
        vmon, vasset = P.Table("monster"), P.Table("monster_asset")
        names = {e.id: e.name.strip() for e in S.enemies(mod.rom)}
        for mid, row in sorted(mon.rows.items()):
            aid = int(row["monster_asset_id"])
            if aid >= port_sprites.IMAGE_ASSET_BASE or mid not in vmon.rows or int(vmon.rows[mid]["monster_asset_id"]) == aid:
                continue
            i = mid - 1
            if i >= port_sprites.N:
                continue
            va = vasset.rows[aid]
            key = f"{va['group_name'].upper()}_{va['asset_name'].upper()}"
            tex = port_sprites.pr_textures(va["group_name"]).get(key)
            sp = mod.sprite(i)
            if tex is None or sp.bbox() is None:
                continue
            snes = Image.frombytes("RGBA", (sp.w, sp.h), sp.rgba()).crop(sp.bbox())
            cells.append((f"{i} {names.get(i, '?')}  swap: {key}", [None, Image.frombytes("RGBA", tex[:2], tex[2]), snes]))
    cols = 2
    cw = max(sum((im.width * Z + 6) if im else 0 for im in ims) for _, ims in cells) + 12
    rows = [cells[k:k + cols] for k in range(0, len(cells), cols)]
    rh = [max(max(im.height for im in ims if im) for _, ims in r) * Z + 18 for r in rows]
    sheet = Image.new("RGBA", (cw * cols, sum(rh) + 16), (34, 34, 52, 255))
    d = ImageDraw.Draw(sheet)
    d.text((4, 2), "each: the PR's art | the result in the mod's colors | the mod's SNES sprite", fill=(220, 220, 220))
    y = 16
    for r, hgt in zip(rows, rh):
        for c, (title, ims) in enumerate(r):
            x = c * cw + 4
            d.text((x, y), title, fill=(255, 255, 255))
            for im in ims:
                if im is None:
                    x += 6
                    continue
                sheet.alpha_composite(im.resize((im.width * Z, im.height * Z), Image.NEAREST), (x, y + 12))
                x += im.width * Z + 6
        y += hgt
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    sheet.save(a.out)
    print(f"{a.out}: {len(cells)} images, {bad} sha1 mismatches")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
