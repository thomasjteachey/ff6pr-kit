"""What a randomizer's seed tells the plugin beyond its tables (any SNES FF6 randomizer on the US
1.0 layout: Worlds Collide's wc_seed.py, Beyond Chaos's bc_seed.py). Each reads the seed's ROM
bytes (ff6snes.rom_bytes: a file or the in-memory output) next to vanilla's and returns JSON-ready
PR ids for the seed's json (the kit's seed library reads them in the plugin).
"""
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import kitpath  # noqa: E402,F401  (the modding kit's tools, when it's this repository's kit/ submodule)
except ImportError:   # the kit repository alone has none (its tools are already on the path)
    pass
import prdata as P  # noqa: E402
import ff6snes as S  # noqa: E402


def coliseum(van_path, seed_path, hidden=lambda b: b != 0):
    """The seed's Coliseum (256 matches of 4 bytes at 0x1FB600, by wagered item: opponent, ?,
    reward, reward hidden) next to vanilla's, in PR ids: [wager content, vanilla party, vanilla
    reward, the seed's party (0: none), the seed's reward, hidden, the seed's monster] (PR monster
    = SNES enemy + 1) for each match the seed changed. The ROMs: paths or ff6snes.Rom objects.
    `hidden(byte 3)`: vanilla hides a reward at $FF (any nonzero); BNW's reversible_bets.asm turned
    byte 3 into the bet's tile and hides at $00 (its plugin data passes `lambda b: b == 0`)."""
    import idmap as M

    def table(src):
        d = src.data if hasattr(src, "data") else S.rom_bytes(src)
        return [d[0x1FB600 + 4 * i:0x1FB600 + 4 * i + 4] for i in range(256)]

    def content(i):
        try:
            return M.item_content(i) if i != 0xFF else 0
        except Exception:  # noqa: BLE001 - items the PR doesn't have
            return 0

    # the PR fights a Coliseum party (ids 1000+), each one Coliseum copy of a regular monster
    # (monster 500+, same name key): SNES enemy e -> PR monster e + 1 -> its Coliseum party
    master = os.path.join(P.VANILLA, "master", "Assets", "GameAssets", "Serial", "Data", "Master")
    key = {int(r["id"]): r["mes_id_name"] for r in csv.DictReader(open(os.path.join(master, "monster.csv"), encoding="utf-8"))}
    party_of_key, alone = {}, {}
    with open(os.path.join(master, "monster_party.csv"), encoding="utf-8") as f:
        rows = csv.reader(f)
        head = next(rows)
        cols = [i for i, h in enumerate(head) if re.fullmatch(r"monster\d", h)]
        for r in rows:
            ms = [int(r[i]) for i in cols if int(r[i]) > 0]
            if len(ms) != 1:
                continue
            if int(r[0]) >= 1000 and key.get(ms[0]):
                party_of_key.setdefault(key[ms[0]], int(r[0]))
            elif int(r[0]) < 1000:
                alone.setdefault(ms[0], int(r[0]))      # a regular battle with that monster alone

    def party(enemy):
        # its Coliseum party, else a regular one-monster battle with it, else 0 (the game's own stays)
        return party_of_key.get(key.get(enemy + 1)) or alone.get(enemy + 1, 0)

    out = []
    for wager, (v, w) in enumerate(zip(table(van_path), table(seed_path))):
        if v == w or wager == 0xFF:
            continue
        wc = content(wager)
        if wc <= 0:
            continue
        out.append([wc, party(v[0]), content(v[2]), party(w[0]), content(w[2]), int(bool(hidden(w[3]))), w[0] + 1])
    return out


def magitek(rom_path):
    """The characters dealt MagiTek (SNES command 29) as a command (PR status ids): the plugin lists
    and allows the PR's Magitek (26) for them anywhere; the port gave them one slot."""
    return [c.id + 1 for c in S.characters(S.Rom(rom_path))[:14] if 29 in c.commands]


