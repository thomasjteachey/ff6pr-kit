"""Check Magicite folders before a test run installs or loads them: game-free, a few seconds (tools/test_batch.py's
pre-flight runs it, so a broken folder bounces back before a launch; the modding kit ships it).

    .venv/Scripts/python tools/magicite_check.py FOLDER [FOLDER...] [--vanilla DIR] [--max N] [--quiet]

Each folder (a Magicite mod folder: <group>/Assets/GameAssets/Serial/..., keys/, files of the mod's own):
  * every .json parses;
  * a master table (.csv) has a header and unique ids (its first column); a text file (key<TAB>text lines) has
    each key once;
  * a map package (Res/Map/Map_<id>/package.json): its maps' names are unique, and so are the names in each of a
    map's lists (script, entity, route_instruction); every asset a map names (tilemap, collision, entity_default,
    each script and entity) is a file of this folder or of the game (DIR, default pr/vanilla, the same path);
  * every script or entity file (sc_*.json / ev_*.json) beside a map package is listed by that package (this
    folder's, else the game's): one that isn't never runs ("script ... didn't start (not in this map's list?)",
    T-Edition, 2026-11-20).
Two or more folders: an asset path that two of them ship (the game reads one copy and the other folder's changes
vanish: tools/magicite_merge.py makes one folder of them); keys/*.json and files outside <group>/Assets aside.
Exit 1 with the errors (the first N, default 20, then a count) when there are any; else 0 and a summary line.
"""
import argparse
import csv
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SCRIPTISH = re.compile(r"^(sc|ev)_.+\.json$")
LIST_KEYS = ("script", "entity", "route_instruction")
ASSET_KEYS = ("tilemap", "collision", "entity_default")


def default_vanilla():
    try:
        import prdata as P
        return P.VANILLA
    except Exception:   # (a kit without the game's data: listed assets are then checked in the folder only)
        return None


def walk(folder):
    """relative paths ("/"-separated) of every file under folder"""
    out = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
        for n in files:
            out.append(os.path.relpath(os.path.join(root, n), folder).replace(os.sep, "/"))
    return sorted(out)


def is_asset(rel):
    """a game asset (<group>/Assets/...), not keys/ or a mod's own file"""
    parts = rel.split("/")
    return len(parts) > 2 and parts[1] == "Assets"


