"""65816 disassembler for SNES ROMs (kit tool: T-Edition's battle code, Beyond Chaos's assembly
patches, BNW checks; pr/MODDING.md "SNES disassembler").

    .venv/Scripts/python tools/snes_disasm.py ROM C2/50B3 [-n 20 | --to C2/5100] [--m16] [--x16]
    .venv/Scripts/python tools/snes_disasm.py ROM C2/2C3B --trace [--no-calls] [--db 7E]

Library:

    import snes_disasm as D
    rom = D.Rom.load(path)                       # HiROM / ExHiROM / LoROM from the size and header
    for i in D.linear(rom, 0xC250B3, count=8):   # straight down, REP/SEP followed
        print(i)                                 # "C2/50B3: 20 C9 26     JSR $26C9"
    code = D.trace(rom, [0xC22C3B], m8=True, x8=True)   # recursive: branches, JSR/JSL, jump tables
    print(code.listing())                        # labels, cross-references, table reads
    code.routines[0xC22C3B].calls                # JSR/JSL targets; .tables: ROM tables it reads

Flags: m8 / x8 = the M and X bits of P (True = 8-bit A / 8-bit X,Y). The tracer follows REP, SEP,
PHP/PLP pairs, XCE (emulation: 8-bit), and gives a JSR/JSL the callee's exit widths when every return
of the callee has the same ones (else the caller's). A routine reached with other widths than the
first time is a conflict (Code.conflicts): the first decoding stays. Hints: `widths={addr: (m8, x8)}`
forces widths at an address; `tables={addr: n}` sizes a jump table (else entries are read until one
points outside the bank's code or the table runs into code); `stop={addr}` ends a path (data that
follows a JSR, a known non-returning call).

Text follows the FF6 community listings (Assassin / Terii Senshi, the comments in BNW's source):
operands in hex with $, branch targets as the in-bank address, accumulator forms bare ("ASL"), long
operands as 6 digits ("$D85000,X").
"""
import argparse
import os
import sys
from collections import defaultdict

# --- addressing modes: name -> (operand bytes, format); "m"/"x" = 1 or 2 bytes by the width flags
IMP, ACC, IMM_M, IMM_X, IMM8, IMM16 = "imp", "acc", "imm_m", "imm_x", "imm8", "imm16"
DP, DPX, DPY, DPI, DPIX, DPIY, DPIL, DPILY = "dp", "dp,x", "dp,y", "(dp)", "(dp,x)", "(dp),y", "[dp]", "[dp],y"
ABS, ABSX, ABSY, ABSI, ABSIX, ABSIL = "abs", "abs,x", "abs,y", "(abs)", "(abs,x)", "[abs]"
LONG, LONGX, REL, RELL, SR, SRIY, MOVE = "long", "long,x", "rel", "rell", "sr,s", "(sr,s),y", "move"

SIZE = {IMP: 0, ACC: 0, IMM8: 1, IMM16: 2, DP: 1, DPX: 1, DPY: 1, DPI: 1, DPIX: 1, DPIY: 1, DPIL: 1,
        DPILY: 1, ABS: 2, ABSX: 2, ABSY: 2, ABSI: 2, ABSIX: 2, ABSIL: 2, LONG: 3, LONGX: 3, REL: 1,
        RELL: 2, SR: 1, SRIY: 1, MOVE: 2}

_GROUP = {   # the eight ALU opcodes share one layout: base + mode offset
    0x01: DPIX, 0x03: SR, 0x05: DP, 0x07: DPIL, 0x09: IMM_M, 0x0D: ABS, 0x0F: LONG, 0x11: DPIY,
    0x12: DPI, 0x13: SRIY, 0x15: DPX, 0x17: DPILY, 0x19: ABSY, 0x1D: ABSX, 0x1F: LONGX}