def esper_bonus(van_path, rom_path):
    """The espers' level-up bonuses (SNES esper byte 10: 0-16, 0xFF none) by PR magicite content
    id: vanilla's, and the seed's where it differs; the plugin answers the PR's bonus lookups."""
    import idmap as M
    d = S.rom_bytes(rom_path)
    van_bonus = [r[10] for r in S.Rom(van_path).table(*S.ESPERS)]
    at, size, count = S.ESPERS
    return {"vanilla": [[M.esper_content(e), van_bonus[e]] for e in range(count)],
            "seed": [[M.esper_content(e), d[at + size * e + 10]] for e in range(count)
                     if d[at + size * e + 10] != van_bonus[e]]}


def command_weapons(van_path, rom_path):
    """The weapons that allow Runic / Bushido (SNES weapon byte 19 bit 7 / bit 1): PR weapon
    content ids, vanilla's and the seed's (the plugin sets the PR's two lists)."""
    import idmap as M
    seed_rom = S.Rom(rom_path)
    van_rom = S.Rom(van_path)
    return {cmd: {k: [x["content_id"] for x in M.select_equipment(M.equipment(r), ("bit", 19, bit), M.equipment_content_ids())]
                  for k, r in (("vanilla", van_rom), ("seed", seed_rom))}
            for cmd, bit in (("runic", 7), ("bushido", 1))}


def pack_formation(rom, pack):
    """An event pack's (a monster-in-a-box's contents) first formation, as port_chests.miab_party reads it."""
    import port_chests as PC
    return int.from_bytes(rom.b(PC.PACK2 + 4 * pack, 2), "little") & 0x7FFF


def reroll_box(rom, pack, pools, key, good=None, seed_dir=None):
    """Another pack for a box whose pack is blank (blank_formation): one of its tier's pool (pools["boss"] if it
    holds the pack, else pools["noboss"]) whose formation isn't blank, picked by key (a string: the same key, the
    same pick). None if that tier has none. good: {tier: its packs that aren't blank}, filled here (a cache);
    seed_dir: blank_formation's (the seed's own monster tables)."""
    import random
    tier = "boss" if pack in pools.get("boss", ()) else "noboss"
    good = {} if good is None else good
    if tier not in good:
        good[tier] = [p for p in pools.get(tier, ()) if not blank_formation(rom, pack_formation(rom, p), seed_dir)]
    return random.Random(key).choice(good[tier]) if good[tier] else None


