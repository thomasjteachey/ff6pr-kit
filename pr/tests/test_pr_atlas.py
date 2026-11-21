"""tools/pr_atlas.py: a PR SpriteAtlas's frames. Game-free: Sprite and SpriteAtlas records built here in Unity 2019.4's
layout. With the game (FF6PR_GAME or the default Steam library): a field NPC group's frames read back as 32x32."""
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import pr_atlas  # noqa: E402


def _str(s):
    b = s.encode()
    return struct.pack("<i", len(b)) + b + b"\0" * (-len(b) % 4)


def sprite_record(name, key, pivot=(0.5, 0.0)):
    out = _str(name)
    out += struct.pack("<4f", 0, 0, 32, 32) + struct.pack("<2f", 0, -16) + struct.pack("<4f", 0, 0, 0, 0)
    out += struct.pack("<f", 1.0) + struct.pack("<2f", *pivot) + struct.pack("<I", 1)
    out += b"\0\0\0\0"                       # m_IsPolygon, aligned
    return out + key + b"\0" * 64            # the render key, then what follows (not read)


def atlas_record(name, entries):
    """entries: [(frame name, key, texture path id, x, y, w, h)]"""
    out = _str(name) + struct.pack("<i", len(entries)) + b"".join(struct.pack("<iq", 0, 7 + k) for k in range(len(entries)))
    out += struct.pack("<i", len(entries)) + b"".join(_str(e[0]) for e in entries)
    out += struct.pack("<i", len(entries))
    for _, key, tex, x, y, w, h in entries:
        rec = key + struct.pack("<iq", 0, tex) + struct.pack("<iq", 0, 0) + struct.pack("<4f", x, y, w, h)
        rec += struct.pack("<2f", 0, 0) + struct.pack("<2f", 0, 0) + struct.pack("<4f", 1, 0, 1, 0)
        rec += struct.pack("<f", 1.0) + struct.pack("<I", 3)
        assert len(rec) == 104
        out += rec
    return out


class Records(unittest.TestCase):
    def test_sprite(self):
        key = bytes(range(16)) + struct.pack("<q", 21300000)
        d = b"\xAA" * 8 + sprite_record("WalkB_02", key)
        self.assertEqual(("WalkB_02", key, (0.5, 0.0)), pr_atlas._sprite(d, 8))
        name, k2, _ = pr_atlas._sprite(sprite_record("Fall_00", key, (0.5, 0.25)), 0)   # a name of another length
        self.assertEqual(("Fall_00", key), (name, k2))

    def test_atlas(self):
        k1 = bytes(16) + struct.pack("<q", 1)
        k2 = bytes([1] * 16) + struct.pack("<q", 2)
        d = atlas_record("MO_FF6_N048_C00", [("Default_00", k1, 99, 72, 60, 32, 32), ("Fall_00", k2, 99, 108, 96, 32, 32)])
        got = pr_atlas._atlas(d, 0)
        self.assertEqual({k1: (99, 72.0, 60.0, 32.0, 32.0), k2: (99, 108.0, 96.0, 32.0, 32.0)}, got)


class Game(unittest.TestCase):
    """mo_ff6_n048_c00 (a scholar: 10 frames on one 256x128 texture) from this PC's game."""

    def setUp(self):
        import pr_art
        try:
            self.art = pr_art.GameArt()
            self.path = self.art.bundle("mo_ff6_n048_c00")
        except (OSError, FileNotFoundError):
            self.path = None
        if not self.path:
            raise unittest.SkipTest("no game")

    def test_frames(self):
        fr = pr_atlas.frames(self.path)
        self.assertEqual({"Default_00", "Default_01", "Default_02", "Fall_00", "WalkB_00", "WalkB_01", "WalkB_02",
                          "WalkL_00", "WalkL_01", "WalkL_02"}, set(fr))
        for name, (w, h, rgba) in fr.items():
            self.assertEqual((32, 32, 32 * 32 * 4), (w, h, len(rgba)), name)
            self.assertTrue(any(rgba[3::4]), name + " has pixels")

    def test_sprites(self):
        sp = pr_atlas.sprites(self.path)
        self.assertEqual([0.5, 0.0], sp["Default_00"]["pivot"])
        for name, e in sp.items():
            x, y, w, h = e["rect"]
            self.assertTrue(0 <= x and 0 <= y and x + w <= 256 and y + h <= 128, name)


if __name__ == "__main__":
    unittest.main()
