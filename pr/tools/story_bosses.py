"""Every story fight of FINAL FANTASY VI PR as a test batch, for any FF6 mod (kit; 2026-11-25).

    .venv/Scripts/python tools/story_bosses.py <bnw|bc|wc|...> [--chunks N] [--out FILE] [--only 464,506]

The story's fights are the parties the game's own event scripts start with EncountBoss (48 in vanilla, found
in vanilla/map_*/.../sc_e_*.json; a mod's Magicite copy of a script overrides vanilla's where it has one). The
batch fights each one in story order (by script number) on the mod's data: the party on auto at 9999 HP, the
enemies brought to 1 HP after a while, the battle must start, its enemies act, and it must end with the field
back. What it catches: a mod's monster, AI, art or rule that stalls or throws in a story fight. What it doesn't:
the scenes around the fights (their own tests), the fight's own win/loss scripting.

Per mod: SETUP (steps before the first fight: a seed for BC, the party for BNW) and KEEP (the mod's "keep battles
moving" command); every fight ends the runner's way (FINISH). A chunk is one game launch: use 4+ chunks for 48 fights
(two machines: the PC runner and tools/remote_batch.py, --only story-bosses-N).
"""
import argparse
import glob
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
PR = os.path.dirname(HERE)

SETUP = {
    "bc": ["until bc mode 240 check bc", "totitle", "bcgen 9859608359 normal New Player",
           "until made in|bcgen: error: 300 check bc", "tofield"],
    "bnw": ["tofield"],
    "wc": ["tofield"],
}
KEEP = {"bc": "bckeep on", "bnw": "aikeep on", "wc": "aikeep on"}
# the runner's own end of a battle (test_batch.END_BATTLE): killall = the mod's endfight or the kit's enemyhp 1,
# then presses until the field is back (a story fight's scripted turns and messages)
FINISH = ["killall", "sleep 6", "endfight", "until scene field 120 repeat press action", "tofield"]
# (the second endfight: reinforcements a death brings in, e.g. party 463's two monster 360s, 2026-11-25)
MAGICITE = {"bc": "BeyondChaos", "bnw": "BraveNewWorld", "wc": "WorldsCollide"}


def walk(o):
    if isinstance(o, dict):
        if o.get("mnemonic") == "EncountBoss":
            yield o["operands"]["iValues"][0]
        for v in o.values():
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)


def story_fights(mod=None):
    """[(party, map, script)] in story order (script number), each party once"""
    scripts = {}
    for f in glob.glob(os.path.join(PR, "vanilla", "map_*", "Assets", "GameAssets", "Serial", "Res", "Map", "**", "sc_e_*.json"),
                       recursive=True):
        scripts[os.path.basename(f)] = f
    if mod in MAGICITE:
        for f in glob.glob(os.path.join(PR, "mods", MAGICITE[mod], "**", "sc_e_*.json"), recursive=True):
            scripts[os.path.basename(f)] = f
    found = {}
    for name, f in scripts.items():
        with open(f, encoding="utf-8") as fh:
            text = fh.read()
        if "EncountBoss" not in text:
            continue
        m = re.search(r"Map_(\d+)", f.replace("\\", "/"))
        for party in walk(json.loads(text)):
            key = (int(re.search(r"sc_e_(\d+)", name).group(1)), name)
            if party not in found or key < found[party][0]:
                found[party] = (key, m.group(1) if m else "?", name[:-5])
    return [(p, mp, sc) for p, (key, mp, sc) in sorted(found.items(), key=lambda kv: kv[1][0])]


def batch(mod, fights, chunks):
    runs = []
    size = (len(fights) + chunks - 1) // chunks
    for i in range(chunks):
        part = fights[i * size:(i + 1) * size]
        if not part:
            continue
        # one request per fight (2026-11-25: one request per chunk stopped the chunk at its first fight the test kill
        # can't end, e.g. BNW's first Ultros, who ends his fight by fleeing; the next request's tofield recovers)
        reqs = []
        for k, (party, mp, sc) in enumerate(part):
            steps = (list(SETUP.get(mod, ["tofield"])) if k == 0 else ["tofield"]) + [KEEP.get(mod, "aikeep on")]
            steps += [f"battle {party}", "until scene battle 60", "sleep 12"] + FINISH
            reqs.append({"id": f"{mod}-story-{party}", "from": "kit story_bosses.py", "keep_going": True,
                         "steps": steps, "pass": [f"battle {party} started"],
                         "fail": "Exception|\\[Error", "note": f"{sc} on map {mp}"})
        runs.append({"name": f"story-bosses-{i + 1}", "kind": "kit" if mod == "bc" else "harness", "graphics": False,
                     "minutes": 4 + 3 * len(part), "requests": reqs})
    return {"name": f"{mod}-story-bosses", "mod": mod, "runs": runs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mod")
    ap.add_argument("--chunks", type=int, default=2)
    ap.add_argument("--only", default="")
    ap.add_argument("--out")
    a = ap.parse_args()
    fights = story_fights(a.mod)
    if a.only:
        keep = {int(x) for x in a.only.split(",")}
        fights = [f for f in fights if f[0] in keep]
    out = a.out or os.path.join(PR, "build", "batches", f"{a.mod}-story-bosses.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(batch(a.mod, fights, a.chunks), f, indent=1)
    print(f"{len(fights)} story fights -> {out}: " + ", ".join(f"{p} ({sc})" for p, mp, sc in fights))


if __name__ == "__main__":
    main()
