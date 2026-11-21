"""tools/pr_scene_cut.py (kit): a cut scene keeps its indices, labels and state steps; menus take the given answer.

  .venv/Scripts/python -m unittest tests.test_pr_scene_cut -v

The cut is checked in a small script model of its own: flow (Branch on story flags, variables and the menu answer,
Jump, Call/Return, Exit, ChangeMap/ChangeScript ending the run) and the state steps it went through; every other
instruction is a step that just happens.
"""
import copy
import glob
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PR = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PR, "tools"))
import prdata as P  # noqa: E402
import pr_script as S  # noqa: E402
import pr_scene_cut as C  # noqa: E402

CMP = {"＝": lambda a, b: a == b, "≠": lambda a, b: a != b, "≧": lambda a, b: a >= b, "≦": lambda a, b: a <= b,
       "＞": lambda a, b: a > b, "＜": lambda a, b: a < b}
FLOW = {"Nop", "Branch", "Jump", "Call", "Return", "Exit", "ChangeMap", "ChangeScript"}


def run(sc, answers=(), limit=50000):
    """(the steps that aren't flow or show, how it ended): a Select takes the next answer (0 when none left)."""
    ms, vals, stack, steps, out = sc["Mnemonics"], {}, [], 0, []
    answers = list(answers)
    pc = 0
    while pc < len(ms):
        steps += 1
        if steps > limit:
            return out, ("loop",)
        o = ms[pc]
        mn, iv, sv = o["mnemonic"], o["operands"]["iValues"], o["operands"]["sValues"]
        nxt = pc + 1
        if mn == "Branch":
            b = iv[1] if sv[2] == "imm" else vals.get((sv[2], iv[1]), 0)
            key = ("MessageSelection", 0) if sv[0] == "MessageSelection" else (sv[0], iv[0])   # one answer, any index
            if CMP.get(sv[1], lambda a, b: False)(vals.get(key, 0), b):
                nxt = iv[2] + 1
        elif mn == "Jump":
            nxt = iv[0] + 1
        elif mn == "Call":
            stack.append(pc + 1)
            nxt = iv[0] + 1
        elif mn == "Return":
            if not stack:
                return out, ("Return",)
            nxt = stack.pop()
        elif mn == "Exit":
            return out, ("Exit",)
        elif mn in ("ChangeMap", "ChangeScript"):
            return out, (mn, tuple(iv[:2]), sv[0])
        elif mn == "Select":
            vals[("MessageSelection", 0)] = answers.pop(0) if answers else 0
        elif mn in ("SetFlag", "ResetFlag"):
            vals[(sv[0], iv[0])] = 1 if mn == "SetFlag" else 0
        elif mn == "Calc" and sv[1] == "←":
            vals[(sv[0], iv[0])] = iv[1] if sv[2] == "imm" else vals.get((sv[2], iv[1]), 0)
        elif mn == "Calc" and sv[1] == "＋":
            vals[(sv[0], iv[0])] = vals.get((sv[0], iv[0]), 0) + (iv[1] if sv[2] == "imm" else vals.get((sv[2], iv[1]), 0))
        if mn not in FLOW and mn not in C.SHOW:
            out.append((mn, tuple(iv[:3]), tuple(sv[:2])))
        pc = nxt
    return out, ("end",)


def menu_script():
    ops = [S.label("Main"), S.op("Msg", s=["K1"]), S.op("Select", s=["A", "B", "C"]),
           S.op("Branch", i=[0, 1, "@b"], s=["MessageSelection", "＝", "imm"]),
           S.op("Branch", i=[0, 2, "@c"], s=["MessageSelection", "＝", "imm"]),
           S.op("SetFlag", i=[1], s=["ScenarioFlag1"]), S.op("Exit"),
           S.label("b"), S.op("Wait", r=[1.0]), S.op("SetFlag", i=[2], s=["ScenarioFlag1"]), S.op("Exit"),
           S.label("c"), S.op("SetFlag", i=[3], s=["ScenarioFlag1"]), S.op("Exit")]
    S._resolve(ops, 0)
    return {"Mnemonics": ops, "Segments": [{"Label": "Main", "EntryPoint": 0, "Count": len(ops)}], "Name": "t"}


class Cut(unittest.TestCase):
    def test_menu_takes_the_answer(self):
        for answer in (0, 1, 2):
            sc = menu_script()
            want = run(copy.deepcopy(sc), answers=[answer])
            C.cut(sc, answer)
            self.assertEqual(run(sc), want, answer)
            self.assertFalse([o for o in sc["Mnemonics"] if o["mnemonic"] in C.SHOW])

    def test_indices_labels_and_segments_stay(self):
        sc = menu_script()
        before = [(o["label"], o["mnemonic"] in C.SHOW) for o in sc["Mnemonics"]]
        segs = copy.deepcopy(sc["Segments"])
        C.cut(sc)
        self.assertEqual([o["label"] for o in sc["Mnemonics"]], [b[0] for b in before])
        self.assertEqual(sc["Segments"], segs)

    @unittest.skipUnless(os.path.isdir(os.path.join(P.VANILLA, "master")), "no PR extract (pr/vanilla)")
    def test_vanilla_scenes_keep_their_state(self):
        """Every vanilla scene script (sc_e_*): the cut reaches the same state steps and end as the original, menus
        answered 0 (the model's limit: scripts that loop in it are compared as looping)."""
        files = glob.glob(os.path.join(P.VANILLA, "map_*", "**", "sc_e_*.json"), recursive=True)
        self.assertGreater(len(files), 1000)
        cut_any = 0
        for f in files:
            with open(f, encoding="utf-8") as fh:
                try:
                    sc = json.load(fh)
                except ValueError:
                    continue
            c = copy.deepcopy(sc)
            cut_any += C.cut(c) > 0
            self.assertEqual(len(c["Mnemonics"]), len(sc["Mnemonics"]), f)
            self.assertEqual(run(c), run(sc), os.path.basename(f))
        self.assertGreater(cut_any, 1000)


if __name__ == "__main__":
    unittest.main()
