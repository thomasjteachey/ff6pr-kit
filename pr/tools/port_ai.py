"""Compile BNW's monster AI into PR scripts (tools/ai_compile.py) and add them to the mod.

Each compiled monster gets its own new script (sc_ai_bnw_NNN) and its
monster.script_id points at it, so shared vanilla scripts stay intact. Scripts
BNW didn't change, and scripts using features the compiler can't express
(bringing monsters in, events, animations) keep the PR's own script.

Bosses are compiled only when nothing else in the PR depends on their AI: the
PR's own script for them sets no modes or battle-specific variables, and their
formations' battle event scripts either don't touch AI state (cosmetic routines,
or ones checked by hand: SAFE_SCRIPTS) or run a routine that owns which monsters
are on screen (ENTRANCE_SCRIPTS). Those fights are hybrids: BNW's AI with its own
"bring in / hide" instructions left out, the PR routine handling entrances.
Anything else (story events, the final battle's tiers) keeps the PR's script.
"""
import json
import os
from collections import Counter

import glob

import ai_compile as AC
import ai_corpus
import port_specials
import prdata as P
import snes_ai as A

AI_PATH = "Assets/GameAssets/Serial/Res/Battle/MonsterAI"
BATTLE_SCRIPTS = os.path.join(P.VANILLA, "battle_script", "Assets", "GameAssets", "Serial", "Res", "Battle", "BattleScript")
GENERIC_SYSCALLS = {"WaitBattleEndEnemyDisappear", "血塗られた盾", "PauseEscapeManipulate", "ResumeEscapeManipulate",
                    "HideBattleUI", "ShowBattleUI", "プレイヤーサイドZ値変更", "プレイヤーサイドZ値戻す"}
# Battle event scripts read by hand (pr/vanilla/battle_script): they don't depend on the
# AI of the bosses in them (Veldt: Gau joining; Cultists' Tower: statuses at the start).
# Nelapa's script is safe after wc_events.nelapa_battle removes the PR-only
# doom/laugh setup in WC mode.  Its WC/SNES AI owns that one-time opening
# action; the remaining PR script only services the escape countdown.
SAFE_SCRIPTS = {"sc_b_0239", "sc_b_2019", "sc_b_2024"}
# Event scripts whose routine decides who is on screen: Chadarnook's switch, Hidon's
# ghosts, Inferno's parts, Air Force's bays, No.128's arms, tentacles, Dream Stooges,
# Ultros moving (Esper Cave), Soul Saver.
# Event scripts that play an SNES battle event when the fight opens, the monsters it brings in
# already on screen in the PR party: the AI's "event N" and its bring-ins are left out (the
# Whelk: event 5 is the Biggs/Wedge talk sc_b_0011 shows first; BNW then brings the head out).
INTRO_SCRIPTS = {"sc_b_0011": {0x05}}
ENTRANCE_SCRIPTS = {"sc_b_2016", "sc_b_2020", "sc_b_2021", "sc_b_2013", "sc_b_2010", "sc_b_2029", "sc_b_2028",
                    "sc_b_2007", "sc_b_0939"}
# PR abilities whose effect writes variables a battle routine reads
COUPLING_PROGS = {"IFRIT_SHIVA_BATTLE_VARIABLE_CALC", "VARGAS_BATTLE_VARIABLE_CALC"}
COUPLED = {"GetEnemyMode", "BattleCondition", "BattleAddEnemy", "BattleSleepEnemy", "BattleForceExit", "BattleEndEnabled"}
FINAL_BATTLE = set(range(343, 352))  # Kefka's tower tiers (SNES ids)


