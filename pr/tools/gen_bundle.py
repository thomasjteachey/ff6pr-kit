"""Building a seed generator a player's install carries (the modding kit's; MODDING.md "A mod's in-game
generator"): the Python it runs on, the pr/tools scripts it needs and their bytecode. A mod's bundle tool
(tools/bc_bundle.py; WC's own is tools/wc_bundle.py, which these came from) adds its randomizer, data and
recipe.

    python_runtime(dst, packages)   CPython copied from this PC's install (the venv's base; no download): runs
                                    on Windows and under Proton on the Steam Deck; `packages`: site-packages
                                    folders to carry too (e.g. Pillow's PIL), with their license files
    generator_tools(entry, skip)    the tool modules the entry scripts import or start, transitively
    copy_tools(dst, entry, skip)    those, copied
    precompile(gen, dirs)           bytecode by the bundled Python (seconds per seed saved, more under Wine)
    no_roms(out)                    refuses a bundle with an SNES ROM in it (the mod is distributed)
"""
import ast
import fnmatch
import glob
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import kitpath  # noqa: E402,F401
except ImportError:   # the kit repository alone has none (its tools are already on the path)
    pass

# not needed to run scripts that use the standard library (and the packages carried)
LIB_SKIP = {"site-packages", "test", "tests", "tkinter", "idlelib", "turtledemo", "ensurepip", "lib2to3",
            "pydoc_data", "__pycache__", "venv", "unittest", "distutils"}
# CPython's own test extensions (_testcapi, _ctypes_test, ...): nothing imports them outside its test suite
DLL_SKIP = ["_tkinter*", "tcl*", "tk*", "*.ico", "*.cat", "_test*", "_ctypes_test*"]
# a plugin starts python.exe with no window (PrKit/Seeds/SeedGenerator.cs): pythonw.exe is unused
EXE_SKIP = {"pythonw.exe"}


def copytree(src, dst, skip_dirs=(), skip_files=()):
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
        rel = os.path.relpath(root, src)
        os.makedirs(os.path.join(dst, rel), exist_ok=True)
        for f in files:
            if any(fnmatch.fnmatch(f, p) for p in skip_files):
                continue
            shutil.copy2(os.path.join(root, f), os.path.join(dst, rel, f))


def size(path):
    return sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(path) for f in fs)


def python_runtime(dst, packages=()):
    base = sys.base_prefix
    os.makedirs(dst, exist_ok=True)
    for f in os.listdir(base):
        if f.lower().endswith((".exe", ".dll")) and not f.lower().startswith(("tcl", "tk")) and f.lower() not in EXE_SKIP:
            shutil.copy2(os.path.join(base, f), os.path.join(dst, f))
    copytree(os.path.join(base, "DLLs"), os.path.join(dst, "DLLs"), skip_files=DLL_SKIP)
    copytree(os.path.join(base, "Lib"), os.path.join(dst, "Lib"), skip_dirs=LIB_SKIP)
    copytree(os.path.join(base, "Lib", "unittest"), os.path.join(dst, "Lib", "unittest"), skip_dirs={"test", "__pycache__"})
    # the PSF license asks that its notice ships with any copy of Python
    shutil.copy2(os.path.join(base, "LICENSE.txt"), os.path.join(dst, "LICENSE.txt"))
    site = os.path.join(sys.prefix, "Lib", "site-packages")
    for pkg in packages:
        copytree(os.path.join(site, pkg), os.path.join(dst, "Lib", "site-packages", pkg), skip_dirs={"__pycache__"})
        for info in glob.glob(os.path.join(site, f"{pkg}*.dist-info")) + \
                [d for d in glob.glob(os.path.join(site, "*.dist-info"))
                 if os.path.exists(os.path.join(d, "top_level.txt")) and
                 pkg in open(os.path.join(d, "top_level.txt"), encoding="utf-8").read().split()]:
            # its license (and METADATA: name, version), beside it
            copytree(info, os.path.join(dst, "Lib", "site-packages", os.path.basename(info)), skip_files=["RECORD"])
    return f"Python {sys.version.split()[0]} from {base}" + (f" + {', '.join(packages)}" if packages else "")


def tool_dirs():
    """{module: folder} for every tool script: this folder's and, when the modding kit is this repository's
    kit/ submodule, the kit's (kitpath.TOOLS); this folder's win."""
    out = {}
    for d in [x for x in (getattr(kitpath, "TOOLS", None), HERE) if x]:
        out.update({f[:-3]: d for f in os.listdir(d) if f.endswith(".py")})
    return out


def generator_tools(entry, skip=()):
    """Tool modules the generator needs: `entry` plus every module of the tools folders they import (anywhere
    in the file, lazy imports too) or name as a script ("bc_run.py"), but `skip` (other mods' modules)."""
    local = tool_dirs()
    seen, todo = set(), list(entry)
    while todo:
        mod = todo.pop()
        if mod in seen:
            continue
        seen.add(mod)
        with open(os.path.join(local[mod], mod + ".py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                names = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                names = [n.module]
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) and re.fullmatch(r"\w+\.py", n.value):
                names = [n.value[:-3]]
            else:
                continue
            todo += [m.split(".")[0] for m in names if m.split(".")[0] in local and m.split(".")[0] not in skip]
    return sorted(seen)


def copy_tools(dst, entry, skip=()):
    os.makedirs(dst, exist_ok=True)
    needed = generator_tools(entry, skip)
    where = tool_dirs()
    for mod in needed:
        shutil.copy2(os.path.join(where[mod], mod + ".py"), dst)
    # the kit's own package (tools/prkit: games, paths) when a tool imports it
    for mod in needed:
        pk = os.path.join(where[mod], "prkit")
        if os.path.isdir(pk) and not os.path.isdir(os.path.join(dst, "prkit")):
            copytree(pk, os.path.join(dst, "prkit"), skip_dirs={"__pycache__"})
    return needed, len(where)


def precompile(gen, dirs):
    subprocess.run([os.path.join(gen, "python", "python.exe"), "-m", "compileall", "-q", "-j", "0"] +
                   [os.path.join(gen, d) for d in dirs], check=False, capture_output=True)


def no_roms(out):
    roms = [os.path.join(r, f) for r, _, fs in os.walk(out) for f in fs if f.lower().endswith((".sfc", ".smc", ".fig", ".swc"))]
    if roms:
        raise SystemExit(f"bundle: SNES ROMs in the bundle, not shipping: {roms[:3]}")


def clean_bytecode(root):
    for r, dirs, _ in os.walk(root):
        for d in [d for d in dirs if d == "__pycache__"]:
            shutil.rmtree(os.path.join(r, d), ignore_errors=True)
