"""Port elemental properties, status immunities/protections and auto-statuses
for enemies and equipment. A PR group is only rebuilt when BNW's SNES bytes
differ from vanilla's, so the PR's own quirks survive everywhere else."""
from collections import Counter

import ff6snes as S
import groups as G
import idmap as M
import prdata as P

ELEM_ATTR = [1, 2, 3, 6, 8, 7, 4, 5]  # SNES element bit -> PR attribute id (fire ice bolt poison wind holy earth water)
ABSORB, NULL, HALF, WEAK = "4", "3", "2", "1"

# SNES status bit (0-15: status bytes 1-2) -> PR condition ids blocked/immune
PROTECT = {0: [9, 89], 1: [15], 2: [10, 88], 4: [33], 5: [13], 6: [11], 7: [5, 50, 68, 72, 82],
           8: [14], 10: [19], 11: [6], 12: [18, 91], 13: [12], 14: [16, 90], 15: [7]}
ENEMY_IMMUNE = {0: [9], 1: [15], 2: [10, 85], 4: [33], 5: [13], 6: [11], 7: [5, 50, 68, 72, 82],
                8: [14], 10: [33], 11: [6], 12: [18], 13: [12], 14: [16], 15: [7],
                17: [20], 18: [25], 19: [21], 20: [26], 21: [22], 22: [23], 23: [24]}
# Equipment auto-status byte (8) bit -> condition id (learned from vanilla). 2 = Slow (25, status 3's
# Slow as in ENEMY_IMMUNE): no vanilla item has it, but the SNES keeps it on like the others (C2/26A0's
# permanent mask #$EE). 4 (Stop) isn't ported: vanilla sets it once at battle start (outside that mask),
# and Brave New World makes it a Stop block (its C1/8C2C never sets it, its mask is #$FE): counted.
AUTO_STATUS = {0: [17], 1: [20], 2: [25], 3: [21], 5: [22], 6: [23], 7: [92]}
# Equipment byte 25 (status byte 2, set at battle start) bit -> condition id, learned from vanilla
# (Cursed Shield, Thornlet, Mirage Vest; the Cursed Ring's Condemned is a Doom of its own, 75, which
# stays with that item). 1 (Near Fatal) and 7 (Sleep): no vanilla item has them, counted.
AUTO_STATUS2 = {0: [14], 2: [19], 3: [6], 4: [18], 5: [12], 6: [16]}
# Enemy initial statuses (learned): bits of bytes 27..30
ENEMY_INITIAL = {0: [89], 2: [88], 4: [33], 12: [91], 14: [90], 15: [7], 16: [96], 19: [95],
                 20: [26], 21: [94], 22: [93], 23: [92], 25: [113]}


def elem_set(pairs):
    """pairs: [(byte, type)] -> {(attr, type)}"""
    out = set()
    for byte, kind in pairs:
        for b in range(8):
            if byte >> b & 1:
                out.add((ELEM_ATTR[b], kind))
    return out


def cond_set(mask, table, nbits):
    return {(c, "1") for b in range(nbits) if mask >> b & 1 for c in table.get(b, [])}


def worn(raw):
    """Conditions an SNES item puts on its wearer: byte 8 (status 3) and byte 25 (status 2)."""
    return cond_set(raw[8], AUTO_STATUS, 8) | cond_set(raw[25], AUTO_STATUS2, 8)


def unported_worn(raw):
    """The bits of bytes 8 and 25 that worn() can't say: [(byte, bit)]."""
    return [(byte, b) for byte, table in ((8, AUTO_STATUS), (25, AUTO_STATUS2))
            for b in range(8) if raw[byte] >> b & 1 and b not in table]


STOP = 26   # the PR's Stop condition (ENEMY_IMMUNE's status-3 bit 4)


