"""Compile-check C# files against the live kit before they go into plugin/PrKit (where every plugin compiles them
at once: a kit file saved with an error breaks every session's build).

    .venv/Scripts/python tools/kit_cs_check.py MyNewFile.cs [More.cs ...]     (files anywhere, e.g. your scratch folder)
    .venv/Scripts/python tools/kit_cs_check.py --replace plugin/PrKit/Ff6/SnesAtb.cs:C:/scratch/SnesAtb.cs

A throwaway project (in a temp folder) imports plugin/PrKit/PrKit.props with every part on (Ff6, Seeds, Snes) and
compiles the kit plus the given files; --replace KIT_FILE:NEW_FILE compiles NEW_FILE in KIT_FILE's place (an edit
checked before it's saved over the kit's copy). Debug, nothing installed, no plugin's obj touched. Exit 0 when it
compiles; the compiler's errors are printed otherwise. A plugin's own files aren't in it: after moving the file in,
build the plugins that use it (pr/MODDING.md, the kit lead's rule: all five FF6 plugins with -c Debug).
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

PR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PROPS = os.path.join(PR, "plugin", "PrKit", "PrKit.props")

PROJECT = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <PrGame>ff6</PrGame>
    <PrKitSeeds>true</PrKitSeeds>
    <PrKitSnes>true</PrKitSnes>
    <AssemblyName>KitCsCheck</AssemblyName>
    <OutputType>Library</OutputType>
    <EnableDefaultCompileItems>false</EnableDefaultCompileItems>
  </PropertyGroup>
  <Import Project="{props}" />
  <ItemGroup>
{removes}{includes}  </ItemGroup>
</Project>
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="new C# files to compile with the kit")
    ap.add_argument("--replace", action="append", default=[], metavar="KIT_FILE:NEW_FILE",
                    help="compile NEW_FILE instead of the kit's KIT_FILE (path relative to pr/ or absolute)")
    ap.add_argument("--keep", action="store_true", help="keep the temp project (its path is printed)")
    a = ap.parse_args(argv)
    if not a.files and not a.replace:
        ap.error("name a file (or --replace KIT_FILE:NEW_FILE)")
    removes, includes = [], []
    for f in a.files:
        includes.append(os.path.abspath(f))
    for r in a.replace:
        parts = re.split(r":(?![\\/])", r)   # not a drive letter's colon (C:/, C:\)
        if len(parts) != 2 or not all(parts):
            ap.error(f"--replace wants KIT_FILE:NEW_FILE, got {r!r}")
        kit, new = parts
        kit = kit if os.path.isabs(kit) else os.path.join(PR, kit)
        removes.append(os.path.abspath(kit))
        includes.append(os.path.abspath(new))
    missing = [p for p in includes if not os.path.isfile(p)]
    if missing:
        sys.exit(f"kit_cs_check: no such file: {missing}")
    tmp = tempfile.mkdtemp(prefix="kit_cs_check_")
    try:
        with open(os.path.join(tmp, "KitCsCheck.csproj"), "w", encoding="utf-8") as f:
            f.write(PROJECT.format(
                props=PROPS,
                removes="".join(f'    <Compile Remove="{p}" />\n' for p in removes),
                includes="".join(f'    <Compile Include="{p}" />\n' for p in includes)))
        r = subprocess.run(["dotnet", "build", "-c", "Debug", "-nologo", "-v", "q"], cwd=tmp,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        out = r.stdout + r.stderr
        errors = sorted({line.strip() for line in out.splitlines() if ": error " in line})
        if r.returncode == 0:
            print(f"kit_cs_check: compiles with the kit ({len(includes)} file(s))")
        else:
            print("\n".join(errors) if errors else out[-3000:])
            print(f"kit_cs_check: FAILED ({len(errors)} error line(s))")
        return r.returncode
    finally:
        if a.keep:
            print("kept:", tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
