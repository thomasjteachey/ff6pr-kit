# Battle engine and plugin lessons

Owner: kit lead. Moved verbatim from `pr/PORTING.md` on 2026-11-20 (roadmap item 5); `git log --follow` / the split commit trace any paragraph. Status rows stay in `pr/PORTING.md`.

## Battle engine (BNW c2.asm; research 2026-11-04)

### What the PR itself does (web research + PR data, 2026-11-05)

Nobody has published the PR's formulas (no datamine or decompile found; GameFAQs and the
Fandom wiki block automated reads, TCRF served bait pages). What is known, with the
source and what it means for BNW:

- Formulas follow the SNES version (Game8: "基本的な仕様はSFC版に準拠"); our 3 logged fights
  agree. Damage cap 9999 (`game_constant_int.csv` MAX_HIT_VALUE).
- **Stat caps 128**: `game_constant_int.csv` MAX_STRNGTH / MAX_VITALITY / MAX_AGILITY /
  MAX_MAGIC / MAX_ABILITY_ATTACK = 128 (Attack, Defense, MDef, evasion 255). BNW caps at
  255 (c2.asm:780 GengiCheckFunction; EL bonuses alone stop at 128, AddEL). Checked
  2026-11-05: BNW characters never pass 128 on natural stats + gear (the part the PR sums;
  the plugin adds EL and esper bonuses after, up to 255); with every EL and the best gear
  in one stat only Locke's Speed (130) and Strago's Magic (134) pass it. Monsters do: four
  scripted ones (Typhon, Ymir, Siegfried, #380; HP 1) have Speed or magic power 255
  (vanilla PR monsters: Speed <= 99, magic power <= 55; the PR keeps monster Speed in
  `agility`, magic power in `ability_attack`). **Done**: `port.py stat_caps` writes
  game_constant_int.csv with the caps at the profile's `stat_cap` (BNW 255) and raises a
  cap to 255 by itself where a ported monster passes it (Beyond Chaos: MAX_AGILITY; Worlds
  Collide: none). The probe shows Vigor past 128 adds nothing to Fight (Vig2 caps at 255),
  as on the SNES.
- **Evade works** in the PR (several player reports; GBA fixed it, PR follows): Evade
  for physical, MBlock for magic, Blind works. BNW uses the same fix (c2.asm:1465 "Terii
  Senshi evasion bugfix") plus: Image clears 1/3 per dodge (done via condition data),
  no evasion penalty from Rerise, no status evasion bonuses, Blind (BlindHelp), evasion
  halved while covering. So H1 is mostly the PR's own; those extras are todo.
- **Rage**: vanilla PR odds are data, `monster.rage_ability_random_group_id` ->
  `ability_random_group.invocation_rate` 25/75 (195 monsters; 59 have 25/38/37), i.e.
  the PR picks the special 75% (SNES 50%). The porter already writes BNW's 67/33
  (c2.asm:2482). v1.2.1: Rage specials ignore Genji Glove/Offering (Fandom).
- **Steal**: PR is the SNES formula, (50 + Lv - target Lv)/128, Sneak Ring x2 (Steam), rare
  slot 12% (`MONSTER_STEAL_RATE_1/2` 88/12; drops the same). BNW (c2.asm:2495): success
  (Speed x2 + 112)/256, sure at Speed >= 72; rare slot Speed/256. Needs a hook.
- **Genji Glove**: PR dual wield deals -25% (jinsoku.net), the same as BNW's dual-wield
  penalty, so it must not be applied twice. Check the GenchisBasho correction value in
  the [relics] log once someone dual-wields.
- Patch 1.0.5 (player.one): in a pincer every character counts as front row; Sketch
  no longer uses MP; Rage can't inflict a status the target's equipment blocks; Quick and
  Trance can't be used while confused; killing with a weapon's instant death no longer
  gives extra rewards.
- **Bushido** charges in the background (the party keeps acting) and has no gauge wait;
  **Blitz** is picked from a list, then its input is shown (Game8, Steam). BNW's Bushido
  and Blitz changes must fit these menus.
- Dragon Horn's extra jumps don't ignore row (Fandom); Trance points aren't used up when
  a battle ends in Trance; Vanish + Doom no longer works, Vanish on a vanished ally
  misses (Game8); crits reportedly also hit defense-ignoring attacks, Throw and X-Fight
  (GameFAQs board, unverified); Throw reportedly ignores MDef (Reddit, unverified).
- Other battle numbers in `game_constant_int.csv` (data, so portable): encounter types
  of 100: normal 68, back 13, pincer 3, side 3, preemptive 13 (by walk/dash and the
  encounter-rate relic); starting ATB % ranges per encounter type
  (ACCUMULATION_ATB_*, e.g. normal 50-80, preemptive 100); Near Fatal below 1/8 HP;
  escape 50% / 20%, escape cool time 340; enemies target each slot 25%;
  ATB_TOTAL_AMOUNT 550, ATP_COEFFICIENT 21 / enemy 12 (meaning unknown: compare with the
  [formulas] ATB log).
- Not found anywhere: Haste/Slow multipliers, ATB formula, magic evasion scale (255 vs
  128 disputed), Dance stumble odds, Offering details, monster magic x1.5.

A research pass mapped BNW's engine changes to PR hook points (asm refs: banks/ and
bnw 3.0/asm/, which wins). Status: [x] done (untested in game unless noted), [ ] todo.

- [x] Monster special attacks (`tools/port_specials.py`): SNES enemy byte 31 decoded
  (vanilla C2/3302, BNW keeps the bits): bit 7 unblockable (content_flag_group 1), bit 6
  no damage (system 5), 0x00-0x1F status n (function 9, value1 = PR **condition id**, not
  a group), 0x20-0x2F damage x(1+(n-0x1F)/2), 0x30/0x31 drain HP/MP (13, 77). Damage = 2
  (physical) + 23 (special). The PR's own specials are hand-made (41% follow the SNES
  byte), so only the 289 BNW changed are rebuilt (257 rows changed, 279 names). The PR
  applies vanilla's multiplier itself, keyed on the monster (logged: BNW's Phalanx, x3,
  hit for vanilla's x2), so the 185 BNW/vanilla **ratios** are exported
  (bnw_data.json spirit.special_multipliers) for the damage hook.
- [x] Spirit-based abilities (spell byte 7 bit 2, c2.asm:1448 StamTest; 33 + proc
  copies): `BattleFormulas.cs` marks CalcControllerProvider.Get{Magic,Recovery,
  FixedBaseValue*}Status when `.ability` is listed, and PlayerCharacterParameter
  .ConfirmedMagic answers ConfirmedVitality meanwhile (logged once). Monsters (v0.14.0):
  EnemyCharacterParameter.ConfirmedMagic answers BNW's monster Stamina (max HP high byte
  + 1, at most 32; c2.asm:2160), x2/3 for the game's monster x1.5 (below).
- [x] ATB speed (c2.asm:397): BattleProgressATBFF6.ATBCalc x BNW/vanilla: characters
  75(Spd+51) vs 96(Spd+20), monsters x1.171875. Logged per speed band to confirm the PR's
  formula is (Spd+20)-shaped.
- [x] Status data (`profiles.condition_tuning`, condition.csv): Haste/Slow rate_value1
  50 -> 20 (BNW x1.2/x0.8; the column reads as percent: Regen 5), Image until_value 25 ->
  33 (1/3 break per dodge), Sleep/Stop 30 -> 15 (BNW 9 vs 18 ticks).
- [x] Damage log (`DamageLog.cs`, v0.12.0): every Fight/magic/heal result with its
  inputs -> BepInEx/bnw_damage.csv (v0.13.0 adds game_value, bnw_factor; an older file
  with other columns is renamed aside). 3 logged fights (2026-11-05) showed the PR runs
  **vanilla FF6's formulas**: player physical BP + Lv^2(BP+2Vig)/256 x3/2 (BP = the PR's
  ConfirmedAttack), monster physical Lv^2(4 Attack + Vigor)/256, magic SP x4 + Lv Mag
  SP/32, x(255-Def)/256+1, variance 224-255/256, Shell/Safe x170/256, back row x0.5.
