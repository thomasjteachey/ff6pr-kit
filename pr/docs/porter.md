# The shared porter (FF6 SNES -> Pixel Remaster data)

Owner: kit lead. Moved verbatim from `pr/PORTING.md` on 2026-11-20 (roadmap item 5); `git log --follow` / the split commit trace any paragraph. Status rows stay in `pr/PORTING.md`.

## Modding kit (any Pixel Remaster; 2026-11-11)

`pr/MODDING.md` is the guide. `tools/kit.py` (package `tools/prkit`) knows all six PRs through Steam's
library list and does extract / api / setup (BepInEx + Magicite into another PR) / new-mod / check /
package / deploy (PC + Deck) / run (headless) for any mod in `pr/modkit.json`. `plugin/PrKit` is the
plugin library new mods compile in (`PrKit.props`): the hooking rules below as code (`Hooks`),
switchable `Feature`s, `Master`/`GameText`, `TestRun` (no saves, muted) and `Harness` (BNW's harness for
every PR), `LiveData`, `SingleGamepad`. Since 2026-11-19 the kit is its own public repository (ff6pr-kit), pinned as kit/ by ff6pr-worlds-collide and ff6pr-brave-new-world (tools/kit_publish.py, wc_publish.py, bnw_publish.py). BNW's plugin is on it since 2026-11-11 (v0.22.1); WC's waits for
the WC session to free WcPlugin (MODDING.md, "Where BNW and WC stand"). `tools/package_mod.py` now reads
the manifest (the same zips, checked file by file).

## Shared porter

`tools/port.py <profile>` diffs a modded US-v1.0-layout ROM against vanilla and
writes `mods/<ModName>/` (Magicite). All converters are mod-agnostic; a profile
(`tools/profiles.py`) only sets the ROM, output name, text policy and extras:

