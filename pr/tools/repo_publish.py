"""Shared by the public repositories' publish scripts: copy a set of this project's files into a
repository's own git tree, with the checks every public copy gets.

The project keeps three public repositories, one each (the user, 2026-11-19: "the shared kit, WC,
and BNW all need to be separate repos"):

    ff6pr-kit                tools/kit_publish.py    the modding kit: porter, PrKit, prkit, harnesses
    ff6pr-worlds-collide     tools/wc_publish.py     Worlds Collide; the kit as its kit/ submodule
    ff6pr-brave-new-world    tools/bnw_publish.py    Brave New World; the kit as its kit/ submodule
    ff6pr-t-edition          tools/ted_publish.py    T-Edition; the kit as its kit/ submodule

Each lands beside this project (C:/Projects/Gamedev/<name>) with the project's layout (pr/...).
Publishing never touches .git: commit and push from the repository's folder. Publish the kit and
commit it first: a mod repository pins the kit's current commit as its kit/ submodule.

Never the game's files (the mods are distributed): no ROM, no pr/vanilla, no build output, and
every copied file is checked against the game's extract (prkit/package.py game_files_in).
"""
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PR = os.path.dirname(HERE)
PROJECT = os.path.dirname(PR)
sys.path.insert(0, HERE)
from prkit import package  # noqa: E402

KIT_REPO = os.path.join(os.path.dirname(PROJECT), "ff6pr-kit")
KIT_URL = "https://github.com/thomasjteachey/ff6pr-kit.git"

SKIP_DIRS = {"bin", "obj", "__pycache__", ".vs", ".git"}
SKIP_EXT = (".sfc", ".smc", ".pyc", ".bin", ".dll", ".exe", ".pdb", ".zip", ".log")
SKIP_FILES = {"Games.props"}  # this PC's game folders (tools/kit.py games writes it)

# tools/*.py that belong to one mod; everything else in tools/ is the kit's
WC_TOOLS = ["wc_*.py", "snes_doma_siege.py", "port_trace.py", "kitpath.py", "wc_basedata_regions.json"]
BNW_TOOLS = ["port_bnw.py", "bnw_plugin_data.py", "profile_bnw.py", "probe_check.py", "probe_headless.ps1",
             "bnw_publish.py", "bnw_dialog.py", "kitpath.py",
             "port_bnw_*.py", "port_boss_events.py", "ai_fights.py"]   # BNW's scenes/rewards/mechanics/dream, story fights, AI fight runner
OTHER_TOOLS = ["battle_options_test.py", "bo_publish.py",   # Battle Options: its own repository
               "run_tests.ps1",                              # every mod's tests at once: the project's only
               "ff6_deploy_mcp.py",                          # the tracker's Deck button (this PC's desktop app): the project's only
               "owners.py",                                  # who owns a path (pr/OWNERS: this project's sessions): the project's only
               "deck_push.sh", "session_budget.py",          # the user's own test setup (pr/OWNERS): the project's only
               "remote_batch.py"]                            # the user's test machines (their host and address): the project's only
BC_TOOLS = ["bc_*.py", "kitpath.py"]                         # Beyond Chaos: its own repository (to come)
TED_TOOLS = ["ted_*.py", "profile_tedition.py", "kitpath.py"]               # T-Edition: ff6pr-t-edition


def mod_tools(name):
    return any(fnmatch.fnmatch(name, p) for p in WC_TOOLS + BNW_TOOLS + BC_TOOLS + TED_TOOLS + OTHER_TOOLS + ["wc_publish.py"])


def collect(parts, exclude=lambda name: False):
    """(source path, published name) for each part: (folder under the project, patterns), where
    ["**"] is the whole folder and anything else matches files of that folder itself."""
    for src, patterns in parts:
        root = os.path.join(PROJECT, *src.split("/"))
        if patterns != ["**"]:
            for f in sorted(os.listdir(root)):
                p = os.path.join(root, f)
                if (os.path.isfile(p) and not f.startswith(".")   # hidden: staging copies (".deploy_test_batch.sh")
                        and not f.lower().endswith(SKIP_EXT) and f not in SKIP_FILES
                        and any(fnmatch.fnmatch(f, x) for x in patterns) and not exclude(f)):
                    yield p, f"{src}/{f}"
            continue
        for r, dirs, fs in os.walk(root):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            rel_dir = os.path.relpath(r, root).replace("\\", "/")
            for f in sorted(fs):
                if f.lower().endswith(SKIP_EXT) or f in SKIP_FILES:
                    continue
                rel = f if rel_dir == "." else f"{rel_dir}/{f}"
                yield os.path.join(r, f), f"{src}/{rel}"