def _opcodes():
    t = {}
    for base, mn in ((0x00, "ORA"), (0x20, "AND"), (0x40, "EOR"), (0x60, "ADC"), (0x80, "STA"),
                     (0xA0, "LDA"), (0xC0, "CMP"), (0xE0, "SBC")):
        for off, mode in _GROUP.items():
            t[base + off] = (mn, mode)
    del t[0x89]                                   # STA # doesn't exist: 89 is BIT #
    rest = {
        0x00: ("BRK", IMM8), 0x02: ("COP", IMM8), 0x04: ("TSB", DP), 0x06: ("ASL", DP), 0x08: ("PHP", IMP),
        0x0A: ("ASL", ACC), 0x0B: ("PHD", IMP), 0x0C: ("TSB", ABS), 0x0E: ("ASL", ABS), 0x10: ("BPL", REL),
        0x14: ("TRB", DP), 0x16: ("ASL", DPX), 0x18: ("CLC", IMP), 0x1A: ("INC", ACC), 0x1B: ("TCS", IMP),
        0x1C: ("TRB", ABS), 0x1E: ("ASL", ABSX), 0x20: ("JSR", ABS), 0x22: ("JSL", LONG), 0x24: ("BIT", DP),
        0x26: ("ROL", DP), 0x28: ("PLP", IMP), 0x2A: ("ROL", ACC), 0x2B: ("PLD", IMP), 0x2C: ("BIT", ABS),
        0x2E: ("ROL", ABS), 0x30: ("BMI", REL), 0x34: ("BIT", DPX), 0x36: ("ROL", DPX), 0x38: ("SEC", IMP),
        0x3A: ("DEC", ACC), 0x3B: ("TSC", IMP), 0x3C: ("BIT", ABSX), 0x3E: ("ROL", ABSX), 0x40: ("RTI", IMP),
        0x42: ("WDM", IMM8), 0x44: ("MVP", MOVE), 0x46: ("LSR", DP), 0x48: ("PHA", IMP), 0x4A: ("LSR", ACC),
        0x4B: ("PHK", IMP), 0x4C: ("JMP", ABS), 0x4E: ("LSR", ABS), 0x50: ("BVC", REL), 0x54: ("MVN", MOVE),
        0x56: ("LSR", DPX), 0x58: ("CLI", IMP), 0x5A: ("PHY", IMP), 0x5B: ("TCD", IMP), 0x5C: ("JML", LONG),
        0x5E: ("LSR", ABSX), 0x60: ("RTS", IMP), 0x62: ("PER", RELL), 0x64: ("STZ", DP), 0x66: ("ROR", DP),
        0x68: ("PLA", IMP), 0x6A: ("ROR", ACC), 0x6B: ("RTL", IMP), 0x6C: ("JMP", ABSI), 0x6E: ("ROR", ABS),
        0x70: ("BVS", REL), 0x74: ("STZ", DPX), 0x76: ("ROR", DPX), 0x78: ("SEI", IMP), 0x7A: ("PLY", IMP),
        0x7B: ("TDC", IMP), 0x7C: ("JMP", ABSIX), 0x7E: ("ROR", ABSX), 0x80: ("BRA", REL), 0x82: ("BRL", RELL),
        0x84: ("STY", DP), 0x86: ("STX", DP), 0x88: ("DEY", IMP), 0x89: ("BIT", IMM_M), 0x8A: ("TXA", IMP),
        0x8B: ("PHB", IMP), 0x8C: ("STY", ABS), 0x8E: ("STX", ABS), 0x90: ("BCC", REL), 0x94: ("STY", DPX),
        0x96: ("STX", DPY), 0x98: ("TYA", IMP), 0x9A: ("TXS", IMP), 0x9B: ("TXY", IMP), 0x9C: ("STZ", ABS),
        0x9E: ("STZ", ABSX), 0xA0: ("LDY", IMM_X), 0xA2: ("LDX", IMM_X), 0xA4: ("LDY", DP), 0xA6: ("LDX", DP),
        0xA8: ("TAY", IMP), 0xAA: ("TAX", IMP), 0xAB: ("PLB", IMP), 0xAC: ("LDY", ABS), 0xAE: ("LDX", ABS),
        0xB0: ("BCS", REL), 0xB4: ("LDY", DPX), 0xB6: ("LDX", DPY), 0xB8: ("CLV", IMP), 0xBA: ("TSX", IMP),
        0xBB: ("TYX", IMP), 0xBC: ("LDY", ABSX), 0xBE: ("LDX", ABSY), 0xC0: ("CPY", IMM_X), 0xC2: ("REP", IMM8),
        0xC4: ("CPY", DP), 0xC6: ("DEC", DP), 0xC8: ("INY", IMP), 0xCA: ("DEX", IMP), 0xCB: ("WAI", IMP),
        0xCC: ("CPY", ABS), 0xCE: ("DEC", ABS), 0xD0: ("BNE", REL), 0xD4: ("PEI", DPI), 0xD6: ("DEC", DPX),
        0xD8: ("CLD", IMP), 0xDA: ("PHX", IMP), 0xDB: ("STP", IMP), 0xDC: ("JML", ABSIL), 0xDE: ("DEC", ABSX),
        0xE0: ("CPX", IMM_X), 0xE2: ("SEP", IMM8), 0xE4: ("CPX", DP), 0xE6: ("INC", DP), 0xE8: ("INX", IMP),
        0xEA: ("NOP", IMP), 0xEB: ("XBA", IMP), 0xEC: ("CPX", ABS), 0xEE: ("INC", ABS), 0xF0: ("BEQ", REL),
        0xF4: ("PEA", IMM16), 0xF6: ("INC", DPX), 0xF8: ("SED", IMP), 0xFA: ("PLX", IMP), 0xFB: ("XCE", IMP),
        0xFC: ("JSR", ABSIX), 0xFE: ("INC", ABSX)}
    t.update(rest)
    assert len(t) == 256, len(t)
    return t


