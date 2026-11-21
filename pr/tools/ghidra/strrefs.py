"""Which methods of the PR's GameAssembly.dll use a string literal (e.g. a Japanese debug-log text).

    pr/.venv/Scripts/python pr/tools/ghidra/strrefs.py <text> [<text> ...]

Every string literal has a slot whose RVA is its "address" in tools/il2cpp_out/stringliteral.json; code
loads it with a RIP-relative mov/lea. This scans the DLL's code ("il2cpp" and ".text" sections) for every
disp32 that resolves to one of those slots (any instruction form: the 4 bytes before the next instruction)
and names the method from script.json, with the offset of the use. The game's battle code logs each step
("後ろ向き補正", "背後から攻撃されたため必中"...), so a rule can be found by its text before decompiling.
Found this way (2026-11-20): the hit-in-the-back x1.5 and sure hit are only in CalcExecuteFF6.PhysicalExecution.
Takes a minute or two (a byte-by-byte scan)."""
import bisect
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import callers as C  # noqa: E402  (the DLL path, script.json, the section reader)


def main(texts):
    data = open(C.DLL, "rb").read()
    js = json.load(open(C.SCRIPT, encoding="utf-8"))
    methods = sorted((m["Address"], m["Name"]) for m in js["ScriptMethod"])
    addrs = [a for a, _ in methods]
    lits = json.load(open(os.path.join(C.ROOT, "tools", "il2cpp_out", "stringliteral.json"), encoding="utf-8"))
    targets = {int(l["address"], 16): l["value"] for l in lits if any(t in l["value"] for t in texts)}
    if not targets:
        sys.exit("no string literal contains that text")
    for name, va, raw, size in C.sections(data):
        if name not in (".text", "il2cpp"):
            continue
        code = data[raw:raw + size]
        for k in range(0, len(code) - 4):
            dest = va + k + 4 + struct.unpack_from("<i", code, k)[0]
            if dest in targets:
                site = va + k
                i = bisect.bisect_right(addrs, site) - 1
                a, n = methods[i] if i >= 0 else (0, "?")
                print(f"{targets[dest]!r}: {n} (method {a:#x}, +{site - a:#x})")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1:])
