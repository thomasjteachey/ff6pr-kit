"""Item identity: the Pixel Remaster row and look each of a mod's item slots gets.

The porter maps SNES item slot s to a fixed PR row (idmap.item: weapons 0-89 -> weapon 2-91,
shields/helmets -> armor 5-46, ...). That holds for mods that keep FF6's item list (BNW, WC, BC). A
mod that rebuilt the list (T-Edition: 110 vanilla items in other slots, new items in freed slots,
weapons in shield and helmet slots, armor in relic slots) would put each item's data on a PR row with
another item's look (icon, battle sprite, equip slot), or on a row of the wrong table. This step
picks, for every slot of the mod:

  * its identity: the vanilla item it is (same kind and name: the PR's name, the SNES name, or a
    close spelling: "Mythril Claw" = "Mythril Claws"), or none (a new item);
  * its PR row: the identity's row; a new item keeps its own slot's row when that row is of the
    right table and free, else takes a free row of that table (a row whose vanilla item the mod
    dropped), the one whose vanilla item looks most like it, else a new row;
  * its template: the vanilla item whose look the row gets (the identity; for a new item the
    vanilla item of the same kind and icon with the closest power, the row's own when it fits).

port.py applies it when a profile asks (`item_identity = True`): idmap.ITEM_OVERRIDES for slots
whose row isn't the default one, a vanilla baseline per row (each row diffed against the vanilla
item it held, so the porters' slot-by-slot diffs write every difference), and the look columns
copied from each template's row (`apply_looks`).

    .venv/Scripts/python tools/item_identity.py tedition     (prints the assignment)
"""
import collections
import difflib
import os
import sys
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ff6snes as S  # noqa: E402
import idmap as M  # noqa: E402
import prdata as P  # noqa: E402

# SNES item kind (ff6snes.ITEM_TYPES) -> PR table; armor rows' equip slot (parts_group_id)
TABLE = {"weapon": "weapon", "armor": "armor", "shield": "armor", "helmet": "armor", "relic": "armor",
         "tool": "item", "item": "item"}
PARTS = {"shield": "2", "helmet": "3", "armor": "4", "relic": "5"}

# what makes a row look like its item (never what it does: the porters write that from the mod's data)
LOOK = {
    "weapon": ["type_id", "category_type", "battle_equipment_asset_id", "battle_effect_asset_id", "guard_icon"],
    "armor": ["type_id", "parts_group_id", "battle_effect_asset_id", "guard_icon", "se_asset_id"],
    "item": ["type_id", "battle_effect_asset_id", "menu_se_asset_id"],
}

SPELLINGS = [("mithril", "mythril"), ("shld", "shield"), ("helmet", "helm"), ("brsh", "brush"),
             ("knuckles", "knuckle"), ("claws", "claw"), ("gloves", "glove")]


def norm(name):
    s = "".join(ch for ch in (name or "").lower() if ch.isalnum())
    for a, b in SPELLINGS:
        s = s.replace(a, b)
    return s


@dataclass
class ModItem:
    slot: int
    names: list          # the mod's names for it, best first (a translation's full name, the ROM's)
    kind: str            # ff6snes.ITEM_TYPES value
    icon: int = None     # the mod's icon byte (its own font: mapped to the US ROM's by learning)
    power: int = 0


@dataclass
class Slot:
    slot: int
    kind: str
    table: str
    pr_id: int
    identity: int = None   # vanilla slot it is, or None (new)
    template: int = None   # vanilla slot whose look the row gets
    occupant: int = None   # vanilla slot whose row this is (None: a new row)
    how: str = ""
    names: list = field(default_factory=list)


class Vanilla:
    """The US ROM's items with the PR's names and rows."""

    def __init__(self):
        self.items = S.items(S.Rom(P.VANILLA_ROM))
        vmsg, content = P.messages(), P.Table("content")
        self.pr_names, self.rows = [], {}
        for it in self.items:
            m = M.default_item(it.id)
            self.pr_names.append(P.strip_tags(vmsg.get(content[M.content_id(*m)]["mes_id_name"], "")) if m else "")
            if m:
                self.rows[m] = it.id
        self.icons = [it.raw and S.rom_bytes(P.VANILLA_ROM)[S.ITEM_NAMES[0] + S.ITEM_NAMES[1] * it.id] for it in self.items]


