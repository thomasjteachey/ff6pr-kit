"""The porter's equipment and natural-magic decoding: weapon Evade/MBlock (port_effects), worn statuses
(port_resist), natural-magic learners behind a JSR or a JSL at C0/A182 (port_spells). Offline, seconds:
synthetic bytes first; the checks against the game's data skip without it (the US ROM in rom/vanilla,
the PR's tables in vanilla/, the WC / BC test ROMs).

    .venv/Scripts/python -m unittest tests.test_porter_items -v
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import ff6snes as S  # noqa: E402
import idmap as M  # noqa: E402
import port_effects as E  # noqa: E402
import port_resist as R  # noqa: E402
import port_spells as PS  # noqa: E402
import prdata as P  # noqa: E402

PROJECT = os.path.normpath(os.path.join(HERE, "..", ".."))
WC_ROMS = {os.path.join(HERE, "..", "build", "snes-test", "gaadl68ix7j4.sfc"): (2, 5),
           os.path.join(HERE, "..", "build", "snes-test", "WC xbcuil6p80kr.sfc"): (11, 1)}
BC_DIR = os.path.join(PROJECT, "build", "beyond-chaos")
HAVE_TABLES = os.path.exists(os.path.join(P.MASTER, "weapon.csv"))


def item(**bytes_):
    """A 30-byte SNES item record, zero but for the given bytes (b8=..., b25=...)."""
    raw = bytearray(30)
    for k, v in bytes_.items():
        raw[int(k[1:])] = v
    return bytes(raw)


class FakeRom:
    def __init__(self, size=0x400000):
        self.data = bytearray(size)

    def put(self, off, hexbytes):
        b = bytes.fromhex(hexbytes)
        self.data[off:off + len(b)] = b


class EvadeMBlock(unittest.TestCase):
    """Weapon byte 26: both nibbles are ff6snes.EVADE_STEPS (bug: Evade was nibble * 10, -10% became +60)."""

    def test_evade_steps(self):
        self.assertEqual([E.evade_step(n) for n in range(16)],
                         [0, 10, 20, 30, 40, 50, -10, -20, -30, -40, -50, 0, 0, 0, 0, 0])
        for n in range(16):   # the same value port.py writes from ff6snes.Item
            self.assertEqual(E.evade_step(n), S.Item(0, "", item(b26=n)).evade)

    def test_mblock_functions(self):
        # +10/20/30/50: the PR's equip abilities (as vanilla's weapons); +40 and the negatives: function 67
        self.assertIsNone(E.weapon_mblock(0))
        self.assertEqual([E.weapon_mblock(n) for n in (1, 2, 3, 5)],
                         [(62, 256, 0, 0), (62, 257, 0, 0), (62, 258, 0, 0), (62, 259, 0, 0)])
        self.assertEqual(E.weapon_mblock(4), (67, 40, 0, 0))
        self.assertEqual([E.weapon_mblock(n) for n in range(6, 11)], [(67, v, 0, 0) for v in (-10, -20, -30, -40, -50)])
        self.assertEqual([E.weapon_mblock(n) for n in range(11, 16)], [None] * 5)

    @unittest.skipUnless(HAVE_TABLES, "no PR tables")
    def test_function_67_is_what_the_mblock_abilities_run(self):
        # vanilla's MBlock +10/20/30/50 abilities (256-259) run function group 103-106 = (67, value, 0, 0)
        ab, fg = P.Table("ability"), P.Table("function_group")
        for nibble in (1, 2, 3, 5):
            f, ability = E.WEAPON_MBLOCK[nibble][0], E.WEAPON_MBLOCK[nibble][1]
            self.assertEqual(f, 62)
            g = fg[int(ab[ability]["menu_function_group_id"])]
            self.assertEqual((int(g["function1_id"]), int(g["function1_value1"]), g["function1_value2"],
                              g["function1_value3"], g["function2_id"]),
                             (E.MBLOCK_FUNC, E.evade_step(nibble), "0", "0", "0"))

    @unittest.skipUnless(os.path.exists(P.VANILLA_ROM) and HAVE_TABLES, "no US ROM / PR tables")
    def test_weapon_target(self):
        van = S.Rom(P.VANILLA_ROM)
        ep = E.EffectPorter(van, van, {}, lambda m: None)
        raw = next(it.raw for it in S.items(van) if it.type == "weapon" and it.raw[26] == 0 and M.item(it.id))
        for b26, evade, func in ((0x66, "-10", (67, -10, 0, 0)), (0x4A, "-50", (67, 40, 0, 0)),
                                 (0x51, "10", (62, 259, 0, 0)), (0xA0, "0", (67, -50, 0, 0))):
            t = ep.weapon_target(raw[:26] + bytes([b26]) + raw[27:], E.VANILLA_SPECIALS)
            self.assertEqual(t["evasion_rate"], evade)
            self.assertIn(func, t["wear_function_group_id"])
        # vanilla's own weapons: the Evade the rules give is the one port.py gives
        for it in S.items(van):
            if it.type == "weapon":
                self.assertEqual(ep.weapon_target(it.raw, E.VANILLA_SPECIALS)["evasion_rate"], str(it.evade))


class WornStatuses(unittest.TestCase):
    """Bytes 8 and 25: statuses equipment puts on its wearer (bug: byte 25 and weapons were never read,
    byte 8's Slow was missing)."""

    def test_byte_8(self):
        self.assertEqual(R.worn(item(b8=0x6A)), {(20, "1"), (21, "1"), (22, "1"), (23, "1")})   # Marvel Shoes
        self.assertEqual(R.worn(item(b8=0x04)), {(25, "1")})                                    # Slow
        self.assertEqual(R.worn(item(b8=0x10)), set())                                          # Stop: counted
        self.assertEqual(R.unported_worn(item(b8=0x14)), [(8, 4)])

    def test_byte_25(self):
        self.assertEqual(R.worn(item(b25=0x79)), {(14, "1"), (6, "1"), (18, "1"), (12, "1"), (16, "1")})
        self.assertEqual(R.worn(item(b25=0x04)), {(19, "1")})
        self.assertEqual(R.unported_worn(item(b25=0x82)), [(25, 1), (25, 7)])
        self.assertEqual(R.worn(item(b8=0x08, b25=0x10)), {(21, "1"), (18, "1")})

    @unittest.skipUnless(os.path.exists(P.VANILLA_ROM) and HAVE_TABLES, "no US ROM / PR tables")
    def test_learned_from_vanilla(self):
        # every vanilla item's worn statuses are in its PR wear group (the Cursed Ring's Condemned is
        # the PR's own Doom 75: R.ResistPorter.wear keeps it with that item)
        cg = P.Table("condition_group")
        groups = {}
        for r in cg:
            groups.setdefault(int(r["group_id"]), set()).add((int(r["condition_id"]), r["type_id"]))
        seen = 0
        for it in S.items(S.Rom(P.VANILLA_ROM)):
            m = M.item(it.id)
            if not m or m[0] == "item" or not (it.raw[8] or it.raw[25]):
                continue
            have = groups.get(int(P.Table(m[0])[m[1]]["wear_condition_group_id"]), set())
            want = R.worn(it.raw)
            if it.name.strip() == "Cursed Ring":
                self.assertEqual((want, have), ({(14, "1")}, {(75, "1")}))
                continue
            self.assertLessEqual(want, have, it.name)
            self.assertEqual(R.unported_worn(it.raw), [], it.name)
            seen += 1
        self.assertEqual(seen, 11)   # Cursed Shield, Force Shield, Thornlet, Mirage Vest, the rings, shoes...


class NaturalLearners(unittest.TestCase):
    """C0/A182: vanilla's compares, WC's JSR, a JSL (bug: a JSL fell back to vanilla's learners)."""

    learners = staticmethod(PS.LearningPorter.natural_learners)

    def test_vanilla_compares(self):
        rom = FakeRom()
        rom.put(0xA182, "C9 00 F0 10 C9 06 F0 2E")
        self.assertEqual(self.learners(rom), {"terra": 0, "celes": 6})

    def test_jsr(self):
        rom = FakeRom()
        rom.put(0xA182, "20 65 9F EA")
        rom.put(0x9F65, "C9 02 D0 05 48 20 96 A1 68 C9 05 D0 05 48 20 B8 A1 68 60")
        self.assertEqual(self.learners(rom), {"terra": 2, "celes": 5})

    def test_jsl_compares(self):
        # a routine elsewhere calling the learners with JSLs; Celes's left as vanilla's compare after it
        rom = FakeRom()
        rom.put(0xA182, "22 00 10 F1 C9 06 F0 2E 4C DA A1")
        rom.put(0x311000, "C9 04 D0 06 48 22 96 A1 C0 68 6B")
        self.assertEqual(self.learners(rom), {"terra": 4, "celes": 6})

    def table_rom(self, chars=12, celes_branch=False):
        rom = FakeRom()
        rom.put(0xA182, "22 00 0C F0" + (" C9 06 F0 2E" if celes_branch else " EA EA EA EA") + " 4C DA A1")
        # CMP #chars; BCS (to an RTL); ...; JSR $0C40; RTL -- and at $0C40: LDY #$0010, LDA $F00D01,X (level),
        # LDA $F00D00,X (spell)
        rom.put(0x300C00, f"C9 {chars:02X} B0 FB 48 DA 5A C2 20 A9 00 00 E2 20 20 40 0C 7A FA 68 6B")
        rom.put(0x300C40, "A0 10 00 A5 08 BF 01 0D F0 C5 0B B0 08 BF 00 0D F0 A8 E8 E8 88 D0 F0 60")
        rom.data[0x300D00:0x300D00 + 32 * chars] = b"\xFF" * (32 * chars)
        rom.put(0x300D00 + 32 * 3, "05 02 0A 09 05 0C")             # character 3: spells 5 (lv 2), 10 (lv 9)
        return rom

    def test_jsl_table(self):
        log = []
        out = self.learners(self.table_rom(), log.append)
        self.assertEqual(out, {"terra": None, "celes": None, "table": {3: [(5, 2), (10, 9)]}})
        self.assertIn("a table per character", log[0])
        out = self.learners(self.table_rom(celes_branch=True))
        self.assertEqual((out["terra"], out["celes"]), (None, 6))

    def test_jsl_table_must_be_magic(self):
        rom = self.table_rom()
        rom.put(0x300D00, "80 05")                                     # spell 0x80: not natural magic
        log = []
        self.assertEqual(self.learners(rom, log.append), {"terra": 0, "celes": 6})
        self.assertIn("can't read", log[0])

    def test_jsl_unknown(self):
        rom = FakeRom()
        rom.put(0xA182, "22 00 20 F2")
        rom.put(0x322000, "A9 01 8D 00 20 6B")
        log = []
        self.assertEqual(self.learners(rom, log.append), {"terra": 0, "celes": 6})
        self.assertIn("vanilla's learners kept", log[0])

    @unittest.skipUnless(os.path.exists(P.VANILLA_ROM), "no US ROM")
    def test_real_roms(self):
        self.assertEqual(self.learners(S.Rom(P.VANILLA_ROM)), {"terra": 0, "celes": 6})
        for path, (terra, celes) in WC_ROMS.items():
            if os.path.exists(path):
                self.assertEqual(self.learners(S.Rom(path)), {"terra": terra, "celes": celes})
        bc = sorted(os.path.join(BC_DIR, f) for f in os.listdir(BC_DIR) if f.endswith(".sfc")) if os.path.isdir(BC_DIR) else []
        for path in bc:
            d = S.rom_bytes(path)
            if bytes(d[0xA182:0xA186]) != bytes([0x22, 0x00, 0x0C, 0xF0]):
                continue
            out = self.learners(S.Rom(path))
            # the table bc_codes.natural_magic reads (F0/0C6C, 12 x 16 pairs)
            want = {c: PS.natural_pairs(d[0x300C6C + 32 * c:0x300C6C + 32 * c + 32]) for c in range(12)}
            self.assertEqual(out["table"], {c: p for c, p in want.items() if p})


class GroupIds(unittest.TestCase):
    """SpellPorter's new function/condition groups never reuse an id another porter added to the shared table
    since it started (BNW: four armors' wear effects were overwritten by the MP heal's and the Jackpot's)."""

    class Rows:
        def __init__(self, rows):
            self.rows = rows

        def __iter__(self):
            return iter(self.rows.values())

    def porter(self, fg_rows, cg_rows):
        from collections import defaultdict
        sp = PS.SpellPorter.__new__(PS.SpellPorter)          # no ROM: only the allocators' state
        sp.fg, sp.cg = self.Rows(dict(fg_rows)), self.Rows(dict(cg_rows))
        sp.next_fg = max(sp.fg.rows) + 1
        sp.next_group = max(int(r["group_id"]) for r in sp.cg) + 1
        sp.next_cg_row = max(sp.cg.rows) + 1
        sp.fg_cache, sp.changed = {}, defaultdict(set)
        return sp

    def test_function_group_after_another_porters_rows(self):
        sp = self.porter({10: {"id": "10"}}, {5: {"id": "5", "group_id": "3"}})
        self.assertEqual(sp.function_group([[1, 2, 3, 0]]), 11)              # no clash: as before
        sp.fg.rows[12] = {"id": "12", "mine": "port_effects"}                 # another porter's row
        sp.fg.rows[13] = {"id": "13", "mine": "port_effects"}
        gid = sp.function_group([[12, 428, 0, 0]])
        self.assertEqual(gid, 14)
        self.assertEqual(sp.fg.rows[12]["mine"], "port_effects")

    def test_condition_group_after_another_porters_rows(self):
        sp = self.porter({10: {"id": "10"}}, {5: {"id": "5", "group_id": "3"}})
        self.assertEqual(sp.new_condition_group([14]), 4)                     # no clash: as before (group 4, row 6)
        sp.cg.rows[7] = {"id": "7", "group_id": "9", "condition_id": "1"}     # another porter's group 9, row 7
        gid = sp.new_condition_group([12, 18])
        self.assertEqual(gid, 10)
        self.assertEqual(sorted(sp.cg.rows), [5, 6, 7, 8, 9])
        self.assertEqual(sp.cg.rows[7]["group_id"], "9")

    def test_group_table_after_another_writers_rows(self):
        import groups as G
        t = self.Rows({1: {"id": "1", "group_id": "1", "condition_id": "3", "type_id": "1"}})
        t.columns = ["id", "group_id", "condition_id", "type_id"]
        gt = G.GroupTable("condition_group", "condition_id", ["type_id"], t)
        self.assertEqual(gt.find_or_create({(5, "1")}), 2)                     # no clash: as before (row 2)
        t.rows[3] = {"id": "3", "group_id": "7", "condition_id": "9", "type_id": "1"}   # another writer's group 7
        self.assertEqual(gt.find_or_create({(6, "1")}), 8)
        self.assertEqual(sorted(t.rows), [1, 2, 3, 4])
        self.assertEqual(t.rows[3]["group_id"], "7")


if __name__ == "__main__":
    unittest.main()