- [x] Damage hook (`BattleFormulas.cs` v0.13.0, config [Battle] DamageRules): postfix on
  CalcControllerProvider.GetFightStatus/GetMagicStatus, Hit/Critical results only, the
  PR's value x factor (1..9999): special-attack ratio; D1 characters' Fight/Jump (ability
  type 4/15/16) BNW BP + 2Vig + BP Lv^2 Vig/6144 over vanilla; D5 hits on characters
  ((255-S) - rand(0..30-S/4))/225 over vanilla's mean 0.9355 (S = Vigor physical, Spirit
  magic; the PR's own 224-255 roll stays, so the spread is a little wider than BNW's);
  D6 back-row characters x0.75 (x1.5 on the PR's x0.5); Defend halves magic. Each rule
  logs "[formulas] ..." once. v0.14.0: exact SNES integer steps for BNW Fight
  ((BP/16)*(Lv*(Lv*Vig/16))/24 + BP + Vig2) and the variance past S = 120; back row read
  from the provider's targetCorpsId (the unit's own row; CalcInfo's is ignored by the game).
  Todo: player-on-player x0.25, Morph, D8 Imp halves.
- [x] D3 monster magic x1.5 (v0.14.0): the formula probe shows the PR multiplies a monster
  caster's **Magic** (not spell power) by 1.5 in magic damage and heals, as vanilla (monster
  Cure with Magic 1 heals 48-54 = Magic x1.5 floored; spell power x1.5 would be 65-74).
  BNW removed it (c2.asm:2169). While GetMagicStatus/GetRecoveryStatus run for a monster
  caster, EnemyCharacterParameter.ConfirmedMagic answers 2/3 so the game's x1.5 lands on
  BNW's value and the 9999 cap comes after (a flat x2/3 on the result undershot capped and
  low-Magic spells).
- [x] Ignore-defense flags (`tools/port_flags.py`, v0.14.0 data): the PR's content flag 5 is
  "ignore defense" (every ability the probe saw ignore Def/MDef had it, no other did; flag
  1 = can't miss, 2 = no split). The porter sets it from the mod's spell byte 2 bit 5:
  profile.defense_flags "mod" (BNW: every spell; 49 set incl. Holy, Maduin, heals; 9
  cleared: Meteor, Merton, Trifecta, Rocks...) or "changed" (default: only bits the mod
  changed). Probe run 5: BNW 532 pass, 6 fail. The "physical" bit (byte 2 bit 0: Def
  instead of MDef; 13 BNW spells incl. Rock 311, Shrapnel 352) has no PR flag (the probe
  saw no magic function meet Defense), so the plugin (v0.15.0) scales those spells by
  (255-Def)/(255-MDef) and uses Vigor for BNW's variance (bnw_data
  spirit.physical_abilities); GrandTrain (Lore) and
  TekMissile (Magitek) still ignore defense without flag 5 (another rule for those types);
  a hit the game capped at 9999 keeps 9999 under BNW's variance, so a 128-Stamina target
  takes 9999 where BNW gives ~7000 (Bum Rush, X-Meteo); Meltdown 1350/1524 ~8x.
- [x] Monster magic residual: the game multiplies the answered Magic by 1.5 as a fraction,
  so the plugin also scales by (4SP + Lv*want*SP/32) / (4SP + Lv*1.5*answer*SP/32), SP from
  the ability (the game passes standardValue 0 for spells).
