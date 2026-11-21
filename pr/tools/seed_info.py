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
import kitpath  # noqa: E402,F401  (the modding kit's tools, when it's this repository's kit/ submodule)
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


def monster_chests(van_path, rom_path):
    """The chests' battles a live seed leaves to the plugin: {"boxes": the SNES monster boxes' PR
    scripts (the port decides their battles: port_chests.box_scripts), "monster_chests": {PR chest
    flag: the PR party it fights} for chests the seed made monster boxes (the plugin empties the
    chest and starts the battle; a PR chest can't without a script)}."""
    import port_chests as PC
    van_rom, seed_rom = S.Rom(van_path), S.Rom(rom_path)
    vc, sc = PC.snes_chests(van_rom), PC.snes_chests(seed_rom)
    new_boxes = {k: c for k, c in sc.items() if c["type"] == PC.MONSTER and (k not in vc or vc[k]["type"] != PC.MONSTER)}
    flags = PC.match_flags(vc)
    out = {"boxes": PC.box_scripts(flags, vc)}
    if new_boxes:
        boxes = {}
        for k, c in new_boxes.items():
            for e in flags.get(k, []):
                if not e["script"]:
                    boxes[str(e["flag"])] = PC.miab_party(seed_rom, c["contents"])
        out["monster_chests"] = boxes
    return out
