"""Monster names: the mod's names onto the PR's monster text keys (battle target list, bestiary, Rage
list, Scan).

The PR's monster rows 1-384 are the SNES monsters 0-383 (row = SNES id + 1); rows past 384 are the
PR's copies for its own fights and keep their row's key. Some PR name keys are shared by monsters the
mod names apart (Brave New World: MSG_MON_NAME_02 is both its Soldier and its Recruit; the four Mag
Roaders; Siegfried and Ziegfried; Lakshmi and Chadarnook): the first SNES row keeps the shared key,
each other one gets a key of its own (MSG_BNW_MON_NAME_<row>), and so does its Rage's content row.

With profile.rename_all every named monster gets the mod's name, else only those the mod renamed.
SNES names the mod left empty or marked as event placeholders ("(Event)") keep the PR's; a leading
"!" (the mod's mark on a scripted copy: "!Whelk") is dropped.
"""
import collections

import ff6snes as S
import prdata as P

RAGE_ABILITY_BASE = 800   # the PR's Rage abilities: 800 + SNES monster id


def display(name):
    name = (name or "").strip()
    if not name or name.startswith("("):
        return ""
    return name.lstrip("!").strip()


CHAR_NAME_KEY = "MSG_CHAR_NAME_{:02d}"   # the PR's names of SNES characters 0-13 (key = SNES id + 1)


def port_character_names(van, mod, messages, log=print):
    """The mod's names for the 14 characters (SNES 0x478C0) onto the PR's MSG_CHAR_NAME_01..14, for the
    characters the mod renamed (opt-in: profile.character_names; Beyond Chaos's c and makeover rename
    them). A name in capitals, as the US ROM writes them ("MADUIN"), is written the PR's way ("Maduin").
    Returns the keys set."""
    pr = P.messages()
    vc, mc = S.characters(van), S.characters(mod)
    done = []
    for i in range(min(14, len(vc), len(mc))):
        name, old = (mc[i].name or "").strip(), (vc[i].name or "").strip()
        key = CHAR_NAME_KEY.format(i + 1)
        if not name or name == old or key not in pr:
            continue
        messages[key] = name.title() if name.isupper() else name
        done.append(key)
    log(f"character names: {len(done)} of 14 renamed ({', '.join(messages[k] for k in done)})")
    return done


def port_monster_names(van, mod, tables, messages, rename_all=False, log=print):
    """messages[key] = the mod's name; new keys where a shared one would name two monsters alike.
    Returns {table: changed row ids}."""
    mo = tables.setdefault("monster", P.Table("monster"))
    content = tables.setdefault("content", P.Table("content"))
    ve, me = S.enemies(van), S.enemies(mod)
    pr = P.messages()
    want = {}   # PR row -> the name it should show
    for r in mo.rows:
        if r > 384 or r - 1 >= len(me):
            continue
        name, old = display(me[r - 1].name), display(ve[r - 1].name)
        if name and (rename_all or name != old):
            want[r] = name
    by_key = collections.defaultdict(list)
    for r, row in mo.rows.items():
        if row["mes_id_name"] not in ("", "None"):
            by_key[row["mes_id_name"]].append(r)
    rage = {int(c["type_value"]) - RAGE_ABILITY_BASE + 1: c for c in content
            if c["type_id"] == "4" and int(c["type_value"]) >= RAGE_ABILITY_BASE and c["mes_id_name"].startswith("MSG_MON_NAME_")}
    changed = {"monster": set(), "content": set()}
    named, own = 0, 0
    for key, rows in by_key.items():
        snes_rows = sorted(r for r in rows if r in want)
        if not snes_rows or key not in pr:   # a key the PR has no text for: a monster it never shows
            continue
        first = snes_rows[0]
        messages[key] = want[first]
        named += 1
        for r in snes_rows[1:]:
            if want[r] == want[first]:
                continue
            new = f"MSG_BNW_MON_NAME_{r}"
            messages[new] = want[r]
            mo[r]["mes_id_name"] = new
            changed["monster"].add(r)
            c = rage.get(r)
            if c is not None and c["mes_id_name"] == key:
                c["mes_id_name"] = new
                changed["content"].add(int(c["id"]))
            own += 1
    same = sum(1 for k in by_key if k in messages and messages[k] == pr.get(k))
    log(f"monster names: {named} name keys get the mod's names ({same} the same as the PR's), {own} monsters a key of their own")
    return changed