def manifest(keep):
    """pr/modkit.json with only the mods in keep (each repository's own)."""
    with open(os.path.join(PR, "modkit.json"), encoding="utf-8") as f:
        doc = json.load(f)
    doc["mods"] = {k: v for k, v in doc["mods"].items() if k in keep}
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def head(repo):
    return subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()


# a local user's folder in a published text (C:\Users\<name>\..., /c/Users/<name>): it names the user and only works on
# this PC (the BNW lead, 2026-11-20: cheap insurance). Code reads the user's folder from the environment instead.
USER_PATH = re.compile(r"(?:\b[A-Za-z]:|/[a-z])[\\/]+Users[\\/]+(?!Public\b)[A-Za-z0-9][\w.-]*", re.I)
TEXT_EXT = (".py", ".cs", ".md", ".json", ".sh", ".ps1", ".txt", ".props", ".csproj", ".java", ".tbl", ".yml", ".yaml",
            ".xml", ".cfg", ".ini", ".bat", ".cmd", ".tsv", ".csv")


def user_paths(entries, texts=None):
    """[(published name, the path found)] for every published text naming a local user's folder."""
    found = []
    for src, name in entries:
        if not name.lower().endswith(TEXT_EXT):
            continue
        try:
            with open(src, encoding="utf-8", errors="replace") as f:
                m = USER_PATH.search(f.read())
        except OSError:
            continue
        if m:
            found.append((name, m.group(0)))
    for name, content in (texts or {}).items():
        m = USER_PATH.search(content)
        if m:
            found.append((name, m.group(0)))
    return found


def write(out, entries, texts, submodules=()):
    """Make out's tree afresh (all but .git): the copied entries, the generated texts
    ({published name: content}), and submodules [(path, url, commit)] as gitlinks."""
    entries = list(entries)
    hits = package.game_files_in(entries, os.path.join(PR, "vanilla"))
    if hits:
        raise SystemExit(f"publish: {len(hits)} of the game's own files, not publishing: {hits[:5]}")
    big = [(n, os.path.getsize(s)) for s, n in entries if os.path.getsize(s) > 2 << 20]
    if big:
        raise SystemExit(f"publish: unexpectedly large files: {big}")
    names = [n for _, n in entries] + list(texts)
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise SystemExit(f"publish: published twice: {dupes}")
    personal = user_paths(entries, texts)
    if personal:
        raise SystemExit(f"publish: {len(personal)} file(s) name a local user folder, not publishing: {personal[:8]}")
    os.makedirs(out, exist_ok=True)
    for name in os.listdir(out):
        if name in (".git",):
            continue
        p = os.path.join(out, name)
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    for src, name in entries:
        dst = os.path.join(out, *name.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    if submodules:
        texts = dict(texts)
        texts[".gitmodules"] = "".join(f'[submodule "{path}"]\n\tpath = {path}\n\turl = {url}\n' for path, url, _ in submodules)
    for name, content in texts.items():
        dst = os.path.join(out, *name.split("/"))
        os.makedirs(os.path.dirname(dst) or out, exist_ok=True)
        with open(dst, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
    for path, url, commit in submodules:
        # the submodule's folder stays empty here (a clone fills it: --recurse-submodules)
        os.makedirs(os.path.join(out, *path.split("/")), exist_ok=True)
        if os.path.isdir(os.path.join(out, ".git")):
            subprocess.run(["git", "-C", out, "update-index", "--add", "--cacheinfo", f"160000,{commit},{path}"], check=True)
    size = sum(os.path.getsize(s) for s, _ in entries)
    return f"{len(entries)} files ({size // 1024} KB)" + "".join(f" + {p} at {c[:10]}" for p, _, c in submodules)


GITIGNORE_COMMON = """bin/
obj/
__pycache__/
*.pyc
.venv/
.vs/
pr/vanilla/
pr/build/
pr/cache/
pr/mods/
pr/plugin/PrKit/Games.props
rom/
build/
*.sfc
*.smc
"""

REQUIREMENTS = "UnityPy>=1.20  # tools/extract.py (pr/vanilla from the game's bundles)\nPillow  # tools/snes_harness.py\n"
