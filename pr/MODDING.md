# Modding kit: any Final Fantasy Pixel Remaster

The kit (PrKit, 2026-11-11) is the shared layer for mods of FF1-FF6 Pixel Remaster: the tooling
that finds and extracts a game, writes and checks its data, builds, installs, packages and tests
a mod; and the plugin library every BepInEx plugin compiles in. A new feature is one class, and a
new mod is one command. PORTING.md holds the FF6 port's history and its lessons. This file is
how to build on them.

| Layer | Where | What it gives a mod |
|---|---|---|
| Game registry | `tools/prkit/games.py` | the six PRs, found through Steam's own library list; every path (exe, `_Data`, bundles, BepInEx, Magicite, the Deck's copy) |
| Game data | `tools/prkit/data.py`, `magicite.py` | read the extracted tables/text; write a Magicite folder (changed rows only); check one loads |
| Manifest | `pr/modkit.json`, `tools/prkit/mods.py` | every mod: its game, plugin, data, build steps, conflicts |
| Build, install, ship | `tools/prkit/deploy.py`, `package.py`, `bepinex.py` | PC + Steam Deck installs, player zips, BepInEx for a new game |
| Tests | `tools/prkit/headless.py`, `plugin/PrKit/TestRun.cs`, `Harness.cs` | headless runs (no window, no sound, no saves), commands over TCP |
| Plugin library | `plugin/PrKit/*.cs` (+ `PrKit.props`) | safe hooks, switchable features, master data/text, live data, gamepad fix |
| Start a mod | `tools/prkit/scaffold.py` | plugin + example feature + data script + test + manifest entry |
| Seeds in game (randomizers) | `plugin/PrKit/Seeds` (opt-in `<PrKitSeeds>`), `tools/seed_live.py`, `seed_info.py` | a randomizer's flags screen, its generator run in the background, seeds applied live and kept per save (Worlds Collide, Beyond Chaos) |

Everything is behind one command: `.venv/Scripts/python tools/kit.py <command>` (from `pr/`).

## A new mod in five commands

```bash
.venv/Scripts/python tools/kit.py games                          # what's installed, BepInEx/interop/Magicite
.venv/Scripts/python tools/kit.py new-mod FiveJobs --game ff5    # plugin, feature, data script, test, manifest
.venv/Scripts/python tools/data_fivejobs.py                      # the mod's game data -> build/FiveJobs/magicite
.venv/Scripts/python tools/kit.py deploy fivejobs --pc           # build + install (the game closed)
.venv/Scripts/python tools/kit.py package fivejobs               # build/dist/FiveJobs-PR-0.1.0.zip
```

`new-mod` options: `--title`, `--id`, `--no-data` (a plugin only), `--no-plugin` (data only).
The scaffold's plugin builds as made (`PRKIT_BUILD=1` in `tests/test_prkit.py` checks that).

## A new game (FF5 and the others)

None but FF6 is installed on this PC (2026-11-11). With one installed through Steam:

1. `kit.py games`: finds it from Steam's `libraryfolders.vdf` and `appmanifest_<appid>.acf`
   (`PRKIT_FF5_DIR=...` if it's somewhere else).
2. `kit.py setup ff5`: BepInEx 6 + Magicite copied from FF6's install (the same files for every
   PR), listed in `pr/games/ff5/install-files.txt`.
3. Start the game once yourself: BepInEx generates `BepInEx/interop` (the game's code as .NET
   assemblies) on that first start. Close it.
4. `kit.py games --write-props`: `plugin/PrKit/Games.props` gets the game's folder, so every plugin
   with `<PrGame>ff5</PrGame>` builds against it.
5. `kit.py extract ff5`: its tables, text and scripts -> `pr/games/ff5/vanilla` (FF6's stay in
   `pr/vanilla`). `kit.py api ff5`: every type/field/method -> `pr/games/ff5/vanilla/Assembly-CSharp.api.txt`,
   where hook targets are found. Decompiling (Ghidra, PORTING.md "Decompiled game code") takes
   the game's `GameAssembly.dll` and `global-metadata.dat` the same way.

The first `kit.py deploy` of a mod to the Deck sends BepInEx there and sets that game's Proton
prefix to load BepInEx's `winhttp.dll` (`tools/deck_winhttp_override.py <appid> <process>`).

## Game data (Magicite)

Every PR keeps its data the same way: `master/.../Master/<table>.csv` (tables), `message/.../Message/<file>_<lang>.txt`
(text: `key<TAB>text`), map/battle scripts and other JSON in their own groups. A Magicite mod folder
holds only what it changes, plus `keys/*.json` per group naming each asset by the game's address
(`assetspath/.../AssetsPath.json`: `item` for a table, `Map_20011_2/sc_e_0021` for a map script).

```python
from prkit import data, magicite
game = data.GameData("ff5")                     # the extract
mod = magicite.MagiciteMod(OUT, game, keys_name="fivejobs")
items = mod.table("item")                       # an editable copy; only changed rows are written
items.set(1, "buy", 25)
new_id = items.add({"buy": 500}, copy_of=1)     # a new row from an existing one
mod.text()["MSG_ITEM_NAME_1"] = "Potion+"
mod.asset("battleextradata", "Assets/GameAssets/Serial/Data/BattleExtraData/battle_extra_data.json", {...})
mod.write()
problems, notes = magicite.validate(OUT, game)
```

`validate` (also `kit.py check <mod>`) flags what doesn't load or does nothing: a keys entry with no
file, a file no keys entry names, a table whose columns differ from the game's (it reads them by
position), a text line without a tab, an address that is the game's but for another file. Notes are
new assets and new row ids (often intended). BNW's and WC's folders pass with no problems.

Tables a mod usually touches (FF6 names; the other PRs share most): `character_status`,
`growth_curve`, `exp_table`, `item`/`weapon`/`armor`, `content` (names/icons for everything),
`ability`, `command`, `job_group` (who equips what), `monster`, `monster_party`, `monster_set`,
`product`/`product_group` (shops), `treasure_box`. Text: `system_en.txt` (names, descriptions),
`story_mes_en.txt` (dialogue). PORTING.md "PR data model" maps them in detail.

### Running the SNES porter (FF6: `tools/port.py`, `tools/port_<mod>.py`)

The porter makes the mod's whole folder (`mods/<Mod>/`) afresh. Anything else kept there must be made
by the port too: a profile's `extra_data(rom)` returns `{file name: data}` written beside the rest (BNW:
`bnw_data.json`, and `bnw_dialog.json` remade from `build/dialog`'s line map).
One port per folder at a time, and nobody reads a half-written one (2026-11-20): `port.main` holds
`mods/<Mod>.porting` (a folder made atomically, `owner.txt` inside: pid, start, command) for the whole
port; a second port of the same folder waits for it (`PORT_LOCK_WAIT` seconds, default 900, then stops
naming the holder), and a lock whose process has ended is taken over. The port writes `mods/<Mod>.new`
and renames it over `mods/<Mod>` at the end, so `mods/<Mod>` is always the last complete port and a
failed port leaves it as it was. Installs and tests of a ported mod wait while `<Mod>.porting` exists.
Every step writes through `profile.out` / its `out_dir` argument, never a path of its own. Files several
ports share (an event flag allocation in `data/`) are written to a temporary file and renamed over.
Its log prints mod names and SNES text: with the output redirected to a file, set
`PYTHONIOENCODING=utf-8`, or a cp1252 console encoding error stops the port half-way.