OPCODES = _opcodes()
BRANCHES = {"BPL", "BMI", "BVC", "BVS", "BCC", "BCS", "BNE", "BEQ"}
ALWAYS = {"BRA", "BRL"}
RETURNS = {"RTS", "RTL", "RTI"}
HALTS = {"BRK", "COP", "STP", "WAI"}       # not followed: in battle code these are data, not code
INDEXED = {ABSX: "X", ABSY: "Y", LONGX: "X", DPX: "X", DPY: "Y", DPIY: "Y", DPILY: "Y", DPIX: "X"}


def snes_str(addr):
    return f"{addr >> 16:02X}/{addr & 0xFFFF:04X}"


def parse_addr(text):
    """'C2/50B3', 'C250B3', '$C250B3', '0xC250B3' -> 0xC250B3."""
    t = text.strip().replace("$", "").replace("/", "").replace(":", "")
    return int(t, 16)


# --- the cartridge ------------------------------------------------------------------------------
class Rom:
    """ROM bytes + the cartridge's address map. mapper: 'hirom', 'exhirom' or 'lorom'."""

    def __init__(self, data, mapper=None):
        if len(data) % 0x8000 == 0x200:            # copier header
            data = data[0x200:]
        self.data = bytes(data)
        self.mapper = mapper or self.detect(self.data)

    @classmethod
    def load(cls, path, mapper=None):
        with open(path, "rb") as f:
            return cls(f.read(), mapper)

    @staticmethod
    def detect(data):
        if len(data) > 0x400000 and len(data) >= 0x410000 and data[0x40FFD5] & 0x0F == 0x05:
            return "exhirom"
        if len(data) > 0x400000:
            return "exhirom"
        hi = data[0xFFD5] if len(data) > 0xFFD5 else 0
        lo = data[0x7FD5] if len(data) > 0x7FD5 else 0
        if hi & 0xEF in (0x21, 0x31) or hi & 0x0F in (0x01, 0x05):
            return "hirom"
        if lo & 0xEF in (0x20, 0x30):
            return "lorom"
        return "hirom"

    def offset(self, addr):
        """SNES address -> file offset, or None if the address isn't ROM."""
        bank, low = addr >> 16 & 0xFF, addr & 0xFFFF
        if self.mapper == "lorom":
            if bank in (0x7E, 0x7F) or (low < 0x8000):
                return None
            off = ((bank & 0x7F) << 15) | (low & 0x7FFF)
        elif self.mapper == "exhirom":
            if bank >= 0xC0:
                off = (bank - 0xC0) << 16 | low
            elif 0x40 <= bank < 0x7E:
                off = 0x400000 + ((bank - 0x40) << 16 | low)
            elif bank >= 0x80 and low >= 0x8000:
                off = (bank - 0x80) << 16 | low
            elif bank < 0x40 and low >= 0x8000:
                off = 0x400000 + (bank << 16 | low)
            else:
                return None
        else:   # hirom
            if bank >= 0xC0 or 0x40 <= bank < 0x7E:
                off = (bank & 0x3F) << 16 | low
            elif low >= 0x8000 and bank not in (0x7E, 0x7F):
                off = (bank & 0x3F) << 16 | low
            else:
                return None
        return off if off < len(self.data) else None

    def is_rom(self, addr):
        return self.offset(addr) is not None

    def read(self, addr, n=1):
        off = self.offset(addr)
        if off is None:
            raise ValueError(f"${addr:06X} is not ROM")
        return self.data[off:off + n]

    def byte(self, addr):
        return self.read(addr)[0]

    def word(self, addr):
        b = self.read(addr, 2)
        return b[0] | b[1] << 8

    def long(self, addr):
        b = self.read(addr, 3)
        return b[0] | b[1] << 8 | b[2] << 16


