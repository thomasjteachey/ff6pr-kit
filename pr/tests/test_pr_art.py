"""Offline tests for the kit's tools/pr_art.py (art for ArtSwap: ArtWriter, monster image keys, packing, pivots).

  pr/.venv/Scripts/python -m unittest discover -s pr/tests -p "test_pr_art.py" -v

Synthetic images only; the table test needs the game's extracted tables (pr/vanilla), skipped without them.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PR = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PR, "tools"))
try:
    import kitpath  # noqa: F401  (a mod repository's kit/ submodule; a bare kit clone has none)
except ImportError:
    pass
import pr_art  # noqa: E402


def solid(w, h, rgb=(200, 10, 10)):
    return bytes([*rgb, 255]) * (w * h)


class Images(unittest.TestCase):
    def test_pivot(self):
        # the old SNES box (8, 8)-(24, 32): bottom-centre (16, 32); a 16x16 picture at the grid's top left
        self.assertEqual(pr_art.pivot([8, 8, 24, 32], 16, 16, 0, 0), [1.0, -1.0])
        # the same box drawn exactly: bottom-centre, the PR's own convention
        self.assertEqual(pr_art.pivot([8, 8, 24, 32], 16, 24, 8, 8), [0.5, 0.0])
        self.assertEqual(pr_art.pivot(None, 10, 10, 0, 0), [0.5, 0.0])

    def test_apply_table_is_port_sprites(self):
        import port_sprites as PS
        px = bytearray(solid(4, 4))
        px[3] = 0                                   # a clear pixel keeps its bytes
        px[4:8] = bytes([1, 2, 3, 255])
        table = {(200, 10, 10): (0, 0, 255), (1, 2, 3): (9, 9, 9)}
        self.assertEqual(pr_art.apply_table(bytes(px), table), PS.apply_table(bytes(px), table))

    def test_pack_shelves(self):
        imgs = {f"K{i}": (30 + i % 7, 40 + i % 5, solid(30 + i % 7, 40 + i % 5)) for i in range(80)}
        pages = pr_art.pack_shelves(imgs, width=256)
        seen = {}
        for png, rects in pages:
            self.assertTrue(png.startswith(b"\x89PNG"))
            boxes = list(rects.values())
            for a in range(len(boxes)):
                x, y, w, h = boxes[a]
                self.assertLessEqual(x + w, 256)
                for b in range(a):
                    X, Y, W, H = boxes[b]
                    self.assertFalse(x < X + W and X < x + w and y < Y + H and Y < y + h, "overlap")
            seen.update(rects)
        self.assertEqual(set(seen), set(imgs))

    def test_thumbnail_size(self):
        self.assertEqual(len(pr_art.thumbnail(20, 30, solid(20, 30))), pr_art.THUMB * pr_art.THUMB * 4)
        self.assertEqual(len(pr_art.thumbnail(120, 90, solid(120, 90))), pr_art.THUMB * pr_art.THUMB * 4)


class Writer(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pr_art_")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_art_json(self):
        w = pr_art.ArtWriter(self.dir)
        w.character("bc_ff6_p001", {"Default_00": solid(32, 32), "Idle_00": solid(32, 32, (1, 1, 1))}, field="mo_ff6_p001")
        w.face("fa_ff6_p001", solid(40, 40))
        w.ui("UI_Common_WindowFrame01", 100, 100, solid(100, 100), border=(45, 45, 45, 45))
        asset = {"id": "1", "group_name": "mn_ff6_001", "asset_name": "c00"}
        key = w.monster(5, "mn_ff6_001", asset, 20, 30, solid(20, 30), pivot=(0.25, -0.5))
        key2 = w.monster(450, "mn_ff6_001", asset, 10, 10, solid(10, 10), pr_id=1066, asset_id=3066, thumb=False)
        w.save()
        art = json.load(open(os.path.join(self.dir, "art.json"), encoding="utf-8"))
        s = art["sprites"]
        self.assertIn("Assets/GameAssets/Serial/Res/Chara/Battle/BC_FF6_P001/Idle_00", s)
        self.assertEqual(set(art["atlases"]["MO_FF6_P001"]), {"Default_00", "Idle_00"})
        self.assertEqual(s["Assets/GameAssets/Serial/Res/Chara/Face/FA_FF6_P001/Default_00"]["pivot"], [0.5, 0.5])
        ui = s["Assets/GameAssets/Common/UI/Common/Sprites/UI_Common_WindowFrame01"]
        self.assertEqual((ui["ppu"], ui["border"], ui["preload"]), (100, [45, 45, 45, 45], True))
        self.assertEqual(key, "MN_FF6_001_B005")
        m = s[f"Assets/GameAssets/Serial/Res/Battle/Monster/MN_FF6_001/{key}"]
        self.assertEqual((m["pivot"], m["preload"]), ([0.25, -0.5], True))
        self.assertEqual(art["keys"]["mn_ff6_001"][key2], f"Assets/GameAssets/Serial/Res/Battle/Monster/MN_FF6_001/{key2}")
        self.assertIn("mt_ff6_001_b005", art["keys"])          # a thumbnail for 5, none for 450 (thumb=False)
        self.assertNotIn("mt_ff6_001_b450", art["keys"])
        self.assertEqual(w.monster_rows[6][0], 2005)            # defaults: PR row m+1, asset 2000+m
        self.assertEqual(w.monster_rows[1066], (3066, dict(asset, id="3066", asset_name="b450")))
        for e in s.values():                                    # every entry names a written PNG
            self.assertTrue(os.path.exists(os.path.join(self.dir, e["png"])), e["png"])

    def test_writers_merge(self):
        a = pr_art.ArtWriter(self.dir)
        a.face("fa_ff6_p002", solid(40, 40))
        a.save()
        b = pr_art.ArtWriter(self.dir)
        b.ui("UI_Common_WindowFrame02", 100, 100, solid(100, 100))
        b.save()
        art = json.load(open(os.path.join(self.dir, "art.json"), encoding="utf-8"))
        self.assertEqual(len(art["sprites"]), 2)

    def test_standalone_battle_textures_keep_field_atlas(self):
        from PIL import Image
        w = pr_art.ArtWriter(self.dir, standalone_battle=True)
        w.character("bc_ff6_p001", {"Default_00": solid(32, 32), "Idle_00": solid(32, 32)}, field="mo_ff6_p001")
        w.monster(0, "mn_ff6_001", {"group_name": "mn_ff6_001"}, 20, 30, solid(20, 30), thumb=False)
        w.save()
        with open(os.path.join(self.dir, "art.json"), encoding="utf-8") as f:
            art = json.load(f)
        char = art["sprites"]["Assets/GameAssets/Serial/Res/Chara/Battle/BC_FF6_P001/Idle_00"]
        mon = art["sprites"]["Assets/GameAssets/Serial/Res/Battle/Monster/MN_FF6_001/MN_FF6_001_B000"]
        for entry, size in ((char, (32, 32)), (mon, (20, 30))):
            self.assertEqual(entry["rect"], [0, 0, *size])
            with Image.open(os.path.join(self.dir, entry["png"])) as img:
                self.assertEqual(img.size, size)
        field = art["atlases"]["MO_FF6_P001"]["Idle_00"]
        self.assertEqual(field["png"], "bc_ff6_p001.png")
        self.assertNotEqual(field["png"], char["png"])

    def test_monster_tables(self):
        try:
            import prdata as P
            vmon = P.Table("monster")
        except Exception:  # noqa: BLE001
            raise unittest.SkipTest("no extracted game tables (pr/vanilla)")
        group, row = pr_art.monster_asset(0)
        w = pr_art.ArtWriter(os.path.join(self.dir, "sprites"))
        w.monster(0, group, row, 8, 8, solid(8, 8))
        mdir = os.path.join(self.dir, *pr_art.MASTER.split("/"))
        pr_art.write_monster_tables(mdir, w.monster_rows)
        import csv
        mon = {r["id"]: r for r in csv.DictReader(open(os.path.join(mdir, "monster.csv"), encoding="utf-8"))}
        self.assertEqual(mon["1"]["monster_asset_id"], "2000")
        self.assertEqual(mon["2"]["monster_asset_id"], vmon.rows[2]["monster_asset_id"])
        assets = {r["id"]: r for r in csv.DictReader(open(os.path.join(mdir, "monster_asset.csv"), encoding="utf-8"))}
        self.assertEqual((assets["2000"]["group_name"], assets["2000"]["asset_name"]), (group, "b000"))


if __name__ == "__main__":
    unittest.main()