def monster_chests(van_path, rom_path, seed_dir=None, log=None, make_missing=False, pools=None):
    """The chests' battles a live seed leaves to the plugin: {"boxes": the SNES monster boxes' PR
    scripts (the port decides their battles: port_chests.box_scripts), "monster_chests": {PR chest
    flag: the PR party it fights} for chests the seed made monster boxes (the plugin empties the
    chest and starts the battle; a PR chest can't without a script)}.
    seed_dir: the seed folder (its full monster_party.csv): a box whose formation's PR party runs a
    story battle script (BOX_SCRIPTS; party 490's sc_b_0115: Shadow's chase scene, then a forced
    exit) fights a plain party with the same monsters instead (chest_parties); a boss's mechanics
    (the Whelk's, Ultros's, the Phantom Train's) stay.
    make_missing (with seed_dir): a box whose formation has no PR party (the PR dropped ~40 SNES
    formations: BC's NP seed 9859608359 put one in chest 207, party 507) fights a party made from
    the seed's formation (port_encounters' party_for) on its map's battle look; without it, logged.
    pools: the randomizer's box pools by tier, {"boss": [event packs], "noboss": [...]} (Worlds Collide's -chrm:
    wc_seed.box_pools): a box whose pack is blank (blank_formation: no monster, or only the PR's nameless event
    dummies; WC's pool holds its "Empty" packs) fights another pack of the same tier (reroll_box), picked by the
    seed's bytes and the chest's flag, logged (the coordinator's rule, 2026-11-21: match the SNES where the fight
    is real, reroll where it isn't)."""
    import hashlib
    import port_chests as PC
    van_rom, seed_rom = S.Rom(van_path), S.Rom(rom_path)
    vc, sc = PC.snes_chests(van_rom), PC.snes_chests(seed_rom)
    new_boxes = {k: c for k, c in sc.items() if c["type"] == PC.MONSTER and (k not in vc or vc[k]["type"] != PC.MONSTER)}
    flags = PC.match_flags(vc)
    out = {"boxes": PC.box_scripts(flags, vc)}
    log = log or (lambda m: None)
    if new_boxes:
        boxes, forms, maps, rerolled, good = {}, {}, {}, [], {}
        key = hashlib.sha1(bytes(seed_rom.data)).hexdigest() if pools else ""
        for k, c in new_boxes.items():
            for e in flags.get(k, []):
                if not e["script"]:
                    flag, pack = str(e["flag"]), c["contents"]
                    if pools and blank_formation(seed_rom, pack_formation(seed_rom, pack), seed_dir):
                        new = reroll_box(seed_rom, pack, pools, f"{key}:{flag}", good, seed_dir)
                        if new is not None:
                            rerolled.append(f"chest {flag}: pack {pack} ({pack_formation(seed_rom, pack):#x}) -> "
                                            f"{new} ({pack_formation(seed_rom, new):#x})")
                            pack = new
                    boxes[flag] = PC.miab_party(seed_rom, pack)
                    forms[flag] = pack_formation(seed_rom, pack)
                    maps[flag] = os.path.basename(os.path.dirname(e["file"]))
        if rerolled:
            log(f"monster chests: blank packs rerolled from their tier's pool: {', '.join(rerolled)}")
        if seed_dir:
            make = party_maker(van_rom, seed_rom, forms, maps, seed_dir) if make_missing else None
            boxes = chest_parties(boxes, forms, seed_dir, log or (lambda m: None), make)
        out["monster_chests"] = boxes
    return out


