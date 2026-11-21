"""Dances: the mod's step table (SNES CF/FE80, 8 dances x 4 steps) onto the PR's step groups.

The PR keeps each dance's steps in ability_random_group (invocation_rate in percent):
  group 1..8    on the dance's own background: the 4 steps, 37/37/19/7
  group 37..44  elsewhere: ability 262 (stumble) 50, then the steps 18/18/10/4
and picks the group by background itself (ActSelectDance). Vanilla's SNES odds were
7/6/2/1 of 16 for steps 1-4.

BNW (3.0 choreography.asm): the 4 bytes are Shift / Repeat / Uncommon / Rare; a dance is
Repeat (10/16) on its own background, Shift (10/16) elsewhere, then Uncommon 5/16 and Rare
1/16, and never stumbles (profile.dance_rules = "bnw"). Other mods: the steps change, the
PR's odds stay.
"""
import os

import os

import ff6snes as S
import idmap as M
import prdata as P

TABLE = 0x0FFE80
NATIVE, ELSEWHERE, STUMBLE = 1, 37, 262
BNW_ODDS = (63, 31, 6)  # 10/16, 5/16, 1/16 in percent


def steps(rom):
    d = rom.data
    out = []
    for k in range(8):
        ids = [M.spell(d[TABLE + 4 * k + j]) for j in range(4)]
        out.append(ids)
    return out


def port(van, mod, tables, log, profile=None, messages=None):
    arg = tables.setdefault("ability_random_group", P.Table("ability_random_group"))
    rows = {}
    for r in arg:
        rows.setdefault(int(r["group_id"]), []).append(int(r["id"]))
    vs, ms = steps(van), steps(mod)
    bnw = getattr(profile, "dance_rules", None) == "bnw"
    changed, checked = set(), 0
    for k, (v, m) in enumerate(zip(vs, ms)):
        native, elsewhere = rows.get(NATIVE + k, []), rows.get(ELSEWHERE + k, [])
        # the PR's groups must hold vanilla's steps in vanilla's order before we touch them
        if [int(arg[i]["ability_id"]) for i in native] != v:
            log(f"dances: group {NATIVE + k} isn't vanilla's dance {k} {v}; left alone")
            continue
        steps_else = [i for i in elsewhere if int(arg[i]["ability_id"]) != STUMBLE]
        stumble = [i for i in elsewhere if int(arg[i]["ability_id"]) == STUMBLE]
        checked += 1
        if bnw:
            shift, repeat, uncommon, rare = m
            plan = [(native, [repeat, uncommon, rare, shift], [*BNW_ODDS, 0]),
                    (steps_else, [shift, uncommon, rare, repeat], [*BNW_ODDS, 0]),
                    (stumble, [STUMBLE], [0])]
        elif "-dns" in os.environ.get("WC_FLAGS", "").split():
            # WC's -dns (dances no stumble): elsewhere as on the dance's own background
            plan = [(native, m, None), (steps_else, m, [int(arg[i]["invocation_rate"]) for i in native]), (stumble, [STUMBLE], [0])]
        else:
            plan = [(native, m, None), (steps_else, m, None)]
        for ids, abilities, rates in plan:
            for n, i in enumerate(ids):
                r = dict(arg[i])
                r["ability_id"] = str(abilities[n])
                if rates is not None:
                    r["invocation_rate"] = str(rates[n])
                if r != arg[i]:
                    arg.rows[i] = r
                    changed.add(i)
    log(f"dances: {checked} dances, {len(changed)} step rows changed" + (" (BNW odds, no stumble)" if bnw else ""))
    return {"ability_random_group": changed}


def describe_steps(mod, messages):
    """WC's -dda (dance abilities displayed): each dance's description lists its four steps
    (PR dance abilities 164-171; step names as the mod's text has them, else the PR's)."""
    names = dict(P.messages())
    names.update(messages)
    content = P.Table("content")
    key = {(r["type_id"], int(r["type_value"])): r for r in content}
    n = 0
    for k, ids in enumerate(steps(mod)):
        dance = key.get(("4", 164 + k))
        if not dance:
            continue
        step_names = [names.get(key[("4", a)]["mes_id_name"], "") for a in ids if a and ("4", a) in key]
        if step_names:
            messages[dance["mes_id_description"]] = " / ".join(step_names)
            n += 1
    return n


RAGE_ABILITY_TYPE = 625   # the PR's Rage abilities (800 + SNES monster id; data_a = the PR monster id)


def describe_rages(texts, tables, messages):
    """Each Rage's two attacks in its description, as BNW's Rage menu shows them (bnw 3.0
    ragedance_descriptions.asm). texts: {SNES monster id: (first attack, second attack)}, the
    mod's own words; any other Rage gets its two abilities' names from its ability_random_group
    rows (as ported). The PR's Rage abilities have content rows without a description key: each
    gets MSG_BNW_RAGE_INF_<PR monster id>, which the battle's ability list and the Skills menu show.
    Returns {"content": changed row ids}."""
    import re
    content = tables.setdefault("content", P.Table("content"))
    mo = tables.get("monster") or P.Table("monster")
    arg = tables.get("ability_random_group") or P.Table("ability_random_group")
    names = dict(P.messages())
    names.update(messages)
    by4 = {int(r["type_value"]): r for r in content if r["type_id"] == "4"}
    groups = {}
    for r in arg:
        groups.setdefault(int(r["group_id"]), []).append(r)

    def plain(key):
        return re.sub(r"<[^>]*>", "", names.get(key, "")).strip()

    def frac(rate, total):
        share = rate / total if total else 0
        for label, v in (("2/3", 2 / 3), ("1/3", 1 / 3), ("1/2", 1 / 2)):
            if abs(share - v) < 0.03:
                return label
        return f"{round(100 * share)}%"

    changed, own, made = set(), 0, 0
    for r in P.Table("ability"):
        if r["type_id"] != str(RAGE_ABILITY_TYPE):
            continue
        aid, mid = int(r["id"]), int(r["data_a"])
        row = by4.get(aid)
        if row is None or mid < 1:
            continue
        e = mid - 1
        if e in texts:
            a, b = texts[e]
            text = f"2/3: {a}; 1/3: {b}"
            own += 1
        else:
            try:
                g = int(mo[mid]["rage_ability_random_group_id"])
            except (KeyError, ValueError):
                continue
            rates = {}   # by name: the PR splits a special over two rows (two ability ids, one name)
            for x in groups.get(g, []):
                a = int(x["ability_id"])
                name = plain(by4[a]["mes_id_name"]) if a in by4 else ""
                if name and int(x["invocation_rate"]) > 0:
                    rates[name] = rates.get(name, 0) + int(x["invocation_rate"])
            if not rates:
                continue
            picks = sorted(rates.items(), key=lambda p: -p[1])
            total = sum(rates.values())
            text = "; ".join(f"{frac(rate, total)}: {name}" for name, rate in picks[:2]) if len(picks) > 1 else picks[0][0]
            made += 1
        key = f"MSG_BNW_RAGE_INF_{mid:03d}"
        if row["mes_id_description"] != key:
            row["mes_id_description"] = key
            changed.add(int(row["id"]))
        messages[key] = text
    return {"content": changed}, own, made