- Probe findings, the PR vs SNES vanilla (pr/probe_report.md, the baseline for every port):
  Fight, monster Fight, magic, heals and Spirit-free spells follow the SNES formulas;
  character Vigor caps at 128 (Vig2 255); the game caches a character's Battle Power for
  its Fight formula (the probe can't vary it). Defense met differs from the vanilla ROM's
  spell flags for Quake, Quasar, Rock (220, 311), Meltdown (ignore MDef in the PR) and
  Aurabolt, Raze, !Aero, Aqua Slash, Avalanche, Shrapnel (meet MDef in the PR; the ROM
  says ignore). The PR keeps these in its own data (content_flag_group: flag 5 on
  Flare/Meteor/Ultima/Merton...; Quake ignores MDef without it), so BNW's flag changes
  (e.g. Holy ignores defense in BNW) are **not ported yet**. Meltdown 1350/1524 hit ~8x
  the formula. Go Fish heals a random 0-303.
- [x] H1 Evade for physical / MBlock for magic: the PR has it (reported, see above). BNW's
  extras (v0.23.0, 2026-11-20): Blind (BlindRules, earlier); the status hit-rate steps
  (`HitRules.cs`): vanilla C2/235B gives x1.25 hit rate against Blind/Zombie/Muddle/Slow/Rerise
  targets, C2/2372 x0.75 against Poison/Near Fatal/Seizure/Haste (read off the US ROM);
  BNW drops Rerise from the first ("PEA $0004") and skips the second. The PR keeps both lists as
  static arrays, `CalcExecuteFF6.HitRatePlusConditions` / `HitRateMinusConditions`, read by
  PhysicalExecution on every hit: the plugin rewrites them once at startup (logged as "[hit]").
  The covering knight (`CoverRules.cs`, c2.asm HalveEvasion / SkipDogBlock): the PR applies
  cover in BattleFunction2.FixedTarget (ProtectExtractTarget's only caller, tools/ghidra/callers.py)
  and runs the act's hits in BattleFunction2.HitCalc (decompiled tools/decomp/cover_hit):
  GetFightStatus rolls Interceptor there (WildFangConditionFunction.CheckDefendInvoke, 50% vs
  physical) and PhysicalExecution reads the target's ConfirmedEvasionRate (vtable slot 20,
  Block = (128 - Evade) * 2). While a covered act's HitCalc runs, the guard's Evade reads
  halved (BattleMath.CoverEvade: BNW's 8-bit math, Evade / 2, 63 at 128+) and the Interceptor
  roll says no.
- [x] H2 Spirit evasion of statuses (`CommandRules.cs`, v0.15.0): StamEvdChk C2/23B2,
  evade if Stamina >= random(128) = (Stamina+1)/128; BNW's 61 Stamina-evadable spells
  (byte 4 bit 4) and 149 monster specials with a status and no "can't dodge" bit
  (bnw_data spirit.special_evade_abilities). Postfix on Serial.FF6.Battle
  .AddConditionFunctionSerial.CheckForceMissCondition(attacker, target, condition) ->
  true = that status misses, the ability read from the current CalcControllerProvider
  (only when its attack/target are the same units). Monster Stamina = max HP high byte
  + 1, <= 32. Damage still lands (BNW: an evade only cancels the status).
- [x] S1 Regen/Poison/Sap (`StatusTicks.cs`, v0.15.0; BNW 3.0 tick-calc.asm, c0.asm
  TickLogic): Regen MaxHP/64 + Stamina*Lv/16, Poison/Sap MaxHP/(Stamina/8 + 16), +2,
  <= 255, variance (BNW's on characters taking damage, vanilla otherwise); Poison counter
  c (x(1+c/2)): characters 0,2,4..31, monsters 0,2,5,11,23,31 (x16.5). Decompiled game:
  BattleConditionFunction.GetRateValue(typeIndex 1 Poison / 4 Sap) postfix;
  RegenerationConditionFunction.GenerateRegeneHeal prefix sets healValue (0xD4); tick
  rate x2 by halving BattleUtility.CalcATBProgressCycleForVital(unit, 1/2) and
  CalcGenerateRegeneCycle (110 - Stamina). Elements still apply after (the game's own).
- [x] Reflect (v0.15.0): permanent (condition 24 until_type 7/60 -> 2, profile
  condition_tuning); TargetFunction.OverrideToReflectAct(act, reflectUser) postfix rolls
  85/256 and removes Reflect when the act ends (BattleConditionController
  .InterruptRemoveCondition(unit, ConditionType.Reflex)), except equipment Reflect
  (GetEquipmentConfirmedConditionList) and monsters (innate, kept).
- [x] Turns (v0.15.0): BattleProgressATB.ActExectionEndDelegate (zeroes the gauge after an
  act; FF6's subclass doesn't override it) postfix: Defend (command 2) / Row (5) ->
  gauge 126/256 of MaxATBGauge (c1.asm HalfTurn $7E); successful Steal/Mug or a
  character's Scan (ability 64) -> full (CheckCantrip). Command per unit recorded in a
  FunctionProvider.CreateActFunction prefix. Todo: failed Blitz half turn.
- [x] Steal (v0.15.0): the PR's StealExecution (decompiled) is (Lv + 50 - target Lv)/99,
  x2 with the steal relic, then GetRandWeight(MONSTER_STEAL_RATE 88/12) -> slot 1
  common / 2 rare; returns (0, slot, HitType Hit) or (0, 0, Non). GetStealStatus copies
  it into CalcResult (stealContentId 0x1C). Postfix there: BNW success (Speed*2+112)/256,
  rare slot Speed/256, empty slot fails. Monsters stealing gil: vanilla in BNW, left.
  Todo: Steal through normal evasion (CoinHelp), Mug misses when its steal fails, Blind
  on Steal/GP Rain/Jump (BlindHelp hit 50).
- [x] Dance (v0.15.0; 3.0 choreography.asm): `tools/port_dances.py` writes BNW's step table
  (CF/FE80: Shift/Repeat/Uncommon/Rare per dance) into the PR's step groups
  (ability_random_group 1-8 = on the dance's background, 37-44 = elsewhere with stumble
  ability 262 at 50): own background Repeat/Uncommon/Rare 63/31/6, elsewhere
  Shift/Uncommon/Rare 63/31/6, stumble 0 (profile dance_rules "bnw"; other mods: steps
  only). The plugin removes the Dance status (condition 51, type 619) when a Dance act
  (command 22) ends: one dance per command. Todo: BNW switches the background to the
  dance's for the rest of the battle.
- [x] Bushido (v0.15.0): the PR uses the skill's spell power as Battle Power (probe:
  Dispatch power 6 hit for ~5 at Lv 1), but BNW's power is a multiplier: BP =
  (right + left weapon + base BP x (2 if dual-wielding)) / 8 x power (GetBushPwr), then
  BNW Fight; damage hook (ability type 601) scales by BNW / vanilla. Base BP per
  character from SNES init byte 10 (bnw_data base_bp; Cyan 64). Gauntlet x1.5 with a grip
  weapon worn (2026-11-06). Todo: BNW's charge speed (the PR charges in the background).
- [x] GP Rain (GIL_THROW) Stamina*10*Level/(2*(targets+1)) and Mantra (CHAKRA)
  (current HP/64 + Level)*Stamina/4: postfix on CalcControllerProvider.GetUniqueStatus by
  ability.ProcessProg. Todo: GP Rain's cost (Stamina*10 GP), BNW's Chakra (MP
  (Stamina+Level)/2; the port turned Spiraler's slot into a fixed-HP function).
- [x] Encounter odds (data, profile game_constants): back/pincer/side 13/13/13, normal 48,
  preemptive 13 (BNW 33/33/33/156 of 255); pincer starts the party's ATB like a front
  attack (ACCUMULATION_ATB_CROSS_FIRE 50-80).
- [x] Imp (v0.16.0, `ImpRules.cs`): BNW skips vanilla's "Imp equipment" rule (c2.asm 858)
  and halves an imped attacker's damage/healing except with Item (c2.asm 4759 ImpNerf). The
  PR copies vanilla in ParameterProvider.GetArmorDefence/GetOffensivePower/
  GetWeaponOffensivePower (decompiled `tools/decomp/imp`: CheckHaveCondition(..., 601) drops
  non-Imp gear; that was the x0.63 seen earlier); while those run the Imp check answers no.
  The x0.5 is in StatusFactor (monsters too). Probe: imped attacker raw x1.0, final x0.50 for
  Attack and Fire in every direction. Todo: BNW lets Imps cast every spell (c2.asm 2245).
- [x] Blind (v0.16.0, `BlindRules.cs`): BNW (Synchysi's patch, c2.asm 1372/5384) gives a
  blinded attacker a physical hit rate of 50, can't-miss attacks included; the PR halves the
  attacker's accuracy (PhysicalExecution: hit rate = ConfirmedAccuracyRate /
  GetArmConfirmedAccuracyRate, 255 = never misses and skips Blind). In battle a blinded
  unit's accuracy now reads 100, so the game's halving gives 50. Probe (new Blind case, 8
  samples): Attack hits PE 4 -> 1, EP 8 -> 4, PP 8 -> 5 of 8; Fire unaffected. Todo: BNW
  also lets Blind affect Steal, GP Rain (CoinHelp) and Jump.
- [x] Edgar's Tools (porter `port_tools.py` + plugin, v0.16.0): the item porter only moved
  tool prices, so BNW's names ran vanilla effects (Defibrator did Debilitator's job). Now:
  tools that cast a spell (BNW Tool_Data_1/2, c2.asm 2767: Bio Blaster 125, Flash 126,
  Defibrillator 154, Mana Battery 155; profile `tool_spells`) take the ported spell's effect,
  power, element, hit and targets; others their power/hit (Chainsaw 255, Drill 200 + Sap,
  Auto Crossbow 180 / hit 100); Bio Blaster 45, Flash 60. Spell fixes found on the way:
  "!Defib" had no template (it borrowed ForceField's) -> alias to Life; "!ManaBat" borrowed
  Dischord's level halving -> an MP heal with the spell formula (function 1, values 2/3;
  profile `mp_heal_spells`), one ally. The plugin gives Drill/Chainsaw/Auto Crossbow BNW's
  Fight formula with the tool's power as BP (BattleFormulas). Already the game's: Drill and
  Chainsaw ignore Defense (IgnoreDefenseItemIds = [35, 33]), Chainsaw's 25% kill. Left:
  Auto Crossbow no-split and its Schematics upgrade, Noise Blaster's Stamina evasion. Other
  BNW spells without a template (port_report), checked 2026-11-05: Blink, !WindSlash,
  G-Force, Gi Nattak come out right (statuses/element/damage function rebuilt over their own
  slot); !Shock (SNES 130, which idmap gives the slot result 214: the Shock command runs the
  PR's ability 19 instead; 2026-11-06 the plugin's, below), Jackpot
  (slot Reflect???; harmless: the PR's 7-7-7 is its own ability 215 "Joker's Death", Death
  to all foes, and SNES slot 85 "Joker Doom" is Dispatch's slot, not a template),
  !WarpFlute (slot Sour Mouth; should warp out of battle like a Warp Stone).
- [x] Morph without a gauge (v0.16.0, `MorphRules.cs`): BNW removed the morph gauge
  (c2.asm 308, 450, 894): always available, lasts until Revert or the battle's end. The PR
  (decompiled `tools/decomp/morph`): command 8 needs MagicLearningValue > 7
  (CommandAvailableData.IsAvailable -> now true), TranceConditionFunction drains
  MagicLearningValue x 0.5/1 by time unless isPermanent (now set in Start: gauge 100, no
  drain). Probe: the hook fires when Morph is applied; Morph damage factors unchanged.
- [x] Setzer's Slot (v0.17.0, `tools/port_slots.py` + `SlotRules.cs`, config [Battle] SlotRules).
  The PR (decompiled `tools/decomp/slot`): Serial.FF6.Management.SlotInfomationData holds the three
  reels as List<SlotDesignPattern> (Diamond 0, Chocobo 1, BAR 2, Airship 3, Bahamut 4, Seven 5; the
  SNES C2/A800 reels in the same order), per-symbol 1-in-N rolls for reels 2/3
  (IsHit{Second,Third}DesignLottery: reel 2 Seven 8, Bahamut 64, BAR/Airship 256; reel 3 Seven 32)
  and GetHitAbility: 3 of a kind -> {Diamond 213, Chocobo 211, BAR 214 (random esper, group 9),
  Airship 212, Bahamut 112, Seven 216 "Joker's Death" on the foes}, 7-7-Bar -> 215 (Joker's
  Death on the party), else 210. BattleSlotReelController.StopReel(isHit, design, isEyeCatching):
  a passed roll slides the reel up to 5 symbols onto the match; a failed one slips reel 3 one
  past it. BNW 3.0 (checked in the ROM, synchysi slots.asm): reels without Bahamut, symbols in
  threes; no rigging (C1/806D, C1/80A6 branch over it); 7-7-Bar can't come up (C2/B4AF); 7-7-7
  casts Jackpot (spell 151, heal power 10 on the party, lifts Death). Now: the porter makes 216
  Jackpot (functions lift Death + revive to max HP/8 as Life does + Cure's heal, power 10, the
  party, Cure 3's animation, its own name key: 215 and 216 shared MSG_MAGIC_NAME_144) and 215 a copy
  of the losing spin (Go Fish); the plugin refills the reel lists with BNW's (bnw_data.json
  "slot", read from the ROM; only if the game's lists are vanilla's) before the slot UI is built,
  and StopReel runs with isHit false / isEyeCatching true (no slide, no slip). Headless check
  (`probe_headless.ps1 -Mods Magicite -Until "\[slot\] reels"`): reels BNW, 7-7-7 -> 216
  (function group 2068, power 10, party), 7-7-Bar and losses -> Go Fish, rigging off. Not
  seen in a real battle yet. The SNES Jackpot slot itself (PR 152, a Lore) still carries the
  Reflect??? effect; nothing casts it. Bar-Bar-Bar (port_slots.bar_espers): the PR's 214 rolls
  ability_random_group 9 (25 espers at 4, Odin/Raiden out, Bahamut via its own copy 1532); BNW
  rolls any of its 27 (C2/37DC "LDA #$1B; JSR random; CLC; ADC #$36", read from the ROM). Group 9
  is now BNW's 27 (weights 19 x 4 + 8 x 3 = 100), Bahamut still via 1532, which takes BNW's
  ported Bahamut (power 150). Headless: "Bar-Bar-Bar espers 27 (total weight 100)".
- [x] Runic and Bushido weapons (v0.17.0, `tools/port_flags.py` + `CommandWeapons.cs`). BNW (readme): Runic absorbs every
  black/white/grey spell and no enemy skill; it needs a weapon that allows it ("Swordless Runic").
  The PR (decompiled `tools/decomp/runic`): MagicSealSwordConditionFunction.ForciblyTarget draws an
  act to the Runic user when its ability has **content flag 3**, which matches the SNES "allow
  Runic" bit (spell byte 3 bit 3) on 247 of vanilla's 249 spells (the PR leaves X-Zone and Imp
  out). port_flags now carries that bit like the ignore-defense one (profile.runic_flags "mod":
  BNW's 54: every black/white/grey spell + Leo's Shock; set Quake, Storm, X-Zone, Meteor, Merton,
  Imp; cleared 15 enemy skills such as Atomic Ray, Giga Volt, Blight, Exploder). The weapons:
  Serial.FF6.Management.BlockMagicSwordData.ValidWeaponContentId (code, exactly the SNES weapons
  with byte 19 bit 7: 51 incl. spears, katanas, Magus Rod); the plugin refills it with BNW's 23
  (daggers, swords, Atma Weapon; bnw_data.json "runic_weapons") when it holds vanilla's (config
  [Battle] ItemEffects). Bushido is the same: Serial.FF6.Management.KillingSwordData
  .ValidWeaponContentId (command 12) = exactly the SNES weapons with byte 19 bit 1 (28); BNW's 14
  (decompiled `tools/decomp/bushido`; bnw_data.json "command_weapons"). Headless: "[weapons] runic
  BNW's 23 (was vanilla's 51); bushido BNW's 14 (was vanilla's 28)". Not checked:
  the MP gained (BNW keeps the SNES spell MP cost / number of Runic users; the PR sets it in
  MagicSealSwordConditionFunction.SetRecoveryValue, caller not found), BNW's elementless and
  Clear-keeping absorb (readme "Non-Elemental Runic", Vanish fixes), the ready stance.