Opt-in text a profile can ask for: `monster_names = True` (`tools/port_names.py`: the mod's monster
names onto the PR's keys, a key of its own for a monster whose PR key another monster shares; with
`rename_all` every monster's, else only those the mod renamed); a `rage_descriptions()` method
(`{SNES monster: (first attack, second attack)}`: each Rage's description, `port_dances.describe_rages`;
other Rages get their two attacks' names); `dance_descriptions = True` (each dance lists its steps).

Equipment effects in the PR's data (what `port_effects` writes): a weapon's or armor's `wear_function_group_id`
names a `function_group` row of up to three (function, value1-3). Function 62 gives an equip ability:
value1 is an `ability` id whose `menu_function_group_id` holds the effect, e.g. function 60 = (stat 1 HP /
2 MP, numerator, denominator): ability 245 = HP +1/8 (Green Beret), 244 = MP +1/8, 286 = HP +2/8 (Red Cap),
287 = MP +2/8; abilities 256-259 = function 67 (MBlock +10/20/30/50). Function 67 with value1 directly is
MBlock + value1 (the porter uses it for +40 and the negatives). New group ids always come after the table's
current highest: several porters add rows to the same tables (`port_spells`, `groups.GroupTable`).

### A mod that rebuilt FF6's item list (FF6: `tools/item_identity.py`)

The porter puts SNES item slot s on a fixed PR row (`idmap.item`), which holds for mods that keep FF6's
list. A mod that moved items to other slots or changed their kind (T-Edition: a weapon in a shield slot)
sets `item_identity = True` in its profile (and `item_mod_items(rom)` for names its ROM doesn't hold in
the menu table: T-Edition's are Mato's full names). Each slot then gets its identity (the vanilla item of
the same kind and name), its row (the identity's, a free row of its table, or a new one) and a template
whose look the row takes; `idmap.ITEM_OVERRIDES` and a vanilla baseline in the mod's item numbering keep
every other porter as it is. `python tools/item_identity.py tedition` prints the choices. New rows a port
makes go in `prdata.ADDED_ROWS` and get `MSG_PORT_*` text keys. More drop slots than the SNES's two: a
profile's `monster_drop_slots(e)` and `game_constants` for the PR's `MONSTER_DROP_RATE_1..8` odds.

### More monsters and formations than FF6's (FF6: `tools/port_monster_ext.py`)

The porter reads FF6's tables at the US ROM's sizes: 384 monsters, 576 formations, AP for 512. A mod
that grew them (T-Edition: 512 monsters, 768 formations) writes the whole grown tables into its image
past the US layout and registers them from its profile's image build:

```python
import port_monster_ext as X
X.register(data, {"formations": (0x320000, 15, 768), "monsters": (0x324000, 32, 512), ...},
           monster_base=1000, monster_names=[...], special_names=[...], sprites=reader, event_maps={f: [maps]},
           formation_monsters={f: [(e, x, y, shown)]}, event_backgrounds={f: bg}, drop_slots={e: [4 items]})
```

`ff6snes.extended(rom, name)` then gives a table's (offset, size, count), or the profile's data: names,
a sprite reader (`sprite(e)` -> a `snes_sprites.Sprite`), where the mod's events fight each formation.
Names: formations, formation_flags, formation_ap, monsters, monster_items (US 4 bytes), sketches,
monster_graphics, map_properties. `idmap.monster(e)` is e + 1, or `monster_base + e` for a monster past
384 (`idmap.MONSTER_EXT`; the PR's own monster rows end at 611). From there the shared porter reads past
the US tables wherever it builds parties: `port_encounters.formation` / `formation_raw` /
`formation_ap`, random sets, the Veldt, monster-in-a-box chests. Parties of formations 600+ get ids of
their own, 30000 + 1000 k + f (under 600 nothing changes: 2000 + f, then 4000 + 600 k + f);
`port_encounters.first_party_id(f)` is the one a mod's event battles fight.

`port_monster_ext.port` (port.py runs it after the encounters; nothing without a registry) makes a PR
monster row per new monster a formation uses: a copy of a template row (the vanilla monster with the
same art, matched by sprite content; for a recolor the vanilla shape; else a normal monster of the
nearest sprite size as a stand-in), with the mod's stats, name (`MSG_PORT_MONSTER_NAME_<id>`), steals,
drops (`monster_drop_slots`), undead flag, elements, immunities, initial statuses, a special attack of
its own (ability 6000 + e from the SNES special byte, `MSG_PORT_MONSTER_ATK_<id>`), Sketch; and the
first party of every grown formation no random set needed, on a learned look (the background of the
SNES map where the mod's events fight it, the music its formation flags ask for, boss settings for a
boss). `monster_ext.json` beside the port lists each new monster's template and art kind (same /
recolor / new: the monster-art work) and the parties with their formations. A mod whose plugin runs the
monsters' SNES scripts (snes_ai) adds the new monsters to port_ai's export with
`port_monster_ext.snes_ai_extend(sa)` from its profile's extra_data (copies {PR id: e}, scripts, shims,
the grown formations' party slots).

### One mod, several tools: merging Magicite folders (`tools/magicite_merge.py`)

The game reads one copy of each asset: if two Magicite folders both ship a map group's `package.json`, an
entity file or the same partial master table, one folder's additions vanish. A mod built by several tools
(a porter, new maps, translated events) ships one folder, merged three-way against the game's own files:
`magicite_merge.merge(dest, [folder, ...])` merges JSON recursively (lists of objects by `id` or `name`,
so a package's maps and scripts and a layer's entities from both sides are kept), master tables by row and
column, text by key, and each group's `keys/*.json` into one file; two sides changing the same thing
differently is reported as a conflict (`tests/test_magicite_merge.py`). T-Edition's `tools/ted_build.py`
uses it: the porter's output (`mods/TEditionPort`) + `mods/TEditionMaps` + `mods/TEditionEvents` ->
`mods/TEdition`, then `prkit.magicite.validate`.

### SNES maps and places → PR maps (FF6: `tools/snes_maps.py`)

Anything an SNES mod places by map and tile (a chest, an NPC, a door, an event tile, a new room's exit) goes
through one table instead of each tool working out its own offsets:

```python
import snes_maps
snes_maps.to_pr(126, 55, 5)          # ('Map_20451_2', 55, 8): SNES map 126 (55, 5) on the PR
snes_maps.pr_maps(126)               # every PR map (room) of SNES map 126, with dx, dy, how and walk
snes_maps.snes_maps("Map_20451_2")   # the other way
snes_maps.map_data(rom, m)           # a map's properties, NPCs, event tiles, exits, chests
snes_maps.layout(rom, m), snes_maps.tile_props(rom, m), snes_maps.tileset(rom, ts)
```

One SNES map is often several PR maps (the PR split big interiors into one map per room, each drawing the
whole SNES layout but walkable only in its room; `to_pr` picks the room walkable at that tile), and one SNES
layout can be several PR maps (World of Balance / Ruin, story states). Each pair says how it was found:
`chests` (contents pair and the tiles agree), `exits` (reached by following doors: the SNES exit, the PR
object with a map_id at the same spot - GotoMaps, the world map's town entrances, doors in ev_*.json story
layers - their destinations and arrival points), `tiles` (the layouts agree: mutual information between the
SNES tile and the PR tile stack per cell), `layout` (an event copy: another placed map's layouts), `manual`
(`data/snes_pr_maps_overrides.json`; the world maps 0 and 1 are seeded there). Every pair carries `walk`: the
share of the PR map's walkable cells on SNES tiles that the SNES tile properties don't make walls (right
pairs 0.9+); pairs that don't walk where the SNES walks are dropped. 319 of 416 SNES maps are placed
(2026-11-20); the rest are unused slots, scene maps the PR redid as events, and a few with no confirmed
match. `python tools/snes_maps.py build [--reuse]` (needs numpy) rebuilds `data/snes_pr_maps.json`;
`show <map>` and `pr <PR map>` print pairs.

A mod with its own table addresses gives a `snes_maps.Tables` (T-Edition: `ted_maps.TED`, 511 maps, tables
in the ExHiROM expansion found from the field code's long loads); every reader takes it (`t=`). A mod on the
Japanese ROM is read through `tools/jp_layout.py` for the porter's tables.

### A new map from an SNES room (`tools/snes_rooms.py`)

The PR kept the SNES grid: each SNES cell is a stack of PR tiles (Bottom/Ground/Upper/Ceil layers on the map
group's atlases) plus a collision value (0 walkable, 1 blocked, 2-11 special). `snes_rooms.model(rom, m)`
learns from the vanilla rooms that look like SNES map m what the PR drew for each SNES cell: first by the
cell's SNES picture (`Look`: the map's graphics sets, palette and tilesets decoded, BG2 under BG1), then by
tile numbers with their neighbours, tier by tier (same graphics, same tilesets, same BG1 tileset); collision
by the SNES tile properties. `model.convert(bg1, bg2, tile_props)` redraws a room the PR never had in one map
group's atlases; `write_map` adds it to that group as a new map (files, package.json entry, keys,
map.csv / map_script.csv rows, an empty map script, objects on the map's own entity layer);
`clone_map` copies a vanilla PR map as a new map (its tiles and collision, cells to patch, its decoration
objects, your doors). `render` and `snes_picture` draw the PR and SNES sides as PNGs without the game.
`python tools/snes_rooms.py eval` measures it on held-out vanilla rooms (collision 98%).
`tools/ted_maps.py build` is the full use (T-Edition's 93 new maps: copies and conversions, doors, arrival
points, chests, data/ted_maps.json); `tools/ted_rooms.py` the one-room example.

### SNES events → PR scripts (FF6: `tools/snes_events.py`, `tools/event_translate.py`)

An SNES mod's events (a new scene, a changed NPC, a quest) are bytecode in banks CA+; the PR's are JSON
scripts (`tools/pr_script.py`). Two kit tools turn one into the other:

```python
import snes_events as E, event_translate as T
rom = E.load("us")                         # "jp", or a mod's: ted_events.load() (its own commands)
prog = E.Program(rom).walk_all()           # every script from every map's entrances, tiles and NPCs
prog.coverage()                            # reachable instructions, unknown opcodes (0 on US/JP/T-Edition)
for ins in E.script(rom, E.parse_addr("CC/B148")): print(ins)
sc, t = T.translate(rom, 0x2B133, "sc_my_scene", snes_map=20, prog=prog)   # a PR script (pr_script format)
t.stubs, t.after                           # what's left per command class; after-battle / arrival scripts
```

`snes_events.py`: field commands with sizes from the ROM's own command table, object queues, the world
map's vehicle scripts (after a load of maps 0-2), branches/calls/choices/switches followed; a mod adds or
changes commands with a `Dialect` (and its map tables with `Tables`: T-Edition's are in `ted_events.py`).
`snes_events.py coverage us|jp|all`, `map <n>`, `dump CA/xxxx`. A mod's ROM loads through its own module,
which registers it in `snes_events.LOADERS` at import (`load("ted")` after `import ted_events`); on the command
line add `--module <its module>`, e.g. `coverage ted --module ted_events` (event_translate.py takes it too).

`event_translate.py`: `learn` pairs each vanilla SNES scene with the PR scene that shows its dialogue
(dialog_map) and ties SNES event bits to PR story flags, songs to BGM, sounds to SE
(`data/snes_event_maps.json`; hand ties in `data/snes_event_overrides.json`). `Translator` emits PR
ops command class by command class (flow, dialogue, flags, puppets, battles, warps, gifts, party, music,
screen); a mod subclasses it for its text (`dialog(key)` -> message keys), its NPCs (`npc_entity(n)`) and
new places (`place(map, x, y)`), and gives a `FlagAlloc` for bits vanilla's PR has no flag for. What
it can't translate is a `SysCall "SNES:<command>"` stub with the SNES bytes in its comment, counted.
`validate` compares 12 translated vanilla scenes with the PR's own (dialogue order, flags, items,
battles, maps); `tests/test_snes_events.py`. A battle ends the script (the PR's Encount names the
script to run after it), and so does a map load (ChangeMap names the arrival script): a scene can be
several scripts, each listed in its map's package.json. Built 2026-11-20 for T-Edition: about 14% of
vanilla's reachable instructions are still stubs (NPC show/hide in the PR's entity layers, tile changes,
sounds, story party joins), and warps into the PR's split rooms don't always pick the PR's room yet.

What a mod changed (`tools/event_diff.py <mod.sfc> [--ranges 230000-260000] [--json out.json]`): both
ROMs walked as above, every map entry's script and every subroutine compared once (calls not inlined,
callees paired through their callers, addresses as labels, a second pass without dialogue numbers):
rows `text` (only dialogue), `changed` (with the commands added and removed), `new`, `removed`, and the
map entries reaching each. `--ranges` adds event-code ranges a mod put outside vanilla's (BNW: bank ED).
BNW's audit with it: PORTING.md "BNW's changed scenes beyond its text".

T-Edition's events (`tools/ted_events.py`): its 22 changed commands and tables, Mato's dialogue
(`tools/ted_dialog.py`: 3-byte pointer tables at 5C/9CE0 and 51/E600, a 112-word dictionary) as new story
keys, and `build()` -> `mods/TEditionEvents` (scripts in their PR maps, the map group's package.json,
story_mes/story_cha keys).

### Cutting a scene down to what it does (`tools/pr_scene_cut.py`)

A mod that removes cutscenes wants each scene's effects without the scene. `pr_scene_cut.cut(script, answer=0)`
turns a PR script's show (lines, menus, puppets, moves, animations, waits, fades out, shakes, flashes, sounds:
`SHOW`) into plain Nops in place and keeps everything else: story flags, variables, party joins/leaves, items and
gil, entity layers, battles, map changes, vehicles, music, recoveries, autosaves, every SysCall. Every instruction
stays at its index (labels too), so all jump targets stay valid. A menu takes `answer`: its Select becomes a Nop
and the MessageSelection branches after it a Jump (the first whose comparison holds for the answer) or Nops.
`pr_scene_cut.py NAME` prints what a cut keeps. Which scripts to cut (a scene's own, not optional talk) and each
menu's answer stay the mod's call; `tests/test_pr_scene_cut.py` checks every vanilla scene's cut against the
original in a small script model (same state steps, same end). First user: Beyond Chaos's notawaiter
(`tools/bc_events.py`, 159 scene scripts; 2026-11-20, bc-events).

### SNES code: the 65816 disassembler (`tools/snes_disasm.py`)

For a mod whose rules live in SNES assembly with no source (T-Edition's battle engine), or to check
an assembly patch (Beyond Chaos's, BNW's) against the ROM it built:

```python
import snes_disasm as D
rom = D.Rom.load(path)                         # HiROM / ExHiROM / LoROM from the size and header
for i in D.linear(rom, 0xC250B3, count=8):     # straight down; REP/SEP and PHP/PLP followed
    print(i)                                   # C2/50B3: 20 C9 26     JSR $26C9
code = D.trace(rom, [(0xC20000, True, True)])  # recursive from entry points, (address, m8, x8)
code.routines[0xC24B5A].calls / .tables        # JSR/JSL targets; ROM tables it reads (TableRef)
print(code.listing(0xC24B5A, 0xC24B70))        # labels (sub_/L_ or yours), "from" xrefs, table notes
D.align(jp_insns, us_insns)                    # {addr: addr} for two builds of the same code
```

The tracer follows branches, JSR/JSL (a callee returns with the widths all its returns agree on),
JMP/JML (tail calls into other banks), `JSR ($xxxx,X)` / `JMP ($xxxx,X)` jump tables (sized by a hint,
`tables={addr: n}`, or read until an entry doesn't look like code; guessed tables are read only
after the sure code is traced, so data can't push real code aside), and records the long (or,
with `db=`, absolute) reads into ROM per routine. `widths={addr: (m8, x8)}` forces widths,
`stop={addr}` ends a path (data after a JSR). `code.conflicts` lists instructions reached with
widths that would decode them differently; `code.overlaps` paths that ran into the middle of an
instruction (both empty on vanilla FF6's battle bank). The listing follows the community
disassemblies (and BNW's comments): `$` hex, branch targets as in-bank addresses, `LDA $D85000,X`.
Command line: `tools/snes_disasm.py ROM C2/50B3 -n 20 [--m16] [--x16]`, `--trace [--bank C2]`.
Tested (`tests/test_snes_disasm.py`) against the vanilla listings quoted in BNW's source and BNW
3.0's own patches decoded from its ROM (471 of 501 `org` blocks, 3,213 instructions; the rest were
overwritten by later patches).

A mod's own reading of it goes in its own tool (T-Edition: `tools/ted_battle.py`, JP vs mod
report in `build/t-edition/battle_code.txt`; the JP v1.0 battle bank is US code at shifted
addresses, `ted_battle.py jp C2/xxxx` gives the US address and BNW's section name).

### Monster images: a mod's recolors and new art (FF6: `tools/port_sprites.py`, `PrKit/MonsterImages.cs`)

The PR's battle monster images are RGBA32 sprites the size of the SNES sprite's opaque box, redrawn in
its (at most 16) colors, in bundles `mn_ff6_NNN` (key `MN_FF6_NNN_C00`; bestiary thumbnails 226x226 in
`mt_ff6_NNN_c00`). A distributed mod ships no game art, so its images are made on the player's machine:

- Porter (profile `sprite_images = True`): `port_sprites.py` compares the mod's SNES sprites with
  vanilla's as drawn (`tools/snes_sprites.py`; `tools/sprite_compare.py` prints the result) and writes a
  recipe: a recolor is a color table over the closest vanilla art (lossless: one new color per PR
  color), a swap points the monster at another PR image, `sprite_new_art {monster: stand-in}` ships the
  mod's own pixels, `sprite_final_tiers` repaints FF6's final-battle tower (`tools/final_tiers.py`, from
  windowless SNES captures). New images get monster_asset rows 2000+monster, key `{GROUP}_B{monster}`.
  `tools/pr_images.py` reads the game's textures with the standard library; `tools/sprite_sheet.py`
  draws a before/after contact sheet.
- Plugin: `MonsterImageRecipe.FromJson(json, "<property>")` then `MonsterImages.Ensure(gameRoot,
  MagiciteDir.FolderPath("<Mod>"), recipe, warn)` in the plugin's `Load`, before Magicite scans its
  folder: game-free, reads the game's bundles itself (~0.5 s once; a marker skips it after), writes
  PNG + `.spriteData` + `keys/Export.json` that Magicite serves. Brave New World:
  `BnwPlugin/BnwMonsterImages.cs` (recipe in bnw_data.json `monster_images`; harness `resload`).
- Tests: `PrKit.Tests` (synthetic recipes), BNW's `Rules.Tests` (every image's sha1 from this PC's game).

### SNES sprites → PR art: characters, portraits, monsters, live (FF6: `tools/snes_charsprites.py`, `tools/pr_art.py`, `PrKit/ArtSwap.cs`)

Any mod's own SNES art (randomizer sprite packs, a mod's costumes, redrawn sprites and portraits, new
monsters) as the PR's own, made on the player's machine and swapped live. What the PR draws (2026-11-20):

- **Characters** are SNES-sized: a character's field frames (`mo_ff6_pNNN`, one SpriteAtlas) and battle
  frames (`bc_ff6_pNNN`, one 32x32 RGBA32 texture each) are the same pixels, 50-62 named frames
  (`Default_00..02`, `WalkB/L/R_*`, `Idle_00`, `Ready_00`, `Win_00`, `Down_00`, `Tent_00`, ...), the
  character 16 px wide at x 8-23, feet on row 31, pivot (0.5, 0), 1 px per unit, point filtered. So an SNES
  sheet goes in 1:1: no scaling, no added outline (SNES sheets carry theirs, as the PR's redraws do).
- **Portraits** (`fa_ff6_pNNN/Default_00`, pivot centre) are the SNES 40x40 portraits.
- **Monsters** are images the size of the SNES sprite's opaque box (`mn_ff6_NNN`, key `{GROUP}_{ASSET}`),
  pivot bottom-centre, with a 226x226 bestiary thumbnail each (group `mt_<group>_<asset>`, key Thumbnail).
- **UI** (window frames, gradients) are sprites in `common`, 100 px per unit, 9-sliced.

**1. Convert** (`snes_charsprites.py`, data `data/ff6_charsprites.json`: maps and slot numbers only, no game
data):
- `group_frames(sheet, palette, names)`: an SNES character sheet (4bpp, 0x16A0 bytes with riding poses) +
  its 16 colors -> {PR frame name: 32x32 RGBA}, for `frame_names(group)`. The pose map ("frames": each PR
  frame -> a pose of the ROM's table at C0/CE3A, mirrored for the R frames, Float raised with a shadow;
  matched on all 14 characters, walk cycles from the PR's own anim_info) covers every character group's
  frames, the per-character extras too (Terra's Wind, Locke's and Celes' blushing Red*).
- `portrait(raw, pal)`: an SNES portrait (0x320 bytes) + its 16 colors -> 40x40 RGBA.
- "slots": SNES sprite slot 0-21 -> the PR's groups (0-13 the cast p001-p014; Soldier p021 (+ green c01),
  Imp p016, Leo p020, Banon p017 (+ c01), Esper Terra p015 + p001_tr (battle trance), Ghost p019, Kefka p018;
  Merchant has no PR character art), with each slot's vanilla palette index and portrait id.
- The PR's own art in other SNES colors (a palette shuffle, a recolour): `GameArt().maps(group)`
  (`ColorMaps`: "color_slots" paired with the player's own frames) + `recolor(rgba, maps, old_pal,
  new_pal)` (Lab, each slot's shades centred on the PR's average: its retouched hues follow);
  `vanilla_palettes(rom)` from the caller's ROM or generator base data.
- `python tools/snes_charsprites.py sheet FILE.bin OUT.png [--pal P.pal] [--portrait P-p.bin]`: a contact
  sheet of every frame; `build [--rc DIR]` (dev PC: ROM + game) remakes the data.

**2. Write** (`pr_art.py`): `GameArt()` reads the player's game (textures per group, cached; `frames`,
`maps`, `face`, `textures_named` for a few textures of a big group). `ArtWriter(folder)` writes PNG sheets +
`art.json` (merged with what's there): `character(group, frames, field="mo_ff6_...")` (battle addresses and
the field atlas), `face(fa_group, rgba)`, `ui(name, w, h, rgba, border)`, `monster(m, group, asset_row, w,
h, rgba, pivot, thumb)` (SNES monster m on an image of its own: key `{GROUP}_B{m:03}` in its own image's
group, monster_asset row 2000+m, its thumbnail; `pivot(box, w, h, x0, y0)` places new art where the SNES
draws it, `monster_asset(m)` gives group and row), `save()`; then `write_monster_tables(master_dir,
writer.monster_rows)` (monster.csv / monster_asset.csv). `apply_table(rgba, {rgb: rgb})` recolours fast.

**3. Serve, live** (`PrKit/ArtSwap.cs`): `ArtSwap.Install(harmony)` once, `ArtSwap.Load(folder)` whenever the
art changes (a seed applied, a costume put on; null: none). `art.json`: `sprites` {address: {png, rect
(top-down px), pivot, ppu, border, preload}} (in ResourceManager's completeAssetDic when the game checks the
address, or at Load for ones it already holds; the game's own put back when no longer served), `atlases`
{atlas name: {frame: ...}} (a field SpriteAtlas: GetSprite/GetSprites/spriteCount answer from it; characters
already on the map change when it reloads) and `keys` {group: {key: address}} the game lacks (added to
AssetBundlePathMatch, as Magicite adds its own). Its CheckCompleteAsset postfix runs after Magicite's.
Magicite can't swap live (it maps only files present at its start and keeps its atlases' sprites).
Static monster art loaded once at startup can instead go through `PrKit/MonsterImages.cs` (Magicite files,
"Monster images" above). Keep the folder with the mod's data (`BepInEx/<Mod>/...`), never under plugins.

**What a mod supplies**: its SNES sheets (+ palettes) and portraits (+ .pal), or pictures; which PR group or
SNES slot each is for; for a recolour, the old and new SNES palettes. Nothing of the game's ships: the PR's
art is read from the player's game when needed.

**Checks offline**: `tests/test_bc_sprites.py` (the pose map against the PR's Terra, all 677 of Beyond
Chaos' sheets, lossless recolour, the data holds no colors, pivots, packing, an `art.json`'s rects;
`BC_SPRITES_SEED=DIR` for a seed folder); contact sheets (`snes_charsprites.py sheet`); against the SNES:
render the same sheet from the ROM with `group_frames` and compare. In game: Beyond Chaos's harness
`bcart [load GROUP KEY | atlas GROUP ATLAS FRAME]` says whether a loaded sprite is the mod's or the game's.
Beyond Chaos uses all of it per seed: `tools/bc_sprites.py` (makeover, `s`, `c`), `bc_monsters.py`
(remonsterate, `c`+`m` monster colours), `bc_palettes.py` (`n` windows), `BcPlugin/BcSprites.cs`.

### SNES music player: a mod's SNES songs in place of the game's tracks (`PrKit/Snes`, `tools/snes_songs.py`)

Songs in FF6's SNES sound format (its "AKAO" sequences, as mfvitools/johnnydmad compile MML) play in game
on the kit's player: an S-DSP and FF6's sound driver re-implemented in C# (no SPC700, no Square code or
samples shipped), streamed through its own sound output (the PRs ship with Unity audio off: winmm, also
under Proton). Any mod, any PR (the hooks are the shared engine's). Beyond Chaos uses it per seed
(`tools/bc_music.py`, `BcPlugin/BcMusic.cs`); T-Edition's songs are next.

1. **A song pack** (`DIR/songs.json + songs.bin`, `SongPack.Load(dir)`): each song as FF6's driver keeps it at
   SPC $1C00 (base address, "no voice" marker, 8 + 8 voice pointers, script) with its 16 instruments
   (programs $20-$2F) by sample id; each sample its BRR blocks, loop offset (bytes), two pitch bytes
   (FF6's multiplier: < $80 = 1 + t/256, else t/256; a finer second byte) and ADSR. Make it with
   `tools/snes_songs.py`: `read ROM --out DIR` reads an FF6-layout ROM's driver tables (the pointers at
   C5/0539, 01E3, 0222, 041C, 049C, 04DE and the count at C5/3C5E; relocated tables are followed), or from
   Python `read_ff6_songs(rom)` then `write_pack(dir, songs, samples, meta)` with your own songs (any slot
   numbers; `"lookahead_patch"`: BC's mfvitools ROM patch, false for an unpatched FF6 driver;
   `"echo_delay"`: 5 = FF6's). `check DIR` lists songs that use the driver's resident waveforms, game
   sound effects or run off their end. Slots are any numbers: a mod with a second driver table (T-Edition's
   bank 43 copy) numbers those songs apart (e.g. $100 + n) in the same pack: `tools/snes_songs_at.py read ROM
   --tables song=..,inst=..,brr=..,loop=..,pitch=..,adsr=..,count=N --slot-offset 0x100 --sample-offset 0x100
   --out DIR --merge` reads tables at any address (6 MB ExHiROM banks too; `--pointers` for pointer slots
   elsewhere; until the WC 0.6.9 kit freeze ends it lives beside snes_songs.py). Packs are data: ship a mod's
   own converted songs and samples, never a ROM's (FF6's 63 instrument samples are byte-identical in
   Beyond Chaos's MIT repo, `music/samples/legacy/01..3F`, johnnydmad's `brr_legacy` table; Beyond Chaos
   builds its pack on the player's machine per seed). FF6's driver keeps 8 built-in waveforms of its own
   (programs $00-$07: wind, rain, train and other layers some songs use); `tools/snes_songs_at.py resident
   ROM --pack DIR` adds them to a pack (`"resident"` rows), `--file F` writes them to a small JSON file a
   mod's bundle carries and `add_resident(DIR, F)` adds that file to a pack made later. FF6's sound driver
   and built-in instrument samples may ship with a mod; nothing else from a ROM does.
2. **What plays where** (`BgmRules.Load(json)`, `bgm.json`): `"tracks"` {PR bgm id: slot}; `"songs"`
   {slot (hex): {name, title, pr_bgm}} (pr_bgm: a slot holding one of the game's own songs, the game plays
   that track); `"maps"` {PR map id: {from: [PR bgm ids], slot}} (an area's own song); `"battles"` {monster
   party: {slot}} (-1: the field song carries on); `"fanfares"` {monster party: {slot}} (that battle's victory
   fanfare in place of the game's `"fanfare_track"`, default 7; -1: none); `"jumps"` [[PR bgm id, slot]] (asked for while that slot
   plays: its conditional jump, FF6's Dancing Mad parts); `"carrier"` (a PR track the game loads and plays
   muted behind a new song; default its first BGM). **New songs** (no PR track): give each a PR bgm id
   the game lacks (convention 1000 + its song number) in `map.csv`'s `bgm_id` and scripts' `PlayBGM`, and a
   `"tracks"` entry to its slot; SnesBgm makes the game load/check/play the carrier for it (the game's
   audio code dereferences an unknown id's asset unchecked). FF6's SNES song -> PR track table:
   `snes_songs.FF6_SONG_PR_BGM` (+ `PR_BGM_EXTRA`, `pr_bgm_to_song()`).
3. **In the plugin** (`<PrKitSnes>true</PrKitSnes>` in the .csproj; namespace `PrKit.Snes`): `SnesBgm.Tag`,
   `.Name`, `.On = () => modActive`; `SnesBgm.Patch(harmony)` once; `SnesBgm.SetMusic(pack, rules)` (null,
   null: the game's music again; any time, e.g. a seed's apply); `SnesBgm.Update()` every frame;
   `SnesBgm.RegisterHarness("mymusic")`. It lets every BGM request through to `AudioManager` (the game's
   state queries keep working), mutes the game's instance where one of the pack's songs plays and follows
   it: fades, stops, battle songs over the field's (the field song resumes where it was, with FF6's
   driver's fade-in), per-party battle songs (`BattleController.PlayBGM`'s id rewritten) and victory
   fanfares, jumps, pitch, the
   master and BGM volumes, the driver's pauses. Below it, `SnesMusicPlayer` (`Play(slot, fadeIn, suspend)`,
   `Stop`, `Suspend`/`Resume`, `ConditionalJump`, `Pitch`/`Tempo`, `Volume`, `Paused`, levels/load stats;
   `Start(silent: TestRun.Running)`: no sound card in test runs), `Ff6Driver`, `SnesDsp`, `SystemWaves`.
   Keep the pack in the mod's data folder (`BepInEx/<Mod>`), not under plugins.
4. **Limits**: FF6's driver format only (a mod that changed the driver needs its changes in `Ff6Driver`);
   16 instruments a song; programs $00-$07 are FF6's resident waveforms when the pack has `"resident"` rows,
   else synthesized stand-ins (close, not the same), $08-$1F silent; a game sound effect command in a song
   (E9/EA) ends that voice; ~130 ms output latency; ~1-2% of one core (render thread).
5. **Checks offline**: `plugin/Snes.Tests` (`dotnet run -c Release -- check | render PACK SLOT SECONDS OUT.wav
   | renderall PACK DIR SECONDS | bench PACK | compare REF.wav OURS.wav | bands | lags`);
   `tools/snes_song_ref.py check ROM PACK --slots 24,14 --seconds 20` records each song from Snes9x
   (`tools/snes_harness.py capture_audio()`, a test copy of the ROM in build/snes-test) and compares level,
   loudness over time, spectrum, tempo and waveforms (Beyond Chaos, 28 songs with the resident waveforms:
   levels within 0.41 dB, spectra within 0.8 dB, tempo within 0.5%). In game: the harness command (state: each channel, the player's song,
   levels before/after volume, load, late ticks; `play SLOT`, `stop`, `vol V` (the game's BGM volume, as its config
   sets it), `log`).

## Plugin features (C#)

A plugin's `.csproj` sets `<PrGame>` and imports `plugin/PrKit/PrKit.props`, which compiles the kit
in and references the game's BepInEx and interop assemblies. The kit is compiled into each plugin,
so mods never depend on one another's kit or version, and it registers no IL2CPP classes, so any
number of kit plugins load side by side.

```csharp
public override void Load()                      // Plugin.cs (the scaffold writes it)
{
    Kit.Init(Log, "Five Jobs");
    if (!Game.Require(PrGame.FF5)) return;       // built on FF5's own code
    if (!MagiciteDir.Has("FiveJobs")) { Kit.Warn("data not installed: off"); return; }
    Features = new FeatureHost(Config, new Harmony(Guid));
    Features.Add(new JobLimits());
    Features.Add(new SingleGamepad());            // the kit's Steam Deck double-press fix
    Features.ApplyAll();
    AddComponent<FiveJobsRunner>();              // its own runner class name (IL2CPP registers by name)
}

class JobLimits : Feature                        // one class per thing the mod changes
{
    public JobLimits() : base("Jobs", "JobLimits", true, "Four jobs per run.") { }
    ConfigEntry<int> count;
    public override void Bind() => count = Setting("Count", 4, "How many jobs.");
    public override void Apply(Harmony h) =>
        Hooks.Patch(h, Hooks.TypeByName("Serial.FF5.Management.JobManager"), "ChangeJob", typeof(JobLimits), prefix: nameof(ChangeJob_Prefix));
    public static bool ChangeJob_Prefix(Il2CppSystem.Object __instance) { ... }
    public override string Check() => Master.Ready ? $"{Master.All<Last.Data.Master.Job>()?.Count} jobs" : null;
}
```

(The FF5 names above are placeholders; find the real ones in `kit.py api ff5`.)

What the host does: a `[Section] Key = default` switch per feature in `BepInEx/config/<guid>.cfg`;
only enabled features are applied; a feature that throws while starting is turned off and logged,
the others still start; `Update`/`OnGUI` are called every frame with each feature's exceptions
logged once; `Check()` runs once the game's data has loaded and its line goes to the log
(`[check] JobLimits: 22 jobs`), which is how a headless run shows a feature works; `[Kit] PerfLog`
times every feature.

Rules every hook follows (from the FF6 crashes in PORTING.md "Plugin"; the engine is the same in
every PR):

- `Hooks.Patch` refuses methods whose machine code is tiny (empty, a jump, a ret within 6 bytes):
  the linker folds identical functions, so hooking one hooks many, and reading the wrong object's
  fields closes the game. Hook the method that does the work.
- Check the instance before touching it: `if (!Hooks.IsA<T>(__instance)) return;`.
- Harmony can't patch `MasterManager`'s generic methods. Read data with `Master.Get<T>(id)` /
  `Master.All<T>()`, text with `GameText.Get/Set`.
- Hooks run on several threads (stat getters do): lock what they share. Log with `Hooks.WarnOnce`
  / `NoteOnce`, never every call.
- `Last.*` types are the shared engine (the same in all six games); `Serial.FF<n>.*` is one game's
  own code. A plugin built against FF6 that touches only `Last.*` usually runs in FF5 too; for
  anything else use `Game.Require` or `Hooks.TypeByName("Serial.FF5....")`.
- UI found in a screen's first frame has stale positions (it slides in), and anything added under a
  layout group becomes a layout item: parent new UI to an existing text (PORTING.md, the EL display).
- The game's build strips the Unity code it doesn't use. The interop DLLs still list it, so it
  compiles, but the call throws `Method unstripping failed`. IMGUI's `GUI.DrawTexture` and
  `GUI.DrawTextureWithTexCoords` are stripped: draw with `GUI.Box(rect, content, style)` where
  `style.normal.background` is the texture (Battle Options' EnemyAtb, the WC flags screen).
  A no-graphics headless run never paints, so it can't catch this. `kit.py check <mod>` reads the
  built DLL and names every stripped method it calls (needs `ilspycmd`).

## Testing

- Offline, in seconds: `.venv/Scripts/python -m unittest discover -s tests` (each scaffolded mod gets
  a `tests/test_<id>.py` that validates its Magicite folder), `cd plugin/PrKit.Tests && dotnet run -c Release`
  (the kit's game-free logic), `kit.py check <mod>`. `tools/run_tests.ps1 -Offline` runs them all.
- A new or changed kit C# file, before it goes into `plugin/PrKit` (every plugin compiles it at once):
  `tools/kit_cs_check.py MyFile.cs` compiles it with the live kit (every part on) in a throwaway project;
  `--replace plugin/PrKit/Ff6/X.cs:C:/scratch/X.cs` checks an edited copy in the kit file's place. Then move
  it in and build the FF6 plugins (`dotnet build -c Debug`).
- In the game, headless, **only with the user's OK and never while they play**:
  `kit.py run ff5 --harness` starts the game with no window and no sound, and a kit plugin of that
  game takes the request: every save is blocked for the run (if the save hooks can't be installed,
  it quits instead), the sound is muted each frame, the harness listens on 127.0.0.1:47811. The run
  stops its own game if a window appears, if anyone else starts the game, on `--until <regex>`, or
  after `--minutes`. Talk to it with the same client as BNW's harness:
  `.venv/Scripts/python tools/game_harness.py state "press action" "wait 60"`. Built-in commands: ping,
  help, state, press, wait, skipmsg, newgame, slots, load, warp, script, battle, encount, log, shot,
  shotinfo, quit.
- Screenshots, still headless: `kit.py run <game> --harness --graphics` (BNW: `probe_headless.ps1
  -Graphics`) keeps a graphics device with no window; `shot <file.png> [width [height]] [layers]`
  draws the frame from the game's cameras (a windowless run draws nothing by itself) and writes a
  PNG, `layers` each off-screen layer too (field, UI); `shotinfo` lists the cameras and canvases.
  A mod adds its own: `Harness.Register("jobs", args => "...", "jobs: each character's job")`; a
  handler that returns null is called again each frame until it answers (waiting for a battle, a map).
- Never by driving the screen (no computer-use, no visible launches).

## Install and ship

`pr/modkit.json` lists every mod. `kit.py deploy <mod>` builds (the entry's `build` commands, then
the plugin, then `post_plugin_build`), installs on the PC (the game closed), then pushes to the Deck
(`--pc` / `--deck` for one side, `--full` resends BepInEx, `--dry-run` shows the plan and the Deck
script). Mods with the same `exclusive` tag for a game are never installed together: the others move
to `BepInEx/mod-shelf` (their Magicite folder beside them as `<Mod>.magicite`), and come back with
their `keep` folders (player data) when deployed again. Brave New World and Worlds Collide keep their
own `tools/deploy.sh` (its WC seed sync and bundle steps); `kit.py deploy bnw|wc` runs it.
`kit.py package <mod>` (= `tools/package_mod.py`) writes the player zip: the plugin folder, the
Magicite folder under the game's own `_Data` name, a README (BepInEx build, Magicite, the Proton
launch option `WINEDLLOVERRIDES="winhttp=n,b" %command%`, the mod's `readme_note`); never a ROM
(`.sfc`/`.smc` are refused), and never the game's own files: a file byte-identical to one in the
game's extract (`pr/vanilla`, `kit.py extract`) is refused (Magicite `keys/` lists aside). A mod
that needs copies of game files makes them on the player's machine from their own game:
`tools/pr_bundle.py` reads any PR's text assets with the standard library alone (byte-identical to
`extract.py`'s on all 2,374 of FF6's text bundles, 30 s), and modkit.json's `package_leave_out` /
`package_magicite: false` keep the made parts out of the zip. `player_setup` names the script the
plugin runs to make them; the packager refuses the mod until the plugin's DLL names it.

Worlds Collide is public (2026-11-12, the user: "just make a github release and make the entire WC
thing public"): https://github.com/thomasjteachey/ff6pr-worlds-collide. `tools/wc_publish.py`
re-exports its tree into `../ff6pr-worlds-collide` (the WC plugin, all of `tools/*.py`, prkit, the WC
tests, these docs; WC itself as the `mods/worlds-collide` submodule at the commit used here; the
same game-file check as the zip), then commit and push from there. Releases carry
`build/dist/WorldsCollide-PR.zip`; it's over the Chrome extension's 10 MB upload limit, so it goes
up in two parts that the release page's JavaScript rejoins into one File (SHA-256 checked) and hands
to its `#releases-upload` input (v0.6.0, 2026-11-12), or by hand. No GitHub CLI on this PC.
Releases through v0.6.3 are marked Pre-release: v0.6.0, v0.6.1 (the setup recipe: first start
~10 s), v0.6.2 and v0.6.3 (playtest and SNES-WC parity fixes). Bump `Plugin.Version` with each.

Worlds Collide's (2026-11-12): `tools/wc_gamedata.py`. Every copy of the game has the same files, so
`wc_bundle.py` works out the player's files once (`make_recipe`, ~40 s): `generator/gamedata_recipe.json`
says how to make each of the 1,633 (a copy of a game file, a game monster AI script under a slot's
name, a line patch of a game file's JSON or text with WC's changes, a duplicate, or one of ours
shipped in `generator/gamedata/`: key lists, the cache), each with its sha1, and
`generator/gamedata.json` lists the 1,584 game files that takes. `wc_gamedata.py setup` (bundled
Python, ~10 s on the PC: 5.5 extract, 4.5 make) reads them from the game's bundles, makes and checks
every file, gives the shipped cache this folder's vcache stamp, then writes `generator/vanilla/.complete`
(the manifest's id). `wc_gamedata.py status` exits 0 when that's current; `selftest` makes a player's
install from the build and compares it file by file.

### Game files made on the player's machine, and a mod's in-game generator (kit; bc-seeds, 2026-11-20)

The kit's versions of WC's, for any mod (WC keeps its own files): `tools/gamedata.py` (a `Spec`: the
mod's folder name and its `package_leave_out`; `make_recipe`, `setup`, `selftest`, `status`, `main`) with a
thin `tools/<mod>_gamedata.py` (Beyond Chaos: `tools/bc_gamedata.py`), and `plugin/PrKit/Seeds/GameData.cs`
(`new GameData { Tag, Title, Script = "<mod>_gamedata.py", MagiciteFolder, Data, Generator }`,
`EnsureSetUp()` first thing in `Load`; the DLL then names the script, which `player_setup` needs). A made
file that isn't any game file is shipped as the mod's own and named in the recipe's output, for a look.
`tools/gen_bundle.py`: the generator's Python (`python_runtime(dst, packages=["PIL"])`: CPython from this
PC's install plus site-packages a mod's randomizer imports, with their licenses), the tool scripts its
entry scripts need (`copy_tools`), bytecode (`precompile`), `no_roms`. A whole player bundle writes
`generator/bundle.json` last (the Deck tooling counts an install as complete by it).

### A randomizer without the SNES ROM: tracing what it reads (`tools/bc_trace.py`, `bc_basedata.py`)

How Beyond Chaos's generator went ROM-free, reusable for any randomizer that runs on ROM bytes:
`bc_trace.py record` runs it with every random draw recorded (each `random.Random`, labelled by where
it's made; seeds too) and every ROM byte it reads (input buffer, and output bytes not yet written)
filed under the function that asked; whole-ROM copies (checksums, mirrors) and `fout.read()` style
reads show as bulk, their bytes recording what's used of them. `diff` compares two runs stage by stage
(a randomizer that reseeds per stage only needs each stage's own reads); `port` lists what our side
(porter and post-steps) reads of both ROMs. `bc_basedata.py` turns the traces into shipped regions by
category (data, maps, palettes, events, code, shapes), less the reads of content the randomizer only
copies or rewrites (stand-ins: `bc_romfree.py`), and `bc_parity.py` makes a seed both ways and compares
the folders. The porter's `port_sprites` takes `profile.sprite_identity = "pointer"` (a monster's sprite
by its graphics pointer, not its pixels) for an input with no graphics.

## Where BNW and WC stand, and what's left

- **The seed system is the kit's** (2026-11-20, `plugin/PrKit/Seeds`, compiled in only with
  `<PrKitSeeds>true</PrKitSeeds>`): `FlagSet`/`FlagValues` (flags JSON from a mod's exporter: WC's
  `-flag value` or BC's `name:value` style), `SeedGenerator` (the mod's `<mod>_seed.py` in a hidden
  process, "[tag] ..." progress), `SeedLibrary` (seeds/<id>/ with full tables + text + changed files,
  `LiveData` apply, Magicite file swaps, the save hooks that remember each save's seed; the mod's rules as
  callbacks), `SeedScreen` (the options screen; subclass it), `TitleMenuEntry`, `PadInput`, `ModDataDir`,
  `ChestBattles`. Python: `seed_live.py` (managed tables/files, the baseline) and `seed_info.py`. Worlds
  Collide's classes are facades over these; Beyond Chaos (`plugin/BcPlugin`) is built on them.

- **Brave New World is on the kit** (2026-11-11, plugin v0.22.1): `BnwPlugin.csproj` imports `PrKit.props`,
  its 236 hook calls use `Hooks.*` (the same code `EsperHooks` held), `GameHarness` is the kit's `Harness`
  plus BNW's `party`/`skipmsg`/`quit`, and `FormulaProbe` blocks saves and mutes with `TestRun`. Its log now
  starts with a `[kit]` line and says `[test] saves blocked ...` / `[test] save to slot N skipped` where it
  said `[probe] ...`. Built and unit-tested (Rules.Tests); not yet deployed or run in game.
- **Worlds Collide is on the kit** (2026-11-19): `WcPlugin.csproj` imports `PrKit.props` (from `../PrKit`, or
  the `kit/` submodule in ff6pr-worlds-collide), WC's `LiveData.cs`/`PadFix.cs` gave way to the kit's
  `LiveData`/`SingleGamepad` (same `[Input] SingleGamepad` switch), `using PrKit;` in five files, WcTest's
  device check and mute go through the kit, `Kit.Init` starts `Load`. WC's own `h.Patch` hooks stay as they
  are, and its `FeatureHost` has `TestRuns = false`: WC's self-tests are WcTest's, not `prkit_test`
  requests. `plugin/Shared` and the one-off `migrate_wc.py` are gone.
- **The SNES monster AI interpreter is the kit's** (2026-11-19): `PrKit/Ff6/SnesAi.cs`, namespace
  `PrKit.Ff6`, compiled into FF6 plugins only (`PrKit.props`: `Ff6\*.cs` when `PrGame` is ff6). WC's
  `WcEnemyAi*.cs` run it in the PR's battles; WcAi.Tests checks it on WC's scripts. Brave New World's
  plugin compiles it too, for its own monsters next (BNW's AI changes are a few conditions: c2.asm FC 06/07,
  counters that can't trigger counters, the Lore range from $84, the vindictive-targeting fix).
  A mod whose boss changes formation (AI F2) on the SNES has no F2 in the kit's host yet: make the fight one PR
  party listing every form (later forms hidden at the start or brought in), and rewrite each F2 as F5 show (0 =
  refill when the F2 has 0x80, else 2) + F5 hide over the merged slots; slot masks and $30-$35 targets of a
  form moved to another slot are renumbered, and after an F2 the block's slot references are the new
  formation's (tools/ted_ex_ai.py rewrite()). HP carried over by an F2 without 0x80 isn't reproduced (each form
  keeps its own). A second mod's battle lines that collide with the first's go on numbers the first's scripts
  never show (the host keys F3 by one byte).
- **The SNES's random battles are the kit's** (2026-11-20): `PrKit/Ff6/SnesEncounters.cs` (the danger counter
  on the PR's move counter, the roll before the game's own check, the party drawn against the set's weights)
  with a per-mod `SnesEncounterMod`, and `SnesEncounterRules.cs` (game-free: the rate tables, the roll, mean
  steps, the zone/terrain and set codes a mod's data may carry; PrKit.Tests checks it). `tools/
  port_encounter_rates.py` reads a mod's rules from its ROM. WC keeps vanilla's (its own tables in
  `WcEncounters.cs`); BNW reads its own from `bnw_data.json`. The harness has `encounters`.
- **The SNES's Offering and Genji Glove penalties** (2026-11-20): `PrKit/Ff6/SnesRelicPenalties.cs` with a
  per-mod `SnesRelicPenaltiesMod` (Offering x0.5 on every physical hit by a character, as the SNES's damage
  formula C2/2B9D does, not only on Attack; Genji Glove: `GenjiRule.SnesBug` = vanilla's own -25% when NOT
  dual wielding, `Pr`, or `None`). It turns the PR's Attack-only corrections off where its rule takes over and
  applies its own on `CalcControllerProvider.GetFightStatus` / `GetThrowStatus`. `SelfTest()` runs Fight and
  Mug through the game's functions in a battle. WC uses it (`WcSnesRules`, config `[Battle] GenjiGlove`); BNW
  keeps its own (BNW fixed the Genji bug and gates by command: `RelicRules`, `BattleFormulas`).
- **Suplex and the monsters that can't be suplexed** (2026-11-20): `PrKit/Ff6/SnesSuplex.cs` with a per-mod
  `SnesSuplexMod` (its list of PR monster ids, its Suplex ability, `Enabled`): the SNES's monster byte $13 bit 2
  makes Suplex miss; the PR's Suplex (ability 134, function 2) never misses for it. `BattleFunction2.HitCalc`'s
  postfix turns the mod's Suplex on a listed monster into a miss; `SelfTest()` runs it through the game's
  functions in a battle. `SnesSuplexRules.cs` (game-free, PrKit.Tests): `VanillaNoSuplex` (159 PR ids: 146 named
  monsters and 13 unnamed slots; `tests/test_snes_rules.py` checks it against the US ROM) and `Misses()`. A mod that
  changes the bit lists its own from its ROM: `[idmap.monster(e.id) for e in ff6snes.enemies(rom) if e.raw[19] & 4]`.
  WC uses vanilla's list (WC never changes the bit); Beyond Chaos doesn't need it (its suplexwrecks clears the bit).
- **Skills given on the party's behalf** (2026-11-20, bc-events): `PrKit/Ff6/StartSkills.cs`. The SNES's SwdTechs,
  Blitzes, Lores, Dances and Rages are the party's; the PR's are each character's abilities (skill level 100 =
  known). `StartSkills.Teach(command, abilities)` teaches them to every owned character holding the command
  (`Sets`: PR command and ability ranges; Rage = 799 + PR monster id); with no holder they wait until
  `TeachPending()` (call it on joins). Opt-in: nothing runs unless a mod calls it. Generalized from WC's
  `WcRages`/`WcSkills` (WC moves onto it after its next release); Beyond Chaos's worringtriad start Lores use it.
- **Config rows** (2026-11-20): `PrKit/ConfigRows.cs` adds a mod's On/Off rows to the game's Config menu
  (a copy of one of the game's On/Off rows with a command type of the mod's own, after the battle rows and
  other mods' rows there; Battle Options' way). BNW's Encounters row is the first.
- **Worlds Collide's player setup** (2026-11-12, `WcGameData.cs`): the first thing in `Plugin.Load`,
  when `generator/vanilla/.complete` is missing or isn't `generator/gamedata.json`'s `"id"`, runs
  `wc_gamedata.py setup` with the bundled Python (42 s on the PC, in the console before the game
  window), then `WcMode` needs its success. BepInEx loads WC before Magicite (independent plugins
  go by GUID), so Magicite reads the folder made on that same start: no restart (headless check:
  setup, startup apply, 534 of 534 Magicite files the seed's). A deploy's install is already set up
  (`wc_bundle.py` writes `.complete` into the build deploy mirrors). The packager checks the DLL
  names `wc_gamedata.py`.
- **T-Edition's plugin** (2026-11-20, `plugin/TedPlugin`, AssemblyName `TEdition.PR`, GUID `ff6mod.tedition`):
  T-Edition's battle rules on the PR's engine, from `pr/ted/BATTLE_SPEC.md`. Built on the kit like Beyond Chaos
  (PrKit.props, FeatureHost features with `[Battle]` switches: Damage, Statuses, Commands, Victory), its
  game-free numbers in `plugin/TedRules` (offline tests in `plugin/Ted.Tests`: `dotnet run -c Release`). The PR
  computes vanilla FF6's formulas, so each rule is T-Edition's step over the game's on the same inputs
  (`CalcControllerProvider.GetFightStatus` / `GetMagicStatus` / `GetRecoveryStatus`: the prefix reads the
  elements, Def/MDef, Safe/Shell, Defend, row, Morph and the ignore-defense flag, the postfix scales the value);
  an attack with several elements reads a view of the target's element table (`ConfirmedResistanceAttributeList`),
  so the game's one-response rule gives 0 or a heal where T-Edition's sum does. The PR's defense block
  (decompiled PhysicalExecution / MagicExecution) is skipped as a whole for content flag 5, heals, Valiant Knife
  (by weapon row 11) and Drill/Chainsaw (by item), so "ignore-defense attacks meet Safe/Shell" is a factor too.
  Kit modules it runs on: SnesAtb (T-Edition's command waits), SnesStatusTicks (the SNES status clock, held while
  an act plays through the AppDomain "pr.battle.timeHeldFrame" channel), SnesHitRates (both lists emptied),
  SnesEsperBonus (every esper "none"), SnesUmaro, SnesAiHost (`ted_ai.json` + EX's `ted_ex_ai.json`, merged; EX's
  attack overrides through `SnesAiMod.AbilityFor`). Its data is in `BepInEx/TEdition` (`tools/ted_plugin_data.py`:
  item slots -> PR content ids/rows/names, new weapon rows, flagged monsters, named items/abilities, vanilla
  esper bonuses), its saves are its own (`ModSaves "TEdition"`), and its success counters (Steal, for
  Orichalcum) live in the save's `OwnedKeyWaordList` behind the marker "TED1" (as BNW's esper data, "BNW1").
  Each rule logs `[ted] rule N: ...` the first time it fires. Harness: `ted`, `tedcheck` (the port as the game
  has it: new weapon rows, every item slot's name, drop slots, the drop-rate constants), `tedgive`, `tedkeep`,
  `enemyhp`, `tedrules`, `teddamage` (each damage rule through the game's own functions, nothing applied: rules
  off vs on against the computed factor), `tedsteal`, `tedgil`, `tedcast`, `tedcond`, `tedcounters`,
  `teddrops`. A test install: `tools/ted_testinstall.py install|restore|status` (through the PC test runner;
  never writes `build.json`).
- The kit hasn't run in a game yet: the first headless run of a kit plugin (or BNW's next probe run)
  should show `[kit]`, `[check]` and `[test] saves blocked` lines.
- FF1-FF5 paths are Steam's names and app ids, not yet seen on this PC.
- The SNES-to-PR porter (`tools/port*.py`, `ff6snes.py`, `idmap.py`) reads FF6's ROM layout; a port of an
  FF5 SNES mod needs FF5's layout first (the converters' approach carries over, the tables don't).
