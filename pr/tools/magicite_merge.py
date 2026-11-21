"""Merge Magicite folders of one game into one folder, against the game's own files (a three-way merge).

The game reads one copy of each asset: when two Magicite folders both ship a map group's package.json
(or the same map's entity file, or the same partial master table), only one folder's copy is used, and
the other folder's additions vanish (T-Edition, 2026-11-20: BNW's package.json for map_20071 hid the
event scripts another folder added). A mod built by several tools (the porter, new maps, translated
events) therefore ships one folder, merged:

    import magicite_merge as MM
    report = MM.merge(dest, [folder_a, folder_b], vanilla=P.VANILLA)   # into dest (dest's own files first)
    report.conflicts   # [(relative path, where, what)]: both sides changed the same thing differently

Per file, by kind:
  * JSON (map packages, entity layers, scripts...): a recursive three-way merge against the game's
    copy of the same path. Objects merge key by key; lists of objects that carry an "id" or a "name"
    merge by that key (in the first side's order, then the other's new items); other lists must agree
    or be changed on one side only. A file the game doesn't have (a new map's, a new script) must be
    identical in both folders, or it is a conflict.
  * master tables (partial CSVs: header + changed rows): rows by id, each column three-way against
    the game's row.
  * text (`key<TAB>text` lines): key by key, against the game's text.
  * keys/*.json (one per group, any name): pairs (key, value) unioned into the destination's keys
    file for that group (the first one's name), so no asset is listed twice.
  * anything else: identical bytes, or a conflict.
A conflict keeps the destination's version and is reported; merge(..., strict=True) raises instead.
"""
import csv
import io
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import prdata as P  # noqa: E402

KEY_FIELDS = ("id", "name")


class Conflict(Exception):
    pass


class Report:
    def __init__(self):
        self.copied, self.merged, self.same, self.conflicts = [], [], [], []

    def __str__(self):
        return (f"{len(self.copied)} files copied, {len(self.merged)} merged, {len(self.same)} identical, "
                f"{len(self.conflicts)} conflicts")


# --- JSON ----------------------------------------------------------------------------------------
_MISSING = object()


def _key_field(*lists):
    """The field ("id", then "name") every item of every list has, unique within each list."""
    for k in KEY_FIELDS:
        ok = any(lists)
        for items in lists:
            if not all(isinstance(x, dict) and k in x for x in items):
                ok = False
                break
            vals = [json.dumps(x[k]) for x in items]
            if len(set(vals)) != len(vals):
                ok = False
                break
        if ok:
            return k
    return None


def merge_json(base, a, b, where="", conflicts=None):
    """Three-way merge of JSON values (base may be _MISSING). Conflicts are appended as (where, what)
    and resolved to a's value."""
    conflicts = [] if conflicts is None else conflicts
    if a == b:
        return a
    if base is not _MISSING and a == base:
        return b
    if base is not _MISSING and b == base:
        return a
    if isinstance(a, dict) and isinstance(b, dict):
        bd = base if isinstance(base, dict) else {}
        out = {}
        for k in list(a) + [k for k in b if k not in a]:
            va, vb, vbase = a.get(k, _MISSING), b.get(k, _MISSING), bd.get(k, _MISSING)
            if va is _MISSING:
                if vbase is _MISSING or vb != vbase:   # added in b, or changed in b and deleted in a
                    out[k] = vb
                continue
            if vb is _MISSING:
                if vbase is _MISSING or va != vbase:
                    out[k] = va
                continue
            out[k] = merge_json(vbase, va, vb, f"{where}/{k}", conflicts)
        return out
    if isinstance(a, list) and isinstance(b, list):
        bl = base if isinstance(base, list) else []
        kf = _key_field(a, b, bl) or _key_field(a, b)
        if kf:
            bl = bl if bl and _key_field(bl) == kf else []
            ia = {json.dumps(x[kf]): x for x in a}
            ib = {json.dumps(x[kf]): x for x in b}
            ibase = {json.dumps(x[kf]): x for x in bl}
            out = []
            for key in list(ia) + [k for k in ib if k not in ia]:
                va, vb, vbase = ia.get(key, _MISSING), ib.get(key, _MISSING), ibase.get(key, _MISSING)
                if va is _MISSING:
                    if vbase is _MISSING or vb != vbase:
                        out.append(vb)
                    continue
                if vb is _MISSING:
                    if vbase is _MISSING or va != vbase:
                        out.append(va)
                    continue
                out.append(merge_json(vbase, va, vb, f"{where}[{kf}={key}]", conflicts))
            return out
        if isinstance(base, list) and len(a) == len(b) == len(base):
            return [merge_json(x, y, z, f"{where}[{i}]", conflicts) for i, (x, y, z) in enumerate(zip(base, a, b))]
    conflicts.append((where or "/", f"{json.dumps(a)[:80]} vs {json.dumps(b)[:80]}"))
    return a


# --- master tables and text ----------------------------------------------------------------------
def _read_csv(text):
    rows = list(csv.reader(io.StringIO(text)))
    return rows[0], [r for r in rows[1:] if r]