- [x] Spell "can't miss" and "no split damage" (`tools/port_flags.py`, 2026-11-05): the PR's content
  flag 1 = can't miss matches SNES spell byte 4 bit 5 on 243 of vanilla's 249 spells, flag 2 = no
  multi-target split matches byte 2 bit 6 on 246. Neither was ported: BNW changed 87 / 52 of
  them (Blitzes and Bushido can miss; Quake, Ultima, Merton, Blizzard, Mantra don't split; some
  summons do), and spells rebuilt on a borrowed template had the template's (Umaro's Blizzard
  lost "can't miss"). Now carried like ignore-defense (profile hit_flags / split_flags "mod" for
  BNW: 35 set and 36 cleared / 40 set and 6 cleared; "changed" for the other mods: no change).
- [~] Umaro (v0.17.0, `UmaroRules.cs` + profile ability_overrides). Headless startup check:
  "BNW odds set 0: 1=70% 201=30%; set 1: 1=41% 200=29% 201=30%; set 2: 1=41% 199=29% 201=29%;
  set 3: 1=10% 199=30% 200=30% 201=29% | GetRand hook ok", every pick's roll lands on it in the
  PR's table; not yet seen in a real Umaro battle. BNW (C2/5269, readme "Umaro Hit Hard"): per relic set (none /
  Rage Ring / Blizzard Orb / both) weights of 255 for Fight, Tackle, Snowstorm, ally toss:
  178/75/-/-, 102/75/-/75, 102/75/75/-, 26/75/75/75 (vanilla SNES 158/95, 94/63/95 ..., the PR
  50/50, 25/37.5/37.5, 13/29/29/29). The PR (decompiled `tools/decomp/umaro`,
  ActSelectUmalo.SetActDataUmalo) builds that table per umaloType inside the method and rolls
  CommonUtility.GetRand(100); the plugin picks with BNW's weights and answers that one GetRand(100)
  with a roll that lands on the pick (GetRand(int) is 12 bytes, a jump to Random.Range; the
  startup check logs whether the hook answers). Magitek armor keeps the PR's. Data: Tackle (PR
  201 "Slam", already ignore-defense) power 190 -> 255, ally toss (200) 250 -> 382 (255 + Gauntlet).
  Blizzard (199): power 90, no split, Spirit-based, Blind (spell data). Checked 2026-11-07:
  Tackle already respects row in the PR (CalcControllerProvider.GetFightStatus ignores row only
  for ability type 602, Blitzes, and machine items) and Blizzard's Blind gets no Stamina check
  (AddConditionFunctionSerial.CheckForceMissCondition has none; the plugin's Spirit evasion
  leaves Blizzard out). The toss of Mog as a sure critical (v0.23.0, 2026-11-20): vanilla's own
  rule (C2/16CF: the thrown ally is character $0A, then "Always Critical"), which BNW keeps
  (C216D6 also sets "Ignore Dmg Inc", the SNES damage incrementor; not ported). The PR lost it:
  its toss is a plain function-2 hit and only the animation picks the ally
  (ThrowAtActFunction.SelectThrowingTarget: random among targetable party members, Umaro too,
  the same side in a side attack, Umaro himself if none). UmaroRules makes one pick per toss:
  whichever of the hit (BattleFunction2.HitCalc, the same rule) or the animation runs first
  picks, the other uses it; while a Mog toss is computed Umaro's critical rate reads 100
  (PhysicalExecution: critical when rand(99) < rate). Mog = character status 11.
