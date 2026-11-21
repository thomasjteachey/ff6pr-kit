"""tools/magicite_check.py: a Magicite folder's packages, scripts, tables and texts, and two folders shipping one file.

    pr/.venv/Scripts/python -m unittest tests.test_magicite_check -v
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import magicite_check as M  # noqa: E402

PKG = "map_20071/Assets/GameAssets/Serial/Res/Map/Map_20071"


def write(root, rel, data):
    p = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(data if isinstance(data, str) else json.dumps(data))


def package(*scripts, maps=("Map_20071_1",)):
    return {"name": "Map_20071", "asset_group_name": "map_20071", "texture": [],
            "map": [{"name": m, "tilemap": f"{m}/tilemap", "collision": f"{m}/collision", "entity_default": f"{m}/entity_default",
                     "entity": [], "script": [{"name": s, "asset": f"{m}/{s}"} for s in scripts], "route_instruction": []}
                    for m in maps]}


class MagiciteCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="magicite_check_")
        self.game = os.path.join(self.tmp, "vanilla")
        # the game's map: its package lists sc_map_20071_1, with its tilemap, collision and entity layer
        write(self.game, f"{PKG}/package.json", package("sc_map_20071_1"))
        for a in ("tilemap", "collision", "entity_default", "sc_map_20071_1"):
            write(self.game, f"{PKG}/Map_20071_1/{a}.json", {})

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def folder(self, name):
        return os.path.join(self.tmp, name)

    def run_check(self, *folders):
        return M.check([self.folder(f) for f in folders], vanilla=self.game).errors

    def test_a_good_folder(self):
        write(self.folder("Mod"), f"{PKG}/package.json", package("sc_map_20071_1", "sc_mod_1"))
        write(self.folder("Mod"), f"{PKG}/Map_20071_1/sc_mod_1.json", {"Mnemonics": []})
        write(self.folder("Mod"), "master/Assets/GameAssets/Serial/Data/Master/item.csv", "id,name\n1,a\n2,b\n")
        write(self.folder("Mod"), "message/Assets/GameAssets/Serial/Data/Message/system_en.txt", "K_1\tone\nK_2\ttwo\n")
        write(self.folder("Mod"), "map_20071/keys/mod.json", {"keys": []})
        self.assertEqual(self.run_check("Mod"), [])

    def test_a_script_its_package_doesnt_list(self):
        # T-Edition, 2026-11-20: the script file shipped, the package without it: "didn't start (not in this map's list?)"
        write(self.folder("Mod"), f"{PKG}/package.json", package("sc_map_20071_1"))
        write(self.folder("Mod"), f"{PKG}/Map_20071_1/sc_new.json", {})
        errs = self.run_check("Mod")
        self.assertEqual(len(errs), 1)
        self.assertIn("sc_new.json: not listed", errs[0])

    def test_a_script_the_games_package_doesnt_list(self):
        write(self.folder("Mod"), f"{PKG}/Map_20071_1/sc_new.json", {})
        errs = self.run_check("Mod")
        self.assertTrue(errs and "the game's" in errs[0], errs)

    def test_a_script_replacing_the_games_is_fine(self):
        write(self.folder("Mod"), f"{PKG}/Map_20071_1/sc_map_20071_1.json", {"changed": 1})
        self.assertEqual(self.run_check("Mod"), [])

    def test_a_listed_script_that_isnt_anywhere(self):
        write(self.folder("Mod"), f"{PKG}/package.json", package("sc_map_20071_1", "sc_missing"))
        errs = self.run_check("Mod")
        self.assertTrue(errs and "lists Map_20071_1/sc_missing" in errs[0], errs)

    def test_names_listed_twice(self):
        write(self.folder("Mod"), f"{PKG}/package.json", package("sc_map_20071_1", "sc_map_20071_1"))
        errs = self.run_check("Mod")
        self.assertTrue(any("listed twice" in e for e in errs), errs)

    def test_json_that_doesnt_parse(self):
        write(self.folder("Mod"), "battleextradata/Assets/x.json", "{oops")
        errs = self.run_check("Mod")
        self.assertTrue(errs and "doesn't parse" in errs[0], errs)

    def test_table_ids_twice(self):
        write(self.folder("Mod"), "master/Assets/GameAssets/Serial/Data/Master/item.csv", "id,name\n1,a\n1,b\n")
        errs = self.run_check("Mod")
        self.assertTrue(errs and "ids twice" in errs[0], errs)

    def test_text_keys_twice(self):
        write(self.folder("Mod"), "message/Assets/GameAssets/Serial/Data/Message/system_en.txt", "K_1\tone\nK_1\tagain\n")
        errs = self.run_check("Mod")
        self.assertTrue(errs and "keys twice" in errs[0], errs)

    def test_two_folders_one_package(self):
        # BNW's map_20071 package hid T-Edition's (2026-11-20): the game reads one copy
        for name in ("A", "B"):
            write(self.folder(name), f"{PKG}/package.json", package("sc_map_20071_1"))
        errs = self.run_check("A", "B")
        self.assertEqual(len(errs), 1)
        self.assertIn("in both A and B", errs[0])

    def test_two_folders_own_files_and_keys_dont_clash(self):
        for name in ("A", "B"):
            write(self.folder(name), "map_20071/keys/k.json", {"keys": []})
            write(self.folder(name), "bnw_data.json", {})
        self.assertEqual(self.run_check("A", "B"), [])

    def test_the_command_line(self):
        write(self.folder("Mod"), f"{PKG}/Map_20071_1/sc_new.json", {})
        self.assertEqual(M.main([self.folder("Mod"), "--vanilla", self.game, "--quiet"]), 1)
        os.remove(os.path.join(self.folder("Mod"), *f"{PKG}/Map_20071_1/sc_new.json".split("/")))
        self.assertEqual(M.main([self.folder("Mod"), "--vanilla", self.game, "--quiet"]), 0)


if __name__ == "__main__":
    unittest.main()
