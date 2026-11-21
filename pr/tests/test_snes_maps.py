"""Offline tests for the kit's SNES map tools (tools/snes_maps.py, snes_rooms.py). T-Edition's maps are
tested in tests/test_ted_maps.py.

  pr/.venv/Scripts/python -m unittest discover -s pr/tests -p "test_snes_maps.py" -v

  * the readers: per-map record ranges (offsets that don't rise, as in T-Edition's map 130), the US
    tables, tile properties, tilesets
  * the map table (data/snes_pr_maps.json): coverage, known pairs, every kept pair walks where the
    SNES walks (snes_maps.walk_agreement)
  * snes_rooms: the rule order of its counts, the "room ends here" cells, an SNES cell's picture
Tests needing the US ROM or the PR extract skip without them.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import prdata as P  # noqa: E402
import snes_maps as SM  # noqa: E402
import snes_rooms as R  # noqa: E402


def us_rom():
    if not P.VANILLA_ROM or not os.path.exists(P.VANILLA_ROM):
        raise unittest.SkipTest("no US ROM")
    with open(P.VANILLA_ROM, "rb") as f:
        return f.read()


class Ranges(unittest.TestCase):
    def test_rising(self):
        t = SM.Tables(maps=4)
        rom = bytes([0, 0, 6, 0, 6, 0, 12, 0, 18, 0])
        self.assertEqual(t.ranges(rom, 0), [(0, 6), (6, 6), (6, 12), (12, 18)])

    def test_out_of_order(self):
        # map 1's records were put after the table (T-Edition's map 130): it runs to the next offset
        # above it; map 0 ends where map 2 starts
        t = SM.Tables(maps=4)
        offs = [0, 30, 6, 12, 18]
        rom = b"".join(o.to_bytes(2, "little") for o in offs) + bytes(40)
        self.assertEqual(t.ranges(rom, 0), [(0, 6), (30, 30), (6, 12), (12, 18)])


class UsTables(unittest.TestCase):
    def test_counts(self):
        rom = us_rom()
        tot = {k: sum(len(SM.map_data(rom, m)[k]) for m in range(416)) for k in ("npcs", "events", "exits", "chests")}
        self.assertGreater(tot["npcs"], 2000)
        self.assertGreater(tot["chests"], 250)
        self.assertEqual(SM.exits(rom, 0)[0]["tiles"], [(30, 6)])     # WoB: Narshe's cliffs exit
        self.assertEqual(SM.exits(rom, 0)[0]["dest"], 14)

    def test_tile_props(self):
        rom = us_rom()
        props = SM.tile_props(rom, 126)
        self.assertEqual(len(props), 256)
        self.assertTrue(any(p[0] == SM.WALL for p in props))

    def test_tileset(self):
        rom = us_rom()
        form = SM.tileset(rom, 9)
        self.assertEqual(len(form), 256)
        self.assertEqual(SM.tile_likeness(form[150], form[150]), 4)


class Table(unittest.TestCase):
    def setUp(self):
        if not os.path.exists(SM.DATA_FILE):
            raise unittest.SkipTest("no data/snes_pr_maps.json")

    # table() and to_pr's walkable-room choice read the PR's own map list and tilemaps (pr/vanilla, the player's
    # extract): a kit clone without it skips these two
    @unittest.skipUnless(os.path.isdir(os.path.join(P.VANILLA, "master")), "no PR extract (pr/vanilla)")
    def test_coverage(self):
        self.assertGreaterEqual(len(SM.table()), 315)   # 319 on 2026-11-20 (was 242)

    @unittest.skipUnless(os.path.isdir(os.path.join(P.VANILLA, "master")), "no PR extract (pr/vanilla)")
    def test_known(self):
        self.assertEqual(SM.to_pr(126, 55, 5), ("Map_20451_2", 55, 8))
        self.assertEqual(SM.pr_maps(0)[0].pr, "Map_10010")

    def test_world_tags(self):
        """The door pass's rooms and the world tags (snes_maps.build, 2026-11-21): rooms reached by vanilla's
        doors walk where the SNES walks; a World of Ruin scene on a World of Balance room is tagged cross."""
        with open(SM.DATA_FILE, encoding="utf-8") as f:
            doc = json.load(f)["maps"]
        rows = [e for es in doc.values() for e in es]
        if not any("world" in e for e in rows):
            self.skipTest("a table built before the door pass")
        doors = [e for e in rows if e["how"] in ("door", "door-in")]
        self.assertGreater(len(doors), 100)
        self.assertTrue(all(e["walk"][0] >= SM.DOOR_WALK_MIN for e in doors))
        self.assertTrue(any(e["pr"] == "Map_20340" and e["cross"] for e in doc.get("157", [])))

    def test_lookalikes(self):
        """Mobliz's inn and arsenal (0xA0/0xA1) share their layout with Thamasa's rooms: the Thamasa rows are
        lookalikes, the Mobliz exit pairs aren't (lookups keep the map's own pair first)."""
        with open(SM.DATA_FILE, encoding="utf-8") as f:
            doc = json.load(f)["maps"]
        if not any("lookalike" in e for es in doc.values() for e in es):
            self.skipTest("a table built before the lookalike tags")
        for m, own in ((0xA0, "Map_20111_1"), (0xA1, "Map_20111_2")):
            rows = doc[str(m)]
            self.assertEqual((rows[0]["pr"], rows[0]["how"], rows[0]["lookalike"]), (own, "exits", False))
            thamasa = [e for e in rows if e["pr"].startswith(("Map_20461", "Map_20271"))]
            self.assertTrue(thamasa and all(e["lookalike"] for e in thamasa))
        # Figaro Castle's basement: both worlds (SNES_WORLD_OVERRIDES)
        self.assertTrue(all(e["world"] in ("both", None) or not e["cross"] for m in range(0x3D, 0x43)
                            for e in doc.get(str(m), [])))

    def test_world_tag(self):
        self.assertEqual(SM.world_tag({"WoB"}, {"WoR"}), ("both", True))
        self.assertEqual(SM.world_tag({"WoR"}, {"WoR"}), ("WoR", False))
        self.assertEqual(SM.world_tag({"WoB", "WoR"}, {"WoR"}), ("both", False))
        self.assertEqual(SM.world_tag(None, None), (None, False))

    @unittest.skipUnless(os.path.isdir(os.path.join(P.VANILLA, "master")), "no PR extract (pr/vanilla)")
    def test_links_detail(self):
        d = SM.pr_map_dirs()["Map_20071_4"]
        gotos, points = SM.pr_links(d)
        doors, pts = SM.pr_links(d, detail=True)
        self.assertEqual({(g[0], g[1], g[2], g[3]) for g in gotos} - {(x["x"], x["y"], x["map_id"], x["point_id"]) for x in doors}, set())
        self.assertTrue(all(x["file"].endswith(".json") and x["id"] is not None and x["layer"] for x in doors))
        self.assertEqual({k: (v["x"], v["y"]) for k, v in pts.items()}, points)

    def test_pairs_walk(self):
        with open(SM.DATA_FILE, encoding="utf-8") as f:
            doc = json.load(f)["maps"]
        bad = [(m, e["pr"], e["walk"]) for m, es in doc.items() for e in es
               if e.get("walk") and e["walk"][0] is not None and e["walk"][1] >= 8 and e["how"] != "manual"
               and e["walk"][0] < (0.4 if e["how"] in ("chests", "exits") else 0.8)]
        self.assertEqual(bad, [])


class Rooms(unittest.TestCase):
    def test_rule_order(self):
        t = R.Tiles()
        wall, floor = ("a", 1), ("a", 2)
        t.add(5, 0, (1, 1, 1, 1), (0, 0), (wall, 0, 0, 0), 1, shape=(0, 0, 0, 0))
        t.add(5, 0, (2, 2, 2, 2), (0, 0), (floor, 0, 0, 0), 0, shape=(1, 1, 1, 1))
        t.add(5, 0, (3, 3, 3, 3), (0, 0), (floor, 0, 0, 0), 0, shape=(1, 1, 1, 1))
        self.assertEqual(t.stack(5, 0, (1, 1, 1, 1))[0][0], wall)            # its neighbourhood first
        self.assertEqual(t.stack(5, 0, (9, 9, 9, 9), shape=(0, 0, 0, 0)), ((wall, 0, 0, 0), 1))  # then walls around
        self.assertEqual(t.stack(5, 0, (9, 9, 9, 9))[0][0], floor)           # then the most common
        self.assertEqual(t.stack(6, 0), (None, 3))
        self.assertEqual(t.collision(5, 0, (0, 0)), 0)
        self.assertEqual(t.stack(5, 0, ok=lambda s: s[0] != floor)[0][0], wall)   # atlases the group lacks skipped

    def test_cut(self):
        # a passable cell the PR blocks, with a passable neighbour outside its room: the room ends there
        props = [(0, 0)] * 256
        props[9] = (SM.WALL, 0xFF)
        bg1 = [[9, 9, 9, 9], [9, 1, 1, 1], [9, 9, 9, 9]]
        walk = {(1, 1)}
        self.assertTrue(R.cut(bg1, props, walk, 2, 1, 0, 0))
        self.assertFalse(R.cut(bg1, props, walk, 0, 0, 0, 0))   # a wall

    def test_picture(self):
        rom = us_rom()
        lk = R.Look(rom, 353)
        self.assertEqual(len(lk.cell(150, 0)), 16 * 16 * 3)
        self.assertEqual(lk.key(150, 0), lk.key(150, 0))
        self.assertNotEqual(lk.key(150, 0), lk.key(1, 0))
        self.assertEqual(len(lk.signature(150, 0)), 48)


if __name__ == "__main__":
    unittest.main()