class BossPolicy:
    """Which bosses can take a compiled script without breaking PR battle events."""

    def __init__(self):
        names = {r["id"]: r["script_name"] for r in P.Table("script")}
        self.risky = {}
        self.adding = set()   # battle scripts that bring monsters in themselves (BattleAddEnemy)
        for f in glob.glob(os.path.join(BATTLE_SCRIPTS, "*.json")):
            doc = json.load(open(f, encoding="utf-8"))
            calls = {m["operands"]["sValues"][0] for m in doc["Mnemonics"] if m["mnemonic"] == "SysCall"}
            used = {m["mnemonic"] for m in doc["Mnemonics"]} & COUPLED
            if "BattleAddEnemy" in used:   # brings monsters in itself (the Flans' split, Chaser's Trappers, Opinicus)
                self.adding.add(os.path.basename(f)[:-5])
            special = calls - GENERIC_SYSCALLS
            if used or special:
                self.risky[os.path.basename(f)[:-5]] = sorted(used) + sorted(special)[:3]
        self.party_scripts = {}
        for r in P.Table("monster_party"):
            name = names.get(r["script_name"])
            for k in range(1, 10):
                m = int(r[f"monster{k}"])
                if m and name:
                    self.party_scripts.setdefault(m, set()).add(name)
        self.parties, self.members = {}, {}
        for r in P.Table("monster_party"):
            if int(r["id"]) >= 2000:  # the porter's own random-encounter formations
                continue
            for k in range(1, 10):
                m = int(r[f"monster{k}"])
                if m:
                    if int(r["id"]) not in self.parties.setdefault(m, []):
                        self.parties[m].append(int(r["id"]))
                    self.members.setdefault(int(r["id"]), set()).add(m)

    def party_members(self, party):
        return self.members.get(party, set())

    def parties_all(self):
        return set(self.members)

    def add_event_parties(self, mpt):
        """The parties port_events made for BNW's story fights (7000 + the PR's event party: BNW's line-up
        on that party's look and battle script) count as the fights their monsters are in."""
        names = {r["id"]: r["script_name"] for r in P.Table("script")}
        for pid, r in mpt.rows.items():
            if not 7000 <= pid < 9000:   # port_events' story fights, and new_fights' (8000 + formation)
                continue
            name = names.get(r.get("script_name"))
            for k in range(1, 10):
                m = int(r.get(f"monster{k}", "0") or 0)
                if not m:
                    continue
                if pid not in self.parties.setdefault(m, []):
                    self.parties[m].append(pid)
                self.members.setdefault(pid, set()).add(m)
                if name:
                    self.party_scripts.setdefault(m, set()).add(name)

    def snes_reason(self, e, vdoc, replaced=()):
        """With the plugin's interpreter (SNES_AI): None if boss e (SNES id) can run its mod script there,
        else why it keeps the PR's AI. The PR AI's own modes and variables matter only where a battle
        script of its fights reads them (GetEnemyMode, a boss routine): those are risky unless the profile
        lists the script as one that works alongside the mod's AI (snes_ai_hybrid_scripts: the plugin
        sets the modes it reads, snes_ai_events). replaced: vanilla parties port_events swapped for BNW's
        line-up (7000 + party): not fought any more."""
        keep = profile_setting("snes_ai_keep", {})
        if e in keep:
            return keep[e]
        if e in FINAL_BATTLE:
            return "final battle (the PR's four tiers are its own battle event)"
        if not [p for p in self.parties.get(e + 1, []) if p not in replaced]:
            if e in profile_setting("snes_ai_brought_in", {}):
                return None   # brought in by a fight on the plugin (checked once pass 1 is done)
            return "no formation of its own (another fight's event brings it in)"
        hybrid = profile_setting("snes_ai_hybrid_scripts", {})
        for name in sorted(self.party_scripts.get(e + 1, ())):
            if name in SAFE_SCRIPTS or name in ENTRANCE_SCRIPTS or name in INTRO_SCRIPTS or name in hybrid:
                continue
            if name in self.risky:
                return f"battle event {name} uses " + "/".join(self.risky[name])
        return None

    def reason(self, e, vdoc, ab=None):
        """(None, hybrid) if boss e (SNES id) can be compiled, else (why not, False)."""
        if e in FINAL_BATTLE:
            return "final battle", False
        if vdoc is None:
            return "PR script not found", False
        if not self.parties.get(e + 1):
            return "no formation of its own (another fight's event brings it in)", False
        if {m["mnemonic"] for m in vdoc["Mnemonics"]} & {"ModeSet", "ModeCount"}:
            return "PR script sets modes for its battle event", False
        if ab is not None:
            progs = {ab[x]["process_prog"] for m in vdoc["Mnemonics"] for x in m["operands"]["iValues"]
                     if m["mnemonic"].endswith("Act") and x in ab.rows}
            if progs & COUPLING_PROGS:
                return "PR script writes variables its battle routine reads (" + "/".join(sorted(progs & COUPLING_PROGS)) + ")", False
        hybrid = False
        for name in sorted(self.party_scripts.get(e + 1, ())):
            if name in SAFE_SCRIPTS:
                continue
            if name in ENTRANCE_SCRIPTS or name in INTRO_SCRIPTS:
                hybrid = True
                continue
            if name in self.risky:
                return f"battle event {name} uses " + "/".join(self.risky[name]), False
        return None, hybrid


# WC seeds: every monster's turns, counters and death are decided by the WC plugin running the mod's own
# SNES script (WcPlugin/WcEnemyAi.cs, SnesAi.cs). Its PR script is a shim whose rows carry markers the
# plugin answers: LoopAct [MARK_TURN] (the turn: one act, several, or the idle "nothing"),
# CounterAct [MARK_COUNTER] (after a hit), FinalAttackAct [MARK_FINAL] (on death). Confused or berserk,
# the PR's own default: its Battle (FF6 RandMonsterAction acts at random too).
MARK_TURN, MARK_COUNTER, MARK_FINAL = 7680, 7681, 7682
SNES_AI = os.environ.get("WC_SNES_AI") == "1"
# a mod whose plugin runs its scripts on the kit's SnesAiHost (PrKit/Ff6): the porter sets these from its
# profile (port.py: snes_ai, snes_ai_rules). Rules: the mod engine's script changes (SnesAiRules: "bnw");
# status effects: the host's FB 0B/0C/02 (BNW's boss deaths), off for Worlds Collide until tested there
SNES_AI_RULES = "vanilla"
SNES_AI_STATUS = False
SNES_AI_F5 = True     # F5 (monsters in and out) by the plugin (WcEnemyAiEntries.cs): on once its fights pass in game
SNES_AI_VERSION = 5   # v5: Nelapa's SNES AI owns its one-shot Doom opening (not PR sc_b_2019)


# what the plugin's interpreter does today (WcEnemyAi.cs): every attack, target, condition, variable,
# timer reset (FB 00/04), battle line (F3) and animation (FA, cosmetic: left out), and on death "everyone
# leaves like a boss" (F5 op 1/4 on mask FF) or the monster's own exit; a monster whose WC script needs
# anything else (bringing monsters in or out, battle events, formation changes, items, forced commands,
# other misc effects) keeps its previous AI until the plugin does it
SNES_AI_MISC = {0x00, 0x04}
# with SNES_AI_STATUS (BNW): the battle's end (02, 09), a status set/cleared on itself (0B/0C), a target
# made invincible / vulnerable (01/05: the SNES's $3A3C zeroes its damage), monsters made targetable /
# untargetable (06/07: $2F46), itself hidden (0D: status 4 bit 5, "removed from battle")
SNES_AI_STATUS_MISC = {0x01, 0x02, 0x05, 0x06, 0x07, 0x09, 0x0B, 0x0C, 0x0D}
PROFILE = None   # the porting profile (port.py): its per-fight AI settings, below
# WC's items and commands (F6 use/throw, F4) as the PR's monster abilities, as Square ported them:
# a thrown weapon is a physical hit with its power (Square's 740-756: Mythril Knife 30 = 740 ... Fuma
# Shuriken 132 = 747; animation by kind), a used item an ability with the item's own effect (Square's
# 760 is Hi-Potion so), Steal 693, Jump 1391 (it lands as 1392), GP Rain 694 (GIL_THROW); Capture
# (steal and hit) has no monster version: Steal. Rows Square has no copy of are made from 7700 on.
ITEM_ABILITY_BASE = 7700
CMD_ABILITY = {0x05: 693, 0x06: 693, 0x16: 1391, 0x18: 694}
THROW_EFFECT = {"5": "1169", "3": "1169", "4": "1167", "15": "1170"}   # weapon category -> throw animation
SQUARE_THROWS = range(740, 757)
SQUARE_ITEM_USE = 760