def identify(mod_items, van=None, log=print):
    """[Slot] for every mod item (see the module doc); slot 255 is "empty" everywhere."""
    van = van or Vanilla()
    mod_items = [mi for mi in mod_items if mi.slot != 0xFF]
    by_kind = collections.defaultdict(list)
    for it in van.items:
        if (van.pr_names[it.id] or it.name) and M.default_item(it.id):
            by_kind[it.type].append(it.id)

    # 1. identity by name: the PR's name, then the SNES name, then one clearly closest spelling
    ident, how = {}, {}
    for pass_ in ("pr", "snes", "close"):
        taken = set(ident.values())
        for mi in mod_items:
            if mi.slot in ident or not any(mi.names):
                continue
            pool = [v for v in by_kind[mi.kind] if v not in taken]
            keys = [norm(n) for n in mi.names if n]
            if pass_ == "pr":
                hits = [v for v in pool if norm(van.pr_names[v]) in keys]
            elif pass_ == "snes":
                hits = [v for v in pool if norm(van.items[v].name) in keys]
            else:
                scored = sorted(((max(difflib.SequenceMatcher(None, k, norm(n)).ratio()
                                      for k in keys for n in (van.pr_names[v], van.items[v].name) if n), v) for v in pool),
                                reverse=True)
                hits = [scored[0][1]] if scored and scored[0][0] >= 0.88 and (len(scored) < 2 or scored[1][0] < scored[0][0] - 0.08) else []
            if len(hits) == 1:
                ident[mi.slot], how[mi.slot] = hits[0], pass_
                taken.add(hits[0])

    # the mod's icon bytes -> the US ROM's, learned from the identities (icons tell sword from dagger)
    votes = collections.defaultdict(collections.Counter)
    for mi in mod_items:
        if mi.slot in ident and mi.icon is not None:
            votes[mi.icon][van.icons[ident[mi.slot]]] += 1
    icon_map = {b: c.most_common(1)[0][0] for b, c in votes.items()}

    def template_for(mi, prefer=None):
        same = [v for v in by_kind[mi.kind]]
        icon = icon_map.get(mi.icon)
        if icon is not None and any(van.icons[v] == icon for v in same):
            same = [v for v in same if van.icons[v] == icon]
        if prefer is not None and prefer in same:
            return prefer
        return min(same, key=lambda v: (abs(van.items[v].power - mi.power), v)) if same else None

    # 2. rows: identities first, then new items on their own row, a free row, or a new one
    out, used = {}, set()
    for mi in mod_items:
        if mi.slot in ident:
            v = ident[mi.slot]
            row = M.default_item(v)
            out[mi.slot] = Slot(mi.slot, mi.kind, row[0], row[1], v, v, v, how[mi.slot], mi.names)
            used.add(row)
    claimed = {s.identity for s in out.values()}
    free = {t: [v for v in sorted(van.rows.values()) if v not in claimed and M.default_item(v)[0] == t
                and M.default_item(v) not in used] for t in ("weapon", "armor", "item")}
    new_ids = {}
    for mi in mod_items:
        if mi.slot in out:
            continue
        table = TABLE.get(mi.kind)
        if table is None or not any(mi.names):
            continue                       # empty slot
        own = M.default_item(mi.slot)
        tmpl = template_for(mi)
        if own and own[0] == table and own not in used and mi.slot in free[table]:
            row, occ, how_ = own, mi.slot, "own row"
            tmpl = template_for(mi, prefer=mi.slot)
        elif free[table]:
            # the free row whose vanilla item looks most like the template (same kind and icon, then power)
            def fit(v):
                t = van.items[tmpl] if tmpl is not None else None
                return (van.items[v].type != mi.kind, t is not None and van.icons[v] != van.icons[tmpl],
                        abs(van.items[v].power - (t.power if t else mi.power)), v)
            occ = min(free[table], key=fit)
            row, how_ = M.default_item(occ), "free row"
        else:
            nid = new_ids.setdefault(table, max(P.Table(table).rows) + 1)
            new_ids[table] += 1
            row, occ, how_ = (table, nid), None, "new row"
        if occ is not None and occ in free[table]:
            free[table].remove(occ)
        used.add(row)
        out[mi.slot] = Slot(mi.slot, mi.kind, row[0], row[1], None, tmpl, occ, how_, mi.names)
    slots = [out[k] for k in sorted(out)]
    c = collections.Counter(s.how for s in slots)
    log(f"item identity: {len(slots)} items: " + ", ".join(f"{n} {k}" for k, n in sorted(c.items()))
        + f"; {sum(1 for s in slots if s.identity is not None and s.identity != s.slot)} vanilla items in another slot, "
        f"{sum(1 for s in slots if (s.table, s.pr_id) != M.default_item(s.slot))} on another row than their slot's")
    return slots


def overrides(slots):
    """{slot: (table, PR id)} for slots whose row isn't idmap's default."""
    return {s.slot: (s.table, s.pr_id) for s in slots if (s.table, s.pr_id) != M.default_item(s.slot)}