def merge_csv(base_text, a_text, b_text, where, conflicts):
    """Partial master tables (header + changed rows) by row id; columns three-way against the game's."""
    ha, ra = _read_csv(a_text)
    hb, rb = _read_csv(b_text)
    if ha != hb:
        conflicts.append((where, "headers differ"))
        return a_text
    base = {}
    if base_text is not None:
        hv, rv = _read_csv(base_text)
        if hv == ha:
            base = {r[0]: r for r in rv}
    rows = {r[0]: r for r in ra}
    order = [r[0] for r in ra]
    for r in rb:
        rid = r[0]
        if rid not in rows:
            rows[rid] = r
            order.append(rid)
            continue
        va, vbase = rows[rid], base.get(rid)
        if va == r:
            continue
        out = []
        for i, col in enumerate(ha):
            x, y = va[i], r[i]
            z = vbase[i] if vbase else None
            if x == y or (z is not None and y == z):
                out.append(x)
            elif z is not None and x == z:
                out.append(y)
            else:
                conflicts.append((f"{where} id {rid}", f"{col}: {x} vs {y}"))
                out.append(x)
        rows[rid] = out
    s = io.StringIO()
    w = csv.writer(s, lineterminator="\n")
    w.writerow(ha)
    for rid in sorted(order, key=lambda v: (not v.lstrip("-").isdigit(), int(v) if v.lstrip("-").isdigit() else 0, v)):
        w.writerow(rows[rid])
    return s.getvalue()


def _read_text(text):
    out = {}
    for line in text.splitlines():
        if "\t" in line:
            k, v = line.split("\t", 1)
            out[k] = v
    return out


def merge_text(base_text, a_text, b_text, where, conflicts):
    base = _read_text(base_text) if base_text is not None else {}
    a, b = _read_text(a_text), _read_text(b_text)
    out = dict(a)
    for k, v in b.items():
        if k not in out or out[k] == v or v == base.get(k):
            out.setdefault(k, v)
            continue
        if out[k] == base.get(k):
            out[k] = v
            continue
        conflicts.append((f"{where} {k}", f"{out[k][:60]!r} vs {v[:60]!r}"))
    return "".join(f"{k}\t{out[k]}\r\n" for k in sorted(out))


# --- folders ----------------------------------------------------------------------------------------
def _files(folder):
    for root, _, fs in os.walk(folder):
        for f in fs:
            p = os.path.join(root, f)
            yield os.path.relpath(p, folder).replace("\\", "/"), p


def _read(path, binary=False):
    with open(path, "rb" if binary else "r", **({} if binary else {"encoding": "utf-8-sig", "newline": ""})) as f:
        return f.read()


def _is_keys(rel):
    parts = rel.split("/")
    return len(parts) == 3 and parts[1] == "keys" and rel.endswith(".json")


def merge(dest, sources, vanilla=None, strict=False, log=print):
    """Merge each source folder into dest (created if missing) against the game's files. Returns a
    Report; with strict, raises Conflict if any."""
    vanilla = vanilla or P.VANILLA
    rep = Report()
    os.makedirs(dest, exist_ok=True)
    for src in sources:
        name = os.path.basename(os.path.normpath(src))
        for rel, path in sorted(_files(src)):
            out = os.path.join(dest, *rel.split("/"))
            if _is_keys(rel):
                _merge_keys(dest, rel, path, rep, name)
                continue
            if not os.path.exists(out):
                os.makedirs(os.path.dirname(out), exist_ok=True)
                shutil.copy2(path, out)
                rep.copied.append(rel)
                continue
            if _read(out, True) == _read(path, True):
                rep.same.append(rel)
                continue
            base_path = os.path.join(vanilla, *rel.split("/"))
            base = _read(base_path) if os.path.exists(base_path) else None
            conf = []
            if rel.endswith(".json"):
                merged = merge_json(json.loads(base) if base is not None else _MISSING,
                                    json.loads(_read(out)), json.loads(_read(path)), "", conf)
                text = json.dumps(merged, ensure_ascii=False, separators=(",", ":"))
            elif rel.endswith(".csv"):
                text = merge_csv(base, _read(out), _read(path), rel, conf)
            elif rel.endswith(".txt"):
                text = merge_text(base, _read(out), _read(path), rel, conf)
            else:
                conf.append(("", "binary files differ"))
                text = None
            for where, what in conf:
                rep.conflicts.append((rel, f"{name}: {where}", what))
            if text is not None:
                with open(out, "w", encoding="utf-8", newline="") as f:
                    f.write(text)
            rep.merged.append(rel)
    if strict and rep.conflicts:
        raise Conflict("\n".join(f"{r} {w}: {x}" for r, w, x in rep.conflicts[:20]))
    log(f"magicite merge -> {dest}: {rep}")
    return rep


def _merge_keys(dest, rel, path, rep, name):
    group = rel.split("/")[0]
    kdir = os.path.join(dest, group, "keys")
    os.makedirs(kdir, exist_ok=True)
    existing = sorted(f for f in os.listdir(kdir) if f.endswith(".json"))
    target = os.path.join(kdir, existing[0] if existing else os.path.basename(path))
    have = json.loads(_read(target)) if os.path.exists(target) else {"keys": [], "values": []}
    add = json.loads(_read(path))
    pairs = dict(zip(have["keys"], have["values"]))
    for k, v in zip(add["keys"], add["values"]):
        if k in pairs and pairs[k] != v:
            rep.conflicts.append((rel, f"{name}: key {k}", f"{pairs[k]} vs {v}"))
            continue
        if k not in pairs:
            have["keys"].append(k)
            have["values"].append(v)
            pairs[k] = v
    with open(target, "w", encoding="utf-8", newline="\n") as f:
        json.dump(have, f, indent=2)
    rep.merged.append(f"{group}/keys/{os.path.basename(target)}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("magicite_merge.py DEST SOURCE [SOURCE...]  (merged into DEST against the game's files)")
    r = merge(sys.argv[1], sys.argv[2:])
    for c in r.conflicts:
        print("  conflict:", *c)