def profile_setting(name, default=None):
    """A per-fight AI setting of the porting profile (profile_bnw: snes_ai_events, ...)."""
    v = getattr(PROFILE, name, None) if PROFILE is not None else None
    return default if v is None else v


def snes_ai_unsupported(main, counter, events_ok=(), formation_ok=False):
    """The first command the plugin can't run yet in this monster's WC script, or None. events_ok: the
    SNES battle events (F7) the fight takes care of another way (the PR's battle script plays it, or the
    plugin sets the PR monster mode its battle script reads: profile snes_ai_events); formation_ok: a
    formation change (F2) the PR's battle routine makes itself."""
    for section, ops in (("main", main), ("counter", counter)):
        for op, args in ops:
            if op == "event" and args[0] in events_ok:
                continue
            if op == "formation" and formation_ok:
                continue
            if op in ("formation", "event"):
                return f"{section}: {op}"
            if op == "misc" and args[0] not in SNES_AI_MISC | (SNES_AI_STATUS_MISC if SNES_AI_STATUS else set()):
                return f"{section}: misc {args[0]:02x}"
            if op == "command" and any(c != 0xFE and c not in CMD_ABILITY for c in args):
                return f"{section}: command {' '.join(f'{c:02x}' for c in args)}"
            # "enemies" (F5): the plugin brings members in and out (WcEnemyAiEntries.cs); until that's on,
            # only a death's "everyone dies" runs there
            if op == "enemies" and not SNES_AI_F5:
                _anim, mode, mask = args
                if not (section == "counter" and mode in (1, 4) and mask in (0x00, 0xFF)):
                    return f"{section}: enemies mode {mode} mask {mask:02x}"
    return None


def shim_script(battle):
    """The PR's layout (sc_ai_17D_UltimaBuster): FinalAttackAct before SyncAI so a death runs whatever
    branch the pass took; SyncAI, Blank, ExecMsg so lines riding on an act get shown (a pass with a
    line set and no ExecMsg spins for good); counters before the confusion branch (SNES counters run
    while confused, only their "if dead"/"if always" blocks); the turn's row in the table."""
    m = AC.mn
    return [m("Nop", label="Main", pad=False),
            m("FinalAttackAct", [MARK_FINAL], [100], pad=False),
            m("SyncAI"), m("Blank"),
            m("ExecMsg", [1], [1], pad=False),
            m("CounterAct", [MARK_COUNTER], [100], pad=False),
            m("IsMyCondition", [AC.CONFUSE, 11]),
            m("StartTable"),
            m("LoopAct", [MARK_TURN], [1], pad=False),
            m("EndTable"), m("JumpBattleAI"),
            m("Nop", label="confused", pad=False), m("StartTable"),
            m("Act", [battle], [100], pad=False),
            m("EndTable"), m("JumpBattleAI"),
            m("Nop", label="EndBattle", pad=False), m("Exit")]


def party_resolver(tables, cap=12):
    """SNES formation f -> the PR party ids that battle can be: f + 1 (the PR numbers parties
    from 1: 255 of vanilla's formations match that way), the parties port_encounters made for a
    BNW formation (NEW_PARTY_BASE + f, and one per further place's look: port_encounters.party_ids),
    and the PR's own copies of party f + 1 (ids past the SNES range with the same monsters:
    Chaser's 123 has 3088)."""
    import port_encounters as E
    import prdata as P
    vmp = P.Table("monster_party")
    mp = tables.get("monster_party") or vmp

    def members(row):
        return tuple(sorted(int(row[f"monster{k}"]) for k in range(1, 13) if row.get(f"monster{k}", "0") not in ("0", "")))

    copies = {}
    for pid, row in vmp.rows.items():
        if pid > 576:
            copies.setdefault(members(row), []).append(pid)

    def parties(f):
        out = []
        if f + 1 in mp.rows:
            out.append(f + 1)
            out += copies.get(members(vmp[f + 1]), []) if f + 1 in vmp.rows else []
        out += E.party_ids(f, mp.rows)
        return sorted(set(out))[:cap]
    return parties


def formation_slots(rom):
    """SNES enemy id -> {slot: {enemy ids}} over every formation it appears in."""
    import port_encounters as E
    out = {}
    for f in range(576):
        raw = rom.data[E.FORMATIONS + 15 * f:E.FORMATIONS + 15 * f + 15]
        here = {s: raw[2 + s] | ((raw[14] >> s & 1) << 8) for s in range(6) if raw[1] >> s & 1}
        for m in set(here.values()):
            slots = out.setdefault(m, {})
            for s, x in here.items():
                slots.setdefault(s, set()).add(x)
    return out


def battle_ability(ab, doc):
    """The monster's own "Battle" ability (attack animation) in its vanilla PR script."""
    if not doc:
        return 1
    counts = Counter()
    for m in doc["Mnemonics"]:
        if m["mnemonic"] in ("Act", "LoopAct", "CounterAct"):
            for x in m["operands"]["iValues"]:
                if x in ab.rows and ab[x]["type_id"] == "4":
                    counts[x] += 1
    return counts.most_common(1)[0][0] if counts else 1