# --- one instruction ----------------------------------------------------------------------------
class Insn:
    __slots__ = ("addr", "raw", "op", "mn", "mode", "value", "m8", "x8", "target", "size")

    def __init__(self, addr, raw, mn, mode, value, m8, x8, target):
        self.addr, self.raw, self.op, self.mn, self.mode = addr, raw, raw[0], mn, mode
        self.value, self.m8, self.x8, self.target, self.size = value, m8, x8, target, len(raw)

    @property
    def next(self):
        return (self.addr & 0xFF0000) | ((self.addr + self.size) & 0xFFFF)

    @property
    def operand(self):
        """The operand as the community listings write it."""
        v, mode = self.value, self.mode
        if mode in (IMP,):
            return ""
        if mode == ACC:
            return ""
        if mode in (IMM_M, IMM_X, IMM8, IMM16):
            if self.mn == "PEA":
                return f"${v:04X}"
            return f"#${v:0{2 * (self.size - 1)}X}"
        if mode in (REL, RELL):
            return f"${self.target & 0xFFFF:04X}"
        if mode == MOVE:
            return f"${v & 0xFF:02X},${v >> 8:02X}"
        w = {1: 2, 2: 4, 3: 6}[SIZE[mode]]
        s = f"${v:0{w}X}"
        return {DP: s, DPX: s + ",X", DPY: s + ",Y", DPI: f"({s})", DPIX: f"({s},X)", DPIY: f"({s}),Y",
                DPIL: f"[{s}]", DPILY: f"[{s}],Y", ABS: s, ABSX: s + ",X", ABSY: s + ",Y", ABSI: f"({s})",
                ABSIX: f"({s},X)", ABSIL: f"[{s}]", LONG: s, LONGX: s + ",X", SR: s + ",S",
                SRIY: f"({s},S),Y"}[mode]

    @property
    def text(self):
        o = self.operand
        return f"{self.mn} {o}" if o else self.mn

    def bytes_hex(self):
        return " ".join(f"{b:02X}" for b in self.raw)

    def __str__(self):
        return f"{snes_str(self.addr)}: {self.bytes_hex():<13}{self.text}"

    __repr__ = __str__

    @property
    def kind(self):
        mn = self.mn
        if mn in BRANCHES:
            return "branch"
        if mn in ALWAYS or mn in ("JMP", "JML"):
            return "jump"
        if mn in ("JSR", "JSL"):
            return "call"
        if mn in RETURNS:
            return "return"
        if mn in HALTS:
            return "halt"
        return "op"

    def long_ref(self, db=None):
        """The 24-bit data address this instruction reads/writes (long modes, or absolute with a
        known data bank), or None."""
        if self.mn in ("JSR", "JSL", "JMP", "JML", "PEA", "PER") or self.mode in (REL, RELL):
            return None
        if self.mode in (LONG, LONGX):
            return self.value
        if db is not None and self.mode in (ABS, ABSX, ABSY):
            return db << 16 | self.value
        return None


def decode(rom, addr, m8=True, x8=True):
    """One instruction at `addr` with the given widths."""
    op = rom.byte(addr)
    mn, mode = OPCODES[op]
    n = SIZE.get(mode)
    if mode == IMM_M:
        n = 1 if m8 else 2
    elif mode == IMM_X:
        n = 1 if x8 else 2
    bank = addr & 0xFF0000
    # operands may cross the 64 KB boundary only within the bank's wrap (rare); read straight
    raw = rom.read(addr, 1 + n)
    if len(raw) < 1 + n:
        raise ValueError(f"instruction at ${addr:06X} runs off the ROM")
    value = int.from_bytes(raw[1:], "little") if n else None
    target = None
    if mode == REL:
        target = bank | ((addr + 2 + (value - 0x100 if value & 0x80 else value)) & 0xFFFF)
    elif mode == RELL:
        target = bank | ((addr + 3 + (value - 0x10000 if value & 0x8000 else value)) & 0xFFFF)
    elif mn in ("JSR", "JMP") and mode == ABS:
        target = bank | value
    elif mn in ("JSL", "JML") and mode == LONG:
        target = value
    return Insn(addr, raw, mn, mode, value, m8, x8, target)