# Every PR battle script a SNES formation's party runs (idmap.party; port_ai's pr/vanilla/battle_script read
# by hand, 2026-11-21), as a monster-in-a-box: "keep" = the fight's own mechanics (it needs them: who comes on,
# splits, flees, timers), lines and all; "story" = a story scene or a scripted end (a character joins or
# changes, a forced exit after the scene), which a box fights without (chest_parties: a plain party).
BOX_SCRIPTS = {
    "sc_b_0239": ("keep", "the ordinary one (~400 parties): Gau's Veldt leap, Shadow leaving, the cursed shield"),
    "sc_b_2024": ("keep", "ordinary (Holy Dragon, the Level N Magic sets)"),
    "sc_b_2026": ("keep", "ordinary: the battle ends on the party's state, Possess leaves (the PR's own boxes)"),
    "sc_b_timer": ("keep", "a field timer's battle: it ends when the timer runs out (the PR's own boxes)"),
    "sc_b_2015": ("keep", "the Angler Whelk's (Presenter's) head (the PR's own box)"),
    "sc_b_2000": ("keep", "the Behemoth King's entrance"),
    "sc_b_2001": ("keep", "Number 024 (no commands)"),
    "sc_b_2004": ("keep", "the Opinicus Fish bring more fish"),
    "sc_b_2006": ("keep", "sc_b_0239 plus Goetia's check"),
    "sc_b_2007": ("keep", "an entrance (port_ai.ENTRANCE_SCRIPTS)"),
    "sc_b_2008": ("keep", "sc_b_0239 plus the Flans splitting (BattleAddEnemy)"),
    "sc_b_2009": ("keep", "Ifrit and Shiva taking turns"),
    "sc_b_2010": ("keep", "Number 128's arms coming back"),
    "sc_b_2013": ("keep", "the Air Force's bays"),
    "sc_b_2016": ("keep", "Chadarnook's switch"),
    "sc_b_2018": ("keep", "the Fiend's counters"),
    "sc_b_2019": ("keep", "Nelapa's Doom and timer"),
    "sc_b_2020": ("keep", "Hidon's Erebus"),
    "sc_b_2021": ("keep", "Inferno's parts"),
    "sc_b_2023": ("keep", "Deathgaze's HP kept between fights"),
    "sc_b_2025": ("keep", "the Phantom Train running"),
    "sc_b_2027": ("keep", "sc_b_0239 plus the Chasers coming back (BattleAddEnemy)"),
    "sc_b_2028": ("keep", "the Dream Stooges"),
    "sc_b_2029": ("keep", "the Tentacles"),
    "sc_b_0011": ("keep", "the Whelk: Biggs and Wedge's warning about its shell, then the fight"),
    "sc_b_0086": ("keep", "the Tunnel Armor: Celes's Runic tip, an ATB reset"),
    "sc_b_0592": ("keep", "Ultima Weapon's opening lines"),
    "sc_b_0709_1": ("keep", "Humbaba fleeing after its breath"),
    "sc_b_0939": ("keep", "Wrexsoul possessing a character"),
    "sc_b_0977": ("keep", "Ultima Buster's opening lines"),
    "sc_b_0115": ("story", "Kefka at the Imperial camp: Shadow's chase, then out of the battle"),
    "sc_b_0065": ("story", "Ultros at the river: kept story-free in chests: its scene targets characters a chest party may "
                           "lack (PlayBattleEffect on Terra/Edgar/Sabin/Banon), then a forced exit; revisit with a save fixture "
                           "(BC lead, 2026-11-21)"),
    "sc_b_0017": ("story", "Terra's memory of Kefka burning soldiers, then out"),
    "sc_b_0036": ("story", "Terra's magic at Figaro: the party's talk, Terra fainting"),
    "sc_b_0055": ("story", "Vargas: Sabin joins mid-battle, the Blitz lesson, a scripted end"),
    "sc_b_0067": ("story", "Locke takes the Merchant's clothes (his look changes)"),
    "sc_b_0071": ("story", "Locke takes the Cadet's clothes (his look changes)"),
    "sc_b_0460_1": ("story", "Kefka at the sealed gate: Terra joins, then out"),
    "sc_b_0547": ("story", "Ultros in the Esper Cave: Relm joins, then out"),
    "sc_b_0555_1": ("story", "Kefka kills Leo: Gestahl and Kefka join, then out"),
    "sc_b_0555_2": ("story", "Kefka takes the magicite, then out"),
    "sc_b_2022": ("story", "the final battle's tiers: rounds 2-4, party changes, Kefka descends"),
}


def plain_box_scripts():
    """Battle scripts (names) a monster-in-a-box may run: BOX_SCRIPTS' "keep" ones and every script the
    PR's own boxes run. A script not in the table (a mod's own) counts as a story one."""
    import port_chests as PC
    mp = P.Table("monster_party").rows
    names = _script_names()
    out = {k for k, (role, _) in BOX_SCRIPTS.items() if role == "keep"}
    for parties in PC.miab_scripts().values():
        for p in parties:
            if p in mp and mp[p]["script_name"] not in ("", "0"):
                out.add(names.get(mp[p]["script_name"], ""))
    out.discard("")
    return out


_names = None


def _script_names():
    global _names
    if _names is None:
        with open(os.path.join(P.MASTER, "script.csv"), encoding="utf-8") as f:
            _names = {r[0]: r[1] for r in csv.reader(f)}
    return _names


_monster_names = None