def port(van, bnw, tables, out_dir, log, battle_messages=False):
    """battle_messages: compiled scripts show the mod's monster battle lines (battle_text);
    the lines they use are left in port.battle_texts {story_mes key: text}."""
    ab = P.Table("ability")
    mo = tables.setdefault("monster", P.Table("monster"))
    scripts = tables.setdefault("monster_ai_script", P.Table("monster_ai_script"))
    vmo = P.Table("monster")
    changed = {"monster": set(), "monster_ai_script": set()}
    stats, reasons = Counter(), Counter()
    bosses = BossPolicy()
    boss_kept, boss_tests = {}, []
    keys, values = [], []
    dest_dir = os.path.join(out_dir, "monster_ai", *AI_PATH.split("/"))
    os.makedirs(dest_dir, exist_ok=True)

    # pass 1: compile everything that can be
    slots = formation_slots(bnw)
    formation_parties = party_resolver(tables)
    import battle_text
    battle_lines = battle_text.Messages(bnw) if battle_messages else None
    compiled = {}  # SNES id -> (mnemonics, ctx)
    is_boss = {e: vmo[e + 1]["boss"] != "0" for e in range(384)}
    import ff6snes as _S
    if AC.scaled_tiers():
        # WC's ability scaling: a row per placeholder the compiled scripts cast (ai_compile
        # SCALED_BASE + k), a copy of a spell of its category; the WC plugin swaps in the spell
        # WC would cast (WcAbilityScaling.cs). No name rows: the act shows the swapped spell's.
        abt = tables.setdefault("ability", P.Table("ability"))
        changed["ability"] = set()
        for k in range(AC.SCALED_COUNT):
            aid, src = AC.SCALED_BASE + k, AC.scaled_stand_in(k)
            if aid in ab.rows:
                raise ValueError(f"ability scaling placeholder {aid} would overwrite an ability")
            row = dict(abt[src], id=str(aid), sort_id=str(aid))
            if abt.rows.get(aid) != row:
                abt.rows[aid] = row
                changed["ability"].add(aid)
    if SNES_AI:
        abt = tables.setdefault("ability", P.Table("ability"))
        changed.setdefault("ability", set())
        for aid in (MARK_TURN, MARK_COUNTER, MARK_FINAL):
            if aid in ab.rows:
                raise ValueError(f"AI marker {aid} would overwrite an ability")
            row = dict(abt[AC.NOTHING], id=str(aid), sort_id=str(aid))
            if abt.rows.get(aid) != row:
                abt.rows[aid] = row
                changed["ability"].add(aid)
        # past the specials' copies (port_specials.COPY_BASE, the same 7700 on: BNW splits shared specials;
        # 2026-11-19 a throw row overwrote monster 184's special copy 7700; WC makes no copies)
        port.item_abilities = item_abilities(bnw, abt, tables, changed["ability"], taken=set(port_specials.plan(van, bnw)[1]))
    shimmed = set()   # monsters whose turns the plugin runs (their PR script is the shim)
    # SNES events the plugin answers with a PR monster mode (or nothing: the PR's battle script plays them)
    event_modes = profile_setting("snes_ai_events", {}) if SNES_AI_STATUS else {}
    pr_entrances = set()   # on the plugin, its F5 entries left to the fight's PR battle routine
    # vanilla parties port_events replaced with BNW's line-up (its 7000 + party): not fought any more
    mpt0 = tables.get("monster_party")
    if SNES_AI:
        changed["monster_party"] = new_fights(van, bnw, tables, log)
    replaced = {p for p in bosses.parties_all() if mpt0 is not None and 7000 + p in mpt0.rows}
    if SNES_AI and mpt0 is not None:
        bosses.add_event_parties(mpt0)
    for e in range(384):
        vmain, vcounter = A.script(van, e)
        bmain, bcounter = A.script(bnw, e)
        if SNES_AI and _S.blank_enemy(bnw, e) and not _S.blank_enemy(van, e):
            stats["slot BNW emptied (kept PR script)"] += 1   # the PR's own fights still field the vanilla monster
            continue
        if SNES_AI:
            # every monster runs its WC script in the plugin, but bosses whose PR battle events need
            # the PR's own AI (modes, variables they read, other fights' entrances) keep it for now
            sid = int(vmo[e + 1]["script_id"])
            vname = scripts[sid]["script_name"] if sid in scripts.rows else None
            vdoc = ai_corpus.load_pr(vname) if vname else None
            if is_boss[e]:
                why = bosses.snes_reason(e, vdoc, replaced) if SNES_AI_STATUS else bosses.reason(e, vdoc, ab)[0]
                if why:
                    boss_kept[e] = why
                    continue
            # any monster (bosses checked above): a party whose PR battle routine decides who is on screen
            # (ENTRANCE_SCRIPTS: Chadarnook's sc_b_2016 switches its forms by NoSelectChad, Hidon's ghosts,
            # Air Force's bays...) keeps its earlier AI: WC's F5 would fight that routine
            # SNES battle events (F7) the fight handles another way: the PR's battle script plays the
            # intro (INTRO_SCRIPTS), or the plugin sets the PR mode a battle script reads (profile)
            events_ok = set(event_modes.get(e, {}))
            events_ok.update(n for s in bosses.party_scripts.get(e + 1, ()) for n in INTRO_SCRIPTS.get(s, ()))
            why = snes_ai_unsupported(bmain, bcounter, events_ok, e in profile_setting("snes_ai_formation_changes", {}))
            moves = any(op == "enemies" and not (args[1] in (1, 5) and args[2] == 0xFF)
                        for op, args in list(bmain) + list(bcounter))   # F5 other than "everyone dies"
            if why is None and moves:
                for name in sorted(bosses.party_scripts.get(e + 1, ())):
                    if name in ENTRANCE_SCRIPTS or name in bosses.adding:
                        if SNES_AI_STATUS:
                            # BNW: its script runs in the plugin all the same, its own bring-ins and hides
                            # left to the PR routine (as the compiled hybrids did: pr_entrances)
                            pr_entrances.add(e)
                        else:
                            why = f"battle event {name} decides who is on screen"
                        break
            if why is None:
                ctx = AC.Context(e, battle_ability(ab, vdoc), None)
                compiled[e] = (shim_script(ctx.battle), ctx)
                shimmed.add(e)
                stats["own script in the plugin"] += 1
                continue
            reasons[f"plugin can't yet: {why}"] += 1   # its previous AI (compiled, or the PR's own)
        if (vmain, vcounter) == (bmain, bcounter):
            stats["unchanged"] += 1
            continue
        if _S.blank_enemy(bnw, e) and not _S.blank_enemy(van, e):
            stats["slot BNW emptied (kept PR script)"] += 1
            continue
        sid = int(vmo[e + 1]["script_id"])
        vname = scripts[sid]["script_name"] if sid in scripts.rows else None
        vdoc = ai_corpus.load_pr(vname) if vname else None
        hybrid = False
        if is_boss[e]:
            why, hybrid = bosses.reason(e, vdoc, ab)
            if why:
                boss_kept[e] = why
                continue
        battle = battle_ability(ab, vdoc)
        special = port_specials.special_of(van, bnw, e, battle)   # its own special (a copy where BNW changed a shared one)
        ctx = AC.Context(e, battle, special, slots.get(e, {}), pr_entrances=hybrid)
        ctx.pr_events = {n for s in bosses.party_scripts.get(e + 1, ()) for n in INTRO_SCRIPTS.get(s, ())}
        ctx.formation_parties = formation_parties
        ctx.message_keys = battle_lines
        try:
            compiled[e] = (AC.compile_script(ctx, bmain, bcounter), ctx)
        except AC.Unsupported as ex:
            if is_boss[e]:
                boss_kept[e] = f"uses {ex}"
            else:
                stats["unsupported (kept PR script)"] += 1
                reasons[str(ex)] += 1

    # a boss only ever brought in by another fight (Chupon by Ultros) runs its mod script only when that
    # fight's monster does (else the PR's AI brings in its own)
    for e, by in profile_setting("snes_ai_brought_in", {}).items():
        if SNES_AI and e in shimmed and by not in shimmed:
            shimmed.discard(e)
            compiled.pop(e, None)
            stats["own script in the plugin"] -= 1
            boss_kept[e] = f"brought in by monster {by}, which keeps its earlier AI"

    # pass 2: a multi-part boss fight switches to BNW's AI only as a whole
    changed_bosses = {e for e in range(384) if is_boss[e] and A.script(van, e) != A.script(bnw, e)}
    while True:
        dropped = False
        for e in [e for e in compiled if is_boss[e]]:
            mates = {m - 1 for p in bosses.parties.get(e + 1, []) if not (SNES_AI and p in replaced)
                     for m in bosses.party_members(p)} - {e}
            blocking = sorted(m for m in mates if (is_boss[m] if SNES_AI else m in changed_bosses) and m not in compiled)
            if blocking:
                del compiled[e]
                boss_kept[e] = f"shares a fight with boss(es) {blocking} that keep the PR script"
                dropped = True
        if not dropped:
            break

    # pass 3: write
    for e in sorted(compiled):
        mnemonics, ctx = compiled[e]
        row = mo[e + 1]
        name = f"sc_ai_bnw_{e:03d}"   # the live slots the WC mod folder ships (wc_live.ai_files): shims too
        doc = {"SystemFlag": {"SkipInitialize": 0, "KeepPlayerPuppet": 0, "KeepBadStatusVisual": 0, "RidingVehicle": 0},
               "Segments": [{"Label": "Main", "EntryPoint": 0, "Count": len(mnemonics)}],
               "ScriptLocal": [], "ScriptLocalValue": [], "Mnemonics": mnemonics, "Animations": [],
               "Name": name + ".json", "Title": {"main": "", "sub": ""}}
        with open(os.path.join(dest_dir, name + ".json"), "w", encoding="utf-8") as f:
            f.write(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))   # dumps: the C encoder
        new_sid = 3000 + e
        scripts.rows[new_sid] = {"id": str(new_sid), "script_name": name}
        changed["monster_ai_script"].add(new_sid)
        if row["script_id"] != str(new_sid):
            row["script_id"] = str(new_sid)
            changed["monster"].add(e + 1)
        keys.append(name)
        values.append(f"{AI_PATH}/{name}")
        stats["compiled"] += 1
        stats["branches skipped"] += ctx.skipped
        if is_boss[e]:
            stats["bosses compiled"] += 1
            # a boss only brought in by another fight (Chupon) starts with its bringer's fight
            by = profile_setting("snes_ai_brought_in", {}).get(e)
            parties = bosses.parties.get(e + 1) or (bosses.parties.get(by + 1, []) if by is not None else [])
            boss_tests.append({"snes_id": e, "parties": parties, "hybrid": ctx.pr_entrances})
            if ctx.pr_entrances:
                stats["bosses compiled as hybrids"] += 1
    stats["boss (kept PR script)"] = len(boss_kept)
    # the PR's own copies of a monster (ids past 384, the original's name: Chaser's 551 in party 124)
    # that a formation's battles field: the original's shim, so the plugin runs its WC script
    copies = {}
    if SNES_AI:
        import re
        in_battles = set()
        mpt = tables.get("monster_party") or vmp_table()
        for f in range(576):
            for p in formation_parties(f):
                row = mpt.rows.get(p)
                if row:
                    in_battles.update(int(row[f"monster{k}"]) for k in range(1, 10) if row.get(f"monster{k}", "0") not in ("0", ""))
        # ...and the Coliseum's copies (profile snes_ai_coliseum_copies: the PR's ids for them, 500-611 in
        # vanilla): the SNES Coliseum runs the monster's own script, the PR gives each copy its own
        lo, hi = profile_setting("snes_ai_coliseum_copies", (0, -1))
        in_battles.update(range(lo, hi + 1))
        for c in sorted(x for x in in_battles if x > 384 and x in mo.rows):
            m = re.fullmatch(r"MSG_MON_NAME_(\d+)", mo[c]["mes_id_name"])
            e = int(m.group(1)) - 1 if m else -1
            if e in shimmed and e in compiled:
                copies[c] = e
                if mo[c]["script_id"] != mo[e + 1]["script_id"]:
                    mo[c]["script_id"] = mo[e + 1]["script_id"]
                    changed["monster"].add(c)
        if hi >= lo:
            col = [c for c in copies if lo <= c <= hi]
            log(f"  Coliseum copies on their regular's script: {len(col)} of {sum(1 for c in range(lo, hi + 1) if c in mo.rows)} "
                f"(the rest: a regular kept on the PR's AI, or no regular by name)")
    # every monster's SNES AI for the plugin's interpreter (the kit's SnesAiHost: WC's seeds, BNW's
    # bnw_data.json), which runs the mod's own scripts the way the SNES runs them (the user, 2026-11-12:
    # "please make all enemies/bosses behave like WC SNES"; 2026-11-19: BNW's too)
    sa = None
    if SNES_AI:
        sa = snes_ai_data(van, bnw, ab, vmo, scripts, tables.get("monster_party"), formation_parties, battle_lines)
    used = set(k for ks in (sa["message_keys"].values() if sa else []) for k in ks if k.startswith("BNW_BTL_"))
    for e in compiled:
        for m in compiled[e][0]:
            used.update(x for x in m["operands"].get("sValues", []) if x.startswith("BNW_BTL_"))
    port.battle_texts = {k: v for k, v in (battle_lines.texts.items() if battle_lines else []) if k in used}
    stats["battle lines"] = len(port.battle_texts)
    os.makedirs(os.path.join(out_dir, "monster_ai", "keys"), exist_ok=True)
    with open(os.path.join(out_dir, "monster_ai", "keys", "bnw_ai.json"), "w", encoding="utf-8") as f:
        json.dump({"keys": keys, "values": values}, f, indent=1)
    log(f"monster AI: {dict(stats)}; unsupported: {dict(reasons)}")
    log(f"  bosses compiled: {[(t['snes_id'], t['parties']) for t in boss_tests]}")
    for e, why in sorted(boss_kept.items()):
        log(f"  boss {e} kept PR script: {why}")
    port.boss_tests = boss_tests
    # BNW's story fights the PR has no event for (Kaiser, Kefka at the Sealed Gate): started from the PR's
    # own map scripts (port_boss_events; their parties are new_fights'). BNW's module, imported only for a
    # profile that asks (the kit repo doesn't carry it: repo_publish BNW_TOOLS)
    if SNES_AI and PROFILE is not None and getattr(PROFILE, "bnw_boss_events", False):
        import port_boss_events
        for name, ids in port_boss_events.port(out_dir, tables, log, PROFILE, bnw.data).items():
            changed.setdefault(name, set()).update(ids)
    if sa is None:
        sa = snes_ai_data(van, bnw, ab, vmo, scripts, tables.get("monster_party"), formation_parties)
    port.snes_ai = sa
    sa["plugin"] = sorted(e for e in shimmed if e in compiled)
    if pr_entrances:
        sa["pr_entrances"] = sorted(e for e in pr_entrances if e in shimmed)
    sa.update(getattr(port, "item_abilities", {}))
    sa["copies"] = copies
    log(f"  SNES AI for the plugin: {len(sa['scripts'])} scripts, {len(sa['message_keys'])} battle lines as the PR's text, "
        f"{len(sa['messages'])} of our own" + (f", no line for messages {sa['unmapped_messages']}" if sa['unmapped_messages'] else ""))
    return changed