def apply_flags(insn, m8, x8):
    """Widths after this instruction (REP/SEP/XCE only)."""
    if insn.mn == "REP":
        m8 = m8 and not insn.value & 0x20
        x8 = x8 and not insn.value & 0x10
    elif insn.mn == "SEP":
        m8 = m8 or bool(insn.value & 0x20)
        x8 = x8 or bool(insn.value & 0x10)
    return m8, x8


def linear(rom, addr, count=None, m8=True, x8=True, until=None, widths=None):
    """Straight-line decoding from `addr` (count instructions, or up to `until`), following REP/SEP
    and PHP/PLP pairs. Doesn't stop at returns: for listings and patch checks."""
    widths = widths or {}
    out, stack = [], []
    while (count is None or len(out) < count) and (until is None or addr < until):
        if addr in widths:
            m8, x8 = widths[addr]
        i = decode(rom, addr, m8, x8)
        out.append(i)
        if i.mn == "PHP":
            stack.append((m8, x8))
        elif i.mn == "PLP" and stack:
            m8, x8 = stack.pop()
        else:
            m8, x8 = apply_flags(i, m8, x8)
        addr = i.next
        if count is None and until is None and i.kind in ("return", "jump") and i.mn != "BRL":
            break
    return out


# --- recursive tracing --------------------------------------------------------------------------
class TableRef:
    """A read/write of ROM data: the instruction, the table's 24-bit address, the index register."""
    __slots__ = ("at", "table", "index", "mn", "mode")

    def __init__(self, at, table, index, mn, mode):
        self.at, self.table, self.index, self.mn, self.mode = at, table, index, mn, mode

    def __repr__(self):
        ix = f",{self.index}" if self.index else ""
        return f"{snes_str(self.at)} {self.mn} {snes_str(self.table)}{ix}"


class Routine:
    def __init__(self, entry, m8, x8):
        self.entry, self.m8, self.x8 = entry, m8, x8
        self.insns = set()          # addresses of its instructions (incl. tail jumps' code)
        self.calls = set()          # JSR/JSL targets (and jump-table entries called)
        self.jumps_out = set()      # JMP/JML/BRL into another bank
        self.exits = set()          # (m8, x8) at its returns
        self.tables = []            # TableRef
        self.indirect = []          # addresses of JMP (abs) / JML [abs] / JSR (abs,X) without a table
        self.callers = set()

    @property
    def end(self):
        return max(self.insns) if self.insns else self.entry

    def __repr__(self):
        return f"<Routine {snes_str(self.entry)} {len(self.insns)} insns, calls {len(self.calls)}>"


class Code:
    """What a trace found: instructions by address, routines by entry, labels, cross-references."""

    def __init__(self, rom):
        self.rom = rom
        self.insns = {}             # addr -> Insn
        self.routines = {}          # entry -> Routine
        self.labels = {}            # addr -> name
        self.xrefs = defaultdict(set)   # target -> {from}
        self.tables = {}            # jump table addr -> [targets]
        self.data = {}              # data table addr -> [TableRef]
        self.conflicts = []         # (addr, (m8,x8) first, (m8,x8) later)
        self.owner = {}             # insn addr -> routine entry (first)
        self.interior = set()       # addresses inside decoded instructions (not their first byte)
        self.overlaps = []          # paths that ran into the middle of an instruction (data, or a bad width)

    # -- naming
    def name(self, addr):
        if addr in self.labels:
            return self.labels[addr]
        if addr in self.routines:
            return f"sub_{addr:06X}"
        return f"L_{addr:06X}"

    def label_targets(self):
        targets = set(self.routines)
        for i in self.insns.values():
            if i.target is not None and i.kind in ("branch", "jump"):
                targets.add(i.target)
        for t in self.tables.values():
            targets.update(t)
        return targets

    def routine_of(self, addr):
        return self.owner.get(addr)

    def listing(self, start=None, end=None, comments=None, db=None):
        """The decoded instructions in address order (optionally a range), with labels, the names
        of call targets and the tables each reads."""
        comments = comments or {}
        targets = self.label_targets() | set(self.labels)
        out = []
        prev = None
        for a in sorted(self.insns):
            if (start is not None and a < start) or (end is not None and a >= end):
                continue
            i = self.insns[a]
            if prev is not None and prev != a:
                out.append("")
            if a in targets:
                xs = sorted(self.xrefs.get(a, ()))
                xr = (" ; from " + ", ".join(snes_str(x) for x in xs[:6]) + (" ..." if len(xs) > 6 else "")) if xs else ""
                out.append(f"{self.name(a)}:{xr}")
            line = str(i)
            notes = []
            if i.target is not None and (i.target in self.labels or i.target in self.routines):
                notes.append(self.name(i.target))
            ref = i.long_ref(db)
            if ref is not None and self.rom.is_rom(ref):
                notes.append(f"table {snes_str(ref)}" + (f",{INDEXED[i.mode]}" if i.mode in INDEXED else ""))
            tab = (a & 0xFF0000 | i.value) if i.mode == ABSIX else None
            if tab in self.tables:
                notes.append(f"jump table {snes_str(tab)}: " + " ".join(f"{t & 0xFFFF:04X}" for t in self.tables[tab]))
            if a in comments:
                notes.append(comments[a])
            if notes:
                line = f"{line:<40}; " + "; ".join(notes)
            out.append(line)
            prev = i.next
        return "\n".join(out)