def blank_formation(rom, f, seed_dir=None):
    """A formation with no real monster: none at all (0x1f8), or only blank ones. A monster is real when it has a
    picture (monster.monster_asset_id other than the PR's empty 1) or a name in system_en, in the seed's own tables
    (seed_dir: its monster.csv; Beyond Chaos's porter draws the PR's nameless 311, SNES Colossus, on another
    monster's shape) else vanilla's (the PR's event dummies 367-384, and 311: blank). seed_info won't make a party
    for a blank formation (party_maker); a randomizer rerolls it from its own pool (the coordinator's rule for WC's
    -chrm, 2026-11-21)."""
    import re
    import idmap as M
    import port_encounters as E
    global _monster_names
    if _monster_names is None:
        text = P.messages("system", "en")
        _monster_names = {i: re.sub(r"<[^>]*>", "", text.get(r["mes_id_name"], "")).strip()
                          for i, r in P.Table("monster").rows.items()}
    rows = None
    path = os.path.join(seed_dir, *"master/Assets/GameAssets/Serial/Data/Master".split("/"), "monster.csv") if seed_dir else ""
    if path and os.path.exists(path):
        with open(path, encoding="utf-8", newline="") as fh:
            rows = P.Table("monster", fh.read()).rows
    if rows is None:
        rows = P.Table("monster").rows

    def real(m):
        r = rows.get(m)
        return bool(_monster_names.get(m)) or (r is not None and r["monster_asset_id"] not in ("", "0", "1"))
    return not any(real(M.monster(e)) for e, _, _ in E.formation(rom, f))


def party_maker(van_rom, seed_rom, forms, maps, seed_dir=None):
    """make(flag, table) for chest_parties: a party for the seed's formation forms[flag] (port_encounters'
    party_for, its layout and ids), on the look of the chest map's random encounters (maps[flag]: the
    map's folder name; else party 1's), with no battle script. None for a formation with no real monster
    (blank_formation: the caller's randomizer rerolls those)."""
    import port_chests as PC
    porter = []

    def make(flag, table):
        import port_encounters as E
        from collections import Counter
        if blank_formation(seed_rom, forms[flag], seed_dir):
            return None
        if not porter:
            porter.append(E.EncounterPorter(van_rom, seed_rom, {"monster_party": table}, lambda m: None))
            porter[0].stats = Counter()
        look = table.rows.get(PC.map_party(maps.get(flag, "")) or 0) or table.rows[1]
        return porter[0].party_for(forms[flag], dict(look, script_name="0"))
    return make


def chest_parties(boxes, forms, seed_dir, log, make=None):
    """{flag: party} with every party whose battle script isn't a box's (plain_box_scripts) moved
    to a plain one: the seed's party with the same monsters and a plain script, else a copy with no
    script (port_encounters' next id for its formation), added to the seed's monster_party.csv.
    A party with no row: make(flag, table) -> a new party id (or None: kept, logged)."""
    import port_encounters as E
    path = os.path.join(seed_dir, *"master/Assets/GameAssets/Serial/Data/Master".split("/"), "monster_party.csv")
    if not os.path.exists(path):
        return boxes
    with open(path, encoding="utf-8", newline="") as f:
        table = P.Table("monster_party", f.read())
    rows, names, plain = table.rows, _script_names(), plain_box_scripts()

    def ok(row):
        return row["script_name"] in ("", "0") or names.get(row["script_name"]) in plain
    out, made, moved, missing = {}, {}, [], []
    vanilla = None
    for flag, party in boxes.items():
        row = rows.get(party)
        if row is None:
            new = make(flag, table) if make else None
            out[flag] = new if new is not None else party
            missing.append(f"{party} (formation {forms[flag]:#x}, chest {flag})" + (f" -> {new}" if new is not None else ""))
            continue
        if ok(row):
            out[flag] = party
            continue
        if party not in made:
            want = E.party_members(row)
            same = next((pid for pid, r in sorted(rows.items()) if pid not in made.values() and ok(r)
                         and E.party_members(r) == want and r["battle_background_asset_id"] == row["battle_background_asset_id"]), None)
            if same is None:
                if vanilla is None:
                    vanilla = P.Table("monster_party").rows
                same = E.next_party_id(forms[flag], rows, vanilla)
                rows[same] = dict(row, id=str(same), script_name="0")
            made[party] = same
            moved.append(f"{party} ({names.get(row['script_name'], row['script_name'])}) -> {same}")
        out[flag] = made[party]
    if moved or any(out[k] != boxes[k] for k in out):
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(table.to_csv(rows.keys()))
    if moved:
        log(f"monster chests: off story battle scripts: {', '.join(moved)}")
    if missing:
        log(f"monster chests: parties with no row{' (made from the formation)' if make else ''}: {', '.join(missing)}")
    return out