def item_abilities(bnw, abt, tables, changed, taken=()):
    """{"item_use": {SNES item: ability}, "throws": {SNES item: ability}, "commands": {command: ability}}
    for every item WC's scripts use or throw (F6 00/01 i1 i2): Square's monster ability where it made one
    (by the weapon's power, the item's effect), else a row of our own from ITEM_ABILITY_BASE up."""
    import idmap as M
    used, thrown = set(), set()
    for e in range(384):
        main, counter = A.script(bnw, e)
        for op, args in list(main) + list(counter):
            if op == "item":
                (thrown if args[0] else used).update(args[1:3])
    content = tables.get("content") or P.Table("content")
    items = tables.get("item") or P.Table("item")
    weapons = tables.get("weapon") or P.Table("weapon")
    out = {"item_use": {}, "throws": {}, "commands": dict(CMD_ABILITY)}
    next_id = ITEM_ABILITY_BASE

    def new_row(base, **cols):
        nonlocal next_id
        while next_id in taken:   # another part of the port's rows (the specials' copies)
            next_id += 1
        aid = next_id
        next_id += 1
        if aid in P.Table("ability").rows:
            raise ValueError(f"item ability {aid} would overwrite an ability")
        row = dict(abt[base], id=str(aid), sort_id=str(aid), **cols)
        if abt.rows.get(aid) != row:
            abt.rows[aid] = row
            changed.add(aid)
        return aid
    for i in sorted(thrown):
        c = content.rows.get(M.item_content(i))
        w = weapons.rows.get(int(c["type_value"])) if c and c["type_id"] == "2" else None
        if not w:
            continue
        effect = THROW_EFFECT.get(w["category_type"], "1169")
        same = [a for a in SQUARE_THROWS if abt[a]["standard_value"] == w["attack"]]   # Square's powers are all different
        out["throws"][i] = same[0] if same else new_row(SQUARE_THROWS[0], standard_value=w["attack"], battle_effect_asset_id=effect)
    for i in sorted(used):
        c = content.rows.get(M.item_content(i))
        it = items.rows.get(int(c["type_value"])) if c and c["type_id"] == "1" else None
        if not it:
            continue
        cols = dict(system_id=it["system_id"], standard_value=it["standard_value"], battle_effect_asset_id=it["battle_effect_asset_id"],
                    battle_function_group_id=it["battle_function_group_id"], condition_group_id=it["condition_group_id"],
                    attribute_id=it["attribute_id"], accuracy_rate=it["accuracy_rate"], invalid_reflection=it["invalid_reflection"])
        sq = abt[SQUARE_ITEM_USE]
        out["item_use"][i] = SQUARE_ITEM_USE if all(sq[k] == v for k, v in cols.items()) else new_row(SQUARE_ITEM_USE, **cols)
    return out