class Tracer:
    def __init__(self, rom, widths=None, tables=None, stop=None, labels=None, follow_calls=True,
                 banks=None, db=None, max_table=64):
        self.rom = rom
        self.widths = widths or {}
        self.table_hint = tables or {}
        self.stop = set(stop or ())
        self.follow_calls = follow_calls
        self.banks = set(banks) if banks else None      # only trace into these banks (calls elsewhere recorded)
        self.db = db                                    # data bank for absolute table reads (None: unknown)
        self.max_table = max_table
        self.code = Code(rom)
        self.code.labels.update(labels or {})
        self._done = {}             # (entry, m8, x8) -> exits
        self._busy = set()
        self.pending = []           # jump tables without a hint: sized after the sure code is traced

    def run(self, entries, m8=True, x8=True):
        """Trace each entry (address, or (address, m8, x8)), then the jump tables found on the way
        (guessed sizes; a table's entries are checked against the code already known)."""
        for e in entries:
            if isinstance(e, tuple):
                self.routine(*e)
            else:
                self.routine(e, m8, x8)
        while self.pending:
            self.pending.sort(key=lambda p: p[1])
            kind, at, table, m8_, x8_, r, stack, db = self.pending.pop(0)
            targets = self._jump_table(at, table, m8_, x8_, near=kind == "jump")
            if not targets:
                r.indirect.append(at)
            for t in targets:
                self.code.xrefs[t].add(at)
                if kind == "call":
                    r.calls.add(t)
                    if self.follow_calls and self.in_scope(t):
                        self.routine(t, m8_, x8_)
                        if t in self.code.routines:
                            self.code.routines[t].callers.add(r.entry)
                else:
                    self._blocks(r, t, m8_, x8_, stack, db)
        return self.code

    def in_scope(self, addr):
        return self.rom.is_rom(addr) and (self.banks is None or addr >> 16 in self.banks)

    def routine(self, entry, m8=True, x8=True):
        """Trace the routine at `entry` reached with these widths; returns its exit widths."""
        if entry in self.widths:
            m8, x8 = self.widths[entry]
        key = (entry, m8, x8)
        if key in self._done:
            return self._done[key]
        if key in self._busy:           # recursion: assume it returns as entered
            return {(m8, x8)}
        self._busy.add(key)     # reached again with other widths: traced again (conflicts per instruction)
        r = self.code.routines.setdefault(entry, Routine(entry, m8, x8))
        self._blocks(r, entry, m8, x8)
        self._busy.discard(key)
        exits = r.exits or {(m8, x8)}
        self._done[key] = exits
        return exits

    def _blocks(self, r, entry, m8, x8, stack=(), db=None):
        code = self.code
        work = [(entry, m8, x8, stack, self.db if db is None else db)]
        seen = set()
        while work:
            addr, m8, x8, stack, db = work.pop()
            recent = []             # the last instructions of this path (for LDA #/PHA/PLB)
            while True:
                if addr in self.widths:
                    m8, x8 = self.widths[addr]
                if addr in self.stop or not self.in_scope(addr):
                    break
                if (addr, m8, x8) in seen:
                    break
                old = code.insns.get(addr)
                if old is not None:
                    if (old.mode == IMM_M and old.m8 != m8) or (old.mode == IMM_X and old.x8 != x8):
                        code.conflicts.append((addr, (old.m8, old.x8), (m8, x8)))
                        break
                    i = old
                else:
                    if addr in code.interior:       # into the middle of another instruction
                        code.overlaps.append(addr)
                        break
                    try:
                        i = decode(self.rom, addr, m8, x8)
                    except ValueError:
                        break
                    if any(a in code.insns for a in range(addr + 1, addr + i.size)):
                        code.overlaps.append(addr)
                        break
                    code.insns[addr] = i
                    code.interior.update(range(addr + 1, addr + i.size))
                seen.add((addr, m8, x8))
                code.owner.setdefault(addr, r.entry)
                r.insns.add(addr)
                ref = i.long_ref(db)
                if ref is not None and self.rom.is_rom(ref):
                    t = TableRef(addr, ref, INDEXED.get(i.mode), i.mn, i.mode)
                    r.tables.append(t)
                    code.data.setdefault(ref, []).append(t)
                k = i.kind
                if i.mn == "PHP":
                    stack = stack + ((m8, x8),)
                elif i.mn == "PLP":
                    if stack:
                        (m8, x8), stack = stack[-1], stack[:-1]
                elif i.mn == "PLB":
                    db = None
                    if recent and recent[-1].mn == "PHK":
                        db = addr >> 16
                    elif len(recent) >= 2 and recent[-1].mn == "PHA" and recent[-2].mn == "LDA" \
                            and recent[-2].mode == IMM_M and recent[-2].size == 2:
                        db = recent[-2].value
                else:
                    m8, x8 = apply_flags(i, m8, x8)
                recent = (recent + [i])[-3:]
                if k == "halt":
                    break
                if k == "return":
                    r.exits.add((m8, x8))
                    break
                if k == "branch":
                    code.xrefs[i.target].add(addr)
                    work.append((i.target, m8, x8, stack, db))
                    addr = i.next
                    continue
                if k == "call":
                    if i.mode == ABSIX:                         # JSR ($xxxx,X): a table of routines
                        table = i.addr & 0xFF0000 | i.value
                        if table not in self.table_hint and table not in code.tables:
                            self.pending.append(("call", addr, table, m8, x8, r, stack, db))
                            addr = i.next
                            continue
                        targets = self._jump_table(addr, table, m8, x8, near=False)
                        for t in targets:
                            code.xrefs[t].add(addr)
                            r.calls.add(t)
                            if self.follow_calls and self.in_scope(t):
                                self.routine(t, m8, x8)
                                if t in code.routines:
                                    code.routines[t].callers.add(r.entry)
                        if not targets:
                            r.indirect.append(addr)
                        addr = i.next
                        continue
                    t = i.target
                    code.xrefs[t].add(addr)
                    r.calls.add(t)
                    if t in self.stop:
                        break
                    if self.follow_calls and self.in_scope(t):
                        exits = self.routine(t, m8, x8)
                        if t in code.routines:
                            code.routines[t].callers.add(r.entry)
                        if len(exits) == 1:
                            m8, x8 = next(iter(exits))
                    addr = i.next
                    continue
                if k == "jump":
                    if i.mode == ABSIX:                         # JMP ($xxxx,X): in-routine cases
                        table = i.addr & 0xFF0000 | i.value
                        if table not in self.table_hint and table not in code.tables:
                            self.pending.append(("jump", addr, table, m8, x8, r, stack, db))
                            break
                        targets = self._jump_table(addr, table, m8, x8, near=True)
                        for t in targets:
                            code.xrefs[t].add(addr)
                            work.append((t, m8, x8, stack, db))
                        if not targets:
                            r.indirect.append(addr)
                        break
                    if i.mode in (ABSI, ABSIL):
                        r.indirect.append(addr)
                        break
                    t = i.target
                    code.xrefs[t].add(addr)
                    if t >> 16 != addr >> 16:
                        r.jumps_out.add(t)
                        if self.follow_calls and self.in_scope(t) and t not in self.stop:
                            self.routine(t, m8, x8)     # a tail call into another bank
                            r.exits |= self._done.get((t, m8, x8), set())
                        break
                    addr = t
                    continue
                addr = i.next

    ODD = {"BRK", "COP", "WDM", "STP", "WAI", "XCE", "RTI", "SED", "CLI", "SEI", "TCS", "TCD", "PLD"}

    def plausible(self, addr, m8, x8, n=10):
        """Does `addr` look like code: not inside a decoded instruction, its first instructions
        neither odd for game code (BRK, COP, WAI, XCE, SED...) nor overlapping decoded ones."""
        code = self.code
        if addr in code.interior or not self.rom.is_rom(addr):
            return False
        if addr in code.insns:
            return True
        try:
            for i in linear(self.rom, addr, count=n, m8=m8, x8=x8):
                if i.mn in self.ODD or i.addr in code.interior:
                    return False
                if i.addr != addr and i.addr in code.insns:
                    break               # joined known code
                if any(a in code.insns for a in range(i.addr + 1, i.addr + i.size)):
                    return False
                if i.kind in ("return", "jump"):
                    break
        except ValueError:
            return False
        return True

    def _jump_table(self, at, table, m8=True, x8=True, near=False):
        """Entries of the word table at `table` (in the program bank). Without a hint (tables=),
        entries are read while they point at plausible code (in-routine tables, near=True: within
        4 KB of the dispatch) and the table doesn't run into code or into its own targets."""
        code = self.code
        if table in code.tables:
            return code.tables[table]
        if not self.rom.is_rom(table):
            return []
        bank = table & 0xFF0000
        n = self.table_hint.get(table)
        out = []
        for k in range(n if n is not None else self.max_table):
            a = table + 2 * k
            if n is None and k and (a in code.insns or a in code.interior or a in out):
                break
            w = self.rom.word(a)
            t = bank | w
            if n is None:
                if w in (0, 0xFFFF) or table <= t < a + 2 or (near and abs(t - at) > 0x1000):
                    break
                if not self.plausible(t, m8, x8):
                    break
            out.append(t)
            if n is None and min(out) > table and a + 2 >= min(out):
                break
        code.tables[table] = out
        return out


