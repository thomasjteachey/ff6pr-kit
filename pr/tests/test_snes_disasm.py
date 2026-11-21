"""The kit's 65816 disassembler (tools/snes_disasm.py) against code whose meaning is written down:

  * the vanilla listings quoted in BNW's source comments ("; C2/50B3: 20 C9 26     JSR $26C9"):
    the US ROM has those bytes there and the disassembler prints the same instruction;
  * BNW 3.0's own patches (mods/brave-new-world/source/bnw 3.0/asm/*.asm, asar source at US
    addresses): every `org` block of code, read from BNW's built ROM, decodes to the source's
    instructions, immediates at the source's widths (REP/SEP followed), local branches landing on
    the source's labels;
  * the recursive tracer on vanilla's battle bank: no width conflicts, no overlapping decodes, the
    known routines found; JP v1.0 vs US addresses matched by `align`.

Needs the US ROM (skipped without it); the BNW checks need BNW's source and built ROM.

  pr/.venv/Scripts/python -m unittest discover -s pr/tests -p "test_snes_disasm.py" -v
"""
import glob
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PR = os.path.dirname(HERE)
PROJECT = os.path.dirname(PR)
sys.path.insert(0, os.path.join(PR, "tools"))
import snes_disasm as D  # noqa: E402

US_ROMS = [os.path.join(PROJECT, "rom", "vanilla", n) for n in
           ("Final Fantasy III (USA).sfc", "Final Fantasy III (USA) (Rev 1).sfc")]
JP_ROM = os.path.join(PROJECT, "rom", "vanilla", "Final Fantasy VI (Japan).sfc")
BNW_SRC = os.path.join(PROJECT, "mods", "brave-new-world", "source")
BNW3_ASM = os.path.join(BNW_SRC, "bnw 3.0", "asm")
BNW_ROM = os.path.join(PROJECT, "build", "brave-new-world", "Brave New World 3.0 FRC.sfc")
US = next((p for p in US_ROMS if os.path.exists(p)), None)

LISTING = re.compile(r";\s*([C-F][0-9A-F])/([0-9A-F]{4}):?\s+((?:[0-9A-F]{2} ){1,4})\s*([A-Z]{3})\b[ \t]*(\S*)")


def norm(text):
    return re.sub(r"\s+", " ", text.strip().upper())


# --- a small asar reader: enough of the syntax for BNW's patches --------------------------------
ALIASES = {"BLT": "BCC", "BGE": "BCS", "TAD": "TCD", "TDA": "TDC", "TAS": "TCS", "TSA": "TSC",
           "SWA": "XBA", "DEA": "DEC", "INA": "INC"}
REPEATABLE = {"ASL", "LSR", "ROL", "ROR", "INC", "DEC", "INX", "INY", "DEX", "DEY", "NOP", "XBA",
              "TDC", "CLC", "SEC", "PHA", "PLA", "PHX", "PLX", "PHY", "PLY", "TAX", "TXA", "TAY", "TYA"}
MNEMONICS = {mn for mn, _ in D.OPCODES.values()}
STOP = re.compile(r"^(%|incbin|incsrc|macro|endmacro|if|else|endif|freecode|freespace|pushpc|pullpc|"
                  r"pad|skip|base|table|cleartable|fillbyte|padbyte|fill|bank|namespace|struct|endstruct|"
                  r"arch|lorom|exlorom|exhirom|sa1rom|norom|function|while|endwhile|for|endfor|rep\b)", re.I)