| Profile | ROM | Text | Extras |
|---|---|---|---|
| `bnw` | build/brave-new-world/…FRC.sfc | BNW names everywhere + BNW descriptions (own encoding) | `bnw_data.json` (esper rules); Rage odds 2/3 : 1/3 |
| `beyond-chaos` | latest build/beyond-chaos/*.sfc | only names/descriptions the seed changed | — |
| `worlds-collide` | latest build/worlds-collide/*.sfc | same | — (events not portable as data) |
| `tedition` | build/t-edition/T-Edition 3.0.7 (Mato).sfc (JP ROM; a US-layout image in memory, tools/jp_layout.py) | Mato's full names where they differ from the PR's | item identity, 4 drop slots; writes mods/TEditionPort, which `tools/ted_build.py` merges with the maps' and events' folders into mods/TEdition |
| `--rom X --name Y` | any US v1.0-based mod | same | — |

Opt-in profile options for what a mod changes in its code rather than its data (all off unless the profile sets them):
- `table_overrides = {table: {row id: {column: value}}}`: single values a mod sets in its event code (BNW: Shadow's
  hire costs 1000 GP, product 562; Phoenix Tear's item row takes Phoenix Down's revive).
- `function_overrides = {table: {row id: {"battle" / "menu": [(function, v1, v2, v3), ...]}}}`: a row's whole effect;
  each list becomes a function group found or made by the spell porter's allocator (`sp.function_group`, past the
  table's highest id). BNW: Restore and Regen / RegenX also cure HP, Elixir and Megalixir lift statuses (2026-11-21).
- `port_exp_table = True`: the mod's character EXP curve (SNES ED/8220, 99 words, x8 cumulative) onto exp_table
  group 1, up to the mod's last non-zero entry; later levels kept non-decreasing. A level cap goes through
  `game_constants` (`MAX_LV`). BNW: level 2 at 64 (the PR's 32), cap 50 (2026-11-21).
- `sync_monster_copies = True`: the PR's Coliseum copies of monsters (500+) take their regular's ported stats.

`port_bnw.py` is a wrapper for `port.py bnw`. Test any port with
`PR_MOD=<ModName> pr/.venv/Scripts/python -m unittest discover -s pr/tests`.
Only one ported mod should be installed in the game's Magicite folder at a time.

Beyond Chaos (New Player seed 9859608359) ports with no BC-specific code:
characters/commands/names, equipment (98 new equip groups), 348 enemies,
espers, shops, 193 chests, 151 encounter sets. Not portable as data: BC's
custom commands, sprite/palette/music shuffles, weapon procs.
T-Edition (2026-11-20): `port.py tedition` through `tools/jp_layout.py` + `profile_tedition.py`
(see "T-Edition feasibility"). Before that: T-Edition needed a Japanese-ROM layout profile (different table offsets, JP text
encoding, 6 MB ExHiROM relocations) — not started.

## Setup (done 2026-11-04)

- Game: `D:\SteamLibrary\steamapps\common\FINAL FANTASY VI PR`
- BepInEx 6.0.0-pre.2 (IL2CPP x64) + Magicite 2.2.0 installed; added files are
  listed in `pr-install-files.txt` (delete them to uninstall).
- Magicite mods go in `FINAL FANTASY VI_Data/StreamingAssets/Magicite/<mod>/`.
- `pr/.venv` — Python 3.12 venv with UnityPy (`.venv/Scripts/python`).
- `tools/extract.py` — dumps every text asset from the game's bundles into
  `vanilla/<group>/<container path>` with `keys/Export.json` (Magicite layout).
  8,173 assets, 141 MB, audio skipped unless `--audio`.

## Sources of truth

- BNW ROM: `build/brave-new-world/Brave New World 3.0 FRC.sfc` vs vanilla
  `rom/vanilla/Final Fantasy III (USA).sfc` (US v1.0).
- BNW source: `mods/brave-new-world/source` (git clone of Gens81/brave-new-world,
  `asm/banks/*.asm` = every code change, commented).
- BNW manual: `mods/brave-new-world/3.0-final-rc/.../Printme 3.0.pdf`,
  `full_changelog.txt` (3.0 delta only).
- SNES table layouts: Worlds Collide's `mods/worlds-collide/data/*.py`.

## PR data model (vanilla/master/.../Master/*.csv, 96 tables)

| SNES table | PR table(s) |
|---|---|
| Character init + level growth | `character_status`, `growth_curve`, `exp_table` |
| Items (one 256 list) | `item` (consumables), `weapon`, `armor` (armor/shield/helm/relic), `content` (names/icons for everything) |
| Spells / skills | `ability`, `ability_group`, `command`, `condition_group`, `attribute_group` |
| Espers + spell learning | `learning`, `ability` (summons), `content` |
| Equip permissions | `job_group` (character combos) via `equip_job_group_id` |
| Enemies | `monster`, `monster_asset`, `monster_flag_group` |
| Enemy AI | `monster_ai/.../MonsterAI/sc_ai_*.json` (72 mnemonics: StartTable/Act/CounterAct/Is*...) |
| Formations / packs | `monster_party`, `monster_set`, `encount_*` |
| Shops | `product`, `product_group` |
| Chests | `treasure_box` + map entity JSON |
| Text | `message/.../Message/system_en.txt` (names, descriptions), `story_mes_en.txt` (dialogue); TSV `KEY\tvalue` |

Stat names in PR: strength=Vigor, agility=Speed, vitality=Stamina(BNW "Spirit"), magic=Magic.

Magicite partial CSVs: header row + only the edited rows (full rows).
Partial TXT: only edited lines.

## Verified mappings (tools/idmap.py, checked against PR vanilla)

- Characters: PR `character_status` id = SNES id + 1 (stats identical).
- Items: weapons 0-89 → `weapon` +2; shields/helms 90-131 → `armor` −85; body
  armor 132-162 → `armor` −84 (PR armor 47 unused); relics 176-230 → `armor` −97;
  tools 163-170 → `item` 30-37; skeans 171-175 → `item` 25-29; consumables
  232-254 → `item` 1-23 (GBA names: Tonic→Potion…); Rename Card 231 → `item` 24.
  254/255 match on stats; stat boosts match 100%.
- Consumables: `port_items` copies only the price. The PR heals by the row's `standard_value`
  (= the SNES power for vanilla's Tonic, Potion, Tincture, Ether, Dried Meat) through function 1
  (value1 1, value2 2 = HP / 3 = MP). `port_item_effects` (run last, so the groups it adds take the
  highest ids) handles a mod's fixed-amount heals (SNES byte 19 0x08 HP / 0x10 MP, without 0x80
  fraction or 0x20 lift; byte 0 bit 5 = battle, bit 6 = menu). If only the power changed, the
  mod's power goes in (BNW's Dried Meat 150 → 100). If the slot held another item, the row is
  rebuilt from the vanilla heal that works the same way, plus the statuses the mod's item adds in
  battle (BNW's Red Bull on Echo Screen's row: 200 HP + Float; Slim Jim on Smoke Bomb's:
  100 HP + Regen + Haste, battle only). T-Edition's Potion, Hi-Potion, Ether and Hi-Ether get its
  powers this way too (90, 255, 100 MP, 250 MP). Fractional heals stay with the mod's plugin
  (BnwPlugin ItemHealRules). Revives and status cures keep the rules they already have.
- Enemies: `monster` id = SNES id + 1 (372/384 identical; rest are dummies).
  Bat.Pwr→`attack`, magic→`ability_attack`. Steal: slot1 = common, slot2 = rare.
  Drops: common only → rate 87, rare only → 12, both → 100 (d1 common, d2 rare).
- Equip permissions: SNES char bit b → PR job b+1, plus jobs 15-18 (guests) for any
  wearable item and job 19 when Terra (job 1) can equip.
- Spells: `idmap.spell()`: black/gray +40, white −14, espers by table, Bushido/Blitz
  +39, dance moves +71, Magitek +87, Lores +1, enemy skills +137, desperation −12.
  241/251 match on MP+power (rest are PR tweaks/removed duplicates).
- Ability fields (learned by tools/learn.py): mp→use_value, power→standard_value,
  accuracy→accuracy_rate, elements→attribute_id/attribute_group_id,
  targets→renge_id/battle_renge_id. Status effects live in
  `battle_function_group_id` → `function_group` (function 9 = add status, value1 =
  condition id; function 3 = damage).
- Learning (`learning.csv`): type 1 = level-up (job = character), type 2 = esper
  spells (value1 = esper content id 61+n, value2 = rate), type 3 = Mog dances,
  type 4 = equipment-taught spells (value1 = equipment content id).
- Growth: `growth_curve` group 1, `hp_value1`/`mp_value1` per level; SNES HP table at
  0x26F4A0 matches PR exactly; PR rebalanced MP (BNW overrides it anyway).

## Spell port design (tools/port_spells.py)

Slot-based: PR ability `idmap.spell(i)` becomes BNW spell i (all BNW references
use slot numbers). Each slot borrows presentation (animation, school, icon, menu
SE, base effect functions) from a *template*: the vanilla spell with BNW's name
(or `ALIASES`), read from an untouched copy of vanilla. Numbers come from BNW via
learned value tables; statuses are rebuilt as function 9 (one status), 10 (status
group) or 12 (removal group, flags3 & 0x04) only when BNW's statuses differ.
Text: names from BNW's relocated tables (Bushido at 0x0F3C40), descriptions
decoded from the BNW ROM's own pointer tables (`tools/bnw_text.py`; the repo asm
is slightly ahead of the 3.0 build, so data always comes from the ROM).
Keys shared with items (`MSG_ITEM_*`, e.g. scrolls) are left to the item pass.

`mods/BraveNewWorld/bnw_data.json`: per-esper SP costs, EL bonus (text + id),
equip bonus text and which characters may equip it, for the plugin.

## Resistances (tools/port_resist.py, tools/groups.py)

Elements: SNES bit → PR attribute [1 fire,2 ice,3 bolt,6 poison/dark,8 wind,7 holy,
4 earth,5 water]; type 4 absorb, 3 null, 2 half, 1 weak (enemies bytes 23-25;
armor half 15, absorb 22, null 23, weak 24; weapon element byte 15). Status
protection bytes 6-7, auto-status byte 8, enemy immunity bytes 20-22, enemy
initial statuses bytes 27-29 (byte 30 = flags). Groups are only rebuilt where BNW
differs from vanilla. Element map rebuilds all 373 vanilla enemies exactly.

## Encounters (tools/port_encounters.py)

PR re-zoned the world maps: areas 164-188 (WoB) / 264-297 (WoR) each use one
`monster_set` (401-425 / 451-484) equal to one SNES pack; dungeons use
`map.monster_set_id`; sets are 4 parties at 80/80/80/16. Sets are matched to
vanilla packs by enemy line-ups (184/188). For each set: SNES places that used
that pack (world zone/terrain slots 0x0F5400/0x0F5500, dungeon maps 0x0F5600
with random battles on: map props 0x2D8F00 byte 5 bit 7) → majority BNW pack
there → set refilled with new parties 2000+formation (vanilla parties untouched
so event battles keep theirs). Layouts: copied from a vanilla party with the
same line-up, else nearest free cell of the 3×3 grid (cells 1-3 front, 4-6
middle, 7-9 back; top/middle/bottom). Packs that are all empty formations are
left alone, and places the mod gives such a pack (BNW's pack 0: its unused maps and terrains
with no battles) don't vote (2026-11-20: 15 sets had kept vanilla's monsters). A random battle's
party odds are the mod's (C0/C258, C0/C3F1 thresholds; BNW 80/80/48/48) as the sets' weights.
Rates (tools/port_encounter_rates.py -> the mod's data -> the kit's PrKit/Ff6/SnesEncounters.cs, the SNES
danger counter on the PR's steps): the rate tables C0/C29F and C0/C2BF, the battle roll (C0/C48C; BNW
4 + random x 233 / 256), world codes per zone (CF/5800, CF/5840) and the cell's terrain group from its
PR ground (foot_information type -> SNES group, learned from vanilla's packs: WoB 2,3,4,7,19 grass, 9
forest, 15 desert; WoR 19,26,28 group 0, 30 forest, 29 desert, 5,6,8,20,25 group 3), other maps per PR
monster set (the codes of the SNES maps of its vanilla pack; BNW's 3 maps without random battles are
NoBattles). Not mappable without SNES map <-> PR map: SNES map 53 (BNW very high) and Fanatics' Tower's
roof (BNW off) share PR sets with other floors; 6 maps BNW gave random battles have no PR set.

## Equipment effects, procs, Rages (tools/port_effects.py, port_procs.py)

Source of truth for the bits: a research pass over BNW's asm (bnw 3.0/asm overrides
asm/banks where they differ; e.g. RandomCast is item.asm:310). Item bytes 5/9/10/11/12/13
-> battle RAM $11DF/$11D5-$11D9, $3C58/$3C59 = bytes 12/13, $3CBC = byte 27.

Relics/armor: `wear_function_group_id` functions 60 HP/MP % (value1 1 HP, 2 MP), 61
command change (from, to), 62 add equip ability (HP+25/50/12.5% = 286/288/245, MP =
287/289/244, Gauntlet 251, Genji 252, Offering 253, MBlock +10..+50 on weapons 256-259),
67 MBlock, 75 MP cost; learned per SNES bit from vanilla (`G.learn_bits`). Cover,
counter, always-hit and SOS live in **`wear_condition_group_id`** instead (conditions
29/48/49/46/47; `CONDITION_BITS`, checked against vanilla armor), built as multi-row
condition groups for BNW's combinations (Leo's Crest = cover + counter + always-hit).
BNW puts relic bits on **weapons** too (HP%, counter, cover, two-hand, dual wield,
Offering, proc rate): applied there as well. BNW-only bit meanings come from the profile
(`relic_bit_funcs`: 10.4 Leo's Crest = Runic -> Shock, 61(16,28)).

Weapons (rebuilt from vanilla's own data: 90/90 weapons for functions, species, evade;
89/90 for program and on-hit condition): byte 26 = MBlock (high nibble, function 62
256-259) + evade/10 (`evasion_rate`); byte 27 high nibble = special effect (low nibble is
only the parry graphic): 1 steal THIEFS_KNIFE, 3 X-Kill ASSASIN_WEAPON + condition group
100, 4 x2 vs humans (`effective_species` 2), 5 drain fg 13, 6 MP drain 77+13, 8 HAWK_EYE,
9 DICE, B Tempest (change_ability_by_weapon), D SWORD_THAT_CUTS_IRON (1/3/4/8/D also
function 23). 2 Atma, 7 MP crit, A Valiant, C heal, E Ogre Nix are id lists in code.
BNW's meanings (`profiles.BraveNewWorld.weapon_specials`): 3 = x2 humans + 50% Net, 5 =
x2 humans + ignore Defense, 6 = 50% Net, B = Windslash, E = 50% Aero replacing the swing,
F = undead slayer (plugin todo). Conditions no SNES bit explains (the PR's condition 64
on Guardian/SwordBreaker/Falchion/Murasame) stay only where BNW kept the same weapon.

Weapon spell procs (`tools/port_procs.py`): the spell is data after all, in the
`battleextradata` group (`battle_extra_data.json`): `add_ability_weapon`
{weapon_id, ability_id, ability_per} (vanilla 18 entries, 25%); `process_prog =
ADD_MAGIC` only marks the weapon. ability_id is a *proc copy* of the spell (vanilla
263-276: the spell's row with type 629, invalid_reflection 1, ability_wait 0,
content_flag 0, nameless content row). SNES byte 18 bit 6 = cast randomly, bits 0-5 =
spell; vanilla data and ROM agree on all 18. BNW: 25 proc weapons (12 new, 7 other
spell, 5 removed), 11 new proc copies (ids 5918+), the 13 vanilla copies carry BNW's
changes to their spell. The file is written whole (Magicite merges JSON by top-level
key, `MergeJsonDictsInPath`). The plugin (`WeaponProcs.cs`) sets every entry's
ability_per to the acting character's chance before each action is built
(`FunctionProvider.CreateActFunction` prefix; BNW: 1 in 4, 1 in 2 with "High Proc
Rate"). Odds (bnw 3.0 item.asm RandomCast, `profiles.proc_odds`): 1 in 4; "Use Brush
Odds" (byte 11 bit 2: Soul Sabre, brushes) 1 in 2; "High Proc Rate" (byte 12 bit 7, on
5 relics and 6 weapons) 1 in 2, or 3 in 4 with brush odds. Weapons' own odds are data
(ability_per); the relic part is the plugin (bnw_data.json procs.weapons rate/high_rate).
Special-effect procs (`special_procs`): 50% Net on Kusarigama and both Kagenui;
change_ability_by_weapon Kazekiri -> Windslash 25%, Mutsunokami/Windbreaker -> Aero 50%.
Relm's brushes need no retargeting: their attack heals/targets allies (NormalAttackHeal
list), so their Safe/Shell/Reflect/Haste procs land on the ally. A mod that clears "cast
randomly" on most vanilla proc weapons but keeps their spells (Beyond Chaos) has its own
proc rules: vanilla procs and rods are kept for it.

Items the PR keys effects on in code (`HardItems.cs`, bnw_data.json hard_items): static
members such as SpcialFlagData.EncountDownItemId/NonEncountItemId/HealingItemId,
CalcExecuteCorrection.Physical/MagicCorrectionAccessoryIds (dict of arrays),
UseMpCriticalWeaponIds, NormalAttackHeal, IgnoreDefenseItemIds, bloodSwordId,
BattleActExectionSerial.UseBrokenWeaponIds, SerialBattleUtility.ArmorIdHornOfDragon,
ParameterProvider.RingsOfTheDeadId, PassiveContentProvider.ContentId* — all static,
settable. BNW reused those slots (Moogle Charm would block encounters, Daryl's Soul double
EXP, Black Belt halve encounters), so each list is rewritten to BNW's items, but only if it
holds exactly the expected vanilla items (as item ids or content ids, whichever it uses);
re-checked every 300 frames until settled (a late static constructor would undo it).
x2 EXP/gil: PassiveContentProvider.GetExp/GetGil postfix returns the base value (BNW has
neither). DashItemId is left alone (BNW: everyone dashes; turning it off might stop dashing).

**Two IL2CPP traps (both shipped once, both fixed):**
- v0.11.0 crashed the game (AccessViolation, uncatchable) writing
  `SpcialFlagData.EncountDownItemId`: it is a C# *constant* (literal field, no storage);
  Il2CppInterop still exposes a settable static property. Before any static write the
  plugin now reads the field's flags (`HardItems.WriteProblem`:
  `NativeFieldInfoPtr_<name>` -> `IL2CPP.il2cpp_field_get_flags`, FIELD_ATTRIBUTE_LITERAL
  0x40) and never writes constants. Constants found: SpcialFlagData.EncountDownItemId /
  NonEncountItemId / HealingItemId, Tamanosuzu.HealingItemId,
  SerialBattleUtility.ArmorIdHornOfDragon, PassiveContentProvider.ContentIdGaleHairpin /
  ContentIdAlarmPiercing, BattlePassiveConstants.BlackBeltCounterPercentage (75).
  Real static fields (rewritten fine): CalcExecuteCorrection lists, bloodSwordId,
  BattleActExectionSerial.UseBrokenWeaponIds.
- v0.11.2 patched SpcialFlagData.IsEncount/GetEncountValue/IsMoveHealing, which take the
  party as `ref List<OwnedCharacterData>`: Il2CppInterop's Harmony support emits invalid
  IL for a by-reference *object* parameter (InvalidProgramException on every call: ~200
  per minute of walking, encounter checks failing). Don't patch such methods. Hooks with
  `ref int` parameters (IsUseMpCriticalOccurrence, GetAccessoryMagicCorrectionValue) have
  not thrown. Still todo: the encounter relics (Moogle Charm slot still blocks
  encounters, Charm Bangle slot halves them) — candidate hook points are the lambdas
  `SpcialFlagData.__c._IsEncount_b__20_0` / `_GetEncountValue_b__22_0`
  (KeyValuePair<EquipSlotType, OwnedItemData> by value), untested. Walking regen is
  cancelled at `Last.Map.Tamanosuzu.CheckUseItem` (no by-ref parameter). Dragon Horn is
  redone in `CanContiniusJumpAttack` on BNW's items (Dragon Helm).
- Physical correction dictionary (`CalcExecuteCorrection.PhysicalCorrectionAccessoryIds`,
  key = PhysicalType): 0 PilgrimsPassport = Offering [armor 114], 1 GenchisBasho = Genji
  Glove [112], 2 BasketsOfGiants = Atlas Armlet/Hero Ring (rewritten to BNW's +25%
  relics), 3 Gauntlet [111]. 0/1/3 key on vanilla relic slots that are dead in BNW, whose
  abilities BNW put on weapons (62(253/252/251)): so Offering weapons/Daryl's Soul likely
  get 4 hits without the damage cut and two-hand/dual wield get no correction. Todo:
  postfix GetAccessoryPhysicalCorrectionValue for 0/1/3 by the wearer's equipment
  abilities, with BNW's values (Offering 2 hits at -25%, dual wield -25%, two-hand x1.5)
  once the value format (multiplier vs fraction) is seen in a log.
  EquipmentAbilityData.TwoHandedMagnification is 2, not 175: it doubles the attack (2026-11-06:
  the grip, below; RelicRules applies BNW's x1.5).
Same porter, weapon usage bits (checked equal on every vanilla weapon): byte 0 bit 4
"throwable" = `throw_flag` (BNW makes Throw a property of a chosen few weapons: the
manual's "Throwable" tag; ~50 weapons lose it) and byte 18 bit 7 "break it from the
Item menu to cast" = `destroy_rate` 100 (BNW: only the Fire/Ice/Thunder Rods;
Windbreaker, Doomstick, Quartrstaff are plain staves).
Rages: SNES 0x0F4600 (2 attacks per monster) → the monster's
`rage_ability_random_group_id` rows (BNW odds 67/33).

## Formations, shops, chests

2026-11-06 (BNW re-port): chests 159 PR chests in 93 map files, 5 of the PR's scripted chests
filled (the game's own Tag / SetGilTag + "Obtained" line + GetItem, as vanilla's pick-ups),
6 boxes with BNW's monsters on their box's background. Shops: 82 matched + 10 PR copies;
SNES shop 86 is new in BNW (vanilla's is unused): a merchant NPC BNW added in Doma Castle (SNES
map 126, NPC 16, WoR). The PR opens each shop with its own SysCall ("ショップを開く:<town>...",
one game method per shop with its group id), so a new shop needs a new NPC and a plugin call.

2026-11-07: the rest. The merchant (tools/port_merchants.py, profile added_merchants; BnwPlugin
ShopCalls.cs): an NPC copied from South Figaro WoR's shopkeeper, placed by the profile (BNW's
spot is behind a wall in the PR room), script 9901 = the shopkeeper's script with SysCall
"BNW:shop <group>", which the plugin answers with the game's Current.OpenShopCommon(group,
isFirstClock). Every new script must be in its map's entry of the map group's package.json
(pr_script.list_in_map): a map loads only the scripts listed there (MapModel.GetScript), and
the field looks scripts up there by name. The six chest changes left were four SNES places with
no vanilla chest and two item chests made boxes. By event bit: map 44's Moogle Charm moved two
tiles up (inside the PR room's wall; the PR's chest keeps its spot, same contents); map 72's
1000 gil is the third SNES copy of a chest already ported (bit 97: maps 68/69/72); map 414's is a
copy of map 296's (bit 235; no exit or event leads to map 414, and its copy holds BNW's blank
item 208); map 408's box moved from its twin map 406 (bit 205). port_chests.moved_chests: a
mod's chest at a new spot whose bit is exactly one vanilla chest's that the mod dropped is that
chest. The two boxes (South Figaro's Earring in both PR copies, Mt. Zozo's Red Cap) get box
scripts of their own (port_chests.new_box: the PR's box script sc_e_0641 opening the chest's
entity, its after-battle script with only the fade-in; script ids 9801-9803; listed in their
maps' package.json), fighting on the map's random-encounter background (map.csv
monster_set_id's first party). Box battles: a box took idmap.party(formation), vanilla's party
for that formation number, but BNW renumbers and edits formations (its 351 is vanilla's 465,
Katanasoul; its 256 is a Dinosaur where vanilla's is four other monsters), so
port_chests.seed_party now uses a vanilla party with BNW's line-up, else a new one from the
encounter porter (party_for). WC seeds don't edit formations: unchanged. Headless (FormulaProbe
"shopcheck=<map>:<point>:<script>" and "boxcheck=..."): the shop opens, both box kinds start
their battle with BNW's monsters.

The Veldt (tools/port_veldt.py): the PR's table is the misc asset's beast_field_encount_table,
group N = SNES formation block N - 1, one entry per formation (flag_index, monster_party_id,
encount_target_party_id + encount_target_other_ids: the parties whose battle opens it). The SNES
offers any met formation its flags allow ($F5900 + 4f, byte 3 bit 1: not on the Veldt); BNW
allows 74. The mod ships its copy with a keys file (misc/keys/mod_misc.json), as battleextradata.

Chests, 2026-11-05 (later): matching rewritten (`port_chests.match_flags`). The old content-only
match let one place's chests take another's when they share common items (SNES map 226's
Running Shoes landed on map 378's chest in PR map 20241, so BNW's item for one place went into
another's chest) and filled only one copy of places the PR keeps twice (Figaro Castle
20051/20371, South Figaro 20071/20361...; the copies share the chest's flag_id). Now: per SNES
map and PR map file, the offset under which the most of its chests sit on same-contents PR
chests; every chest of the map (empty and monster-in-a-box too) takes the flag at its spot
(every matched content chest lands on vanilla-equal PR contents); the content match stays as a
fallback inside groups the layout tied to that map; where the PR merged a place's two SNES maps
into one set of chests, the chest the mod changed wins. Writes go to every entity of the flag;
a vanilla monster-in-a-box that BNW made a plain chest loses its battle script (Zephyr Cape,
Umaro's Bone Club, a Dried Meat). BNW: 121 of its 129 item/gil chest changes placed (was 118,
some at the wrong spot), 135 PR chests written (was 118); left: 5 with no PR chest near
(Psycho Belt, Phoenix Down, Green Beret, 1000 gil, Wing Edge) and 3 on chests the PR shares
with another changed chest.

- AP: SNES magic-point table 0x1FB400 (512) → `monster_party.get_value` (PR id = formation + 1).
- Formations: SNES 0x0F6200 × 15 bytes (mold, slot mask, ids, positions, id msb);
  455/576 match PR party f+1 by enemy set. BNW reshuffled 559 of 576 formations.
- Shops: SNES 0x047AC0 × 9; PR `product` rows grouped by `group_id`; matched by
  stock overlap (82 exact). Extra rows are parked in group 9999.
- Chests: SNES ptrs 0x2D82F4 → data 0x2D8634 (5 bytes: x, y, bit, type|bit9,
  contents; type by priority item 0x40 > gold 0x80 > monster 0x20 > empty 0x08).
  PR chests are `entity_default.json` objects (action_id 6, content_id = content.csv
  id, 1 = Gil with content_num). PR flag_ids are renumbered, so chests are matched
  per map by contents (`tools/port_chests.py`, 222/233), then by position (16 px tiles,
  per-map offset from the paired chests). The 13 BNW chests left have no PR entity of their
  own: two SNES chests share one spot where the PR has one entity (e.g. bits 116/257 on map
  378, World of Balance/Ruin versions), or vanilla's chest was empty/monster and the PR has
  none there. Adding chests needs new entities and save flags: not done (known limit). Modified map files are
  written whole, keyed from `vanilla/assetspath/.../AssetsPath.json`
  (map keys look like `Map_20011_1/entity_default`).
- Enemy slots: BNW renamed/re-statted 288 enemy slots mostly in place (same sprite).

### BNW's changed scenes beyond its text (event audit, 2026-11-20, `tools/event_diff.py`)

`tools/event_diff.py <mod.sfc> --ranges 230000-260000` (kit; on `tools/snes_events.py`): both ROMs'
field scripts decoded from every map's entrance, event tiles and NPCs, each script and each subroutine
compared once (calls not inlined, callees paired through their callers; addresses as labels; once with
and once without dialogue numbers). BNW's added event code is in bank ED (event addresses 0x23xxxx)
and in freespace in CA-CC; 17 spots still stop the decoder (opcodes 66/BD/C1 and calls into code it
doesn't reach yet). Against vanilla: 195 script units changed, 39 entries new, 36 removed, 15 text-only.
By kind (rows = script units or entries; a place listed once per unit):

| Kind | Rows | Where | Status |
|---|---:|---|---|
| Dialogue only | 15 | Narshe, Nikeah, Owzer's, Esper Cave, Kefka's Tower... | ported (DialogText) |
| Event battles (formations; 4 also flip a battle flag: Phantom Train, Zozo, Cultists' Tower, map 119) | 6 | Narshe, Doma, Phantom Train, Zozo, Cultists' Tower | formations ported (port_events); the battle flags not checked |
| Julian's Schematics (SNES 55), Kaiser after the 8 dragons (304, the tally), the Sealed Gate's Kefka fight + lines | 4+ | Figaro, Kefka's Tower, Sealed Gate | ported (Julian earlier; Kaiser and the Sealed Gate by bnw-enemy-ai, tools/port_boss_events.py) |
| Doma's new merchant | 1 | Doma Castle 126 | ported (port_merchants) |
| New save points | 22 (11 places) | Figaro Castle 63, Zozo 225, Zone Eater 276, Yeti's Cave 281, Burning Home 351, Cave on the Veldt 353, Cave to the Sealed Gate 384, Cultists' Tower 369, Ancient Castle 408, Kefka's Tower 337, map 414 | ported 9 (bnw-enemy-ai, tools/port_bnw_mechanics.py: the PR's SavePoint + sparkle pair on the room that draws the cell walkable); Figaro 63's room isn't among the PR maps snes_maps pairs with it, map 414 has no PR room |
| Event rewards changed (items, espers, gil the scripts give) | 18 | Returners' Hideout (Banon's gifts), Narshe Mines, Figaro Castle 58, South Figaro 15, Mobliz (Phunbaba's magicite), Owzer's hidden items (4), Darill's Tomb, Floating Continent, Cave to the Sealed Gate ("ninja stuff"), Cultists' Tower 368, Ancient Castle (Odin/Raiden), Fenrir (398) | ported (bnw-enemy-ai, tools/port_bnw_rewards.py: 15 PR scripts' GetItem/RemoveItem changed, 11 given BNW's new gifts: 5 Dried Meat after Tritoch's flash, Daryl's Soul, Dadaluma's Hell Claw when fed Dried Meat (his battle bit on a PR flag), the Imperial and Celes optimized on the Floating Continent, the party restored before its escape fight, the Veldt cave's Kagenui swap; Odin's statue gives none, the Queen's gives Odin and takes nothing); the blacksmith is bnw-text-ui's, Leo's Crest bnw-scenes' |
| The auction house gone; its espers sold by "Bob" (gil_remove + esper_add) | 18 removed + 3 added | Jidoor 200 (the auction's NPCs), Dragon's Neck Cabin 186, Coliseum 413, Cultists' Tower 362 | ported (port_bnw_mechanics): BNW's Jidoor has no exit into the auction house (map 198), so the PR's two town maps lose that door; Bob sells Golem and Zoneseek in the Dragon's Neck Cabin (a new script on its old man) and the Coliseum, Alexandr in the Cultists' Tower, BNW's prices and conditions (plugin SysCall "BNW:pay", flags ScenarioFlag4 0-2) |
| Join levels (vanilla's 32 `char_level_avg` 77s: BNW turned 13 World of Ruin recruitments into its command 66, level = max(own, 21; Edgar 19, Sabin/Celes 18, Setzer 20; c0.asm Level18/RejoinLvl), removed 15 World of Balance rejoins' (Terra and the IMTRF four, Thamasa after Leo x7, Mog, Locke and Terra after the banquet), kept Shadow's 3 and Setzer's 1; first-join offsets (ED/7CB5) all 0 but Gogo -3 / Umaro +5; the audit's 10 rows were the decoded ones) | 10 | Mt. Zozo (Cyan), Tzen (Sabin), Cultists' Tower (Strago x4), Terra after the IMTRF, the banquet 250/251 (Locke, Terra) + the undecoded rest | ported (bnw-engine): `BnwPlugin/JoinLevels.cs` takes over the PR's `CorrectLevel` (the rule: `Rules/JoinRules.cs`, Rules.Tests); harness `joinlv` checks it through the game's JoinCharacter (run pending) |
| Leavers unequipped (char_unequip added) | 4 | Baren Falls, Narshe 20/30, map 391 | ported: all are Shadow leaving (Baren Falls 156/391, Narshe 20); the PR's own leave (sc_e_0216, sc_e_0286/_1) is followed by the plugin's "BNW:unequip 4" (the game's OwnedCharacterClient.RemoveAllEquip, as its party-wide SysCalls do: decompiled tools/decomp/unequip); Narshe 30's 24 unequips are the "Unequip anyone?" NPC (not needed: the PR's Equip menu has Remove All) |
| Scenes added or extended | 11 | Narshe 24 (the blacksmith: forge Apocalypse or Illumina), Imperial Palace 250 (the banquet, x2), Falcon 17 (before Kefka's Tower), Kohlingen 191 (Shadow's fee and a full party), Thamasa 340/344 (Leo's grave, the traveller), South Figaro 81 | ported (2026-11-20; "The added scenes, ported" below): the blacksmith and the fee (bnw-text-ui), Kefka's Tower's barrier, Leo's Crest, the traveller, Shadow's full-party hire, South Figaro's wall (bnw-scenes, `tools/port_bnw_added_scenes.py`); the banquet needs nothing (the PR already asks) |
| Cyan's dream ("Cyan's Uneventful Dream", PowerPanda): no party split, rescue pieces of Cyan's psyche | ~33 (map 317) | Dreamscape | ported (bnw-dream, tools/port_bnw_dream.py: "Cyan's dream as BNW's" below) |
| Scenes cut or shortened (lines and moves removed) | 19 | Imperial Camp 117 (x2), South Figaro Cave 150, Figaro Castle 64, Owzer's Mansion 208, Ebot's Rock 405, South Figaro 78 (the cider thief), Cabin 115, map 7, map 340, Jidoor 198 (3 NPCs), Narshe 20 (2 NPCs) | to port where it's story (with the kit's scene skips, as WC cuts scenes); the NPC lines not needed |
| Party handling in scenes (who joins, leads, stays) | 10 | Doma 120/124, Cabin 116, Floating Continent 393/394, Kefka's Tower 261, Narshe 22 (the Battle for Narshe), Narshe Mines 44, map 7, map 55 | to review: some are BNW's speed-ups |
| Veldt freebies (a new command at the world's end marks the missable WoB formations met) | 1 | the World of Ruin's start | ported: veldt-freebies.asm's table (45 formations, all on BNW 3.0's Veldt) opened in the PR's world's-end scene (sc_e_0607_7) by the plugin's "BNW:veldt_open", the game's own BeastFieldEncount.EncounterMonsterParty for each one's Veldt party (decompiled tools/decomp/veldt_met) |
| Lines removed | 8 | Duncan (Dragon's Neck, his cabin), Imperial Observation Post, Thamasa, Narshe 107, maps 8/55/340 | small: skip those lines |
| Pacing and look (waits and moves turned into nops, palettes, small object changes) | 77 | across the game | not needed: the PR's scenes are its own redraws with their own timing |
| Tutorials and save-point help (BNW removed the save-point tutorial, the Narshe school's hints) | 4 | Narshe 34, 104-107 | not needed: the PR's own tutorials and save points |
| Game over goes to the load menu | 1 | map 3 | not needed: the PR's own game over |
| Other (Magitek Factory's escape: an esper gift and a restore replaced by "NO! BAD PLAYER!", the Coliseum's entry, Kohlingen, Phantom Train, Serpent Trench, the Returners' Hideout, Zozo, Imperial Palace 331...) | 30 | | to review one by one |

Rough size: save points, rewards, the level and unequip rules, Bob and the Veldt freebies are small
(about a day); the added scenes, Cyan's dream and the story cuts are the bulk (several days);
the "review" rows decide the rest.

Split (the coordinator, 2026-11-20): bnw-enemy-ai the mechanics (save points, rewards, the auction and
Bob, the Veldt freebies, leavers unequipped), bnw-engine the joins without level averaging, bnw-text-ui
the scenes (added, Cyan's dream, cuts) and the review rows. Done by bnw-text-ui so far
(`tools/port_bnw_scenes.py`, from profile_bnw.extra_data): the Narshe blacksmith (sc_e_0873: Forge
Apocalypse 121 / Forge Illumina 120 / Wait, BNW's option text, the third option under
BNW_E0873_00_010_c_03), and 8 lines BNW cut (NPC chatter in Narshe, Jidoor's "This is the Jidoor
Auction House", Mobliz WoR; the cabin's Empire exchange before Doma: the PR Msg ops jump past them; two
Jidoor NPCs say their lines from their map entities and keep them); Shadow's hire in Kohlingen costs BNW's 1000 GP (the PR's sc_e_0285 takes RemoveGil [203]: External.Misc.RemoveGil charges the coefficient of the product whose group is the operand, product 562; decompiled tools/decomp/bnw_gil; profile_bnw table_overrides, a new generic port.py option). The text side: a PR line placed on a
dialogue number BNW reuses in another scene (the auction's lines became the Sealed Gate's, Bob's...)
keeps the PR's text unless BNW's shares its wording (bnw_dialog.repurposed_dialogues: 13 lines).
The cut rows rechecked with calls followed (the per-unit diff doesn't inline calls, and BNW often rewrote a scene's start and calls into the rest of vanilla's): not cut, same dialogue restructured: the Imperial Camp (x2), the cider thief (78), map 8, Duncan (127, 128), the Observation Post (377); moved: map 340's two lines (into the Leeroy scene, bnw-scenes'); cut and skipped: Narshe 20 (2), Jidoor 198 (3, two said from entities and kept), Mobliz 340 CB/73FE, the cabin 115 (4), Owzer's 208 (BNW shows none of the five magicite lines; bnw-enemy-ai removes the gift); no PR line to skip: map 55 (0xB68, 0xB6A), Thamasa 349 (0xA16), Jidoor (0xA8B); tutorials (not needed): Narshe 104, 105, 107; mechanics (the party-change prompt on map 7, "ninja stuff"): bnw-enemy-ai's; not readable yet: Figaro Castle 64, South Figaro Cave 150, Ebot's Rock 405 (the decoder stops in BNW's code there; BNW's captions hold rewrites of their lines, so not cut). Review scenes kept by bnw-text-ui: Mog's two Dance tips after his World of Ruin join (BNW_E0778_01/02, sc_e_0778); Mikhail pointing Edgar to Julian (58, BNW CB/5201: "have you spoken with Julian?" unless the Schematics are fetched and the world hasn't collapsed; the PR's script can't read the plugin's flag, so DialogText swaps the text of the chancellor's E1036_00_031_a_01 by Schematics.Have and ScenarioFlag2 41); the Returners' briefing's end (CB/034D: Edgar "Uh, Locke...", Locke "Right.", Sabin "What do you see in that guy?" where vanilla had Sabin's "Guy's got a point": the PR's a_39 and a_40 take BNW's, Locke's inserted; BNW_D016B-D, both copies of sc_e_0062_1/_2). All the review rows are now decided or done.

Hand-over (bnw-text-ui, 2026-11-20, session ended to free RAM; the BNW lead takes these):
- Pending in game (QA batch bnw-11): the blacksmith's choice (harness: warp 10 1; script sc_e_0873; ~9 presses; shot the
  3-option box; choose Wait: no item, ScenarioFlag2 161 stays clear) and a draining cast bar (bnwui join 7 2; battle 26;
  turn 7; down, down, action = Celes's Magic; action, action; `bnwui bars` must say "Celes: waiting, N% left (cast bar)").
  Waits in harness requests are frames. Gau's Rage and Terra's Magitek have no chant in BNW, so they show no cast bar.
- Checked offline only: Mog's Dance tips (sc_e_0778), Mikhail's Julian hint (DialogText swaps E1036_00_031_a_01 by
  Schematics.Have and ScenarioFlag2 41), the Returners' briefing lines (sc_e_0062_1/_2), the 13 cut lines.
- Not readable yet: Figaro Castle 64, South Figaro Cave 150, Ebot's Rock 405 (the decoder stops in BNW's code there;
  judged "not cut" from BNW's captions holding rewrites of their lines). Calls into code outside the ranges given to
  event_diff.rom_for (CA-CC and bank ED) are the likely cause: more ranges would let the decoder reach them.
- Rage descriptions are one line ("2/3: ...; 1/3: ...") and fit the battle window; not looked at in the field menu's
  Skills > Rage list. FAIL/NULL are English only (other languages keep the game's Miss sprite).
- Open question for the kit lead: bnw_text.rage_descriptions (BNW's Rage table at C4/A820) sits in a kit file; it
  could move to a bnw_* file.
- Tools: event_diff.py (audit), port_bnw_scenes.py (blacksmith, Mog, briefing, CUT_LINES), bnw_dialog.ADDED_LINES /
  ADDED_DIALOGUES / EXTRA_OPTIONS / ADDED_SPEAKERS (BNW-only lines), notes for the scenes sessions in the shared notes
  folder (bnw-scenes-plan.md).

The added scenes, ported (bnw-scenes, 2026-11-20; `tools/port_bnw_added_scenes.py`, called from
port_boss_events.port with profile `bnw_added_scenes`; BNW's lines are bnw_dialog keys BNW_D<n> and, where the
speaker changes inside a dialogue, BNW_D<n>_T<nn> per speaker turn (ADDED_TURN_DIALOGUES); new flags
ScenarioFlag4 8 / 9 from data/snes_event_alloc_bnw.json; scripts 9981-9982). Read with BNW's bank-ED code:
- Kefka's Tower's barrier: the audit's "Falcon 17" and "Narshe 24" rows are one scene (CA/01A2 -> EE/AF50;
  the blacksmith NPC only shares the code block; `if 0x127 clear` is FF6's goto). Until the party has Terra's
  pendant (bit 0x2DB: the Cultists' Tower top's battle, the PR's ScenarioFlag2 168 set by sc_e_0881_1, so
  nothing gets stuck) Setzer won't fly in: the forcefield, the Warring Triad, the pendant lost with the
  Blackjack, back to the Falcon (the short version on later tries); with it, "The pendant is glowing!",
  "We're through!", then the PR's own scene. In the PR's sc_e_0966_3 after its first line, first visit only.
- Leo's Crest: World of Ruin South Figaro's cider deliveryman (BNW's CB/51FC; bit 0x0A4 = the World of
  Ruin) trades Celes's cider for "Leo's Spirits"; at Leo's grave in Thamasa (CC/0977) Celes pours it and
  gets Leo's Crest (SNES item 0xB0, the PR's content 275). The PR's World of Ruin town has no deliveryman:
  a new NPC with the World of Balance one's look in Map_20361_5; the grave (Map_20460 entity 44) runs
  sc_bnw_leo_grave. BNW lets the trade repeat, so each trade and visit gives another crest (ported as is).
- Thamasa's traveller (CB/756E): only his line about the Zone Eater's island; BNW gave the story trip's
  dialogue numbers to Celes's grave scene (the PR's trip line would have shown her farewell). sc_e_0941.
- Shadow in Kohlingen (CC/6FEB -> ED/8DC6): a full party is asked too; paid, "Choose 3 characters." and
  the one-party menu; still four, the fee back. sc_e_0285 (the fee itself: bnw-text-ui's price override).
- South Figaro (81's entrance, CB/51A5): the cell before the rich man's basement stairs is wall until the
  Lete River raft (bit 0x19, the PR's ScenarioFlag1 48 from sc_e_0063_1); the first visit can't go down
  early (Locke's scenario always comes after the raft). Map_20071_8: an invisible blocking object (the
  PR's own kind) in an entity set its map script shows.
- The banquet (Imperial Palace 250, CC/85E3 / CC/860D, "550 commands"): BNW's only change is the door's
  "Are you done talking to the soldiers?" (the unit grew because the banquet became reachable from the
  tile); the PR already asks it (sc_e_0471 / sc_e_0472). Its char_level_avg removal is bnw-engine's rule.
- Handed over by bnw-enemy-ai (review rows that are scenes): the Coliseum (413, CB/78C3) without vanilla's
  Shadow after the Striker match (the PR's code runs sc_e_0750 then: restore and fade-in only); Kefka's
  Tower's drop outside (331 = Map_30871_12, CB/5252) "Sealed by a mysterious force." until AtmaWeapon
  there falls (the PR's ScenarioFlag2 223; sc_e_0978); the Falcon's wheel (CB/5230, dialogue 0x6A5) with
  "Find Doom Gaze" until Bahamut (sc_e_FAoutboard: a third option taking off into the PR's Deathgaze fight,
  EncountBoss 464, through a new world-map script sc_bnw_find_deathgaze); the Zone Eater's three train
  conductors leave after knocking the party off once (276; BNW's new_events.asm, bits 0x0EE-0x0F0: scripts
  9983-9985 and Map_30791_2's map script hiding the ones met). Found on the way: BNW's Coliseum table (all
  256 wagers changed) isn't ported at all (WC's is, in WcPlugin/WcColiseum.cs); the BNW port still fights
  vanilla's Coliseum matches.

The review rows, decided (2026-11-20):
- mechanics, to bnw-enemy-ai: the Blackjack's timers and battles (map 6, CA/F532), the Phantom Train's
  status toggles (146), the Magitek Factory's "NO! BAD PLAYER!" gate in place of a restore and an esper
  (272, x2), the Imperial Palace door "Sealed by a mysterious force" (331), the Floating Continent's
  removed battle (393), the final battle's setup in Kefka's Tower (411, CC/193F), the Coliseum's changed
  entry (413, CB/78C3), the Zone Eater's exit (276), the raft's status cures (113), the party routine 73
  scenes share (map 8, CB/2E2B), the unequips at Kefka's Tower 261 and the Floating Continent 393/394;
- scenes, bnw-text-ui's: Shadow's fee in Kohlingen (191, x2: "enough to feed my dog, 1000 GP"),
  Mikhail asking Edgar about Julian (58, a new conditional line), Mog's World of Ruin join shortened (44),
  the Returners' briefing's two added lines (one routine at 109/241/263), Cyan's dream (317, x4);
- not needed: palette and object tweaks (149, 153, 394 CA/DD1E, 411 CA/055D), party_char vs
  party_active in Doma (120, 124) and Figaro (55), the Battle for Narshe's setup sped up (22), the
  "Unequip anyone?" NPC (map 7 CC/3510: the PR's Equip menu has Remove All), Gau's father's house
  party check (116), Setzer's WoR scene and Zozo's mugger (191 CC/3BF8, 221: their text is ported);
- not readable yet: the Serpent Trench's two units (175: the decoder stops in BNW's code there).

The mechanics rows, decided by bnw-enemy-ai (2026-11-20, each vanilla/BNW unit diffed):
- ported: the Floating Continent's "removed battle" (393 CA/DA48) isn't removed: BNW restores the party
  (CA/CFBD: HP, MP, statuses) before the escape's fight (pack 0x51, the PR's party 452): sc_e_0606 does
  the same with the PR's rest ops; the unequips added for Shadow's leaves (Baren Falls, Narshe 20);
- for bnw-scenes (scene changes with lines of their own): the Coliseum's entry (413 CB/78C3: BNW removes
  vanilla's Shadow recruitment there, the Striker bet and his join: the PR's sc_e_0750), the Imperial
  Palace door (331: "Sealed by a mysterious force", dialogue 0xFB, until BNW's own bit 0x0E1, which a
  trigger on the same map sets at CB/524F), the Blackjack's wheel (map 6 CA/F532: its choices reordered,
  a second menu (dialogue 0x6A5) once bit 0x0E2 is set and 0x0A4 clear, a call ED/8C34 before take-off),
  the Zone Eater's exit (276: vanilla's way out at CB/8251 is gone from that tile; BNW's counterpart unit
  is CB/84CD: where its exit went still to be read);
- not needed: the Magitek Factory's "NO! BAD PLAYER!" (272, x2) and the same line in the final battle's
  setup (411 CC/193F; its other change only reorders the tiers' switch): BNW's guards on its debug room
  and a debug path the PR doesn't have; the Phantom Train (146: vanilla's boarding sets the SNES's ghost
  status 0x0800 on the party, BNW plays a pose instead; the PR's train sets none); the raft (113: BNW's
  cure clears statuses 0x0840 instead of all: the PR's full cure kept); map 8's party routine (CB/2E2B:
  the PR merges parties its own way); the unequips at 261, 393 and 394 (vanilla's own, moved within
  the scene).

### Cyan's dream as BNW's (bnw-dream, 2026-11-20, `tools/port_bnw_dream.py`)

BNW (PowerPanda's "Cyan's Uneventful Dream", bnw 3.0/asm/cyans_uneventful_dream.asm; read with
snes_events: SNES map 317 and the Doma bed CB/82B1) changes only the Dreamscape and two calls of the bed.
Vanilla's bed puts the leader, then the next leader, as NPCs at two spots (CB/84FF, CB/854F) and the third
looks for them; BNW keeps all three together (Cyan still leaves: 3F 02 00) and sets the NPC bits of three
Cyans, pieces of his psyche (53A-53C, SNES (13,49), (17,46), (27,52)): talked to, each gets up, shakes his
head and vanishes in a flash (blue, red, green; sound 0x45). The door (46,56) pushes back until all three are
gone. Three Dream Stooges meet the party on the way ("...you again?", 0x0ACD): a new first one beside the first
Cyan (NPC (14,49), triggers (13,50)/(14,50), bit 0x188), vanilla's second, vanilla's third with its NPC moved
to (26,51). The fight is pack 0x5A = BNW's formation 346: Curly, Larry, Moe and Shemp (monster 37, hidden,
brought in by Larry's and Moe's counters). Nothing after it (the train, Doma, Wrexsoul, the waking) differs.

The PR's dream: the bed sc_e_0895 (map 300, Map_20451_4) moves Cyan to the reserve (MoveReserveCayenne) and
splits the party (夢のダンジョン：分離 = SeparateCorpsAtDreamscape, tools/decomp/dream) into map 520
(Map_30821_1 = SNES 317's west; PR objects at SNES + (2, 1), script coordinates + (2, 0)), where the two
companions lie (ev_e_0897/0899, the slot leaders shown by the map script's puppet swap; ScenarioFlag2
181/183) and two Stooges wait (ev_e_0896/0898, 180/182); map 521 (Map_30821_2, the door, SNES + (0, 1))
pushes back until 181 and 183 (ev_e_0900), then the fight (sc_e_0901, party 461; 184). Map 521's script
swaps the slot 2/3 leaders' puppets in on every entry; with nobody in those slots GetLeaderResidentEntityId
returns 0, i.e. entity 0 (decompiled: pr/tools/ghidra/dream_puppets.txt -> tools/decomp/dream_puppets).

Ported (from port_boss_events, profile `bnw_dream`; `--inplace` puts it onto an already ported folder):
- the bed: Cyan to the reserve as before, no split; the three Cyans set present, 181/183 set;
- map 520: Cyan #1 and Stooge #1 as new entity sets (ev_bnw_dream_cyan1/_stooge1: Cyan NPCs are asset 122,
  entities 63-65, Cyan #1's touch object 66, Stooge #1's boy 67 and triggers 68/69; scripts 9971
  sc_bnw_dream_cyan1, 9972 sc_bnw_dream_stooge1); Cyan #2/#3 on the companions' spots (their touch objects
  55/51 run the Cyans' scripts: the PR's step-aside moves, then the get-up, the flash and the vanish);
  Stooge #3's boy at BNW's spot; the map script lays the Cyans down ('Fall') and drops the puppet swaps;
- map 521: the push-back while any Cyan is left, no puppet swap; the fight on party 8346 (bnw-enemy-ai's
  snes_ai_new_fights {346: 461}: BNW's formation with Shemp on 461's look; 461 while a port lacks it).
Flags (data/snes_event_alloc_bnw.json): ScenarioFlag4 3-5 = Cyan #1-#3 still there (BNW's polarity),
6 = Stooge #1 met. The lines are the PR's keys (0x0ACD's E0896_00_520_a_01 for the new Stooge too: the line
map already shows BNW's text). Harness (BnwPlugin/DreamTest.cs): dreamparty [ids], dreamstate.
Shemp has BNW's own art (bnw-sprites, 2026-11-20: profile_bnw sprite_new_art). The Stooges' scene at the door (sc_e_0901) dropped vanilla's split-party puppets (entity 0, 9-11: the other groups' leaders, which BNW's no-split dream doesn't have; the scene waited on them for ever: QA bnw-11 dream-1, BNW lead 2026-11-20, port_bnw_dream.SPLIT_PUPPETS); its rerun is bnw-12's.

## Enemy AI (tools/snes_ai.py, ai_compile.py, port_ai.py)

BNW restructured 377/384 SNES AI scripts, so they're compiled, not patched.
PR AI JSON (`vanilla/monster_ai/.../MonsterAI/*.json`) is run by
`Last.Interpreter.BattleAICore`; each mnemonic is a static handler on
`Last.Interpreter.Instructions.BattleAI`. Model: `Main` → Is* checks jump to
labels (operand = mnemonic index) → `StartTable`…`EndTable` with one `Act` row
per turn (cycled), `CounterAct*`/`FinalAttackAct` rows active for that table →
`JumpBattleAI`. Conventions: SNES "Battle" → monster's own type-4 attack ability
(from its vanilla script, default 1); "Special" → the monster's own special
(port_specials.special_of: the type-3 ability its PR AI / Control group uses, or a copy
from 7700 where BNW split a shared one; it was 377 + SNES enemy id until 2026-11-07, right
for 25 monsters only);
"Nothing" → 696; HP ≤ n×128 → `IsCheckHp [n*128]`; timers in SNES units; SNES
cmd Fight→4, Magic→2, Bushido→601, Blitz→602, Steal→607.
v1: regular enemies compiled to `sc_ai_bnw_NNN` (monster.script_id = 3000 +
SNES id). Approximations: several random actions in one SNES turn become
consecutive turns; targeting and battle messages are dropped; unsupported
conditions skip their branch. PR dropped SNES slots 164/170; BNW's Bio Blast/Boil
get new ability + content rows there.

v2 (boss work, 2026-11-04): 320 compiled (271 regular + 49 bosses, 24 of them hybrids).
- Variables: PR AI variables are 0..14. SNES vars used whole keep their index;
  each tested/set bit (`FC 14/15 VV BB`, `F9`: BB is a bit NUMBER) and whole vars
  above 14 get a free PR index from the top. Setting a whole var also sets its bit
  vars (v1 kept them apart, so "first turn only" flags never cleared).
- Timers: `FB 00`/`FB 04` (reset monster/battle timer) after a timer check -> the
  branch's first action is `TimerAttackAct [0, ids] [0, rates]` (acts + resets),
  the PR's own idiom (Dadaluma, Inferno).
- Death: "monsters die like a boss" (`F5 xx 01/05 FF`) on death -> `FinalAttackAct
  [735]` (SM_ERASER: everyone vanishes, battle ends), as the PR's boss scripts do.
- Counters that change variables -> Main-section routes, like the PR's scripts:
  `IsCheckReceiveCommand [cmd, L]` / `IsRecevieAbility [ability, L]` /
  `DamagedJump [L]` -> table with the counter attack + the variable updates.
- `FD` (wait) inside a condition block continues the block next turn (until its
  `FE`): a branch can be several turns (v1 ended the block, leaking the rest into
  the default rotation). `F9 00` bit toggle = compare-and-jump (the PR has no XOR).
- `F5` modes: 00 bring in (HP restored), 01 kill, 02 bring in (HP as is), 03 hide
  (HP restored), 04 hide, 05 die like a boss; mask = formation slots, 0 = self.
  "Bring in" is resolved against every BNW formation the monster appears in
  (`port_ai.formation_slots`): slots that don't exist are no-ops (Heartfire); a
  monster bringing itself back on death right before "VAR >= n: die like a boss"
  with n reached in that same pass is FF6's trick for the boss death animation ->
  FinalAttackAct 735 (all eight legendary dragons). Real extra lives (Isis, Myria:
  n = 2) and real summons stay unsupported. The PR summons with special abilities
  made of battle function 20 = (add monster id, grid cell) entries (up to 3 per
  ability, e.g. 704, 708), guarded by alive checks/variables in its scripts; every
  boss that genuinely summons in BNW is also tied to a PR battle-event routine.
- `FA` animations are cosmetic: ignored. In a death block, `FB 0B 07` (give
  myself Death) is dropped, and `FB 02` (end battle) = erase all if death is the
  only condition, else dropped (the fight ends once everyone is dead: Crane).
- Still unsupported (script keeps the PR's): real summons, hiding/killing specific
  monsters (`F5` 01/03/04 with a mask) outside hybrids, extra lives, events
  (`F7`), command changes (`F4`), formation change (`F2`), end battle / self-Death
  outside death blocks.

Bosses (`port_ai.BossPolicy`): 49 of 88 changed bosses run BNW's AI. The PR
moves many boss mechanics into hard-coded routines called from the fights' battle
event scripts (`Last.Interpreter.Instructions.SystemCall.Current`: IfritMoveCheck,
HiddenEnemyCheck, ChadarnookSwich, No128RebornCheck, AirForceDeadCheck,
TentacleBattle, CurlaxsBattle, InfernoEnemyCheck, OrthrusMove*, CheckSoulSaver,
AnglerWhelk*, Deathgaze HP...). Their code isn't readable here, so the event
scripts were read by hand and sorted:
- cosmetic/flow only, or checked to ignore the boss's AI (`GENERIC_SYSCALLS`,
  `SAFE_SCRIPTS`: Veldt/Gau, Cultists' Tower statuses) -> normal compile;
- the routine owns who is on screen (`ENTRANCE_SCRIPTS`: Chadarnook, Hidon, Inferno,
  Air Force, No.128, tentacles, Dream Stooges, Ultros at the Esper Cave, Soul Saver)
  -> hybrid: BNW's AI with its own F5 bring-in/hide/kill left out
  (`Context.pr_entrances`), the PR routine handling entrances (24 bosses; F9 log
  marks them). UNTESTED: if a routine also reads the PR AI's variables, its
  mechanic (e.g. ghosts appearing) may not trigger; the fight should still end.
- everything else keeps the PR's script: the PR script sets modes (Vargas, Hell
  Angel, Doom Gaze, Kefka 298, Ultros 300/302, event 371) or uses abilities that
  write battle variables a routine reads (`COUPLING_PROGS`: Ifrit/Shiva, Asura,
  Isis), story event scripts (Vargas/Bear, Phunbaba #4, Kefka 372, Nerapa timer,
  Intangir 281, Soul Train), the final battle's 9 tiers, monsters only brought in
  by another fight (Chupon, Rizopas...), Dadaluma and Guardian
  274 (`F4` command), Myria (extra life), and 3 whose PR script isn't extracted.
  Rules applied to every boss: it has a formation of its own, and every other
  changed boss in its fights compiles too (all-or-nothing).
  Decompiled (2026-11-05, `pr/tools/ghidra/boss_routines.txt` -> tools/decomp/bosses): 17
  routines (IfritMoveCheck, ChadarnookSwich, No128RebornCheck, TentacleBattle,
  CurlaxsBattle, HiddenEnemyCheck, InfernoEnemyCheck, AirForceDeadCheck, CheckSoulSaver,
  NerapaDoomAttack, Orthrus*, AnglerWhelk*). They talk to the bosses through the AI
  variables (`SetEnemyCurrentVariableArray`) and battle-script flags (`DataStorage`), and
  some force acts (`InstanseActAbility`), so the remaining bosses need, per boss, the
  variables its routine writes kept out of (or read by) the compiled BNW AI.

Testing: plugin F9 (with [Testing] TestKit) starts the next BNW-AI boss fight from
the field via `FieldMap.fieldController.ExcuteEncount(party, bg)`; F10 in battle
defeats every enemy left (`BattlePlugManager.Instance().GetEnemyUnits()`: HP 0 +
`BattleConditionController.InterruptAddCondition(unit, UnableFight)`), so the fight
ends as a normal win whatever the party's level. Tried: the win screen shows; EXP and
gil are paid only for monsters on `BattleAddExpPlug.SetExpditionMonsters`, which
normal kills join, so v0.8.3 adds each F10 kill there too (v0.8.2 paid 0 EXP).
Still 0 in v0.8.5 against Holy Dragon (monster 37: 0 EXP in vanilla, 5000 in BNW):
vanilla bosses give no EXP (111 of 113 have 0) and the result came out 0 with the
dragon on the list, so the PR seems to leave bosses out of its total. v0.8.6
(`BattleRewards.cs`, config [Battle] BossExp) prefixes `BattleResultProvider.Genelate`:
if the EXP of the monsters on `expeditionMonsters` beats `GetExp(partyId)`, it adds
the difference (through `CheatSettingsClient.GetResultExp`, the Boost setting) to
`expValue`, so levels, EP and EL follow. The 5 formations with capped called-monster
EXP (`monster_party_max_exp`) keep the game's figure. F10 also records its kills'
EXP as a fallback. Logs "[rewards] formation N: game EXP ..." for the first 3
battles and every corrected one (to confirm the boss theory).
v0.8.6 log: list [37, 37] (the game adds a dead monster itself, so F10's own
SetExpditionMonsters doubled it: removed in v0.8.7), GetExp 10000, yet expValue 0,
and `BattlePlugManager.MonsterParty` already null when the result is built. So the
zeroing is in the caller (`SystemCall.Current.GetBattleResult`), not GetExp; either
bosses or F9-started fights (no MonsterParty?) get 0. v0.8.7 raises expValue to the
game's own `GetExp(party)` total, with the formation tracked during the battle
(`BattleRewards.Track`, every 10 frames) so the 5 capped formations keep their caps.
Tried v0.8.7 on the Deck: "game passed EXP 0, its total 5000 -> paying 5000 EXP";
4 in the party, so 1250 XP each, (1250/8)*10 = 1560 EP; from EP 5887 (test kit) to
7447: EL 11 at 5888 and EL 12 at 6912, so EL 10 -> 12 is right. MonsterParty was -1
for the whole F9 fight, so F9-started fights lack it; whether a boss met normally
also gets 0 is still open (the first 3 "[rewards]" lines of a session will say).
Formation reward columns: `get_value` = Magic AP (matches SNES AP for all 463
formations); EXP/gil come from the monsters. Battle result hook confirmed in game:
SP for EP = `BattleResultData.GetMp` (the "Magic AP" total).

### More conditions (2026-11-05): skipped branches 189 -> 86

The compiler dropped a branch whenever it couldn't translate an SNES condition. Matched
against the game's own scripts (vanilla monsters that use both forms), it now emits:
- FC 08/09 44 st (a random party member has / lacks a status) -> `IsCheckUnitStatus [1,
  condition type, 1/0, J]` (Earth Dragon: Float -> [1, 409, 1, J]; the type comes from
  condition.csv for the status's condition id);
- FC 0F 44 n (a random party member's level >= n) -> `IsLevelCheck [1, n, J]` (Silver Lobo);
- FC 1A 36 elements (I'm weak to one of them) -> `IsWeakCheck [PR element, J]` per element
  (Number 024 checks 1-8 = PR attribute ids: ELEM_ATTR);
- counters "hit by element" (FC 04) that change variables -> `IsReverseAttribute [PR
  element, J]` (Number 024's "炎属性の攻撃を受ける" branches);
- counter blocks that start with a plain condition ("if VAR001 >= 3") run on every hit, as
  in the SNES: their own trigger first if they have one, else "any hit" (DamagedJump).
70 compiled scripts use the new checks (36 status, 28 element hits, 10 level, 2 weakness).
Still skipped (68 in the compiler, 86 in the port): "monster in slot" (FC 19) and "these
monsters alive/dead" (FC 11/12): the PR's IsEnemyUnitIndex / IsUnitAlive number units per
formation, not by SNES slot mask.
2026-11-05 (later): FC 1B "this battle is formation a + 256 b" -> IsCheckMonsterPTId [PR party,
J] (vanilla Chaser: FC 1B 7B 00 -> 123 and the PR copy 3088) for party f + 1 (the PR numbers
parties from 1: 255 vanilla formations match), the party port_encounters made for a BNW
formation (2000 + f) and the PR's own copies of party f + 1 (ids past 576 with the same
monsters, at most 6 checks): skipped 86 -> 81 (WC 65). FC 19 can't follow: IsEnemyUnitIndex is
the PR party's monster column (Opera Ultros: SNES slots 1/2/4/8 -> columns 5/4/9/3), and the
PR hand-placed its formations (nearest-cell placement predicts the column for only 605 of
1264 vanilla monsters). tests/test_mod.py checks mnemonics, operand shapes and
jump targets against the game's own scripts (passes). Not yet seen in a battle: the probe
run on formation 4 (two monsters with the new checks) was interrupted.

### Battle lines (2026-11-05, `tools/battle_text.py`, profile battle_messages)

The SNES AI's "message xx" (F3 xx yy) shows monster speech from one table: C1/9846 `LDA
$CFDFE0,X` (pointer read from that instruction), menu encoding, $01 new line, $05 pause, $02 nn
= character nn's name, BNW's $D3 opening quote and icons ($D0/$D1 arrows, $D6 the confirm
button, $D5 a music note). BNW renumbered the table (its #0 is vanilla's #12, Ultros). The PR
shows battle lines from story_mes_en keys given in an act's sValues (Cactuar: Act [696]
s[M109_01]; Ultros: FirstAttackAct with three keys in turn), speaker in story_cha_en (empty for
monsters), names as codename tags "(MASH)". Now each message line becomes BNW_BTL_<msg>_<line>
in story_mes_en/story_cha_en (port.write_messages writes extra text files; Magicite merges
them: headless, the game has both BNW_BTL_018_01 "BARF!" and its own E0055_02_343_b_13), and
the compiler puts a turn's/counter's/death's lines on its first act (a block that only talks
gets a do-nothing act, 696). 45 lines in the compiled scripts (dragons, Ultros, the Stooges,
Atma, Crane, Guardian's song...); 41 on Act/FinalAttackAct/TimerAttackAct (types the game uses
with lines), 6 on CounterAct/CounterActReceiveCommand (the game has no example: may stay
silent). BNW only (WC's live seeds apply system_en only). Not seen in a battle yet.

### Bosses still on the PR's AI (39, analysed 2026-11-05)

From port_report: 9 final-battle tiers (policy), 7 whose PR script sets/counts modes for
their battle event (Vargas 259, Tunnel Armor 260, Deathgaze 285, Kefka at Narshe 298, Ultros
300/302, an event monster 371), 6 with special battle-event routines (Phantom Train 262,
timers 280, King Behemoth 281, 333, Phunbaba 364, 372), 4 Ifrit/Shiva/Vargas variable
couplings (264, 265, 295, 296), 4 without a formation of their own, 3 PR scripts not found,
5 using commands/events/enemies/self-revival, 1 sharing a fight. The mode group looks
closest: `ModeCount` is a per-turn counter the battle event reads, but it sits only in some
phases (Tunnel Armor and Narshe Kefka count only while above an HP threshold; Deathgaze every
turn; Ultros 300 on its final attack). A hybrid (BNW's compiled AI + the PR's ModeCount at the
same phase) needs the battle event read first (what the count triggers) and a played fight to
check; not done unattended.

### Every reachable monster on BNW's own script (2026-11-20, the enemy-AI session)

Now 327 monsters run BNW's SNES scripts on the kit's interpreter (was 286 + 16 compiled + 10
unsupported); nothing is compiled any more (`sc_ai_bnw_NNN` are all shims). What it took:
- **BNW's formation numbers in the story fights** (`port_ai.event_formations`, profile
  `snes_ai_event_formations`): the PR's event scripts start their battles by party (vanilla's
  formation + 1); BNW renumbered its boss formations (Vargas and his bears are 0x142, not 435;
  the Whelk 0x140; the Guardian 0x18c with two monsters brought in later; Ultros + Chupon 0x16b...).
  The AI data had given those parties vanilla's number, so FC 1B checks (the Bears' "formation
  0x142", Phunbaba's 0x182/0x183) never matched and the slots (FC 19, F5 masks) came from a
  formation of other monsters (by cell order). Each event party now gets the formation BNW's own
  event calls at that place (port_events' anchored pack entries, kept when the party's monsters
  are in it; a boss party no pack names gets the one formation holding exactly its monsters;
  `snes_ai_formations` overrides: 423 = 0x182, the first Phunbaba). The 7000+ parties port_events
  made for BNW's line-ups (the Cranes' 7441) count as their monsters' fights.
- **FB misc effects read off the ROM** (C2/1E5E: command $30's table at C2/1F09, the same in BNW):
  01/05 invincible on/off ($3A3C: C2/13B0 zeroes the damage; the host puts back what a hit took),
  06/07 targetable/untargetable ($2F46, what CheckTargetsPresent allows: the PR's NotTargeting
  667, which the interpreter's target filter now honours, with NoSelect 625), 09 the battle's end
  (as 02), 0D itself hidden (status 4 bit 5: as F5's hide). 03 (Gau joins) only !Gau 370 uses: no
  PR fight fields it. Crane, the Guardian (273), Nimufu, Clyde, Ultros 360 and the Stooges use them.
- **Battle events (F7) as the PR's modes** (profile `snes_ai_events`, data `event_modes`): a PR
  battle script that reads its boss's mode (GetEnemyMode: `EnemyCharacterParameter.CurrentMode`,
  what the PR AI's ModeSet/ModeCount write; ModeCount = +1, decompiled) plays the scene when
  BNW's script reaches the SNES event: Vargas 07 -> 1 (Mash joins), 09 -> 3 (Pummel ends it);
  Lete River Ultros 0a -> 1; Kefka's escape 1d -> 1; the Merchant/Trooper (Locke's disguise)
  0f/0e -> 1. In that pass the script's own entries and battle end are the PR scene's (dropped).
  Events with no PR counterpart or played by the PR's script anyway (Tunnel Armor's intro 10,
  Kefka 298's 20, Ziegfried's 13, the Whelk's 05) are skipped and logged once.
- **Bosses whose PR battle script is harmless alongside BNW's AI** (profile `snes_ai_hybrid_scripts`,
  read in `tools/decomp/bosses2`): Soul Train's MagicTrainAnimStart (party pose), Doom Gaze's HP
  save, Fiend's FiendCounterAttack and Ifrit/Shiva's IfritMoveCheck (both act only on the PR AI's
  variable 9, which nothing sets now; Shiva's NoSelect from sc_b_2009 is lifted in the battle's
  first seconds, `start_shows`: BNW shows both from the start), Phunbaba's breath routine (BNW's
  attack ea = the PR's 371; the PR ends that fight: `pr_ends`). Vargas fights on at 0 HP until
  Pummel (`zero_hp_wait`: no one-minute limit). Chupon comes in with Ultros 360's F5 (it and
  Rizopas, `snes_ai_brought_in`).
- **Fights whose PR routine decides who is on screen** (Chadarnook, Air Force, Number 128,
  Inferno, the Stooges, Hidon, Chaser, the Piranhas, Ultros 301): their monsters run BNW's
  scripts in the plugin with their own F5/FB 0D left to the routine (`pr_entrances`, as the
  compiled hybrids did); "everyone dies like a boss" stays; no start-of-battle hides there; the
  PR's own off-field conditions (Escape, NoSelectChad, EventFadeOut) count as out for the scripts.
- Kit fix found on the way (WC too): `EventCommand.RecoveryConditionEnemy` takes a condition's
  *id*, AddConditionEnemy its *type*; the host lifted F5 hides and FB 0C statuses by type, which
  removes nothing for types past 111 (NoSelect, Hide, NoSelectChad...). Now by id (master Condition).

New fights (`port_ai.new_fights`, profile `snes_ai_new_fights`): BNW's fights the PR has no party
for get one (8000 + formation, the look of a template party, no battle routine; a formation in profile
`snes_ai_new_fights_keep_routine` keeps its template's script_name and not_escape instead, for a template that is
the same fight: BNW's 8346 Stooges on 461, whose sc_b_2028 puts them on stage): 8410 = Kaiser
(0x19A, BNW's post-game superboss; its opening event 0b skipped) and 8377 = Kefka with two
Centurions (0x179, where vanilla had only an event battle). Their triggers (`tools/port_boss_events.py`,
profile `bnw_boss_events`), read with tools/snes_events.py:
- Kaiser: BNW's dragon tally (CB/5090 -> CC/1F9F, event word 6) says "No dragons left..." at the eighth
  and sets bit 0x3A3, which shows Kaiser (NPC 0 of map 304 at (82, 33), dragon sprite) in a corridor BNW
  added to Kefka's Tower (new exits from maps 334/337); his talk (CB/52C5) is the fight, then "Broke the
  dragon seal! Got the magicite Ragnarok" and the esper (index 15, the PR's content 87). BNW's corridor is
  map 304's dragon-platform room (layout 315: the room the Yellow and Green Dragons stand in on maps
  335/354), which vanilla never let anyone into: BNW reroutes the door between maps 334 and 337 through it
  (334 (29, 36) -> 304 (82, 42), 304 (82, 30), a doorway cut into its back wall -> 337 (8, 29), and the
  way back), walls up its side alcoves and puts Kaiser on the platform. The PR gets the same room as a new
  map with the kit's room importer (tools/snes_rooms.py, the T-Edition sessions' shared tooling):
  `clone_map` of the PR's own drawing of that room (Map_30871_9) as Map_30871_33 (map 806, map script
  629), BNW's doorway drawn as the PR drew the room's other top-wall doorway, the pillars from
  snes_rooms' model of BNW's tiles. BNW's 8 dragon markers (statues around the platform, BG2 0x5F, that
  its entrance shows while each dragon lives and each dragon's tally takes away) are there the PR's way,
  as Kefka's Tower's floor switches do it (Map_30871_18): four statues where the PR drew vanilla's, four
  added (Ground 160, Upper 279 of map255), those two tiles given a second frame (map255's cell 1023, which
  no PR map uses: empty), a TileAnimRegion over each marker (entities 301-308) and the map script cueing
  a fallen dragon's region to that frame (CueAnim [1]); markers by the dragon whose tally clears them
  (Brown/Earth 178, Purple/Storm 108, White/Holy 166, Silver/Ice 138, Red 148, Blue 175, Green/Skull 220,
  Gold/Yellow 225). BNW's tally visit after each dragon (CB/5090 -> CB/4FE5, CC/1F9F; ported 2026-11-20,
  `port_boss_events.dragon_visits`, profile bnw_dragon_visits): each dragon's after-battle script hands
  its tally (ChangeScript sc_e_0975) to a trip: its visit flag (ScenarioFlag4 13-20, FlagAlloc 0x2000 +
  dragon flag), fade out, ChangeMap to the room (point 2) with `sc_bnw_dragon_tally`: the party hidden at
  (82, 34), fade in, a rumble (SE 187, a shake), that dragon's marker cued off (the room's map script
  skips a visiting dragon's marker), the tally's own "N dragons left" line, fade out, ChangeMap back with
  `sc_bnw_dragon_back` in the dragon's room: the party on the dragon's cell (free after the fight; Map_20440's
  on its after-battle spot (60, 44), BNW's own reload spot there), fade in, and what the after-battle did
  after a tally call (Map_20440: its line and the autosave). The PR's ChangeMap takes only an entry point
  (decompiled tools/decomp/changemap), hence the cell by SetPos. Not played yet (QA bnw-visit-1). The PR's doors from Map_30870 (29, 36) and Map_30871_7 (14, 31) lead into it, its own
  lead on to where those went. Its map script spawns Kaiser (ev_bnw_kaiser: the Yellow Dragon's entity
  with his script) once all 8 dragon flags (ScenarioFlag2 108, 138, 148, 166, 175, 178, 220, 225) are set
  and until the seal flag (221); the PR's 9 copies of the tally (sc_e_0975) stop at "No dragons left..."
  (E0981_00_551_a_01); sc_bnw_kaiser (the PR's dragon talk, EncountBoss 8410) and sc_bnw_kaiser_1 (he's
  hidden, the seal's effects, a_02, flag 221, GetItem 87). tests/test_mod.py checks the new map's files
  and lets doors into maps past the game's ids differ from vanilla.
- Kefka: BNW's Sealed Gate scene (CB/39CA) replaces vanilla's first event battle there with the fight,
  after six new lines (SNES 0xA60-0xA65); the PR's sc_e_0460_1 (map 40034) takes party 8377 in its first
  Encount, BNW's lines (bnw-text-ui's BNW_E0460_01..06, DialogText's added lines) before its fade to it.

Still on the PR's AI (16), each with its reason (`profile_bnw.snes_ai_keep`, port_report):
the final battle's 9 tiers (343-351: the PR's four-round battle event swaps parties, music and
backgrounds on its own signals); 281 Intangir (its death changes the formation to 0x153, Intangir
Z; the PR stages that as the same unit rising, KingBehemahInBattle, with its own AI's second
phase); 302 Ultros at the Esper Cave (Relm joins from the PR AI's own variables and timers; BNW's
Ultros moves among four slots the PR's party lacks); 359 Soulblazer (the PR's Wrexsoul fight,
party 463, fields vanilla's line-up: BNW's Wrexsoul is monster 13 in formation 0x15c, not staged
by the PR's event); 371 (a story scene its battle event plays on its own signal); 276 (BNW's script
is SNES event 04 + the end: the PR's ability 1414 plays that scene); 64 Chupon, 277 (no PR fight
fields them). Non-bosses off the plugin: 13 Wrexsoul (only in the PR's vanilla Dark
Force parties), 366/370/378/379 (no PR fight).

Testing: `BnwPlugin/AiFights.cs` adds harness commands (aikeep on|off: Active mode, auto, party
at 9999 HP; ko [PR id]: a knockout through the game's death check; aistat; endfight: everyone
left dies the game's way) and `tools/ai_fights.py` drives many fights in one run; runs go
through the PC test runner session (harness lists: boot; aikeep on; battle N; until scene
battle; sleep; ko; aistat; endfight; tofield; ...).