# vanilla tables that name items by slot (renumbered in the baseline) and that are indexed by item (permuted)
SHOPS, SHOP_COUNT = 0x047AC0, 128            # 9 bytes: type, 8 items
MONSTER_ITEMS = 0x0F3000, 4, 384            # steals and drops
CHAR_INIT = 0x2D7CA0, 22, 64                # bytes 15-20: starting equipment
MORPH_SETS = 0x047F40, 4, 26                # metamorph results
CHEST_PTRS, CHEST_DATA, CHEST_MAPS = 0x2D82F4, 0x2D8634, 416   # 5 bytes: x, y, bit, flags, contents
CHEST_ITEM = 0x40


def baseline_image(van, slots):
    """The vanilla ROM in the mod's item numbering, for the porters' slot-by-slot diffs: slot s holds the
    vanilla item whose PR row s now has (its record and name; a new row: its template's), with the mod's
    kind (a helmet on a body armor's row is diffed as a helmet), and every vanilla reference to an item
    (shops, chests, steals and drops, starting equipment, metamorph) names the slot that now has that
    item's row (an item whose row no slot took: empty)."""
    img = bytearray(van.data)
    rec, nam = S.ITEMS, S.ITEM_NAMES
    vraw, vnames = van.table(*rec), van.table(*nam)
    count = max([256] + [s.slot + 1 for s in slots])
    if count > 256:   # a mod with more items than the US table (T-Edition: 280): the slots past 255 in a grown
        grown = len(img)  # table past the image's end, registered as the mod's is (ff6snes.items reads both)
        img += bytes(count * (rec[1] + nam[1]))
        rec, nam = (grown, rec[1], count), (grown + count * rec[1], nam[1], count)
        for i in range(256):
            img[rec[0] + rec[1] * i:rec[0] + rec[1] * (i + 1)] = vraw[i]
            img[nam[0] + nam[1] * i:nam[0] + nam[1] * (i + 1)] = vnames[i]
    host = {}
    for s in slots:
        src = s.occupant if s.occupant is not None else s.template
        if src is None:
            continue
        if s.occupant is not None:
            host[s.occupant] = s.slot
        r = bytearray(vraw[src])
        kind = next(k for k, v in S.ITEM_TYPES.items() if v == s.kind)
        r[0] = (r[0] & ~7) | kind
        for base, size, val in ((S.ITEMS[0], S.ITEMS[1], r), (S.ITEM_NAMES[0], S.ITEM_NAMES[1], vnames[src])) if s.slot < 256 else ():
            img[base + size * s.slot:base + size * (s.slot + 1)] = val
        if count > 256:
            img[rec[0] + rec[1] * s.slot:rec[0] + rec[1] * (s.slot + 1)] = r
            img[nam[0] + nam[1] * s.slot:nam[0] + nam[1] * (s.slot + 1)] = vnames[src]

    def ren(b):   # (a vanilla item now in a slot past 255: no byte can name it, as in the mod's own tables: empty)
        return b if b == 0xFF else host.get(b, 0xFF) if host.get(b, 0xFF) < 256 else 0xFF
    for sh in range(SHOP_COUNT):
        for k in range(1, 9):
            a = SHOPS + 9 * sh + k
            img[a] = ren(img[a])
    for base, size, count, fields in ((MONSTER_ITEMS[0], 4, 384, range(4)), (CHAR_INIT[0], 22, 64, range(15, 21)),
                                      (MORPH_SETS[0], 4, 26, range(4))):
        for i in range(count):
            for k in fields:
                img[base + size * i + k] = ren(img[base + size * i + k])
    ptr = [int.from_bytes(img[CHEST_PTRS + 2 * m:CHEST_PTRS + 2 * m + 2], "little") for m in range(CHEST_MAPS + 1)]
    for c in range(ptr[0] // 5, ptr[-1] // 5):
        a = CHEST_DATA + 5 * c
        if img[a + 3] & CHEST_ITEM:
            img[a + 4] = ren(img[a + 4])
    out = bytes(img)
    if count > 256:
        S.EXTENDED[id(out)] = {"items": rec, "item_names": nam, "_image": out}
    return out


def make_rows(tables, slots, messages, log=print):
    """New PR rows (a copy of the template's row) with their content rows and name/description keys.
    Returns {table: new ids}."""
    content = tables.setdefault("content", P.Table("content"))
    vmsg = P.messages()
    changed = collections.defaultdict(set)
    for s in slots:
        if s.occupant is not None:
            continue
        t = tables.setdefault(s.table, P.Table(s.table))
        ttab, tid = M.default_item(s.template)
        t.rows[s.pr_id] = dict(t[tid], id=str(s.pr_id))
        P.ADDED_ROWS.setdefault(s.table, {})[s.pr_id] = dict(t.rows[s.pr_id])
        changed[s.table].add(s.pr_id)
        src = content[M.content_id(ttab, tid)]
        cid = max(content.rows) + 1
        tag = s.table.upper()
        content.rows[cid] = dict(src, id=str(cid), mes_id_name=f"MSG_PORT_{tag}_NAME_{s.pr_id}",
                                 mes_id_description=f"MSG_PORT_{tag}_INF_{s.pr_id}", type_value=str(s.pr_id))
        M.add_content(s.table, s.pr_id, cid)
        P.ADDED_ROWS.setdefault("content", {})[cid] = dict(content.rows[cid])
        changed["content"].add(cid)
        old = vmsg.get(src["mes_id_name"], "")
        icon = old[:old.index(">") + 1] if old.startswith("<IC_") else ""
        messages[f"MSG_PORT_{tag}_NAME_{s.pr_id}"] = icon + (s.names[0] if s.names else "")
        messages[f"MSG_PORT_{tag}_INF_{s.pr_id}"] = vmsg.get(src["mes_id_description"], "")
    if changed:
        log(f"item identity: new rows {', '.join(f'{k} {sorted(v)}' for k, v in changed.items() if k != 'content')}")
    return changed


def apply_looks(tables, slots, log=print):
    """Copy each template's look columns onto its slot's row (an armor row also gets the equip slot
    of the mod's kind). Returns {table: changed ids}."""
    changed = collections.defaultdict(set)
    for s in slots:
        if s.template is None or s.template == s.occupant:
            continue
        t = tables.setdefault(s.table, P.Table(s.table))
        src, row = t[M.default_item(s.template)[1]], t[s.pr_id]
        for col in LOOK[s.table]:
            if col in row and row[col] != src[col]:
                row[col] = src[col]
                changed[s.table].add(s.pr_id)
        if s.table == "armor" and s.kind in PARTS and row["parts_group_id"] != PARTS[s.kind]:
            row["parts_group_id"] = PARTS[s.kind]
            changed["armor"].add(s.pr_id)
    log(f"item identity: {sum(len(v) for v in changed.values())} rows took their template's look")
    return changed


def prepare(profile, van, mod, tables, messages, log=print):
    """The porter's entry (port.py main): off unless the profile sets `item_identity`. Sets
    idmap.ITEM_OVERRIDES, makes new rows, copies looks, and returns (the vanilla baseline Rom,
    {table: changed ids}, slots)."""
    M.ITEM_OVERRIDES.clear()
    for t in ("weapon", "armor", "item", "content"):
        P.ADDED_ROWS.pop(t, None)
    if not getattr(profile, "item_identity", False):
        return van, {}, []
    items = profile.item_mod_items(mod) if hasattr(profile, "item_mod_items") else mod_items_from(mod)
    slots = identify(items, Vanilla(), log)
    M.ITEM_OVERRIDES.update(overrides(slots))
    changed = collections.defaultdict(set)
    for part in (make_rows(tables, slots, messages, log), apply_looks(tables, slots, log)):
        for k, v in part.items():
            changed[k] |= v
    key = os.path.abspath(P.VANILLA_ROM) + "#item-identity"
    S.MEMORY[key] = baseline_image(van, slots)
    return S.Rom(key), dict(changed), slots


def mod_items_from(rom, names=None, icons=None):
    """ModItems from a US-layout ROM image (names: the mod's full names by slot, icons: their icon bytes)."""
    out = []
    raw_names = rom.table(*S.ITEM_NAMES)
    for it in S.items(rom):
        n = [names[it.id]] if names and names[it.id] else []
        out.append(ModItem(it.id, n + ([it.name] if it.name else []), it.type,
                           icons[it.id] if icons else raw_names[it.id][0], it.power))
    return out


def main(argv):
    if not argv or argv[0] != "tedition":
        sys.exit(__doc__)
    import profile_tedition as T
    data = T.build()
    rom = S.Rom(T.MATO)
    assert rom.data is data
    n = T._Image.names
    slots = identify(mod_items_from(rom, n.items, n.item_icons))
    van = Vanilla()
    for s in slots:
        if s.identity != s.slot or s.how not in ("pr", "snes"):
            occ = f"{van.items[s.occupant].name}" if s.occupant is not None else "-"
            tm = f"{van.pr_names[s.template]}" if s.template is not None else "-"
            print(f"  {s.slot:3} {s.kind:6} {s.names[0] if s.names else '':18} -> {s.table} {s.pr_id:3} "
                  f"({s.how}; row of {occ}; look of {tm})")


if __name__ == "__main__":
    main(sys.argv[1:])
