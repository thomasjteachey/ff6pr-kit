"""Hook audit: every game method a plugin hooks with Harmony, checked against the game's machine code before a
game run. Dev only: it needs the game's GameAssembly.dll and Il2CppDumper's dump.cs (its RVAs and file offsets);
without them it says so and passes.

The two ways a hook breaks the game (PrKit/Hooks.cs, rules 1 and the short-code note):
  - shared code: the linker folds identical bodies (identical-code folding), so a hook on one method runs for every
    method with that body; one in another class hands the hook that class's objects. Hooks.Patch refuses it at run
    time (Hooks.SharedWith), so the hook is off; a raw Harmony call (harmony.Patch(...)) isn't checked at all
    (Worlds Collide's WcTrack, 2026-11-21: a 4-byte setter body seventeen methods share).
  - tiny code (a ret, a jump, a ret in the first 6 bytes: Hooks.TinyNativeCode) and short code with a short jump
    inside it (Hooks.ShortNativeCode: a detour moves the jump into the padding).
A hook site is found in the plugins' C# by its method: AccessTools.Method / DeclaredMethod / Property(Getter|Setter)
(typeof(X), "M" or nameof(..M)), Hooks.Patch(h, typeof(X), "M", ...), a variable holding one, and a foreach over
("M", ...) tuples with a typeof variable. "guarded" = it reaches Hooks.Patch (refused at run time: the hook is off),
"raw" = a Harmony instance's own Patch (nothing checks it), "other" = a helper of the file's own.

A finding exits 1. A comment "hook-audit: <why>" on the patch call's line or the 3 lines above it accepts it (a raw
hook on shared code whose hook checks its instance with Hooks.IsA, say).

    .venv/Scripts/python tools/hook_audit.py [--dump dump.cs] [--dll GameAssembly.dll] [--plugins plugin] [-v]
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PR = os.path.dirname(HERE)

RVA = re.compile(r"// RVA: 0x([0-9A-Fa-f]+) Offset: 0x([0-9A-Fa-f]+)")
CLASS = re.compile(r"^(?:[a-z]+ )*(?:class|struct|interface|enum) ([^\s:]+)")
NAME = r'(?:"(\w+)"|nameof\(\s*[\w.]*?(\w+)\s*\)|(\w+))'
TYPE = r"(?:typeof\(\s*(?:global::)?([\w.]+)\s*\)|(\w+))"
ACCESS = re.compile(r"AccessTools\.(Method|DeclaredMethod|PropertyGetter|PropertySetter|DeclaredPropertyGetter|"
                    r"DeclaredPropertySetter)\(\s*" + TYPE + r"\s*,\s*" + NAME)
HOOKS_TYPE = re.compile(r"Hooks\.Patch\(\s*\w+\s*,\s*" + TYPE + r"\s*,\s*" + NAME + r"\s*,\s*typeof")
HOOKS_METHOD = re.compile(r"Hooks\.Patch\(\s*\w+\s*,\s*(\w+)\s*,\s*typeof")
RAW = re.compile(r"\b(\w+)\.Patch\(\s*(AccessTools\.|\w+\s*,)")
OTHER = re.compile(r"\b(?!Patch\b)(\w+)\(\s*\w+\s*,\s*typeof\(\s*(?:global::)?([\w.]+)\s*\)\s*,\s*" + NAME)
MARK = "hook-audit:"


def strip_generic(name):
    return re.sub(r"<[^<>]*>$", "", name)


class Dump:
    """dump.cs: methods by (class, name) and by RVA. A class is "Namespace.Name" (nested: Il2CppDumper's "Outer.Inner")."""

    def __init__(self, text):
        self.by_name, self.by_rva, self.classes = {}, {}, set()
        ns, cls, pending = "", None, None
        for line in text.splitlines():
            if line.startswith("// Namespace:"):
                ns = line.split(":", 1)[1].strip()
                continue
            m = CLASS.match(line)
            if m:
                cls = (ns + "." if ns else "") + strip_generic(m.group(1))
                self.classes.add(cls)
                continue
            m = RVA.search(line)
            if m:
                pending = (int(m.group(1), 16), int(m.group(2), 16))
                continue
            if pending and cls:
                n = re.search(r"([^\s(]+)\(", line)
                if n:
                    name = strip_generic(n.group(1))
                    rva, off = pending
                    entry = (cls, name, line.strip(), rva, off)
                    self.by_name.setdefault((cls, name), []).append(entry)
                    self.by_rva.setdefault(rva, []).append(entry)
                pending = None

    def find_classes(self, name, usings=(), aliases=None):
        """The dump classes a C# type name can be: an alias's target (using X = A.B;), the full name, a nested class
        (Il2CppDumper lists Outer.Inner with no namespace: "Last.Interpreter.Instructions.External.Item" is
        "External.Item"), else every class of that short name (narrowed to the file's using namespaces when that
        leaves some)."""
        name = name.replace("global::", "")
        name = (aliases or {}).get(name, name)
        if name in self.classes:
            return [name]
        nested = [c for c in self.classes if name.endswith("." + c) and "." in c]
        if nested:
            return nested
        short = [c for c in self.classes if c.endswith("." + name) or c == name]
        narrowed = [c for c in short if c.rsplit(".", 1)[0] in usings]
        return narrowed or short


def body(data, off):
    """(length up to its ret and padding, or None; tiny: Hooks.TinyNativeCode's reason; short: ShortNativeCode's)."""
    code = data[off:off + 64]
    if len(code) < 8:
        return None, None, None
    tiny = None
    if code[0] == 0xC3:
        tiny = "empty (ret)"
    elif code[0] in (0xE9, 0xEB) or code[:3] == b"\x48\xff\x25":
        tiny = "a jump"
    else:
        for i in range(1, 6):
            if code[i] == 0xC3:
                tiny = f"{i + 1} bytes"
                break
    length = next((i + 1 for i in range(len(code) - 1) if code[i] == 0xC3 and (code[i + 1] == 0xCC or (off + i + 1) % 16 == 0)), None)
    short = None
    end = next((i for i in range(1, 24) if code[i] == 0xC3 and code[i + 1] == 0xCC), -1)
    for i in range(0, max(end - 1, 0)):
        if 0x70 <= code[i] <= 0x7F or code[i] == 0xEB:
            to = i + 2 + (code[i + 1] - 256 if code[i + 1] > 127 else code[i + 1])
            if 0 < to <= end:
                short = f"{end + 1} bytes with a short jump at byte {i} to byte {to}"
                break
    return length, tiny, short


def _last_assign(text, var, before, pattern):
    found = None
    for m in re.finditer(r"\b" + re.escape(var) + r"\s*=\s*" + pattern, text):
        if m.start() < before:
            found = m
    return found


def _names(text, name_groups, before):
    """A NAME match's method names: the literal, or a foreach variable's tuple/array strings."""
    lit, nameof, var = name_groups
    if lit or nameof:
        return [lit or nameof]
    loops = [m for m in re.finditer(r"foreach\s*\(\s*var\s*\(?\s*" + re.escape(var) + r"\b[^)]*\)?\s*in\s*new\s*[\w()]*\s*\[\]\s*\{(.*?)\}\s*\)",
                                    text, re.S) if m.start() < before]
    if not loops:
        return []
    return re.findall(r'(?:\(\s*)?"(\w+)"\s*[,)}]', loops[-1].group(1))


def _types(text, type_groups, before):
    full, var = type_groups
    if full:
        return full
    m = _last_assign(text, var, before, r"typeof\(\s*(?:global::)?([\w.]+)\s*\)")
    return m.group(1) if m else None


def _ref_targets(text, m, before):
    """AccessTools match -> [(type name, method name)]."""
    kind = m.group(1)
    t = _types(text, (m.group(2), m.group(3)), before)
    names = _names(text, (m.group(4), m.group(5), m.group(6)), before)
    pre = "get_" if kind.endswith("Getter") else "set_" if kind.endswith("Setter") else ""
    return [(t, pre + n) for n in names] if t else []


def sites(root):
    """Every hook site in the plugins: (file, line, how, type name, method name, (usings, aliases), accepted reason)."""
    out = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ("obj", "bin")]
        for fn in files:
            if not fn.endswith(".cs"):
                continue
            path = os.path.join(dirpath, fn)
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            if "Patch" not in text:
                continue
            usings = {u for u in re.findall(r"^using\s+([\w.]+)\s*;", text, re.M)}
            aliases = dict(re.findall(r"^using\s+(\w+)\s*=\s*(?:global::)?([\w.]+)\s*;", text, re.M))
            lines = text.splitlines()

            def line_of(pos):
                return text.count("\n", 0, pos) + 1

            def accepted(ln):
                for k in range(max(0, ln - 4), ln):
                    if MARK in lines[k]:
                        return lines[k].split(MARK, 1)[1].strip()
                return None

            def add(pos, how, targets):
                ln = line_of(pos)
                for t, n in targets:
                    out.append((path, ln, how, t, n, (usings, aliases), accepted(ln)))

            seen = set()
            for m in HOOKS_TYPE.finditer(text):
                t = _types(text, (m.group(1), m.group(2)), m.start())
                if t:
                    add(m.start(), "guarded", [(t, n) for n in _names(text, (m.group(3), m.group(4), m.group(5)), m.start())])
                seen.add(m.start())
            for pat, how in ((HOOKS_METHOD, "guarded"), (RAW, "raw")):
                for m in pat.finditer(text):
                    if how == "raw" and m.group(1) == "Hooks":
                        continue
                    if how == "raw":
                        head = text[m.end(1) + 7:]
                        inline = ACCESS.match(head.lstrip())
                        if inline:
                            add(m.start(), how, _ref_targets(text, inline, m.start()))
                            continue
                        var = re.match(r"\s*(\w+)", head).group(1)
                    else:
                        var = m.group(1)
                    a = _last_assign(text, var, m.start(), r"(AccessTools\.\w+\([^;]*\))")
                    if a:
                        r = ACCESS.match(a.group(1))
                        if r:
                            add(m.start(), how, _ref_targets(text, r, a.start()))
            for m in OTHER.finditer(text):
                if m.group(1) in ("Method", "DeclaredMethod", "PropertyGetter", "PropertySetter") or \
                        any(abs(m.start() - s) < 40 for s in seen):
                    continue
                add(m.start(), "other:" + m.group(1), [(m.group(2), n) for n in _names(text, (m.group(3), m.group(4), m.group(5)), m.start())])
    return out