def asar_blocks(path):
    """`org` blocks of code in an asar file: [(address, [(label_or_None, mnemonic, operand), ...])].
    A block stops at what this reader doesn't follow (macros, data with expressions, defines it
    can't resolve)."""
    defines = {}
    blocks, cur = [], None
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    for raw in lines:
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"^!(\w+)\s*=\s*(.+)$", line)
        if m:
            defines[m.group(1)] = m.group(2).strip()
            continue
        line = re.sub(r"!(\w+)", lambda mm: defines.get(mm.group(1), mm.group(0)), line)
        m = re.match(r"^org\s+\$?([0-9A-Fa-f]{6})\s*$", line, re.I)
        if m:
            cur = (int(m.group(1), 16), [])
            blocks.append(cur)
            continue
        if re.match(r"^org\b", line, re.I):
            cur = None
            continue
        if cur is None:
            continue
        if re.match(r"^(warnpc|hirom|print|assert|reset|check|math|optimize|warnings)\b", line, re.I):
            continue
        if STOP.match(line):
            cur = None
            continue
        for part in re.split(r"\s+:\s+|\s+:(?=\s*[A-Za-z])", line):
            part = part.strip()
            label = None
            m = re.match(r"^([A-Za-z_][\w.]*|\.[\w.]+|[+\-]+)(:?)\s*(.*)$", part)
            if m and (m.group(2) or m.group(1).startswith(".") or m.group(1)[0] in "+-") \
                    and m.group(1).upper().split(".")[0] not in MNEMONICS:
                label, part = m.group(1), m.group(3).strip()
                cur[1].append((label, None, None))
                if not part:
                    continue
            m = re.match(r"^(db|dw|dl|dd)\s+(.+)$", part, re.I)
            if m:
                vals = [v.strip() for v in m.group(2).split(",")]
                if not all(re.fullmatch(r"\$[0-9A-Fa-f]+|\d+", v) for v in vals):
                    cur = None
                    break
                n = {"db": 1, "dw": 2, "dl": 3, "dd": 4}[m.group(1).lower()]
                cur[1].append((None, "DATA", n * len(vals)))
                continue
            m = re.match(r"^([A-Za-z]{3})(\.[bwlBWL])?\b\s*(.*)$", part)
            if not m or (m.group(1).upper() not in MNEMONICS and m.group(1).upper() not in ALIASES):
                cur = None
                break
            mn = m.group(1).upper()
            mn = ALIASES.get(mn, mn)
            suffix = (m.group(2) or "").lower()
            op = m.group(3).strip()
            if suffix == ".l" and mn in ("JMP", "JSR"):
                mn = "JML" if mn == "JMP" else "JSL"
            rm = re.fullmatch(r"#(\d+)", op)
            if mn in REPEATABLE and rm:
                cur[1].extend([(None, mn, "")] * int(rm.group(1)))
                continue
            if op.upper() == "A":
                op = ""
            cur[1].append((None, mn, op + ("@" + suffix if suffix else "")))
        if cur is None:
            continue
    return [b for b in blocks if any(mn not in (None, "DATA") for _, mn, _ in b[1])]


def literal(op):
    """The source operand in the disassembler's spelling, or None if it names a label/expression."""
    op = op.split("@")[0].replace(" ", "")
    if not op:
        return ""
    m = re.fullmatch(r"#\$([0-9A-Fa-f]+)", op)
    if m:
        return "#$" + m.group(1).upper()
    m = re.fullmatch(r"([(\[]?)\$([0-9A-Fa-f]+)((?:,[XxYySs])?[)\]]?(?:,[XxYy])?)", op)
    if m:
        return (m.group(1) + "$" + m.group(2) + m.group(3)).upper()
    return None


def check_block(rom, addr, items, m8, x8):
    """Walk the source and the ROM together from `addr`: (matched, total, first mismatch)."""
    labels, branches = {}, []
    pc, total, ok = addr, 0, 0
    stack = []
    for label, mn, op in items:
        if mn is None:
            labels.setdefault(label, []).append(pc)
            continue
        if mn == "DATA":
            pc += op
            continue
        total += 1
        i = D.decode(rom, pc, m8, x8)
        if i.mn != mn:
            return ok, total, f"{D.snes_str(pc)}: ROM {i.text}, source {mn} {op}"
        lit = literal(op)
        if lit is not None:
            mine = i.operand.upper()
            if i.mode in (D.REL, D.RELL):
                if re.fullmatch(r"\$[0-9A-F]{1,2}", lit or "") and int(lit[1:], 16) == i.value:
                    lit = None          # xkas-style relative offset ("BRA $02")
                else:
                    lit = lit and "$" + lit[-4:]
        if lit is not None:
            if lit and lit.startswith("#") and len(lit) != len(mine):
                return ok, total, f"{D.snes_str(pc)}: width: ROM {i.text}, source {mn} {op}"
            if lit and mine.lstrip("#$").lstrip("0") != lit.lstrip("#$").lstrip("0") and \
                    mine.replace("$", "").lstrip("#") != lit.replace("$", "").lstrip("#"):
                if not (i.mode in (D.ABS, D.ABSX, D.ABSY, D.DP, D.DPX) and int(re.sub(r"[^0-9A-F]", "", lit) or "0", 16) & 0xFFFF == (i.value or 0)):
                    return ok, total, f"{D.snes_str(pc)}: operand: ROM {i.text}, source {mn} {op}"
        elif i.mode in (D.REL, D.RELL) and op:
            branches.append((pc, i.target, op))
        ok += 1
        if i.mn == "PHP":
            stack.append((m8, x8))
        elif i.mn == "PLP" and stack:
            m8, x8 = stack.pop()
        else:
            m8, x8 = D.apply_flags(i, m8, x8)
        pc = i.next
    for at, target, op in branches:     # local labels: the branch lands where the source puts it
        name = op.split("@")[0]
        if name and name[0] in "+-":
            cands = [a for a in labels.get(name, [])]
            if not cands:
                continue
            good = (min((a for a in cands if a > at), default=None) == target) if name[0] == "+" else \
                (max((a for a in cands if a <= at), default=None) == target)
        elif name in labels and len(labels[name]) == 1:
            good = labels[name][0] == target
        else:
            continue
        if not good:
            return ok, total, f"{D.snes_str(at)}: branch to {D.snes_str(target)}, source label {name}"
    return ok, total, None