class Checker:
    def __init__(self, vanilla=None):
        self.vanilla = vanilla
        self.errors = []
        self.files = 0
        self.game_packages = {}   # the game's map packages read so far: {rel: listed assets or None}

    def err(self, folder, rel, what):
        self.errors.append(f"{os.path.basename(os.path.normpath(folder))}/{rel}: {what}")

    def load_json(self, folder, rel):
        try:
            with open(os.path.join(folder, rel), encoding="utf-8-sig") as f:
                return json.load(f)
        except (OSError, ValueError) as e:
            self.err(folder, rel, f"doesn't parse ({str(e)[:160]})")
            return None

    def game_has(self, rel):
        return bool(self.vanilla) and os.path.isfile(os.path.join(self.vanilla, *rel.split("/")))

    def check_folder(self, folder):
        files = walk(folder)
        self.files += len(files)
        have = set(files)
        packages = {}
        for rel in files:
            low = rel.lower()
            if low.endswith(".json"):
                data = self.load_json(folder, rel)
                if data is not None and rel.endswith("/package.json") and "/Res/Map/" in rel:
                    packages[rel] = data
            elif low.endswith(".csv") and is_asset(rel):
                self.check_csv(folder, rel)
            elif low.endswith(".txt") and "/Message/" in rel:
                self.check_text(folder, rel)
        for rel, data in packages.items():
            self.check_package(folder, rel, data, have)
        # scripts and entities beside a package must be listed by it (this folder's package, else the game's)
        for rel in files:
            name = rel.rsplit("/", 1)[-1]
            if not SCRIPTISH.match(name) or "/Res/Map/" not in rel:
                continue
            parts = rel.split("/")
            if len(parts) < 3:
                continue
            pkg_dir = "/".join(parts[:-2])          # .../Map_20071
            asset = "/".join(parts[-2:])[:-len(".json")]   # Map_20071_1/sc_x
            pkg_rel = pkg_dir + "/package.json"
            listed = self.listed_assets(folder, pkg_rel, packages)
            if listed is None:
                self.err(folder, rel, f"no map package lists it (no {pkg_rel} here or in the game)")
            elif asset not in listed:
                self.err(folder, rel, f"not listed in {pkg_rel} ({'this folder' if pkg_rel in packages else 'the game'}'s): "
                                      f"the map never runs it")

    def listed_assets(self, folder, pkg_rel, packages):
        data = packages.get(pkg_rel)
        if data is None:
            if pkg_rel not in self.game_packages:
                game = None
                if self.game_has(pkg_rel):
                    try:
                        with open(os.path.join(self.vanilla, *pkg_rel.split("/")), encoding="utf-8-sig") as f:
                            game = self.listed_of(json.load(f))
                    except (OSError, ValueError):
                        game = None
                self.game_packages[pkg_rel] = game
            return self.game_packages[pkg_rel]
        return self.listed_of(data)

    @staticmethod
    def listed_of(data):
        out = set()
        for m in data.get("map") or []:
            for k in LIST_KEYS:
                for item in m.get(k) or []:
                    if isinstance(item, dict) and item.get("asset"):
                        out.add(item["asset"])
        return out

    def check_package(self, folder, rel, data, have):
        if not isinstance(data, dict) or not isinstance(data.get("map", []), list):
            self.err(folder, rel, "a map package without a map list")
            return
        pkg_dir = rel[:-len("/package.json")]
        names = [m.get("name") for m in data.get("map") or [] if isinstance(m, dict)]
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            self.err(folder, rel, f"maps named twice: {dup[:5]}")
        for m in data.get("map") or []:
            if not isinstance(m, dict):
                self.err(folder, rel, "a map entry that isn't an object")
                continue
            assets = [m[k] for k in ASSET_KEYS if isinstance(m.get(k), str) and m.get(k)]
            for k in LIST_KEYS:
                items = m.get(k) or []
                inames = [it.get("name") for it in items if isinstance(it, dict)]
                dup = sorted({n for n in inames if inames.count(n) > 1})
                if dup:
                    self.err(folder, rel, f"{m.get('name')}: {k} names listed twice: {dup[:5]}")
                assets += [it["asset"] for it in items if isinstance(it, dict) and it.get("asset")]
            for a in assets:
                f = f"{pkg_dir}/{a}.json"
                if f not in have and not self.game_has(f):
                    self.err(folder, rel, f"{m.get('name')}: lists {a}, which is neither in this folder nor the game's")

    def check_csv(self, folder, rel):
        try:
            with open(os.path.join(folder, rel), encoding="utf-8-sig", newline="") as f:
                rows = list(csv.reader(io.StringIO(f.read())))
        except (OSError, UnicodeDecodeError, csv.Error) as e:
            self.err(folder, rel, f"doesn't read as CSV ({e})")
            return
        if not rows or not rows[0]:
            self.err(folder, rel, "no header")
            return
        if rows[0][0].strip().lower() != "id":
            return   # (a table keyed otherwise: not checked)
        seen, dup = set(), []
        for r in rows[1:]:
            if not r or not r[0].strip():
                continue
            if r[0] in seen:
                dup.append(r[0])
            seen.add(r[0])
        if dup:
            self.err(folder, rel, f"ids twice: {sorted(set(dup))[:8]}")

    def check_text(self, folder, rel):
        try:
            with open(os.path.join(folder, rel), encoding="utf-8-sig") as f:
                lines = f.read().splitlines()
        except (OSError, UnicodeDecodeError) as e:
            self.err(folder, rel, f"doesn't read ({e})")
            return
        keys = [l.split("\t", 1)[0] for l in lines if "\t" in l]
        if len(keys) < len([l for l in lines if l.strip()]) // 2:
            return   # (not key<TAB>text lines)
        seen, dup = set(), []
        for k in keys:
            if k in seen:
                dup.append(k)
            seen.add(k)
        if dup:
            self.err(folder, rel, f"keys twice: {sorted(set(dup))[:8]}")

    def check_across(self, folders):
        owner = {}
        for folder in folders:
            for rel in walk(folder):
                if not is_asset(rel):
                    continue
                if rel in owner:
                    self.errors.append(f"{rel}: in both {os.path.basename(os.path.normpath(owner[rel]))} and "
                                       f"{os.path.basename(os.path.normpath(folder))} (the game reads one: merge them, "
                                       f"tools/magicite_merge.py)")
                else:
                    owner[rel] = folder


def check(folders, vanilla="default"):
    """-> Checker (its .errors) for these folders"""
    c = Checker(default_vanilla() if vanilla == "default" else vanilla)
    for f in folders:
        if not os.path.isdir(f):
            c.errors.append(f"{f}: no such folder")
            continue
        c.check_folder(f)
    if len(folders) > 1:
        c.check_across([f for f in folders if os.path.isdir(f)])
    return c


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("folders", nargs="+")
    ap.add_argument("--vanilla", default="default", help="the game's files (default pr/vanilla); 'none': this folder only")
    ap.add_argument("--max", type=int, default=20)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    c = check(a.folders, None if a.vanilla == "none" else a.vanilla)
    if c.errors:
        for e in c.errors[:a.max]:
            print("  " + e)
        if len(c.errors) > a.max:
            print(f"  ... {len(c.errors) - a.max} more")
        print(f"magicite check: {len(c.errors)} errors in {len(a.folders)} folder(s), {c.files} files")
        return 1
    if not a.quiet:
        print(f"magicite check: ok ({len(a.folders)} folder(s), {c.files} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