def audit(dump, data, found, log=print, verbose=False):
    """Findings (strings) for the hook sites; the rest logged when verbose."""
    findings = []
    for path, ln, how, tname, mname, (usings, aliases), ok in found:
        where = f"{os.path.relpath(path, PR)}:{ln}"
        classes = dump.find_classes(tname, usings, aliases)
        entries = [e for c in classes for e in dump.by_name.get((c, mname), [])]
        if not entries:
            if verbose:
                log(f"  ?  {where} {how} {tname}.{mname}: not in the dump (inherited, or not a game method)")
            continue
        for cls, name, sig, rva, off in entries:
            length, tiny, short = body(data, off)
            others = [e for e in dump.by_rva.get(rva, []) if e[0] != cls]
            twins = [e for e in dump.by_rva.get(rva, []) if e[0] == cls and e[1] != name]
            problem = []
            if tiny:
                problem.append(f"tiny code ({tiny})")
            if others:
                problem.append(f"code shared with {len(others)} other classes' methods: " +
                               ", ".join(f"{e[0].rsplit('.', 1)[-1]}.{e[1]}" for e in others[:4]) + (" ..." if len(others) > 4 else ""))
            if short and how != "guarded":
                problem.append(f"short code ({short})")
            what = f"{where} {how} {cls}.{name} (RVA 0x{rva:X}, {length or '?'} bytes)"
            if not problem:
                if verbose:
                    note = f"; same-class twin {', '.join(e[1] for e in twins)}" if twins else ""
                    log(f"  ok {what}{note}")
                continue
            effect = "Hooks.Patch refuses it: the hook is off" if how == "guarded" and (tiny or others) else \
                "nothing checks a raw hook" if how == "raw" else "check the helper"
            line = f"{what}: {'; '.join(problem)} ({effect})"
            if ok:
                log(f"  accepted {line} [{ok}]")
            else:
                findings.append(line)
    return findings


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dump", default=os.path.join(os.path.dirname(PR), "tools", "il2cpp_out", "dump.cs"))
    ap.add_argument("--dll")
    ap.add_argument("--plugins", default=os.path.join(PR, "plugin"))
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    dll = a.dll
    if not dll:
        try:
            sys.path.insert(0, HERE)
            from prkit import games
            g = games.get("ff6")
            dll = os.path.join(g.install, "GameAssembly.dll") if g.installed else None
        except Exception:  # noqa: BLE001
            dll = None
    if not (dll and os.path.exists(dll) and os.path.exists(a.dump)):
        print(f"hook audit skipped: needs the dump ({a.dump}) and GameAssembly.dll ({dll or 'no FF6 install found'})")
        return 0
    with open(a.dump, encoding="utf-8", errors="replace") as fh:
        dump = Dump(fh.read())
    with open(dll, "rb") as fh:
        data = fh.read()
    found = sites(a.plugins)
    findings = audit(dump, data, found, verbose=a.verbose)
    for f in findings:
        print("  FINDING " + f)
    print(f"hook audit: {len(found)} hook sites, {len(findings)} findings")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