def vmp_table():
    import prdata as P
    return P.Table("monster_party")


def party_slots(rom, mp, formations, members=None):
    """{PR party: [-1, SNES slot of cell 1, ..., of cell 9]} (-1: no SNES member there): each member of
    the party's SNES formation to the cell holding the same monster nearest its SNES position
    (port_encounters' placement), so the plugin's monster slots are the SNES ones (WC scripts aim at
    slots $30-$35, check them, and bring monsters in and out by slot masks). A formation's byte 1 is
    its shown-at-start mask: a member outside it starts hidden (13 vanilla formations: Air Force's Bit,
    Chupon, Flame Eater's balloons...) and the PR's parties mostly leave it out (Square brings it in
    with an AddEnemy ability: EventCommand.InBattleEnemy into a cell); it gets the free cell nearest
    its SNES position. members (filled if given): {party: [[SNES id, cell, shown at start, the PR
    party lists it] or None for each slot 0-5]}."""
    import port_encounters as E
    out = {}
    for p, f in formations.items():
        row = mp.rows.get(p)
        if not row:
            continue
        raw = rom.data[E.FORMATIONS + 15 * f:E.FORMATIONS + 15 * f + 15]
        ids = [raw[2 + s] | ((raw[14] >> s & 1) << 8) for s in range(6)]
        pos = [(raw[8 + s] >> 4, raw[8 + s] & 15) for s in range(6)]
        shown = [s for s in range(6) if raw[1] >> s & 1]
        hidden = [s for s in range(6) if not raw[1] >> s & 1 and ids[s] not in (0x1FF, 0xFF)]
        listed = {k: int(row[f"monster{k}"]) - 1 for k in range(1, 10) if row.get(f"monster{k}", "0") not in ("0", "")}
        free = dict(listed)
        m = [-1] * 10
        mem = [None] * 6

        def near(cells, s):
            x, y = pos[s]
            return min(cells, key=lambda c: (E.CELL_XY[c][0] - x) ** 2 + (E.CELL_XY[c][1] - y) ** 2)
        for s in sorted(shown, key=lambda t: (-pos[t][0], pos[t][1])):
            cand = [k for k, v in free.items() if v == ids[s]]
            if not cand:
                continue
            k = near(cand, s)
            m[k] = s
            mem[s] = [ids[s], k, 1, 1]
            del free[k]
        for s in sorted(hidden, key=lambda t: (-pos[t][0], pos[t][1])):
            cand = [k for k, v in free.items() if v == ids[s]]
            if cand:                               # the PR lists it (spawned at the start: hidden by the plugin)
                k = near(cand, s)
                del free[k]
                mem[s] = [ids[s], k, 0, 1]
            else:                                  # brought in when its script shows it
                empty = [c for c in range(1, 10) if c not in listed and m[c] < 0]
                if not empty:
                    continue
                k = near(empty, s)
                mem[s] = [ids[s], k, 0, 0]
            m[k] = s
        if any(x >= 0 for x in m):
            out[p] = m
            if members is not None:
                members[p] = mem
    return out