- [x] Sketch needs a brush (v0.17.0, `CommandWeapons.cs`, config [Battle] ItemEffects). BNW "Brushless
  Sketch" (c2.asm SketchBrshChk/BrushHand: an item whose name starts with the brush icon $E2 in a
  hand; BNW's 4 brushes, content 155-158, bnw_data.json "sketch"). Postfix on
  CommandAvailableData.IsAvailable (command 18) turns Sketch off without one. Headless (latest
  save): "Sketch off for ...: no brush". The PR's Sketch (decompiled tools/decomp/commands,
  ActSelectSketch/SketchConditionFunction) makes Relm the attacker of the sketched monster's
  ability, so her level, Magic and Battle Power are already used (BNW's "Sketch uses Relm's
  stats"). Magic for Vigor (v0.20.0, BattleFormulas): a sketched physical attack (calc under the
  Sketch command) runs BNW's formula with her Magic doubled in 8 bits as Vigor (c2.asm
  SketchMag, BattleMath.SketchVigor: Magic 128+ wraps, as in BNW).
- [x] True Knight cover (v0.20.0, `CoverRules.cs`, 2026-11-07; see the progress row: a postfix on
  TargetFunction.ProtectExtractTarget, BattleMath.CoverGuard, the probe battle's self-test; the
  research below). BNW (c2.asm 968) covers a Near
  Fatal ally always and a back-row ally with Stamina/192 (better when Defending), only from the
  front row, not when the guard is Near Fatal, with a longer status blacklist, single-target
  attacks only, the guard with the most HP, no monster guards. The PR decides in
  Last.Battle.Function.TargetFunction.ProtectTarget(act, otherSameParty, target, protected,
  protectUnit) (decompiled `tools/decomp/cover`) through three lambdas (<>c.b__15_0..2), then
  SetProtectData (since 2026-11-07 the Ghidra script writes <>c classes too: "()c" in the file name). A
  replacement needs the row and status checks (done) and a played fight with a True Knight (the
  back-row Stamina cover is still unseen in one).
- [x] Steal through evasion (v0.16.0, CommandRules): BNW's CoinHelp (c2.asm 2773) sends
  Steal (and GP Rain) through hit determination with hit rate 255, 50 when blinded: before
  BNW's success roll, Steal now misses unless 255 (or 50) * (256 - 2*Evade) / 256 >
  random(0..99), Evade = the monster's evasion. Not probe-measurable (logged once).
- [x] nATB is native to the PR (decompiled BattleProgressATB.Update, `tools/decomp/natb`): the
  whole ATB update (status timers via BattleConditionController.Update, gauges, charging)
  returns while BattleActExection.GetStatingAct() or !BattleUtility.IsStagingEnd(). So BNW's
  shorter timers apply as they are: Sleep/Stop 30 -> 15 (BNW 9 of 18), Freeze 60 -> 18 (BNW
  10 of 34, profile condition_tuning). NatbRules stays as an option, off by default.
  **Doubtful (found 2026-11-12 in the WC work, not re-checked for BNW):** FF6 runs its own
  BattleProgressATBFF6.Update, which doesn't make that check: it stops only for
  BattleUIManager.IsWaiting / IsForceWaiting. Measured headless in a WC battle (WcTest turn_cycle,
  Active mode): no stopped time across whole turns, the attacks included (gauges, charging and status
  timers ran on). So BNW's nATB is probably not native after all, and NatbRules (off) may be needed.
- [x] (2026-11-21) Not native: BNW's nATB is the kit's SnesActionFreeze (BattleActExection.GetStatingAct; nowState is
  never written, so NatbRules never stopped time) + BattleSettingsLock (Wait, x1, rows hidden); BnwPlugin/AtbRules.cs.
- [-] (superseded) nATB hook (v0.16.0, `NatbRules.cs`, config [Battle] nATB): time stops while an action plays
  (c2.asm 873, c3.asm 2542): BattleProgressATB.UpdateGaugeIncrease (ATB fill) and
  UpdateChantTime (spell charging) are skipped while BattleActExection.nowState is
  InPrepare/InAction/InAfterAction/CounterAct/CounterAI; never more than 15 s in a row
  (safety). Unverified: the probe battle never refills ATB (a command menu stays open), so
  the hook never ran there; the first real battle logs "[natb] time stopped ... s".
  Todo: BNW's shorter Sleep/Stop/Freeze timers (c2.asm 3608-3628) and status timers
  pausing too.
- GP Rain (investigated 2026-11-05, `tools/decomp/gilthrow`): the PR's cost is Level x 30
  (capped at the gil owned), BNW's Stamina x 10, both inside
  UniqueUpdateParameterProvider.HitCalcGilThrow (by-ref dictionary parameter: not
  patchable); the spent gil goes through BattleAddExpPlug.AddPlayerSideLostGil(int), which
  monsters stealing gil also use. HitCalcGilThrow also computes the damage itself
  (thrown x 2 / targets): whether our GetUniqueStatus formula reaches real battles needs a
  played GP Rain ("[commands]" log).
- [~] Dual wield and Offering (v0.16.0, RelicRules): BNW puts both on weapons (abilities
  252/253); the PR keys its Genji Glove / Offering corrections on accessories BNW turned
  into consumables (decompiled `tools/decomp/relics`: IsDisorderlyShootAttack = accessory
  armor 114; GetAccessoryPhysicalCorrectionValue 0 -> 0.5, 1 -> 0.75 if IsSecondlyAttack,
  2 -> 1.25, applied to Fight). Now: type 1 returns 0.75 when holding two weapons (BNW's
  Genji effect is on only for weapon/weapon, c2.asm 799-844), type 0 returns 0.75 with an
  Offering weapon (c2.asm 2104-2125: each -25%, multiplied), IsDisorderlyShootAttack is true
  for Offering weapons and CreateContinuousActData's strike count 4 -> 2 (c2.asm 1099).
  The probe party had no such weapons: the paths run (logged per character at probe start)
  but the values are unseen in a real fight.
