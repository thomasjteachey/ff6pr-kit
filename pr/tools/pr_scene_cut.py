"""Cut a PR scene down to what it does: the same script without its show (kit tool, any Pixel Remaster event script).

  .venv/Scripts/python tools/pr_scene_cut.py NAME [--answer N]     # what a cut keeps and drops of a vanilla script

A mod that removes cutscenes (Beyond Chaos's notawaiter; Worlds Collide and Brave New World cut scenes by hand) wants
the scene's effects without the scene: its story flags, variables, party changes, items and gil, entity layers,
battles, map changes, vehicles, music, recoveries and autosaves, and every SysCall, but none of its lines, menus,
puppets, moves, animations, waits, fades out, shakes, flashes or sounds. cut() does that in place, keeping every
instruction at its index: a dropped one becomes a plain Nop (an unlabelled Nop runs as nothing; a label stays where it
was), so every jump, branch and call target (instruction indices, tools/pr_script.py) stays valid and the script's
segments too. A menu (Select) takes a given answer: the Select becomes a Nop and the MessageSelection branches right
after it become a Jump (the first whose comparison holds for that answer: ＝, ≠, ＜...) or Nops; when none holds the
script falls through, as the game does when no branch matches.

What stays a judgement for the mod: which scripts to cut (the scene's own scripts, not optional talk), and the answer
each menu takes. tests/test_pr_scene_cut.py checks the cut against the original in a small script model.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pr_script as S  # noqa: E402

EQ = "＝"
CMP = {"＝": lambda a, b: a == b, "≠": lambda a, b: a != b, "≧": lambda a, b: a >= b, "≦": lambda a, b: a <= b,
       "＞": lambda a, b: a > b, "＜": lambda a, b: a < b}   # Branch's comparisons (category value OP operand)

# the show: instructions a cut turns into Nops
SHOW = frozenset({
    "Msg", "MsgClose", "MsgFunfare", "Select",                                 # lines and menus
    "Wait",                                                                     # timing
    "SetPuppet", "ExecPuppet", "FinishPuppet",                                  # puppets
    "Move", "MoveTo", "LookAt", "SetPos", "PlayAnim", "CueAnim", "Lerp", "Route", "AssignMoveRoute", "Orient",
    "RideVehicleNPC",                                                           # an NPC's ride (animation)
    "PlaySE", "StopSE", "SyncSE",                                               # sounds
    "Shake", "Flash", "ColorFade", "ScreenEffect", "FadeOut", "ShowMapTitle", "Blank", "Water",   # screen
})


def _nop(o):
    return S.op("Nop", label=o.get("label", ""), kind=o.get("type", 1))


def cut(sc, answer=0):
    """Cut a script in place (SHOW -> Nop; menus answered `answer`). Returns how many instructions were cut."""
    ms = sc["Mnemonics"]
    n = 0
    for k, o in enumerate(ms):
        mn = o["mnemonic"]
        if mn not in SHOW:
            continue
        ms[k] = _nop(o)
        n += 1
        if mn != "Select":
            continue
        j = k + 1
        while j < len(ms) and ms[j]["mnemonic"] == "Branch" and ms[j]["operands"]["sValues"][0] == "MessageSelection":
            iv, sv = ms[j]["operands"]["iValues"], ms[j]["operands"]["sValues"]
            hit = sv[2] == "imm" and CMP.get(sv[1], lambda a, b: False)(answer, iv[1])
            ms[j] = S.op("Jump", i=[iv[2]], label=ms[j].get("label", "")) if hit else _nop(ms[j])
            j += 1
            if hit:
                break
    return n


def kept(sc):
    """The instructions a cut keeps that change something (not flow, not Nops): [(index, mnemonic)]."""
    flow = {"Nop", "Branch", "Jump", "Call", "Return", "Exit", "BranchByLeader", "BranchByCharacter",
            "BranchByNumOfMember", "BranchByPlayerDirection"}
    return [(k, o["mnemonic"]) for k, o in enumerate(sc["Mnemonics"]) if o["mnemonic"] not in SHOW | flow]


if __name__ == "__main__":
    import collections
    import copy
    args = sys.argv[1:]
    answer = 0
    if "--answer" in args:
        i = args.index("--answer")
        answer = int(args[i + 1])
        del args[i:i + 2]
    if not args:
        sys.exit(__doc__)
    for name in args:
        sc = S.load(name)
        c = copy.deepcopy(sc)
        n = cut(c, answer)
        dropped = collections.Counter(o["mnemonic"] for o in sc["Mnemonics"] if o["mnemonic"] in SHOW)
        print(f"{name}: {len(sc['Mnemonics'])} instructions, {n} cut ({', '.join(f'{k} {v}' for k, v in dropped.most_common())})")
        print("  kept: " + ", ".join(f"{k}:{m}" for k, m in kept(c)))