@unittest.skipUnless(US, "no US ROM")
class Decoder(unittest.TestCase):
    def test_opcode_table(self):
        self.assertEqual(len(D.OPCODES), 256)
        self.assertEqual(D.OPCODES[0x89], ("BIT", D.IMM_M))
        self.assertEqual(D.OPCODES[0xFC], ("JSR", D.ABSIX))
        self.assertEqual(D.OPCODES[0x5C], ("JML", D.LONG))
        rom = D.Rom(bytes([0xA9, 0x34, 0x12, 0xA2, 0x01, 0x00, 0x80, 0xFE] + [0] * 0x10000), "hirom")
        a8 = D.decode(rom, 0xC00000, m8=True)
        a16 = D.decode(rom, 0xC00000, m8=False)
        self.assertEqual((a8.text, a8.size, a16.text, a16.size), ("LDA #$34", 2, "LDA #$1234", 3))
        self.assertEqual(D.decode(rom, 0xC00003, x8=False).text, "LDX #$0001")
        self.assertEqual(D.decode(rom, 0xC00006).text, "BRA $0006")

    def test_mappers(self):
        r = D.Rom(bytes(0x600000))
        self.assertEqual(r.mapper, "exhirom")
        self.assertEqual(r.offset(0xC21234), 0x021234)
        self.assertEqual(r.offset(0x41EA00), 0x41EA00)
        self.assertEqual(r.offset(0x5F58F0), 0x5F58F0)
        self.assertEqual(r.offset(0x7E0000), None)
        us = D.Rom.load(US)
        self.assertEqual(us.mapper, "hirom")
        self.assertEqual(us.offset(0xC24B5A), 0x024B5A)

    def test_vanilla_listings_in_bnw_source(self):
        """Every '; C2/xxxx: bytes MNEMONIC' line in BNW's source: bytes on the US ROM (v1.0 or
        v1.1), and the same instruction text from the disassembler."""
        files = glob.glob(os.path.join(BNW_SRC, "**", "*.asm"), recursive=True)
        if not files:
            self.skipTest("no BNW source")
        roms = [D.Rom.load(p) for p in US_ROMS if os.path.exists(p)]
        seen, checked = set(), 0
        for path in files:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = LISTING.search(line)
                    if not m:
                        continue
                    addr = int(m.group(1) + m.group(2), 16)
                    raw = bytes(int(b, 16) for b in m.group(3).split())
                    if addr in seen:
                        continue
                    seen.add(addr)
                    rom = next((r for r in roms if r.read(addr, len(raw)) == raw), None)
                    self.assertIsNotNone(rom, f"{os.path.basename(path)}: {line.strip()}: bytes not on the US ROM")
                    op = D.OPCODES[raw[0]]
                    m8 = not (op[1] == D.IMM_M and len(raw) == 3)
                    x8 = not (op[1] == D.IMM_X and len(raw) == 3)
                    i = D.decode(rom, addr, m8, x8)
                    operand = m.group(5) if re.match(r"[#(\[]?\$[0-9A-Fa-f]", m.group(5)) else ""   # a label: mnemonic only
                    want = norm(m.group(4) + " " + operand)
                    got = norm(i.text) if operand or not i.operand else norm(i.mn)
                    self.assertEqual(got, want, f"{os.path.basename(path)}: {line.strip()}")
                    self.assertEqual(i.raw, raw)
                    checked += 1
        self.assertGreaterEqual(checked, 30)


