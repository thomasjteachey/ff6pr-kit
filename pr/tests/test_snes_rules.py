"""The kit's SNES battle rules (plugin/PrKit/Ff6) against the SNES game's own data: what a rule's C# list says
is what the US ROM has. Offline, a second; skips without the ROM (rom/vanilla, never shipped).

    .venv/Scripts/python -m unittest tests.test_snes_rules -v
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import ff6snes as S  # noqa: E402
import idmap as M  # noqa: E402
import prdata as P  # noqa: E402

FF6 = os.path.join(HERE, "..", "plugin", "PrKit", "Ff6")


def cs_ints(file, name):
    """The int list of a C# `name = { ... };` in PrKit/Ff6/<file>."""
    text = open(os.path.join(FF6, file), encoding="utf-8").read()
    body = re.search(name + r"\s*=\s*\{([^}]*)\}", text).group(1)
    return [int(x) for x in re.findall(r"\d+", body)]


@unittest.skipUnless(os.path.exists(P.VANILLA_ROM), "no US ROM")
class Vanilla(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.enemies = S.enemies(S.Rom(P.VANILLA_ROM))

    def test_no_suplex_list_is_the_roms(self):
        # monster byte $13 bit 2 ("can't suplex"), as PR monster ids (SnesSuplexRules.VanillaNoSuplex)
        rom = [M.monster(e.id) for e in self.enemies if e.raw[19] & 4]
        self.assertEqual(cs_ints("SnesSuplexRules.cs", "VanillaNoSuplex"), rom)
        named = [e for e in self.enemies if e.raw[19] & 4 and e.name.strip()]
        self.assertEqual(len(named), 146)

    @unittest.skipUnless(os.path.isdir(os.path.join(P.VANILLA, "master")), "no PR extract (pr/vanilla)")
    def test_no_suplex_copies_are_the_coliseums(self):
        # the PR's Coliseum copies (ids 500+) of those monsters, by port.monster_copies (SnesSuplexRules.VanillaNoSuplexCopies)
        import port
        flagged = set(cs_ints("SnesSuplexRules.cs", "VanillaNoSuplex"))
        copies = sorted(c for c, r in port.monster_copies().items() if r in flagged)
        self.assertEqual(cs_ints("SnesSuplexRules.cs", "VanillaNoSuplexCopies"), copies)


if __name__ == "__main__":
    unittest.main()
