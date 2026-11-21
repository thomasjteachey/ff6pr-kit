"""The kit's SNES event tools: the decoder (tools/snes_events.py) and the SNES -> PR translator
(tools/event_translate.py), on the US and Japanese ROMs. (T-Edition's commands, text and events:
tests/test_ted_events.py, in T-Edition's repository.)

  * decoding: every event script reachable from every map's entrance, event tiles and NPCs decodes
    with no unknown command in the US ROM and the Japanese ROM; known scenes decode to the commands
    they are; world-map tiles run the world map's own vehicle-script commands;
  * translation, on vanilla scenes the PR also has (event_translate.VALIDATION, short to long): the
    translated script shows the PR scene's dialogue (mostly, in its order), gives the same items,
    starts the same battles, goes to the same maps and sets the same story flags where the learned
    ties know them; every script is well formed (event_translate.check).

Needs the US and JP ROMs (skipped without them); the translation tests need
build/dialog/dialog_map.json (tools/dialog_map.py) and data/snes_event_maps.json (event_translate learn).

  pr/.venv/Scripts/python -m unittest discover -s pr/tests -p "test_snes_events.py" -v
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PR = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PR, "tools"))
import snes_events as E  # noqa: E402

HAVE_US = os.path.exists(E.US_ROM)
HAVE_JP = os.path.exists(E.JP_ROM)
HAVE_DIALOG = os.path.exists(os.path.join(PR, "build", "dialog", "dialog_map.json"))

_progs = {}


def prog(name):
    if name not in _progs:
        _progs[name] = E.Program(E.load(name)).walk_all()
    return _progs[name]


@unittest.skipUnless(HAVE_US and HAVE_JP, "needs the US and JP ROMs")
class Decoder(unittest.TestCase):
    def test_every_vanilla_script_decodes(self):
        for name in ("us", "jp"):
            c = prog(name).coverage()
            self.assertEqual(c["unknown"], {}, name)
            self.assertEqual(c["obj_unknown"], {}, name)
            self.assertGreater(c["instructions"], 44000, name)
            self.assertGreater(c["bytes"], 170000, name)
            # decorations whose NPC record holds no event (mid-script addresses, data)
            self.assertLess(len(c["entries_not_code"]), 80, name)

    def test_command_sizes_from_the_rom(self):
        rom = E.load("us")
        # the ROM's own command table (C0/98C4) agrees with the sizes the decoder uses
        d = rom.data
        handlers = [d[0x98C4 + 2 * i] | d[0x98C4 + 2 * i + 1] << 8 for i in range(203)]
        self.assertEqual(handlers[0xB2 - 0x35], 0xB1A1)    # call
        self.assertEqual(handlers[0xFE - 0x35], 0xB8D7)    # return
        for code, size in ((0x4B, 3), (0x4D, 3), (0x6B, 6), (0xB2, 4), (0xB3, 5), (0xE8, 4), (0x5D, 3), (0x70, 3)):
            self.assertEqual(rom.dialect.ops[code].size, size, hex(code))

    def test_a_known_scene(self):
        # Figaro's hidden wall (tile at map 20 (15, 57)): the scene and its "second time" branch
        p = prog("us")
        names = [p.code[(o, "field")].name for o in (0x2B148, 0x2B14C, 0x2B14E, 0x2B150, 0x2B151, 0x2B153)]
        self.assertEqual(names, ["call", "shake", "sound", "wait_30", "bit_set", "return"])
        self.assertEqual(p.code[(0x2B151, "field")].args["bit"], (0x1F0, True))
        ins = p.code[(0x2B190, "field")]
        self.assertEqual((ins.name, ins.args["dlg"]), ("dialog", 0x1AA))

    def test_world_map_scripts(self):
        # a World of Balance event tile runs the world map's vehicle commands: an if, then a map load
        p = prog("us")
        a = p.code[(0x5EB5, "vehicle")]
        self.assertEqual((a.name, a.args["bits"], a.targets), ("v_if_all", [(0x10B, False)], [("cond", 0x5EB4)]))
        b = p.code[(0x5EBB, "vehicle")]
        self.assertEqual((b.name, b.args["map"], b.next_mode), ("v_map", 0x37, "field"))


@unittest.skipUnless(HAVE_US and HAVE_DIALOG, "needs the US ROM and build/dialog/dialog_map.json")
class Translation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import event_translate as T
        cls.T = T
        cls.results = {a: r for a, *r in T.validate(prog=prog("us"))}

    def test_validation_scenes(self):
        # entry: (min dialogue share, dialogue in the PR's order, items, battles, maps) checked
        expect = {
            "CC/33F4": (1.0, True, None, None, None),
            "CC/0B70": (1.0, None, [213], None, None),
            "CC/0B1E": (1.0, True, [86, 121], None, None),
            "CB/B7F8": (0.8, True, None, [480], None),
            "CB/E767": (0.7, True, None, [450], [186]),
            "CA/9749": (0.85, None, None, None, None),
            "CB/75BF": (0.7, None, None, None, [311, 305, 310]),
        }
        for a, (share, order, items, battles, maps) in expect.items():
            g, res, stubs, done, n = self.results[a]
            self.assertGreaterEqual(res["msgs"]["share"], share, a)
            if order is not None:
                self.assertEqual(res["msgs"]["in_order"], order, a)
            if items is not None:
                self.assertEqual(sorted(res["items"]["ours"]), sorted(items), a)
            if battles is not None:
                self.assertEqual(res["battles"]["ours"], battles, a)
            if maps is not None:
                self.assertEqual(res["maps"]["ours"], maps, a)

    def test_story_flags(self):
        for a, flag in (("CA/7913", ("ScenarioFlag1", 61)), ("CC/0B70", ("ScenarioFlag2", 162)),
                        ("CC/0B1E", ("ScenarioFlag2", 161)), ("CB/B7F8", ("ScenarioFlag1", 117)),
                        ("CA/9749", ("ScenarioFlag1", 149))):
            self.assertIn(flag, [tuple(x) for x in self.results[a][1]["sets"]["ours"]], a)

    def test_scripts_are_well_formed(self):
        T = self.T
        p = prog("us")
        for a in T.VALIDATION:
            off = E.parse_addr(a)
            m = next(e[2] for e in p.entries if e[0] == off)
            sc, t = T.translate(p.rom, off, f"sc_snes_{off:06x}", snes_map=m, prog=p)
            for s in [sc] + [x[1] for x in t.after]:
                self.assertEqual(T.check(s), [], (a, s["Name"]))

    def test_figaro_wall_matches_the_pr(self):
        # the PR's own sc_e_0089: the same two lines in order, the scene's flag (bit 020 =
        # ScenarioFlag1 67, learned), Terra's step down and turn
        T = self.T
        p = prog("us")
        sc, t = T.translate(p.rom, 0x2B133, "sc_x", snes_map=20, prog=p)
        msgs = [m["operands"]["sValues"][0] for m in sc["Mnemonics"] if m["mnemonic"] == "Msg"]
        self.assertEqual(msgs, ["E0089_00_003_a_01", "E0089_00_003_a_02"])
        sets = [(m["operands"]["sValues"][0], m["operands"]["iValues"][0]) for m in sc["Mnemonics"]
                if m["mnemonic"] == "SetFlag"]
        self.assertIn(("ScenarioFlag1", 67), sets)
        moves = [m["operands"]["iValues"][:3] for m in sc["Mnemonics"] if m["mnemonic"] == "Move"]
        self.assertIn([2, 1, -1], moves)

    def test_lost_battle_and_gil(self):
        # after a battle, "lost -> the game-over scene" (CA/5EA9) needs no PR code (Encount's own game
        # over); "not enough gil" (bit 1BE after 85) is RemoveGil's result in MapLocalVariable 0
        T = self.T
        p = prog("us")
        t = T.Translator(p.rom, "sc_x", prog=p)
        self.assertTrue(t.game_over_check(0x5EA9))
        self.assertFalse(t.game_over_check(0x2B148))
        ins = E.Instr.__new__(E.Instr)
        ins.op, ins.off, ins.args = 0xC0, 0, {"bits": [(T.GIL_SHORT, True)], "event": 0x10}
        self.assertEqual([(o["mnemonic"], o["operands"]["iValues"][:3], o["operands"]["sValues"][0]) for o in t.cond(ins)],
                         [("Branch", [0, 0, "@L_000010"], "MapLocalVariable")])

    def test_party_ops(self):
        # 3C (the party is c1-c4) -> OrganizePartySlot [1, ids, 0] as vanilla's pairs (CC/9F6D: 3C 00 0E 0F FF =
        # [1, 1, 31, 32, -2, 0]); 99 with bit 7 of its count (vanilla's 99 81) -> the party menu; walk-in bits decided
        T = self.T
        p = prog("us")
        t = T.Translator(p.rom, "sc_x", prog=p)
        ins = E.Instr.__new__(E.Instr)
        ins.op, ins.off, ins.name, ins.cls, ins.size = 0x3C, 0, "party_set", "party", 5
        ins.mode = ins.next_mode = "field"
        ins.flow, ins.targets, ins.raw = "next", [], b"\x3C\x00\x0E\x0F\xFF"
        ins.args = {"c1": 0, "c2": 0x0E, "c3": 0x0F, "c4": 0xFF}
        ops, ok = t.instr(ins, False, None)
        self.assertEqual([(o["mnemonic"], o["operands"]["iValues"][:6]) for o in ops], [("OrganizePartySlot", [1, 1, 31, 32, -2, 0])])
        ins.op, ins.name, ins.cls, ins.args = 0x99, "party_menu", "menu", {"parties": 0x81, "fixed": 0}
        ops, ok = t.instr(ins, False, None)
        self.assertEqual([(o["mnemonic"], o["operands"]["sValues"][0]) for o in ops], [("SysCall", T.PARTY_MENU.format("１"))])
        ins.op, ins.args = 0xC0, {"bits": [(0x1CC, True)], "event": 0x10}          # if 1CC set: never on a walk-in
        self.assertEqual(t.cond(ins), [])
        ins.op = 0xC8                                                                # any of (1CC clear): always
        ins.args = {"bits": [(0x1CC, False), (0x123, True)], "event": 0x10}
        self.assertEqual([o["mnemonic"] for o in t.cond(ins)], ["Jump"])

    def test_graft(self):
        # a PR script grafted into a translation (a mod's event that ends in vanilla's routine): its
        # code comes along with every jump target a label again, and the result is well formed
        import pr_script as S
        T = self.T
        p = prog("us")
        t = T.Translator(p.rom, "sc_x", snes_map=86, prog=p)
        label = t.graft(S.load("sc_npc_20071_23_1"))
        sc = t.assemble("sc_x", [T.lab("Main"), T.op("Jump", i=["@" + label]), T.op("Exit")], t.blocks)
        self.assertEqual(T.check(sc), [])
        msgs = [m["operands"]["sValues"][0] for m in sc["Mnemonics"] if m["mnemonic"] == "Msg"]
        self.assertIn("N004_C00_061_01_01", msgs)
        # callable: its main-level Exits become Returns (a puppet's Exit stays), so a Call comes back
        label = t.graft(S.load("sc_npc_20071_23_1"), callable_=True)
        sc = t.assemble("sc_x", [T.lab("Main"), T.op("Call", i=["@" + label]), T.op("Exit")], t.blocks)
        self.assertEqual(T.check(sc), [])
        start = next(s["EntryPoint"] for s in sc["Segments"] if s["Label"] == label)
        seg = next(s for s in sc["Segments"] if s["Label"] == label)
        ops = sc["Mnemonics"][start:start + seg["Count"]]
        self.assertFalse([m for m in ops if m["mnemonic"] == "Exit" and m.get("type", 1) == 1])
        self.assertTrue([m for m in ops if m["mnemonic"] == "Return"])


if __name__ == "__main__":
    unittest.main()
