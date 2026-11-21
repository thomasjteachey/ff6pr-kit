"""SNES event scenes a mod changed: vanilla's and the mod's field scripts, map entry by map entry.

Both ROMs are decoded with tools/snes_events.py (every script reachable from each map's entrance event,
event tiles and NPCs, following calls, branches and choices). Each entry's script is rendered canonically
(instruction names and arguments, addresses as labels in visit order) once with its dialogue numbers and
once without, so a mod that moved code around or only changed text compares equal:

    same       nothing changed
    text       only dialogue numbers changed (the PR shows the mod's text through its own dialogue map)
    changed    commands changed (summary: the commands added and removed, the dialogues around them)
    new        an entry only the mod has (a new NPC, tile or map event)
    removed    an entry only vanilla has

Entries are matched by map and kind: the entrance; a tile by its x, y; an NPC by its x, y and sprite (then
by its index on the map). A mod's event code outside vanilla's area is decoded when its ROM ranges are
given (Brave New World: event addresses 0x230000-0x260000, its code in bank ED).

    .venv/Scripts/python tools/event_diff.py <mod.sfc> [--ranges 230000-260000] [--json out.json]
"""
import argparse
import collections
import difflib
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import snes_events as E  # noqa: E402

ADDRESS_ARGS = ("event",)


def rom_for(path, extra_ranges=(), name=None):
    tables = E.Tables(code_ranges=[(0, 0x2E600)] + list(extra_ranges))
    rom = E.Rom(path, E.US_DIALECT, tables=tables, name=name or os.path.basename(path))
    rom.dialog_choices = E._choices_us(rom)
    return rom


def _render(ins, lab, mask):
    parts = [ins.name]
    for k in sorted(ins.args):
        v = ins.args[k]
        if k in ADDRESS_ARGS:
            continue
        if k == "cases":
            v = [(c, lab(a)) for c, a in v]
        if mask and k in ("dlg", "dialog"):
            v = "D"
        parts.append(f"{k}={v}")
    if ins.targets:
        parts.append("->" + ",".join(lab(t) for _, t in ins.targets))
    return " ".join(parts)


def canon(prog, start, m, mode, mask):
    """(lines, dialogue numbers, instruction count, callees) of one script unit from `start`: its
    branches, gotos and choices followed, its calls not (each "call C<k>"; callees = [(address, mode)]
    in order), so a changed subroutine is one unit, not a change in every script that calls it."""
    labels, callees = {}, []

    def lab(a):
        if a not in labels:
            labels[a] = len(labels)
        return f"L{labels[a]}"
    lab(start)
    out, dlgs, seen, todo, n = [], [], set(), collections.deque([(start, mode)]), 0
    queued = {(start, mode)}
    while todo:
        off, md = todo.popleft()
        out.append(f"{lab(off)}:")
        last = None
        while True:
            if (off, md) in seen:
                out.append(f"goto {lab(off)}")
                break
            seen.add((off, md))
            ins = prog.code.get((off, md)) or E.decode(prog.rom, off, {"map": m}, last, md)
            if ins is None:
                out.append("?")
                break
            n += 1
            if ins.cls == "dialog" and "dlg" in ins.args:
                dlgs.append(ins.args["dlg"])
                last = E.dialog_key(ins)
            if ins.flow == "call":
                t = (ins.targets[0][1], md)
                if t not in callees:
                    callees.append(t)
                out.append(f"{ins.name} " + " ".join(f"{k}={v}" for k, v in sorted(ins.args.items()) if k not in ADDRESS_ARGS)
                           + f" ->C{callees.index(t)}")
            else:
                out.append(_render(ins, lab, mask))
                for _, tg in ins.targets:
                    lab(tg)
                    if (tg, md) not in seen and (tg, md) not in queued:
                        queued.add((tg, md))
                        todo.append((tg, md))
            if ins.flow in ("end", "choice") or off in prog.dead or ins.off in prog.map_ends:
                break
            off += ins.size
            md = prog._next_mode(ins, off, m, last)
            if md is None:
                break
    return out, dlgs, n, callees


def entries(prog):
    """{key: (address, map, mode)}: key = (map, kind, place)."""
    out, idx = {}, collections.Counter()
    for off, kind, m, det in prog.entries:
        if kind == "npc_object":
            continue
        mode = "vehicle" if m in E.WORLD_MAPS and kind != "npc" else "field"
        if kind == "entrance":
            key = (m, "entrance", None)
        elif kind == "tile":
            key = (m, "tile", det)
        else:
            key = (m, "npc", (det["x"], det["y"], det["sprite"]))
            if key in out:
                idx[key] += 1
                key = (m, "npc", (det["x"], det["y"], det["sprite"], idx[key]))
        out[key] = (off, m, mode, det)
    return out


