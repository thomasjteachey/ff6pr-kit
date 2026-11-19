# FF6 Pixel Remaster modding kit

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