_AI_OPCODES = {v: k for k, v in A.NAMES.items()}


def _ai_bytes(ops):
    """A parsed AI section (snes_ai.parse) back to its bytes."""
    return b"".join(bytes(args) if name == "attack" else bytes([_AI_OPCODES[name]]) + bytes(args) for name, args in ops)


def snes_ai_data(van, bnw, ab, vmo, scripts, mp=None, resolver=None, battle_lines=None):
    """{scripts: {SNES id: hex of its main and counter sections}, battle/special: {SNES id: PR ability
    of its Battle (0xEE) / special (0xEF)}, attacks: [PR ability for each SNES attack index, 0 = none],
    messages: {message index: [PR text lines]} for every "message" (F3) a script shows}.
    battle_lines (battle_text.Messages, a mod that ships its battle text: BNW): every line a script shows
    as the mod's own (story_mes keys BNW_BTL_...). The mod's engine: rules (SNES_AI_RULES), its attack ->
    command table where it differs from vanilla's (C2/1DD8), and with BNW's rules the monsters HP loss
    doesn't kill (boss_death: monster byte $12 bit 6, c2.asm BossDeath)."""
    import battle_text
    import idmap as M
    d = bnw.data
    out = {"version": SNES_AI_VERSION, "scripts": {}, "battle": {}, "special": {}, "messages": {},
           "attacks": [M.spell(i) or 0 for i in range(256)],
           "items": [M.item_content(i) or 0 for i in range(256)]}   # SNES item -> PR content id (F6, "if item used")
    shown = set()
    for e in range(384):
        # through snes_ai.script, so a profile's own script source (T-Edition's scripts past 3 MB) is the one
        # exported; its ops back to bytes give the same main + counter sections as the ROM's table
        main, counter = A.script(bnw, e)
        raw = _ai_bytes(main) + _ai_bytes(counter)
        out["scripts"][e] = raw.hex()
        i = 0
        while i < len(raw):
            if raw[i] == 0xF3 and i + 1 < len(raw):
                shown.add(raw[i + 1])
            i += A.SIZES.get(raw[i], 1)
        sid = int(vmo[e + 1]["script_id"])
        vname = scripts[sid]["script_name"] if sid in scripts.rows else None
        vdoc = ai_corpus.load_pr(vname) if vname else None
        battle = battle_ability(ab, vdoc)
        out["battle"][e] = battle
        out["special"][e] = port_specials.special_of(van, bnw, e, battle) or battle
    # battle lines: the PR's own (its text, in the player's language) where it has the line, else the
    # few short ones of our own; none from the ROM (the ROM-free generator ships no dialogue)
    out["message_keys"], out["unmapped_messages"] = {}, []
    for k in sorted(shown):
        if battle_lines is not None:
            keys = battle_lines(k)
            if keys:
                out["message_keys"][k] = keys
            else:
                out["unmapped_messages"].append(k)
        elif k in battle_text.PR_KEYS:
            out["message_keys"][k] = battle_text.PR_KEYS[k]
        elif k in battle_text.OWN_TEXT:
            out["messages"][k] = battle_text.OWN_TEXT[k]
        else:
            out["unmapped_messages"].append(k)
    # monsters' weak elements (byte $19 of their data: "if weak to element", FC 1A) and the SNES
    # formation each PR party stands for ("if this battle is formation n", FC 1B)
    import ff6snes as S
    out["weak"] = {e: x.raw[0x19] for e, x in enumerate(S.enemies(bnw)[:384]) if len(x.raw) > 0x19 and x.raw[0x19]}
    out["formations"] = {p: f for p, f in M.party_formation().items() if p}
    if resolver:   # every party a formation's battles use (the PR's copies, the porter's own)
        for f in range(576):
            for p in resolver(f):
                out["formations"].setdefault(p, f)
    if profile_setting("snes_ai_event_formations", False):
        # the story's fights: the formation the mod's own event calls there (its scripts check it: FC 1B,
        # and its slots are what they aim at and bring in: BNW renumbered its boss formations)
        out["formations"].update(event_formations(van, bnw, mp or P.Table("monster_party")))
    modes = {e: {ev: m for ev, m in evs.items() if m} for e, evs in profile_setting("snes_ai_events", {}).items()}
    if any(modes.values()):
        out["event_modes"] = {e: m for e, m in modes.items() if m}
    for key in ("pr_ends", "zero_hp_wait", "start_shows"):
        v = sorted(profile_setting("snes_ai_" + key, []))
        if v:
            out[key] = v
    # the SNES's battle event bits a mod's scene reads after the fight (BNW's Dadaluma: fed Dried Meat, he
    # leaves a Hell Claw, CA/96A9 -> ED/8E09 "if battle bit 4F"): the battle's vars $04-$17 hold $1DC9-$1DDC
    # (C2/2437 copies them in, C2/49D7 back out), so bit n is var 4 + n / 8, mask 1 << n % 8. Each gets a PR
    # flag (the mod's FlagAlloc file, keyed 0x1000 + n: story bits stay below 0x1000) the host reads at the
    # fight's start and writes when a script changes it; the PR's after-battle script branches on it.
    bits = profile_setting("snes_ai_event_bits", ())
    if bits:
        import event_translate as T
        path = profile_setting("snes_event_alloc")
        assert path, "snes_ai_event_bits needs the profile's snes_event_alloc (its FlagAlloc file)"
        alloc = T.FlagAlloc(path if os.path.isabs(path) else os.path.join(P.ROOT, path))
        out["event_bits"] = [[4 + n // 8, 1 << n % 8, *alloc.get(0x1000 + n)] for n in sorted(bits)]
        alloc.save()
    out["party_members"] = {}
    out["party_slots"] = party_slots(bnw, mp or P.Table("monster_party"), out["formations"], out["party_members"])
    if SNES_AI_RULES != "vanilla":
        out["rules"] = SNES_AI_RULES
    table = list(d[CMD_TABLE:CMD_TABLE + 22])
    if table != list(van.data[CMD_TABLE:CMD_TABLE + 22]):
        out["command_table"] = table
    if SNES_AI_RULES == "bnw":
        out["boss_death"] = [e for e, x in enumerate(S.enemies(bnw)[:384]) if len(x.raw) > 0x12 and x.raw[0x12] & 0x40]
    return out


CMD_TABLE = 0x021DD8   # GetCmdForAI's ranges: 11 first attacks, then their 11 commands


NEW_FIGHT_BASE = 8000


def new_fights(van, bnw, tables, log):
    """Parties for the mod's fights the PR has none for (profile snes_ai_new_fights {formation: template
    party}): 8000 + formation, the formation's monsters on the template party's look (background, music,
    battle script, escape), so an event can start the fight (BNW's Kaiser, formation 0x19a, its
    post-game superboss: CB/52C5 calls pack 0x9A; Kefka with two Centurions, 0x179: CB/3ADC, pack 0x79,
    where vanilla had only an event battle). Which PR event starts them is the events' side."""
    import port_encounters as E
    plan = profile_setting("snes_ai_new_fights", {})
    if not plan:
        return set()
    # formations whose template is the same fight (its monsters in its slots): they keep the template's
    # battle routine and escape type (BNW's Stooges, 346 on 461: sc_b_2028's "dream brothers" system call
    # puts them on stage; without it they stood at 0 HP and the battle never left its opening)
    keep = set(profile_setting("snes_ai_new_fights_keep_routine", ()) or ())
    mp = tables.setdefault("monster_party", P.Table("monster_party"))
    porter = E.EncounterPorter(van, bnw, tables, log)
    made = set()
    for f, template in sorted(plan.items()):
        pid = NEW_FIGHT_BASE + f
        if pid in P.Table("monster_party").rows:
            raise ValueError(f"new fight party {pid} would overwrite one of the game's")
        row = porter.party_row(f, mp[template], pid)
        if f not in keep:
            row["script_name"] = "0"   # the look only: none of the template fight's battle routine
            row["not_escape"] = "2" if any(bnw.data[0x0F0000 + 32 * e + 19] & 0x08 for e, _, _ in E.formation(bnw, f)) else row["not_escape"]
        mp.rows[pid] = row
        made.add(pid)
        log(f"  new fight: formation {f:#x} as party {pid} ({'party ' + str(template) + ', its routine kept' if f in keep else 'look of party ' + str(template)})")
    return made


def event_formations(van, bnw, mp, log=None):
    """{PR party: the mod's formation for that story fight} where it isn't the party's own number - 1.
    The PR's event scripts start their battles by party (vanilla's formation + 1); the SNES events call
    two-formation packs, and the mod's pack entry at the same place (port_events' anchors) holds its
    formation there: BNW keeps Vargas and his bears but as formation 0x142 (vanilla's 435), the Whelk
    as 0x140... (their scripts check that number, FC 1B, and aim at its slots). A party port_events
    made for BNW's line-up (7000 + party) gets the same. Kept only when the party's monsters are all in
    it; then a boss party no event pack names gets the one formation holding exactly its monsters, and
    the profile's snes_ai_formations override both."""
    import port_events as EV
    from collections import defaultdict
    import idmap as M
    pf = M.party_formation()
    anchors = EV.anchored_packs(van, bnw)
    entries = defaultdict(list)
    for p in range(256):
        for i, f in enumerate(EV.pack2(van, p)):
            entries[f].append((p, i))

    def ids(rom, f):
        return [e for e, _ in EV.slots(rom, f) if e != 0xFF]

    def members(row):
        return [int(row[f"monster{k}"]) - 1 for k in range(1, 10) if row.get(f"monster{k}", "0") not in ("0", "")]
    out = {}
    for party in sorted(EV.event_battles()):
        fv, row = pf.get(party), mp.rows.get(party)
        if fv is None or row is None:
            continue
        cands = sorted({EV.pack2(bnw, p)[i] for p, i in entries.get(fv, []) if p in anchors})
        cands = [f for f in cands if ids(bnw, f)]
        if len(cands) != 1 or cands[0] == fv:
            continue
        f = cands[0]
        if set(members(row)) <= set(ids(bnw, f)):
            out[party] = f
        if EV.EVENT_PARTY_BASE + party in mp.rows:
            out[EV.EVENT_PARTY_BASE + party] = f
    vmo = P.Table("monster")
    for party, fv in pf.items():
        row = mp.rows.get(party)
        if party in out or row is None or party > 576:
            continue
        mem = members(row)
        if not mem or not any(m < 384 and vmo[m + 1]["boss"] != "0" for m in mem) or set(mem) <= set(ids(bnw, fv)):
            continue
        exact = [f for f in range(576) if sorted(ids(bnw, f)) == sorted(mem)]
        if len(exact) == 1:
            out[party] = exact[0]
    out.update({NEW_FIGHT_BASE + f: f for f in profile_setting("snes_ai_new_fights", {})})
    out.update(profile_setting("snes_ai_formations", {}))
    return out