def diff(van_rom, mod_rom):
    """One row per script unit that differs (an entry's own script or a subroutine, each once), with
    the map entries that reach it; plus entries only one ROM has."""
    pv, pm = E.Program(van_rom).walk_all(), E.Program(mod_rom).walk_all()
    ev, em = entries(pv), entries(pm)
    # an NPC moved or re-sprited: match the leftovers on a map by index
    lv = {k: v for k, v in ev.items() if k not in em}
    lm = {k: v for k, v in em.items() if k not in ev}
    for kv, (off, m, mode, det) in list(lv.items()):
        if kv[1] != "npc":
            continue
        for km, (off2, m2, mode2, det2) in list(lm.items()):
            if km[0] == m and km[1] == "npc" and det2["npc"] == det["npc"]:
                em[kv] = em.pop(km)
                lm.pop(km)
                break
    rows, units = [], {}
    todo = collections.deque()
    for key in sorted(set(ev) | set(em), key=lambda k: (k[0], k[1], str(k[2]))):
        if key not in em:
            off, m, mode, det = ev[key]
            rows.append({"key": key, "status": "removed", "van": E.fmt(off), "dlgs": canon(pv, off, m, mode, False)[1]})
        elif key not in ev:
            off, m, mode, det = em[key]
            lines, dl, n, _ = canon(pm, off, m, mode, False)
            rows.append({"key": key, "status": "new", "mod": E.fmt(off), "dlgs": dl, "size": n})
        else:
            (o1, m1, md1, _), (o2, m2, md2, _) = ev[key], em[key]
            todo.append(((o1, md1), (o2, md2), m1, key))
    while todo:
        (o1, md1), (o2, md2), m, key = todo.popleft()
        u = units.get(o1)
        if u is not None:
            u["entries"].add(key)
            continue
        f1, d1, n1, c1 = canon(pv, o1, m, md1, False)
        f2, d2, n2, c2 = canon(pm, o2, m, md2, False)
        k1, k2 = canon(pv, o1, m, md1, True)[0], canon(pm, o2, m, md2, True)[0]
        u = units[o1] = {"van": E.fmt(o1), "mod": E.fmt(o2), "map": m, "entries": {key}, "dlgs": d1, "mod_dlgs": d2,
                         "size": (n1, n2)}
        sm = difflib.SequenceMatcher(None, k1, k2, autojunk=False)
        u["status"] = "same" if f1 == f2 else "text" if k1 == k2 else "changed"
        if u["status"] == "changed":
            added, removed = collections.Counter(), collections.Counter()
            for op, a1, a2, b1, b2 in sm.get_opcodes():
                if op in ("replace", "delete"):
                    for x in k1[a1:a2]:
                        removed[x.split(" ")[0]] += 1
                if op in ("replace", "insert"):
                    for x in k2[b1:b2]:
                        added[x.split(" ")[0]] += 1
            u.update(ratio=round(sm.ratio(), 2), added=dict(added.most_common(8)), removed=dict(removed.most_common(8)),
                     new_callees=max(0, len(c2) - len(c1)))
        # callees: paired where the two scripts line up (the same call lines in matching spans)
        call = lambda line: line.split("->C")[-1] if "->C" in line and not line.endswith(":") else None
        for op, a1, a2, b1, b2 in sm.get_opcodes():
            if op not in ("equal", "replace"):
                continue
            x = [call(l) for l in k1[a1:a2] if call(l) is not None]
            y = [call(l) for l in k2[b1:b2] if call(l) is not None]
            if op == "replace" and len(x) != len(y):
                continue
            for i, j in zip(x, y):
                todo.append((c1[int(i)], c2[int(j)], m, key))
    for u in units.values():
        if u["status"] != "same":
            u["entries"] = sorted(u["entries"], key=str)
            rows.append(u)
    return rows


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("mod")
    ap.add_argument("--ranges", default="", help="extra event-code ranges (event addresses), e.g. 230000-260000")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    ranges = [tuple(int(x, 16) for x in r.split("-")) for r in a.ranges.split(",") if r]
    rows = diff(E.load("us"), rom_for(a.mod, ranges))
    c = collections.Counter(r["status"] for r in rows)
    print(dict(c))
    if a.json:
        json.dump(rows, open(a.json, "w"), indent=1, default=str)
    return rows


if __name__ == "__main__":
    main(sys.argv[1:])