- [x] The two-handed grip (v0.18.0, RelicRules; 2026-11-06). The PR: PlayerCharacterParameter
  .ConfirmedAttack and .GetArmConfirmedAttack (natural + added + weapon attack) multiply by
  EquipmentAbilityData.TwoHandedMagnification (2) when OwnedCharacterData.HasTwohand: the
  character has ability 251 (EquipmentAbilityData.BothHandsAbilityId) and one hand holds a
  weapon off the InvaliteTwoHandeds list (23 content ids, vanilla's non-grip weapons: daggers,
  rods, brushes...) with the other hand empty (decompiled tools/decomp/twohand: the .ctor fills
  the list, 2 and 251). BNW (c2.asm 799-850 WeapChk, 4914 PlayerPhys): Battle Power x1.5 for a
  weapon with the grip bit (byte 19 bit 6) and the two-hand effect (relic byte 12 bit 3), no
  shield or second weapon; only its 15 grip weapons have both (Mythril Pike, Trident, Stout
  Spear, Partisan, Longinus, Fire Lance, Gungnir, Hanzo, Kotetsu, Ichimonji, Kazekiri,
  Murasame, Masamune, Mutsunokami, Excalibur), and the port gives 251 to exactly these (the
  PR's Gauntlet, armor 111, keeps it, but BNW has no Gauntlet: its slot 208 is a blank item;
  test_mod checks all of it). So the game's check is BNW's and only the factor changes: while
  the game computes the attack, HasTwohand answers no, and the attack gets x1.5. Bushido: x1.5
  with a grip weapon worn, shield or not (C2/185B BushidoCommand checks only the relic bit).
  Windslash / Aero (byte 7 bit 3 "Respect Weapon Flags", c2.asm Wpn_Chk): x1.5 gripped, else
  x0.75. Startup line "[grip] check" (each grip-weapon holder's attack, BNW's and the game's).
  Callers found with pr/tools/ghidra/callers.py (direct calls to a method's RVA: the managed
  code is GameAssembly.dll's "il2cpp" section, not .text).
- [x] Shock (v0.18.0, BattleFormulas; 2026-11-06). The PR's Shock command (28) runs ability 19
  (type 618, power 128, a magic hit). BNW (c2.asm C23EDD): 3/4 (Level x Stamina + current HP)
  in 16 bits (sums past 65535 wrap, as in BNW), halved from the back row, ignoring defense
  (port: content flag group 11 = flags 1 + 5), the user taking max HP / 8 (BNW shows it as a
  number; here the HP drops a frame after the hits, KO through the condition controller).
  Used by Leo and by Celes with Leo's Crest (Runic -> Shock, relic bit 10.4). Formula probe:
  79 of 79 cases on BNW's numbers; the cost needs a real Shock.
- [x] Relic damage corrections, rest (v0.23.x, 2026-11-20). CalcExecuteCorrection
  .GetAccessoryPhysicalCorrectionValue(type) reads one accessory list per type from
  PhysicalCorrectionAccessoryIds (its .cctor: 0 Offering [114] x0.5, 1 Genji Glove [112] x0.75 when
  dual wielding, 2 Atlas Armlet/Hero Ring [99, 104] x1.25, 3 Gauntlet [111] x2; only accessory slots
  count), types 0/1 on Fight (ability type 4) only (decompiled PhysicalExecution). HardItems used to
  rewrite every key with the Atlas bit's items (keys 0/1/3 then logged "not the expected" and kept
  vanilla's ids, blank items in BNW). Now one list per key, accessories only
  (`bnw_plugin_data.HARD_ITEMS` "dict:<key>:armor", `HardList.Key`): 0 = Daryl's Soul (131, BNW's only
  Offering accessory), 1 = none (dual wield is a weapon property), 2 = BNW's Atlas items, 3 = none (the
  grip is the attack's own, ConfirmedAttack). RelicRules makes type 0 BNW's x0.75 for any ability-253
  wearer (an Offering weapon or Daryl's Soul), the game's x0.5 included. Self-test "accessory lists".
- [x] From the BNW command research (2026-11-05; closed 2026-11-20, bnw-engine session; rules in
  `EngineRules.cs`, `BattleFormulas.cs`, `CommandRules.cs`, self-tests in `EngineTests.cs`):
  - failed Blitz half turn: does not apply. BNW (bnw 3.0 halfturn_blitz_stumble.asm, C215A5
    BlitzSlice): a wrong Blitz input shows "Incorrect Blitz input!" and leaves half a turn. The PR's
    Blitz (command 15) is list_type 3: a list of the learned Blitzes, picked and run, with no input to
    get wrong; its "Incorrect blitz command input!" (MSG_SYSTEM_064) has no code reference (string
    literal scan of GameAssembly.dll). The dance-stumble half turn in that file is commented out in BNW.
  - Mug misses when its steal fails (Bropedio's "Mug Better", c0.asm MugHelper: steal messages 0-2,
    nothing to steal included): ported. The PR's Mug is BattleFunction23 (ability 9 "StealAttack":
    UniqueUpdateParameterProvider works out the hit, then, unless it missed, the steal); CommandRules
    records each steal's outcome, a BattleFunction23.HitCalc postfix turns the strike of an empty steal
    into a Miss (no damage, no weapon effect). Only the first strike of a dual-wield Mug mugs (C231AE):
    the PR's second strike (SerialBattleUtility.CreateContiniousActData, secondlyAttack) copies the
    act's command and ability, so a prefix makes it a plain Attack. Mug's strike (ability type 608)
    now gets BNW's Fight formula (it had the PR's vanilla one: BattleFormulas only rescaled types
    4/15/16) and BNW's -25% for an Offering and for two weapons (PhysDmgJump covers every command
    below Bushido; the PR applies those corrections to type 4 only).
  - Steal through evasion: done (v0.16.0). Blind hit 50: Fight and can't-miss weapons (BlindRules),
    Steal (CommandRules' CoinHelp), GP Rain: ported (the PR's HitCalcGilThrow never misses; BNW's
    CoinHelp gives a blinded thrower hit rate 50 against Evade: EngineRules on BattleFunction23, which
    GP Rain also uses), Jump: ported (dn's Blind Jump Fix, c3.asm C3_BlindJump2: the landing can't miss
    unless the jumper is blinded; the PR's landing, ability 22, has content flag 1 "can't miss", so the
    self-test saw 40 of 40 blinded landings hit; a BattleFunction2.HitCalc postfix rolls 50 against
    Evade for a blinded jumper's landing).
  - Tools: Chainsaw's 25% kill and Drill/Chainsaw ignoring Defense are the game's
    (IgnoreDefenseItemIds [35, 33]); Drill's Sap (port_tools); Auto Crossbow's no split is the game's
    own (GetFightStatus: every tool is a "machine": no split damage, no row; vanilla C2/2B5D sets
    "No Split Damage" too). Ported: Drill and Chainsaw respect row (C22B38 Drill_Saw: x0.5 from the
    back row; BattleFormulas); Noise Blaster's Muddle evaded by Spirit (c2.asm Noiseblaster: "Stamina
    Evade"; the act carries the tool, PR item 30, so CommandRules' Spirit evasion checks it); Chainsaw
    on a death-immune target does its cut instead of a wasted kill (ChainInit; the PR's Chainsaw picks
    ability 205 KO / 206 cut from group 10 in BattleFunction46.SetRandomAbility and builds the act in
    CreateAbility, decompiled tools/decomp/chainsaw: a prefix there swaps 205 for 206 when the target
    resists KO); the Schematics (`Schematics.cs`): BNW's Figaro engineer Julian (SNES map 55 NPC 9, event
    CB520D) is the PR's soldier on Map_20370 (map 247, Figaro Castle, entity 329); while that map is up
    after the world's collapse (ScenarioFlag2 41, BNW's event bit 0A4) his talk key is the mod's BNW_JULIAN / BNW_JULIAN_SCHEMATICS, whose text (BNW's
    captions 1667 and 1654, English) comes from a MessageManager.GetMessage postfix, and fetching the
    gift text with Edgar in the party sets bit 0 of BNW's flags word in the save (EsperStore "BNWF");
    with it Auto Crossbow (item 37) reads power 225 and accuracy 255 (BNW: "Power +50%, Accuracy =
    100%"). Not ported: the chancellor's hint (caption 1652).
  - Rage clearing innate statuses: the PR's own (RampageConditionFunction.Remove takes the rage's start
    conditions back off; decompiled tools/decomp/bnw_engine). Ported BNW's other Rage change
    (C22E17 GauRageStatuses): raging as a monster that blocks a status cures it on Gau (SNES status
    bytes 1-2), unless his own gear blocked it already (RampageConditionFunction.Start pre/postfix).
  - Back-attack bonus removed: ported. Vanilla's +50% for a hit in the back (C2/3447) is the PR's
    PhysicalExecution "後ろ向き補正" x1.5 when CalcInfo.isSideAttack (string scan + decompile);
    BattleFormulas undoes it (the sure hit stays, as in BNW). The PR has no such step for spells,
    vanilla does: SNES_PR_DISCREPANCIES.md.
  - D7 elemental averaging (BNW's "Elemental Share", c2.asm C20BD3 + c0.asm EleModLoop): ported.
    Per element immune 0 / resistant 1 / normal 2 / weak 4 points, none = no damage, points / 2 vs the
    number of elements = normal, more = x2, fewer = x0.5, absorb first (BattleMath.ElementShare; 16 BNW
    spells have 2+ elements). The PR rates elements in CalcExecuteFF6.DamageAppliedResistanceAttribute
    (returns a ValueTuple: not patched); while it works out a multi-element spell (GetMagicStatus) the
    target's element table (ConfirmedResistanceAttributeList, slot 33) reads with one element carrying
    BNW's outcome (BattleMath.ElementView), so the game's own rule gives BNW's.
  - Done earlier: Sketch's Magic for Vigor, Leap, X-Magic, Mimic, Umaro, Shock, Morph, Imp,
    character on character, Offering 2 hits -25%, Gauntlet x1.5, cover halving Evade, nATB.

## Plugin (pr/plugin/BnwPlugin)

`dotnet build -c Release -p:Deploy=true` (game closed) builds `BraveNewWorld.PR.dll`
and copies it plus `mods/BraveNewWorld/bnw_data.json` into
`BepInEx/plugins/BraveNewWorld/`. `MasterManager.Instance.GetData<T>(id)` reads live
master data; Harmony can't patch `MasterManager` methods (generic base) but patches
ordinary game methods fine. API dump: `vanilla/Assembly-CSharp.api.txt` (`tools/TypeDump`).
Switches in `BepInEx/config/ff6mod.bravenewworld.cfg` ([Espers] RestrictEquip,
EsperLevels, EquipBonuses, DisableLevelUpBonus, AutoSpendEL, SpendKey).

Hooking rule (learned the hard way, v0.6.0 crashed the game at startup): the game's
C++ is linked with identical-function folding, so tiny methods (empty, or one call)
share one machine-code body with many others. Hooking StatusDetailsController.UpdateView
(empty) made the hook run for unrelated objects; reading their "fields" was an access
violation, which .NET cannot catch, so the game closed. Now (v0.6.1): `EsperHooks.Patch`
reads each target's first code bytes and refuses ret/jump-only methods (logged with the
bytes), and every hook checks `EsperHooks.IsA<T>(__instance)` (native class pointer)
before touching the object. Hook the method that does the work, not a wrapper.
v0.6.1-0.8.0 had a broken guard: `Il2CppClassPointerStore<T>.NativeClassPtr` can be 0
until the interop type's static constructor runs, so IsA rejected everything and
every guarded hook (EP/EL, stat/equip bonuses, esper menus, EL display) was silently
off. v0.8.1: `ClassOf<T>` runs the static constructor first and caches the pointer,
the check is `il2cpp_class_is_assignable_from` (as `TryCast<T>`), a startup
self-test logs "[guard] self-test", and each type logs once what it rejected.
Since 2026-11-11 (v0.22.1) these helpers are the modding kit's (`plugin/PrKit/Hooks.cs`, same code, for
every PR): BNW calls `Hooks.Patch/IsA/WarnOnce/NoteOnce/TinyNativeCode`; `EsperHooks` keeps BNW's own
self-test line. The harness (`Harness.cs`) and the probe's save block and mute (`TestRun.cs`) are the
kit's too; BNW's `GameHarness` adds party/skipmsg/quit. Probe runs now log "[test] saves blocked ..." and
"[test] save to slot N skipped (test run)" instead of the "[probe] ..." lines.

