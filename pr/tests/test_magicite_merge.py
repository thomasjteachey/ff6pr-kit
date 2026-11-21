"""The kit's three-way Magicite merge (tools/magicite_merge.py), on small made-up folders.

    pr/.venv/Scripts/python -m unittest tests.test_magicite_merge
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
import magicite_merge as MM  # noqa: E402

PKG = "map_1/Assets/GameAssets/Serial/Res/Map/Map_1/package.json"
ENT = "map_1/Assets/GameAssets/Serial/Res/Map/Map_1/Map_1_1/entity_default.json"
CSV = "master/Assets/GameAssets/Serial/Data/Master/script.csv"
TXT = "message/Assets/GameAssets/Serial/Data/Message/system_en.txt"


def write(root, rel, content):
    p = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(content if isinstance(content, str) else json.dumps(content))


def read(root, rel):
    with open(os.path.join(root, *rel.split("/")), encoding="utf-8", newline="") as f:
        return f.read()


class Merge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.van, self.a, self.b, self.out = (os.path.join(self.tmp, n) for n in ("van", "a", "b", "out"))
        pkg = {"name": "Map_1", "map": [{"name": "Map_1_1", "script": [{"name": "sc_1", "asset": "x"}]}]}
        ent = {"layers": [{"name": "L", "objects": [{"id": 1, "name": "chest", "properties": [{"name": "item", "value": 5}]},
                                                    {"id": 2, "name": "npc", "properties": [{"name": "script", "value": 10}]}]}]}
        write(self.van, PKG, pkg)
        write(self.van, ENT, ent)
        write(self.van, CSV, "id,name,value\n1,a,10\n2,b,20\n")
        write(self.van, TXT, "K1\tvanilla one\r\nK2\tvanilla two\r\n")
        # side a (the porter): a chest's item, a new script, a table row, a text line
        pa = json.loads(json.dumps(pkg))
        pa["map"][0]["script"].append({"name": "sc_a", "asset": "a"})
        ea = json.loads(json.dumps(ent))
        ea["layers"][0]["objects"][0]["properties"][0]["value"] = 99
        write(self.a, PKG, pa)
        write(self.a, ENT, ea)
        write(self.a, CSV, "id,name,value\n1,a,11\n")
        write(self.a, TXT, "K1\tmod one\r\n")
        write(self.a, "map_1/keys/a.json", {"keys": ["package"], "values": ["Assets/x/package"]})
        # side b (new maps / events): a new room, an NPC's script, a new object, another row and line
        pb = json.loads(json.dumps(pkg))
        pb["map"].append({"name": "Map_1_2", "script": []})
        eb = json.loads(json.dumps(ent))
        eb["layers"][0]["objects"][1]["properties"][0]["value"] = 77
        eb["layers"][0]["objects"].append({"id": 3, "name": "door", "properties": []})
        write(self.b, PKG, pb)
        write(self.b, ENT, eb)
        write(self.b, CSV, "id,name,value\n2,b,21\n9,new,90\n")
        write(self.b, TXT, "K2\tmod two\r\nK9\tnew line\r\n")
        write(self.b, "map_1/keys/b.json", {"keys": ["package", "Map_1_2/tilemap"], "values": ["Assets/x/package", "Assets/x/t"]})

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def merged(self):
        shutil.copytree(self.a, self.out)
        return MM.merge(self.out, [self.b], vanilla=self.van, log=lambda *_: None)

    def test_both_sides_kept(self):
        rep = self.merged()
        self.assertEqual(rep.conflicts, [])
        pkg = json.loads(read(self.out, PKG))
        self.assertEqual([m["name"] for m in pkg["map"]], ["Map_1_1", "Map_1_2"])
        self.assertEqual([s["name"] for s in pkg["map"][0]["script"]], ["sc_1", "sc_a"])
        objs = {o["id"]: o for o in json.loads(read(self.out, ENT))["layers"][0]["objects"]}
        self.assertEqual(objs[1]["properties"][0]["value"], 99)
        self.assertEqual(objs[2]["properties"][0]["value"], 77)
        self.assertIn(3, objs)
        self.assertEqual(read(self.out, CSV).splitlines(), ["id,name,value", "1,a,11", "2,b,21", "9,new,90"])
        self.assertEqual(read(self.out, TXT), "K1\tmod one\r\nK2\tmod two\r\nK9\tnew line\r\n")
        keys = json.loads(read(self.out, "map_1/keys/a.json"))
        self.assertEqual(keys["keys"], ["package", "Map_1_2/tilemap"])
        self.assertFalse(os.path.exists(os.path.join(self.out, "map_1", "keys", "b.json")))

    def test_conflict_reported(self):
        write(self.b, CSV, "id,name,value\n1,a,12\n")   # both changed row 1's value differently
        rep = self.merged()
        self.assertEqual(len(rep.conflicts), 1)
        self.assertIn("id 1", rep.conflicts[0][1])
        self.assertIn("1,a,11", read(self.out, CSV))     # the destination's value kept


if __name__ == "__main__":
    unittest.main()
