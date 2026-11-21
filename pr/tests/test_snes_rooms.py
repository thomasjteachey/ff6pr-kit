"""snes_rooms' learned-tiles cache (pr/cache/snes_rooms_tiles.pickle) registers the PR maps' tileset entries exactly
as learning does (roadmap item 6, 2026-11-20). room_tilesets writes, for each atlas, the entry of the first PR map that
registered it, and 77 of FF6's 173 atlases have entries that differ between maps (tile animations, some images), so a
run that reads the learned Tiles from disk must register the same entries, in the same order, as one that learns them.

  pr/.venv/Scripts/python -m unittest discover -s pr/tests -p "test_snes_rooms.py" -v

Each case runs in its own process (the registry is module state) with a temporary cache file, never the live one;
~1 min (it learns twice). Skips without the PR extract (pr/vanilla) or the vanilla ROM.
"""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.normpath(os.path.join(HERE, "..", "tools"))
sys.path.insert(0, TOOLS)
import prdata as P  # noqa: E402

HAVE = os.path.isdir(P.VANILLA) and os.path.exists(P.VANILLA_ROM)

# learn tiers in order (or read them from the cache) until 20+ atlases are registered (the first tiers have one or
# two maps; the 11th, ~90, brings 27 atlases, 18 of them with entries that differ between maps), then print the
# registry's hash and its atlas names
SCRIPT = r"""
import hashlib, json, sys
sys.path.insert(0, sys.argv[1])
import snes_rooms as R
cache = sys.argv[2]
R.Vanilla._disk_path = staticmethod(lambda: cache)
v = R.vanilla()
for key in v.by_key:
    v.tiles(key)
    if len(R._tileset_entries) >= 20:
        break
reg = json.dumps(list(R._tileset_entries.items()), sort_keys=True)
print(hashlib.sha1(reg.encode()).hexdigest())
print(json.dumps(sorted(R._tileset_entries)))
"""


def differing_atlases():
    """Atlases whose tileset entries differ between the PR's maps (firstgid aside)."""
    import collections
    import json
    import snes_maps as SM
    seen = collections.defaultdict(set)
    for path in SM.pr_tilemaps().values():
        with open(path, encoding="utf-8") as f:
            for ts in json.load(f).get("tilesets", []):
                seen[ts["name"]].add(json.dumps({k: v for k, v in ts.items() if k != "firstgid"}, sort_keys=True))
    return {n for n, v in seen.items() if len(v) > 1}


@unittest.skipUnless(HAVE, "needs pr/vanilla and the vanilla ROM")
class TilesCache(unittest.TestCase):
    def run_once(self, cache, **env):
        e = dict(os.environ, PYTHONHASHSEED="0", **env)
        e.pop("SNES_ROOMS_NOCACHE", None) if "SNES_ROOMS_NOCACHE" not in env else None
        r = subprocess.run([sys.executable, "-c", SCRIPT, TOOLS, cache], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=e, timeout=900)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        sha, names = r.stdout.strip().splitlines()[-2:]
        return sha, names

    def test_cached_registers_like_learning(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            cache = os.path.join(d, "snes_rooms_tiles.pickle")
            off = self.run_once(cache, SNES_ROOMS_NOCACHE="1")
            self.assertFalse(os.path.exists(cache), "SNES_ROOMS_NOCACHE wrote a cache")
            names = set(json.loads(off[1]))
            # the case that matters: atlases whose entry depends on which map registered them first
            self.assertGreaterEqual(len(names & differing_atlases()), 10, f"too few contested atlases learned: {names}")
            cold = self.run_once(cache)
            self.assertTrue(os.path.exists(cache), "the cold run kept no cache")
            warm = self.run_once(cache)
            self.assertEqual(off, cold, "learning with the cache on registers differently")
            self.assertEqual(off, warm, "the learned Tiles read from disk register differently")


class TilePlan(unittest.TestCase):
    """snes_rooms.tile_plan on a made-up 4x3 room (no game files): an event opening a wall cell."""
    FLOOR, WALL = (0, ("a", 1), 0, 0), (0, ("a", 2), 0, 0)

    def setUp(self):
        import snes_rooms as R
        self.R = R
        self.bg1 = [[1, 1, 1, 1], [1, 2, 2, 1], [1, 1, 1, 1]]
        self.bg2 = [[0] * 4 for _ in range(3)]
        self.props = [(0, 0)] * 256
        self.props[2] = (0xF7, 0)                                    # tile 2: a wall
        self.cells = [[(self.WALL if t == 2 else self.FLOOR, 1 if t == 2 else 0) for t in row] for row in self.bg1]

    def plan(self, x, y, tiles, writes=None):
        return self.R.tile_plan(self.cells, (0, 0), self.bg1, self.bg2, self.props, x, y, len(tiles), 1, bytes(tiles),
                                writes=writes)

    def test_open_a_wall(self):
        p = self.plan(1, 1, [1])
        self.assertEqual(p["tag"], "passability")
        (px, py, src, attr), = p["cells"]
        self.assertEqual((px, py), (1, 1))
        self.assertEqual(self.cells[src[1]][src[0]][0], self.FLOOR)   # copied from a floor cell of the same map
        self.assertIsNone(attr)                                       # no model: no collision value

    def test_unchanged_and_put_back(self):
        self.assertEqual(self.plan(1, 1, [2])["tag"], "none")
        p = self.plan(1, 1, [2], writes={(0, 1, 1): True})           # another event opens it: put back as loaded
        self.assertEqual(p["cells"], [(1, 1, (1, 1), 1)])

    def test_layers(self):
        self.assertEqual(self.plan(1, 1 | 2 << 6, [1])["tag"], "bg3")
        self.assertEqual(self.R.stack_gids([{"name": "a", "firstgid": 10}], self.WALL), (0, 12, 0, 0))
        self.assertIsNone(self.R.stack_gids([{"name": "b", "firstgid": 1}], self.WALL))


if __name__ == "__main__":
    unittest.main()