@unittest.skipUnless(os.path.isdir(BNW3_ASM) and os.path.exists(BNW_ROM), "no BNW 3.0 source or ROM")
class BnwPatches(unittest.TestCase):
    def test_org_blocks_decode_as_written(self):
        """BNW 3.0's code blocks (US addresses in banks C0-C4, EE) decode from its built ROM to the
        source instructions with the right widths; most blocks match for one choice of entry widths.
        Blocks that later patches overwrote don't match; the share that must is set below."""
        rom = D.Rom.load(BNW_ROM)
        results = []
        for path in sorted(glob.glob(os.path.join(BNW3_ASM, "*.asm"))):
            if os.path.basename(path).startswith("vnw_"):
                continue            # Vanilla New World's alternatives: not in this build
            for addr, items in asar_blocks(path):
                if not rom.is_rom(addr):
                    continue
                best = None
                for m8 in (True, False):
                    for x8 in (True, False):
                        try:
                            r = check_block(rom, addr, items, m8, x8)
                        except ValueError:
                            continue
                        if best is None or (r[2] is None, r[0]) > (best[2] is None, best[0]):
                            best = r
                if best:
                    results.append((os.path.basename(path), addr, best))
        whole = [r for r in results if r[2][2] is None]
        insns = sum(r[2][1] for r in whole)
        width_bugs = [r for r in results if r[2][2] and "width" in r[2][2]]
        if os.environ.get("SNES_DISASM_VERBOSE"):
            for f, a, (ok, tot, why) in results:
                if why:
                    print(f, D.snes_str(a), ok, tot, why)
        self.assertGreaterEqual(len(results), 100)
        self.assertGreaterEqual(len(whole) / len(results), 0.9, f"{len(whole)} of {len(results)} blocks")
        self.assertGreaterEqual(insns, 2000)
        self.assertLessEqual(len(width_bugs), len(results) // 50, width_bugs[:5])


@unittest.skipUnless(US and os.path.exists(JP_ROM), "no US/JP ROM")
class Tracer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.us = D.Rom.load(US)
        cls.jp = D.Rom.load(JP_ROM)
        entries = [0xC20000, 0xC20003, 0xC20006, 0xC20009]   # the battle bank's jump vector
        cls.us_code = D.trace(cls.us, entries, banks=[0xC2])
        cls.jp_code = D.trace(cls.jp, entries, banks=[0xC2])

    def test_battle_bank_clean(self):
        for code in (self.us_code, self.jp_code):
            self.assertEqual(code.conflicts, [])
            self.assertEqual(code.overlaps, [])
            self.assertGreater(len(code.insns), 10000)

    def test_known_routines(self):
        c = self.us_code
        for r in (0xC24B5A, 0xC24781, 0xC24792, 0xC22D71, 0xC226C9):   # random, multiply, divide, monster load, ...
            self.assertIn(r, c.routines, D.snes_str(r))
        self.assertEqual(c.insns[0xC2000C].text, "PHP")
        self.assertIn(0xCF0000, {t.table & 0xFFFF00 for t in c.routines[0xC22D71].tables} |
                      {t.table for r in c.routines.values() for t in r.tables if t.table == 0xCF0000})
        listing = c.listing(0xC24B5A, 0xC24B70)
        self.assertIn("sub_C24B5A:", listing)

    def test_widths_followed(self):
        """C2/2D71 loads the formation's monster data with 16-bit A (REP #$20) and back."""
        c = self.us_code
        self.assertEqual(c.insns[0xC22D78].text, "LDA $CF8400,X")
        self.assertFalse(c.insns[0xC22D78].m8)
        self.assertTrue(c.insns[0xC22D82].m8)

    def test_jp_us_alignment(self):
        """The JP v1.0 battle bank is US code at shifted addresses: `align` pairs them."""
        a = [self.jp_code.insns[k] for k in sorted(self.jp_code.insns)]
        b = [self.us_code.insns[k] for k in sorted(self.us_code.insns)]
        m = D.align(a, b)
        self.assertGreater(len(m), 0.9 * len(a))
        self.assertEqual(m.get(0xC2000C), 0xC2000C)
        inv = {v: k for k, v in m.items()}
        self.assertIn(0xC24B5A, inv)          # US random() has a JP twin
        self.assertEqual(self.jp.read(inv[0xC24B5A], 8), self.us.read(0xC24B5A, 8))


if __name__ == "__main__":
    unittest.main()