Layout: `plugin/Rules/` = BNW rules with no game types (shared by the plugin and the
tests), `plugin/BnwPlugin/` = hooks, `plugin/Rules.Tests/` = offline test runner
(`cd pr/plugin/Rules.Tests && dotnet run -c Release`, 21 tests; it checks every
decoded EL/equip bonus against BNW's own bonus text).

Data: `tools/bnw_plugin_data.py` reads the BNW ROM and writes `bnw_data.json` in PR
terms: EP chart (ED/8BCA), EL bonus table (C2/614E), equip bonuses (C0/D690, 10
bytes/esper), esper users (C3/F0F5) as character_status ids, esper content ids.
The repo asm differs from the 3.0 release in places (e.g. ELTable), so the ROM wins.
The porter also writes `MSG_BNW_ESPER_BONUS_nn` text ("EL: +2 Vigor   Equip: Halves
Bolt damage") for the esper screen's bonus line.

Esper system (v0.8.4, `EsperHooks.cs`, `EsperMenu.cs`, `EsperList.cs`, `EsperStore.cs`):
- Restrictions: on the esper list (KeyInput `MagicStoneListController.ContentUpdate`
  + `MagicStoneListContentController.SetFocus`) espers the character can't use are
  greyed out (`IconTextView.SetTextColor`), as in BNW; equipping one
  (`MagicStoneDetailsController.EquipMagicStone(target, list, bool)`) plays the
  buzzer and does nothing; `OwnedCharacterClient.SetMagicStone` refuses it as a
  backstop. (v0.3.0 hid them as "not owned" instead: that left blank cells and a
  stray check mark when someone else had the esper equipped.)
- Vanilla level-up bonus off: `MagicStoneData.GetParameterType` → `Non`,
  `GetParameterValue` → 0; `GetMagicBonusMessageId` → BNW bonus text key.
- EP/EL: postfix `BattleResultProvider.Genelate`. For each character that got XP
  with an esper equipped: SP bank += SP (cap 30), EP += XP/8 × SP (cap 50,000; the
  SNES keeps 16 bits, we saturate), EL up per EP chart (cap 25, Terra..Gau only).
  SP = max(result.GetMp, result.GetAbp) (logged once to confirm which one).
  New ELs go to the EL bank (AutoSpendEL=true spends them at once on the equipped
  esper instead). Stat gains stop at 128 (base + spent), as in BNW's AddEL.
- EL bank menu (`EsperMenu.cs`, KeyInput UI = keyboard/gamepad, not touch), like
  BNW's "cursor on the esper bonus, press A". The details screen's bonus row is
  `levelUpText` ("At level up:") + `parameterValueText` (our MSG_BNW_ESPER_BONUS line).
  The label becomes `Unspent EL: 8` (BNW's wording), gold while there are ELs to
  spend; the description box on that row also gives `EL 10, next EL in 1,234 EP.` (A coloured badge behind it was tried and dropped: the bonus row's parent
  lays its children out in a row, so any added sibling becomes a layout item and
  pushes the texts sideways. Anything added there must be a child of the label.)
  Navigation uses the game's own keys, so it follows rebinding on keyboard and
  gamepad: `WaitInputUpdate` prefix reads Up/Down/Action itself; Down from the last
  spell row (`Contents` rows with AbilityData) moves the game's hand `Cursor` onto
  an anchor (child of the label) in the spell rows' cursor column on the label's
  line. The hand follows a target through a PositionConstraint, so moving its
  transform does nothing: `Cursor.SetSource(anchor)` retargets it (and
  `SetSource(row.CursorParent)` puts it back). The description box shows
  `EsperRules.SpendHint`; Confirm spends (`ShopAccounting` / `BeepId`); Up goes
  back (`SelectAbilityDataContent`).
  While on the row, Up/Down/Action are hidden from the screen via postfixes on
  `InputListener.GetKeyDown` and `GetKey` (only during `WaitInputUpdate`). Leaves the
  row if the game moves its cursor or redraws for another esper.
  Seen in the user's log: details screen polls Up/Down/Left/Right/Action/Shortcut/
  Cancel; keyboard defaults Action=Return, Cancel=Backspace, Menu=Tab, Shortcut=Q,
  Start=Space, Select=Home, PageUp=Z, PageDown=X, L/R=2/3 (the screen's Shortcut/Q
  opens the magicite list). Rect positions read in the screen's first frame are
  stale (it slides in). Optional extra key: config SpendKey (default None).
- Esper list (`EsperList.cs`): see Restrictions above.
- Saved in the save file: `DataStorage.global` was the first idea but has only 16
  slots (checked in game). Instead the block lives in FF2's keyword list
  (`UserDataManager.OwnedKeyWaordList`, `List<int>`, saved as `ownedKeyWaordList`;
  FF6 never uses it): marker "BNW1" + 3 packed ints per character_status id 1..14
  (EP/EL/EL bank/SP bank; spent HP/MP; spent stats). Other entries are left alone.
  The game computes stats on several threads (the Deck's log showed a corrupted
  Dictionary in the MaxHp/MaxMp hooks): EsperStore and the one-time log sets are
  locked since v0.8.4.
  Save -> load confirmed (2026-11-20, decompiled tools/decomp/bnw_engine): UserDataManager.ToJSON
  writes the list as `ownedKeyWaordList` (JSON of {"target": [...]} inside the save JSON) and
  FromJsonAsync clears the list, then reads it back from the save, so a load never keeps the last
  save's block. Self-test "EL in the save": an EL/EP set in the block reads back from the game's own
  save text (ToJSON).
- Stats: spent EL totals + equip bonus added in postfixes on
  `PlayerCharacterParameter.Confirmed*` (MaxHp/MaxMp incl. HP/MP %, Power,
  Agility, Vitality, Magic, Defense, AbilityDefense, EvasionRate,
  AbilityEvasionRate). Nothing is written into the game's own stat fields, so
  turning the plugin off reverts the bonuses.
- Elements/statuses: `ConfirmedResistanceAttributeList` gets half (type 2; cancels
  weak, never downgrades null/absorb), `ConfirmedResistanceCondtionList` gets the
  blocked conditions (value 1), `GetEquipmentConfirmedConditionList` gets the
  auto-statuses (Haste 21, Shell 22, Safe 23, Regen 20, Reflect 92). The plugin logs
  one sample of each dictionary to confirm the value meanings.
- Checked in game (auto-closed launches + the user's own session): plugin loads,
  hooks attach, bonus text shows on the esper screen, the keyword-list store is
  reachable, esper restriction applies to the list. Not yet seen: battle EP/EL,
  save/load of the block, stat display, the grey-out and spend key in v0.3.1.

SP bank (v0.9.0; `SpellBank.cs`, `EsperMenu.cs`, rules `EsperRules.TryLearn`):
- BNW (c2.asm Add_EP, c3.asm Pressed_A): each battle's SP (capped 30) is banked for
  a character with an esper equipped, besides normal learning. On the esper screen,
  A on a spell row pays the spell's full SP cost from the bank (partial progress
  doesn't count) and learns it, if the character may use that esper (it needn't be
  equipped) and doesn't know it; else buzz. Only esper data slots 0-2 hold spells
  (3-4 hold unrelated bytes); costs 1..30, in bnw_data.json espers[].spells
  (`ability_id` = PR ability).
- PR screen: Confirm on any spell row equips, and the cursor opens on spell 1, so
  BNW's layout is rebuilt: the esper's name is a cursor stop and where the screen
  opens (Confirm = the game's equip/remove), spell rows take Confirm to learn, the
  bonus row spends ELs. Up/Down move between them (the game's keys, so rebinding and
  gamepads work); the description box says what Confirm does on each stop.
- Learning: the character's `OwnedAbility` (added with
  `OwnedCharacterClient.AddAbility` if battles never started it) gets SkillLevel 100;
  the row is refreshed with `SetData(target, new MagicStoneAbilityData(...))`.
- BNW learns nothing in battle (c2.asm "Remove learning spells from post-combat
  routine"): the bank is the only way. Profile flag `spell_bank_only` (BNW) makes the
  porter write learn rate 0 for esper spells (learning.csv value2), so the PR's battle
  learning never advances; natural magic (type 1 rows) is untouched.
- Display (v0.9.1), BNW's rows (c3.asm MPCost/SPCost, "skip drawing spell progress"):
  name, MP cost (`Ability.UseValue`) + "MP", SP cost + "SP" (blank once learned; the
  PR's star marks it), no colon/progress/rate; headings "" and "Learn"; "SP 20/30"
  ("SP" in the heading color, number white) in the empty 5th row slot, right edge on
  the rows' SP units, as BNW right-aligns it under "Learn". Units are copies of the
  heading text placed after each number (children of the row texts).
- v0.9.0 bug: the readout was a copy of the "Progress" heading and
  `ColorUtility.ToHtmlStringRGB` threw IndexOutOfRange (IL2CPP), so the copy kept saying
  "Progress" on top of the real one. No ColorUtility/rich text since.
- Seen in game (Deck, v0.9.0): Locke bought Fire 2 for 15 SP (20 -> 5), skill level
  100. v0.9.1 layout checked by the user ("sp seems fine"). The help bar still says
  Equip/Remove on spell rows.

Test kit (`TestKitHotkey.cs`, rules in `Rules/TestKit.cs`; config [Testing]
TestKit, off by default): F8 with a save loaded adds every BNW esper
(`OwnedItemClient.AddMagicStone`), sets Terra..Gau to at least EL 10 with 10 ELs
banked, EP one short of the next EL and 20 SP banked (never lowers anything), and
tops gil up to 500,000 (`AddGil`). The player then saves to a spare slot: the game
writes the save itself, so no hand-made (encrypted) save files.
Controller (Steam Deck has no F-keys, v0.8.5): click both sticks in, L3 + R3. Tap in
battle = F10, tap on the field = F9, hold 1.5 s on the field = F8 (fires on release
for taps). Read through the game's own `InputListener.GetKey(Key.StickL/StickR,
GamePad)` or Unity's `JoystickButton8/9` (Xbox layout, what Proton shows the game);
the log notes once which one saw it ("[test kit] L3+R3 seen (...)").

Where SNES BNW shows EL (c3.asm): total EL beside LV ("LV 35  EL 10") in every
character header drawn by C3/0C81 (main menu party, party select C3/797D, status,
skills menus; only after meeting Ramuh, never for Gogo+); "Next EL" + EP needed
under "Next LV" on the status screen (EPUpTxt); "Unspent EL: NN" under the esper
bonus on the esper screen (Unspent_EL, C3/5A3B); banked SP beside the esper's spells.

PR version (`EsperLevelDisplay.cs`, v0.6.1): "EL n" after the level number in the
main-menu party panels (KeyInput `StatusWindowContentController.SetData`) and the
ability/status character header (`AbilityCharaStatusController.UpdateView`); the two
texts are `Instantiate` copies of the level text (font/outline match), "EL" restyled
like the "LV" label, kept as children of the level text so no layout group moves.
Status screen (`StatusDetailsController.SetParameter` / `SetMagicStoneBouns`): the
"Level Up Bonus" row becomes "Next EL" + EP needed (0 at max; blank for Gogo+).
Shown once the party owns an esper (PR stand-in for BNW's "met Ramuh" bit).
Geometry and the status screen's texts are logged once. Not yet seen in game; other
LV displays (party select, save/load, shops) not done.

Esper TODO (all done by 2026-11-20): SP bank spell buying (v0.9.0), Alexandr/Ragnarok "+25% output"
(RelicRules), EL/EP display (EsperLevelDisplay), the "EL gained" message (`EsperResultRows.cs`: BNW's
"<name> gained an EL", c2.asm Show_EL / message $46, once per character whose EL went up, as a row of
the PR's victory screen: KeyInput.ResultSkillController.SetLevelUpList rows made with the game's own
CreateLevelUpContents and drawn as its sentence rows; IsToAbilityLevelUp shows that page when someone
gained an EL; the touch menu is the phone's, not done), unequip disallowed espers in old saves
(EsperHooks.UnequipDisallowed: every 2 s outside battle, an esper the character may not use comes off
through OwnedCharacterClient.RemoveMagicStone, logged: a vanilla PR save, which BNW's own saves start
as, can have one).

## HD-2D plugin (pr/hd2d, pr/plugin/Hd2dPlugin)

Separate from BNW: an Octopath-style look (tilt-shift, bloom, grade, vignette) applied to
the main-game image before the game composites it with the UI. Shaders need Unity
2019.4.26f1 (installed 2026-11-04). `deploy.sh` installs it on the PC and the Deck. See
`pr/hd2d/README.md`.
