"""A mod's SNES random-battle rates, for the kit's encounter hook (plugin/PrKit/Ff6/SnesEncounters.cs,
SnesEncounterRules.Parse reads what rules() returns).

SNES (field/battle.asm CheckBattleWorld C0/C176, CheckBattleSub C0/C33?): a danger counter gains a rate
per step and a battle comes when a roll is below its high byte.
  * rates: C0/C29F (world maps) and C0/C2BF (other maps), 16 words each, [relics x 4 + code] (relics bit 0
    Charm Bangle, bit 1 Moogle Charm).
  * codes: other maps 2 bits per SNES map (CF/5880); world maps 2 bits per 32x32 zone and terrain group
    (CF/5800 World of Balance, CF/5840 World of Ruin; a zone's groups 0-3 at bits 7-6 .. 1-0). The group
    is the tile's battle background's (C0/C297 by background 0-7: grass 0, forest 1, desert 2, 3).
  * the roll (C0/C479): vanilla the field RNG's byte; Brave New World 4 + a random 0-232 (its C0/C48C:
    LDA #$E9, JSR $FF90 -> JSL C2/FBEA -> JSR C2/4B65, the battle RNG's 0..A-1; CLC, ADC #$04), so no
    battle comes before the danger's high byte passes 4: its "minimum of 10 steps between encounters".
  * the party (C0/C24B world, C0/C3E4 other maps): a random byte against 3 thresholds, vanilla $50/$A0/$F0
    (5/16, 5/16, 5/16, 1/16), BNW $50/$A0/$D0 (80/80/48/48 of 256): party_odds; port_encounters gives the
    PR's sets those weights.
PR: world maps keep the SNES's 256x256 cells and 8x8 zones (encount_grid.json: an area per cell;
attribute.json: the cell's ground, foot_information type 1-32). foot_groups() learns each ground's SNES
terrain group from vanilla: a cell's area set is one vanilla SNES pack (port_encounters.set_to_pack), and the
group of that pack in the cell's SNES zone is the ground's. Other maps: a PR map's monster set is one vanilla
pack, used by one or more SNES maps (a dungeon's floors); the mod's code of those maps.
"""
import json
import os
from collections import Counter, defaultdict

import prdata as P
import port_encounters as PE

WORLD_RATES, MAP_RATES = 0xC29F, 0xC2BF
WORLD_ZONES = {1: 0xF5800, 2: 0xF5840}
WORLD_PACKS = {1: 0xF5400, 2: 0xF5500}
MAP_CODES, MAP_PACKS, MAP_PROPS, MAPS = 0xF5880, 0xF5600, 0x2D8F00, 415
WORLD_ODDS, MAP_ODDS = (0xC24C, 0xC252, 0xC258), (0xC3E5, 0xC3EB, 0xC3F1)
VANILLA_ODDS = (80, 80, 80, 16)
PR_WORLDS = {1: 10010, 2: 10020}   # EncountAreaGridId 1/2: the PR's World of Balance / World of Ruin maps
NONE = -1                          # SnesEncounterRules.NoBattles


def words(rom, at, n=16):
    d = rom.data
    return [d[at + 2 * i] | d[at + 2 * i + 1] << 8 for i in range(n)]


def roll(rom):
    """(add, range): the battle roll is add + random byte x range / 256; vanilla (0, 256)."""
    d = rom.data
    code = d[0xC48C:0xC494]
    # BNW: LDA #range; JSR $FF90 (JSL C2/FBEA: JSR C2/4B65, the battle RNG's 0..A-1); CLC; ADC #add
    if code[0] == 0xA9 and code[2:5] == bytes((0x20, 0x90, 0xFF)) and code[5:7] == bytes((0x18, 0x69)) \
            and d[0xFF90:0xFF95] == bytes((0x22, 0xEA, 0xFB, 0xC2, 0x60)) and d[0x2FBEA:0x2FBEE] == bytes((0x20, 0x65, 0x4B, 0x6B)):
        return code[7], code[1]
    if code != bytes((0xBF, 0x00, 0xFD, 0xC0, 0x18, 0x6D, 0xA4, 0x1F)):
        raise ValueError(f"the battle roll at C0/C48C is neither vanilla's nor BNW's: {code.hex(' ')}")
    return 0, 256


def odds(rom, at):
    """The 4 parties' weights from the 3 CMP #thresholds; vanilla's unless the code is there (a ROM made
    from WC's ROM-free baseline, data/wc_base.bin, holds no field code)."""
    d = rom.data
    t = [d[a] for a in at]
    if any(d[a - 1] != 0xC9 for a in at) or not 0 < t[0] < t[1] < t[2] <= 255:
        return VANILLA_ODDS
    return (t[0], t[1] - t[0], t[2] - t[1], 256 - t[2])


def party_odds(rom):
    """{"world": (4 weights), "map": (4 weights)}: the parties' odds of 256 (vanilla 80/80/80/16)."""
    return {"world": odds(rom, WORLD_ODDS), "map": odds(rom, MAP_ODDS)}


def enabled(rom, m):
    return bool(rom.data[MAP_PROPS + 33 * m + 5] & 0x80)