class ResistPorter:
    def __init__(self, van, bnw, tables, log, stop_block=False):
        """stop_block: the mod reads equipment byte 8 bit 4 as a Stop block, not vanilla's auto-Stop
        (Brave New World: its C1/8C2C never sets it, its mask is #$FE; White Cape and Ribbon "Block
        ... Stop"): such armor's resistance group gets Stop (profile.equip_stop_block)."""
        self.van, self.bnw, self.tables, self.log = van, bnw, tables, log
        self.stop_block = stop_block
        self.ag = G.GroupTable("attribute_group", "attribute_id", ["type_id"],
                               tables.setdefault("attribute_group", P.Table("attribute_group")))
        self.cg = G.GroupTable("condition_group", "condition_id", ["type_id"],
                               tables.setdefault("condition_group", P.Table("condition_group")))
        self.changed = {"monster": set(), "weapon": set(), "armor": set()}
        self.unknown = Counter()
        self.vanilla = {}

    def setv(self, table, rid, col, val):
        row = self.tables[table][rid]
        if row[col] != str(val):
            row[col] = str(val)
            self.changed[table].add(rid)

    def enemies(self):
        n = {"elements": 0, "immunity": 0, "initial": 0}
        for ev, eb in zip(S.enemies(self.van), S.enemies(self.bnw)):
            if S.blank_enemy(self.bnw, ev.id) and not S.blank_enemy(self.van, ev.id):
                continue                  # a slot BNW emptied keeps the PR's monster
            v, b, rid = ev.raw, eb.raw, ev.id + 1
            if v[23:26] != b[23:26]:
                gid = self.ag.find_or_create(elem_set([(b[23], ABSORB), (b[24], NULL), (b[25], WEAK)]))
                self.setv("monster", rid, "resistance_attribute", gid)
                n["elements"] += 1
            if v[20:23] != b[20:23]:
                gid = self.cg.find_or_create(cond_set(b[20] | b[21] << 8 | b[22] << 16, ENEMY_IMMUNE, 24))
                self.setv("monster", rid, "resistance_condition", gid)
                n["immunity"] += 1
            if v[27:30] != b[27:30]:  # byte 30 is special flags (Runic, Float...), not statuses
                gid = self.cg.find_or_create(cond_set(b[27] | b[28] << 8 | b[29] << 16, ENEMY_INITIAL, 24))
                self.setv("monster", rid, "initial_condition", gid)
                n["initial"] += 1
        self.log(f"enemy resistances: {n}")

    def wear(self, table, rid, iv, ib):
        """An armor or weapon row's wear conditions from the mod's bytes 8 and 25: their statuses (worn()),
        the relic conditions port_effects ports (CONDITION_BITS) and, for the same item, what the PR's own
        row has beyond the SNES bits (the Moogle Suit's 105; the Cursed Ring's Doom is its own 75, not 14).
        Statuses worn() can't say are counted. True if the row changed."""
        import port_effects as E
        v, b = iv.raw, ib.raw
        for byte, bit in unported_worn(b):
            if not v[byte] >> bit & 1:
                self.unknown[f"{table} byte {byte} bit {bit} (status worn)"] += 1

        def relic(raw):
            return {(c, "1") for c in E.EffectPorter.bit_conditions(raw)}
        want = worn(b) | relic(b)
        if iv.name.strip() == ib.name.strip():
            if table not in self.vanilla:
                self.vanilla[table] = P.Table(table)
            vrow = self.vanilla[table].rows.get(rid)
            have = self.cg.members(int(vrow["wear_condition_group_id"])) if vrow else frozenset()
            want = (want - (worn(v) - have)) | (have - worn(v) - relic(v))
        if want == self.cg.members(int(self.tables[table][rid]["wear_condition_group_id"])):
            return False
        self.setv(table, rid, "wear_condition_group_id", self.cg.find_or_create(want))
        return True

    def equipment(self):
        n = {"elements": 0, "protect": 0, "auto": 0, "weapon_element": 0}
        weapon_worn = 0
        for iv, ib in zip(S.items(self.van), S.items(self.bnw)):
            m = M.item(ib.id)
            if not m or m[0] == "item" or iv.type != ib.type:
                continue
            table, rid = m
            v, b = iv.raw, ib.raw
            if table == "weapon":
                if v[15] != b[15]:
                    attrs = [ELEM_ATTR[x] for x in range(8) if b[15] >> x & 1]
                    self.setv("weapon", rid, "attribute_id", attrs[0] if attrs else 0)
                    if len(attrs) > 1:
                        self.log(f"  weapon {ib.name}: multi-element {attrs}, kept first")
                    n["weapon_element"] += 1
                # status protection (bytes 6-7): the PR's weapons have no resistance column
                if v[6:8] != b[6:8]:
                    self.unknown["weapon status protection (no PR column)"] += 1
                # worn statuses (bytes 8, 25): the weapon's wear conditions, as armor's
                if (v[8], v[25]) != (b[8], b[25]):
                    weapon_worn += self.wear(table, rid, iv, ib)
                continue
            if (v[15], v[22], v[23], v[24]) != (b[15], b[22], b[23], b[24]):
                gid = self.ag.find_or_create(elem_set([(b[15], HALF), (b[22], ABSORB), (b[23], NULL), (b[24], WEAK)]))
                self.setv("armor", rid, "resistance_attribute", gid)
                n["elements"] += 1
            stop = self.stop_block and b[8] & 0x10
            if v[6:8] != b[6:8] or stop:
                conds = cond_set(b[6] | b[7] << 8, PROTECT, 16) | ({(STOP, "1")} if stop else set())
                gid = self.cg.find_or_create(conds)
                self.setv("armor", rid, "resistance_condition", gid)
                n["protect"] += 1
                if stop:
                    n["stop_block"] = n.get("stop_block", 0) + 1
            if (v[8], v[25]) != (b[8], b[25]):
                self.wear(table, rid, iv, ib)
                n["auto"] += 1
        self.log(f"equipment resistances: {n}")
        if weapon_worn:
            self.log(f"  weapons with the mod's worn statuses: {weapon_worn}")

    def port(self):
        self.enemies()
        self.equipment()
        out = dict(self.changed)
        out["attribute_group"] = self.ag.new_rows
        out["condition_group"] = self.cg.new_rows
        self.log(f"  new group rows: attribute {len(self.ag.new_rows)}, condition {len(self.cg.new_rows)}")
        if self.unknown:
            self.log(f"  not portable as data (need plugin): {dict(self.unknown.most_common())}")
        return out
