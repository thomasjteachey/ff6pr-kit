"""The public modding-kit repository (ff6pr-kit): what every mod of this project builds on.

    .venv/Scripts/python tools/kit_publish.py [OUT]     (default: ../../ff6pr-kit)

The porter (SNES FF6 mod -> Pixel Remaster data), PrKit (the C# library plugins compile in),
prkit/kit.py (games, extract, package, deploy, headless runs), the harnesses and the decompiling
tools, with the project's layout (pr/...). No mod's own code: Worlds Collide and Brave New World
have their own repositories and pin this one as their kit/ submodule (tools/repo_publish.py).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bnw_text  # noqa: E402
import repo_publish as R  # noqa: E402

DEFAULT_OUT = R.KIT_REPO

PARTS = [
    ("pr/plugin/PrKit", ["**"]),
    ("pr/plugin/PrKit.Tests", ["**"]),
    ("pr/tools", ["*.py", "*.sh", "*.ps1"]),
    ("pr/tools/prkit", ["**"]),
    ("pr/tools/ghidra", ["**"]),
    ("pr/tools/TypeDump", ["**"]),
    ("pr/tests", ["test_prkit.py"]),
    ("pr", ["MODDING.md", "PORTING.md"]),
]
# prkit/migrate_wc.py moves the WC plugin onto PrKit inside this project (one use, then deleted)
NOT_PUBLISHED = {"pr/tools/prkit/migrate_wc.py"}

README = """# FF6 Pixel Remaster modding kit

The shared base of this project's mods for the Steam FINAL FANTASY Pixel Remasters (FF6 above
all): what turns an SNES FF6 mod into Pixel Remaster data, the library their BepInEx plugins
compile in, and the tools to build, test, package and install them.

The mods have their own repositories and pin this one as their `kit/` git submodule:

- [Worlds Collide](https://github.com/thomasjteachey/ff6pr-worlds-collide), the open-world randomizer, played in the Pixel Remaster
- [Brave New World](https://github.com/thomasjteachey/ff6pr-brave-new-world) (in development)

## What's here

- `pr/tools/port.py` and `port_*.py`: the porter. It diffs a modded FF6 ROM (US v1.0 layout)
  against vanilla and writes a Magicite mod: characters, items, spells, espers, monsters and
  their AI, formations, encounters, shops, chests, text. A mod's settings are its profile
  (`profiles.py`; a mod repository adds its own as `profile_<name>.py`).
- `pr/tools/prdata.py`, `ff6snes.py`, `idmap.py`: the Pixel Remaster's tables, the SNES game's
  tables, and the mapping between them.
- `pr/tools/snes_ai.py`, `ai_compile.py`, `port_ai.py`: FF6's monster AI scripts, read and
  compiled to the Pixel Remaster's.
- `pr/plugin/PrKit`: the C# library a plugin compiles in (`PrKit.props`): hooking rules,
  switchable features, master data and text, headless test runs, a test harness.
- `pr/tools/kit.py` (package `prkit`): every PR game Steam has installed, extract a game's data,
  set up BepInEx + Magicite, start a mod, check, package and deploy it, run the game headless.
  `pr/MODDING.md` is the guide.
- `pr/tools/snes_harness.py`: a windowless SNES (a libretro core in-process) for side-by-side
  checks against the SNES game. `pr/tools/game_harness.py`: talk to a plugin's harness in a
  headless game run.
- `pr/tools/ghidra`, `pr/tools/TypeDump`: decompile the game's code (Ghidra, headless) and dump
  its types, to find what to hook.
- `pr/PORTING.md`: the project's full development log.

No game files and no ROMs are here or in any mod built with it: a mod makes the copies it
needs on the player's machine from their own game.

## Use

    git clone <this repo> kit          # or: git submodule add <this repo> kit, in a mod repository
    cd kit/pr && python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
    .venv/Scripts/python tools/kit.py games
    .venv/Scripts/python tools/kit.py extract ff6          # pr/vanilla from your game

As a mod repository's `kit/` submodule, the tools work on that repository's `pr/` (its data,
builds and output): `prdata.ROOT`, `prkit.PR` and `deploy.sh` find it themselves
(`FF6PR_ROOT` overrides), and the mod's own tools put the kit on their path (`kitpath.py`).

Needs Windows, the game with BepInEx 6 (IL2CPP) and Magicite, .NET 6 SDK, Python 3.12, and the
US v1.0 SNES ROM for the porter (never shipped).

## Credits

BepInEx, Il2CppInterop, HarmonyX; Magicite by Silvris; Il2CppDumper, Ghidra. FINAL FANTASY is
Square Enix's; this is unofficial fan tooling.
"""


def main():
    out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT)
    entries = [(s, n) for s, n in R.collect(PARTS, exclude=R.mod_tools) if n not in NOT_PUBLISHED]
    entries.append((bnw_text.VWF_TBL, "pr/data/vwf.tbl"))  # the menu font's text table (description decoding)
    # the SNES chests' areas for the chest matcher (port_chests.wc_areas), from Worlds Collide (MIT)
    entries.append((os.path.join(R.PR, "data", "snes_chest_areas.json"), "pr/data/snes_chest_areas.json"))
    entries.append((os.path.join(R.PROJECT, "mods", "worlds-collide", "LICENSE.txt"), "pr/data/LICENSE-WorldsCollide.txt"))
    texts = {"README.md": README, ".gitignore": R.GITIGNORE_COMMON, "pr/requirements.txt": R.REQUIREMENTS,
             "pr/modkit.json": R.manifest(keep=())}
    print("kit publish:", R.write(out, entries, texts), "->", out)


if __name__ == "__main__":
    main()