def map_code(rom, m):
    return (rom.data[MAP_CODES + m // 4] >> (m % 4 * 2)) & 3


def unused_pack(rom, p):
    """A pack the mod keeps no battles in (BNW's pack 0: four empty formations, its unused places)."""
    return any(not PE.formation(rom, f) for f in PE.pack(rom, p))


def _map_dir(n):
    return os.path.join(P.VANILLA, f"map_{n}", "Assets", "GameAssets", "Serial", "Res", "Map", f"Map_{n}", f"Map_{n}")


def foot_groups(van, s2p=None):
    """{world: {PR ground type: SNES terrain group}}, learned from the PR's world maps and vanilla's packs
    (a cell whose set's pack sits in one group of its zone votes 1, in several 1/n each)."""
    s2p = s2p or PE.EncounterPorter(van, van, {}, lambda *a: None).set_to_pack()
    areas = {int(r["encount_area_grid_number"]): r for r in P.Table("encount_area")}
    out = {}
    for world, n in PR_WORLDS.items():
        d = _map_dir(n)
        with open(os.path.join(d, "encount_grid.json"), encoding="utf-8") as fh:
            cells = json.load(fh)["cells"]
        with open(os.path.join(d, "attribute.json"), encoding="utf-8") as fh:
            ground = json.load(fh)["layers"][0]["data"]
        votes = defaultdict(Counter)
        for i, cell in enumerate(cells):
            ft, row = ground[i], areas.get(int(cell))
            if row is None or not 1 <= ft <= 32:
                continue
            s = int(row[f"foot{ft:02d}_monster_set"])
            if s not in s2p:
                continue
            z = (i // 256 // 32) * 8 + (i % 256) // 32
            gs = [g for g in range(4) if van.data[WORLD_PACKS[world] + 4 * z + g] == s2p[s]]
            for g in gs:
                votes[ft][g] += 1.0 / len(gs)
        out[world] = {ft: min(v, key=lambda g: (-v[g], g)) for ft, v in sorted(votes.items())}
    return out


def set_codes(van, mod, s2p=None, log=print):
    """{PR monster set: the mod's code on the SNES maps of its vanilla pack} (0, normal, left out; NONE: the
    mod has no battles there). SNES maps the mod doesn't use (an empty pack) are left out unless all are."""
    s2p = s2p or PE.EncounterPorter(van, van, {}, lambda *a: None).set_to_pack()
    used = sorted({int(r["monster_set_id"]) for r in P.Table("map") if int(r["monster_set_id"]) > 0})
    out, mixed = {}, []
    for s in used:
        if s not in s2p:
            continue
        maps = [m for m in range(MAPS) if enabled(van, m) and van.data[MAP_PACKS + m] == s2p[s]]
        live = [m for m in maps if not (enabled(mod, m) and unused_pack(mod, mod.data[MAP_PACKS + m]))] or maps
        codes = Counter(map_code(mod, m) if enabled(mod, m) else NONE for m in live)
        if not codes:
            continue
        on = Counter({c: k for c, k in codes.items() if c != NONE})
        code = min(on, key=lambda c: (-on[c], c)) if on else NONE   # battles if any of its maps has them
        if len(codes) > 1:
            each = ", ".join(f"{m}:{map_code(mod, m) if enabled(mod, m) else 'off'}" for m in live)
            mixed.append(f"set {s} (SNES maps {each}) -> {code}")
        if code:
            out[s] = code
    if mixed:
        log(f"encounter rates: {len(mixed)} PR sets stand for SNES maps the mod rates differently: " + "; ".join(mixed))
    gained = [m for m in range(MAPS) if enabled(mod, m) and not enabled(van, m) and not unused_pack(mod, mod.data[MAP_PACKS + m])]
    if gained:
        log(f"encounter rates: SNES maps with random battles only in the mod (no PR set to give them): {gained}")
    return out


def rules(van, mod, name, log=print):
    """The mod's rules for SnesEncounterRules.Parse."""
    s2p = PE.EncounterPorter(van, van, {}, lambda *a: None).set_to_pack()
    add, rng = roll(mod)
    out = {
        "name": name,
        "world_rates": words(mod, WORLD_RATES),
        "map_rates": words(mod, MAP_RATES),
        "roll": {"add": add, "range": rng},
        "world_zones": {str(w): list(mod.data[a:a + 64]) for w, a in WORLD_ZONES.items()},
        "foot_group": {str(w): {str(f): g for f, g in fg.items()} for w, fg in foot_groups(van, s2p).items()},
        "set_codes": {str(s): c for s, c in set_codes(van, mod, s2p, log).items()},
        "party_odds": party_odds(mod),
    }
    zc = Counter((b >> (2 * (3 - g))) & 3 for w in (1, 2) for b in out["world_zones"][str(w)] for g in range(4))
    log(f"encounter rates ({name}): roll {add}-{add + rng - 1}, world codes {dict(sorted(zc.items()))}, "
        f"{len(out['set_codes'])} PR sets not normal ({dict(Counter(out['set_codes'].values()))}), party odds {out['party_odds']}")
    return out