def trace(rom, entries, m8=True, x8=True, **kw):
    """Trace from each entry (address, or (address, m8, x8)); returns the Code."""
    return Tracer(rom, **kw).run(entries, m8, x8)


# --- comparing two builds of the same code ------------------------------------------------------
def shape(i):
    """An instruction with its in-bank code addresses blanked: equal shapes = the same instruction
    in two builds whose code moved (JP vs US)."""
    if i.target is not None or i.mn in ("JSR", "JMP") or i.mode in (REL, RELL):
        return (i.mn, i.mode)
    return (i.mn, i.mode, i.value)


def align(a_insns, b_insns, min_run=4):
    """Map addresses of one build's instructions to the other's (lists of Insn in address order):
    {a_addr: b_addr} for runs of at least `min_run` instructions of the same shape."""
    import difflib
    sa = [shape(i) for i in a_insns]
    sb = [shape(i) for i in b_insns]
    sm = difflib.SequenceMatcher(None, sa, sb, autojunk=False)
    out = {}
    for blk in sm.get_matching_blocks():
        if blk.size >= min_run:
            for k in range(blk.size):
                out[a_insns[blk.a + k].addr] = b_insns[blk.b + k].addr
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("rom")
    ap.add_argument("addr", help="SNES address: C2/50B3")
    ap.add_argument("-n", "--count", type=int, default=None)
    ap.add_argument("--to", default=None, help="stop before this address")
    ap.add_argument("--m16", action="store_true", help="start with 16-bit A")
    ap.add_argument("--x16", action="store_true", help="start with 16-bit X/Y")
    ap.add_argument("--trace", action="store_true", help="follow branches and calls")
    ap.add_argument("--no-calls", action="store_true", help="with --trace: don't descend into calls")
    ap.add_argument("--bank", action="append", default=[], help="with --trace: banks to follow (hex)")
    ap.add_argument("--db", default=None, help="data bank for absolute table reads (hex)")
    ap.add_argument("--mapper", default=None, choices=("hirom", "exhirom", "lorom"))
    a = ap.parse_args(argv)
    rom = Rom.load(a.rom, a.mapper)
    addr = parse_addr(a.addr)
    m8, x8 = not a.m16, not a.x16
    if a.trace:
        code = trace(rom, [addr], m8, x8, follow_calls=not a.no_calls,
                     banks=[int(b, 16) for b in a.bank] or None, db=int(a.db, 16) if a.db else None)
        print(code.listing(db=int(a.db, 16) if a.db else None))
        for c in code.conflicts:
            print(f"; width conflict at {snes_str(c[0])}: first {c[1]}, then {c[2]}", file=sys.stderr)
    else:
        until = parse_addr(a.to) if a.to else None
        n = a.count if (a.count or until) else 30
        for i in linear(rom, addr, count=None if until and not a.count else n, m8=m8, x8=x8, until=until):
            print(i)


if __name__ == "__main__":
    main()
