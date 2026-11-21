"""SNES FF6 field event scripts: a decoder for the US ROM, the Japanese ROM and a mod's own
commands (T-Edition: tools/ted_events.py), the map entry points, and coverage.

The field event engine runs bytecode at CA/0000+ (an "event address" is the 24-bit
offset from CA/0000 that every command stores; bank = CA + its high byte, so a 6 MB ExHiROM mod's
code reaches bank 40+). Opcodes 00-34 are object action queues (object, length byte with bit 7 =
wait for it, then that many action bytes: poses 00-7F, steps 80-AB, speed C0-C5, turns CC-CF,
D5 x y, E0 frames, FC/FD back/forward jumps...), 35-FF the event commands. Their sizes come from
the ROM's own command table (US C0/98C4, JP C0/97F9: 203 handlers for 35-FF; each handler ends
with LDA #size, JMP advance), checked against Imzogelmo's/Tsushiy's command list and WC's
instruction set (mods/worlds-collide/instruction/field). Variable sizes: 73/74 (5 + w*h tiles),
B6 (one 3-byte target per choice of the dialogue just shown), BE (2 + 3n), C0-CF (1 + 2k bits + 3).

Event bits: 0-0x6FF at 7E/1E80 (D0-DD set/clear the 0x100 ranges; C0-CF test up to 8 of them,
bit 15 of each = "is set"); 0x1A0-0x1AF are the case word ($1EB4), loaded by DE-E4 and the word
compare EB (0x1A0 =, 0x1A1 >, 0x1A2 <); 0x300-0x6FF are the NPC visibility bits. Event words
($1FC2 + 2n): E8 set, E9 add, EA subtract, EB compare. Battle bits: B7/B8/B9.

Entry points, per map: entrance events (D1/FA00, 3 bytes per map), event tiles (C4/0000: 2-byte
offsets, 5-byte x, y, address entries), NPCs (C4/1A10: 9-byte entries, 18-bit address); calls,
branches, choices, switches and timers are followed from there (`Program.walk`). A mod with moved
tables gives a `Tables` of its own (T-Edition: tiles at 4B/0000, NPCs at 4D/7CC0, 512 maps).

    .venv/Scripts/python tools/snes_events.py coverage [us|jp|all]   (reachable code, unknowns)
    .venv/Scripts/python tools/snes_events.py map 26 [us|jp]          (a map's events, decoded)
    .venv/Scripts/python tools/snes_events.py dump CA/5EB3 [us|jp]    (one script from an address)

A mod's ROMs: add `--module <its module>` (T-Edition: `coverage ted --module ted_events`); "all" is
us, jp and every ROM the given modules register.

In code:

    import snes_events as E
    rom = E.load("us")                    # or E.load("jp"); a mod's: import ted_events; E.load("ted")
    prog = E.Program(rom); prog.walk_all()
    prog.coverage()                       # {"instructions", "bytes", "unknown": Counter(op)...}
    for ins in E.script(rom, 0x5EB3): print(ins)
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import kitpath  # noqa: E402,F401  (a mod repository's: the kit on the path; the kit has none)
except ImportError:
    pass
import prdata as P  # noqa: E402

PROJECT = os.path.normpath(os.path.join(P.ROOT, ".."))
US_ROM = P.VANILLA_ROM
JP_ROM = os.path.join(PROJECT, "rom", "vanilla", "Final Fantasy VI (Japan).sfc")
EVENT_BANK = 0xCA
CASE_BIT = 0x1A0          # the case word's first bit (DE-E4, EB results)


# --- ROM addressing --------------------------------------------------------------------------------
def file_offset(bank, addr, size):
    """A SNES address -> file offset (HiROM 3-4 MB, ExHiROM 6 MB: banks 40-7D = the upper 4 MB)."""
    if size > 0x400000 and 0x40 <= bank < 0x7E:
        return 0x400000 + ((bank - 0x40) << 16) + addr
    return ((bank & 0x3F) << 16) + addr


def event_file(off, size):
    """An event address (offset from CA/0000, as commands store it) -> file offset."""
    bank = (EVENT_BANK + (off >> 16)) & 0xFF
    return file_offset(bank, off & 0xFFFF, size)


def fmt(off):
    bank = (EVENT_BANK + (off >> 16)) & 0xFF
    return f"{bank:02X}/{off & 0xFFFF:04X}"


def parse_addr(s):
    """'CA/5EB3' or '0x5EB3' -> event address."""
    s = s.strip()
    if "/" in s:
        b, a = s.split("/")
        return ((int(b, 16) - EVENT_BANK) & 0xFF) << 16 | int(a, 16)
    return int(s, 0)


# --- commands -----------------------------------------------------------------------------------------
# kinds of argument: b byte, w word, a event address (3 bytes: a target), m map word (map | flags)
class Op:
    __slots__ = ("code", "name", "size", "args", "flow", "cls")

    def __init__(self, code, name, size, args="", flow="next", cls="misc"):
        self.code, self.name, self.size, self.args, self.flow, self.cls = code, name, size, args.split(), flow, cls


# flow: next (falls through), end, call (target + falls through), cond (target + falls through),
# choice (targets only), switch (targets + falls through), random (target + falls through)
VANILLA = [
    (0x35, "obj_wait", 2, "obj:b", "next", "object"),
    (0x36, "obj_pass_off", 2, "obj:b", "next", "object"),
    (0x37, "obj_graphics", 3, "obj:b gfx:b", "next", "object"),
    (0x38, "screen_hold", 1, "", "next", "camera"),
    (0x39, "screen_free", 1, "", "next", "camera"),
    (0x3A, "player_control", 1, "", "next", "object"),
    (0x3B, "party_formation", 1, "", "next", "object"),
    (0x3C, "party_set", 5, "c1:b c2:b c3:b c4:b", "next", "party"),
    (0x3D, "obj_create", 2, "obj:b", "next", "object"),
    (0x3E, "obj_delete", 2, "obj:b", "next", "object"),
    (0x3F, "party_char", 3, "char:b party:b", "next", "party"),
    (0x40, "char_props", 3, "char:b props:b", "next", "party"),
    (0x41, "obj_show", 2, "obj:b", "next", "object"),
    (0x42, "obj_hide", 2, "obj:b", "next", "object"),
    (0x43, "obj_palette", 3, "obj:b pal:b", "next", "object"),
    (0x44, "obj_vehicle", 3, "obj:b vehicle:b", "next", "object"),
    (0x45, "objs_refresh", 1, "", "next", "object"),
    (0x46, "party_active", 2, "party:b", "next", "party"),
    (0x47, "party_leader", 1, "", "next", "party"),
    (0x48, "dialog_nowait", 3, "dlg:w", "next", "dialog"),
    (0x49, "dialog_close", 1, "", "next", "dialog"),
    (0x4A, "dialog_keywait", 1, "", "next", "dialog"),
    (0x4B, "dialog", 3, "dlg:w", "next", "dialog"),
    (0x4C, "battle_nogameover", 3, "pack:b bg:b", "next", "battle"),
    (0x4D, "battle", 3, "pack:b bg:b", "next", "battle"),
    (0x4E, "battle_random", 1, "", "next", "battle"),
    (0x4F, "game_restore", 1, "", "next", "misc"),
    (0x50, "tint_bg", 2, "tint:b", "next", "screen"),
    (0x51, "tint_bg_range", 4, "tint:b first:b last:b", "next", "screen"),
    (0x52, "tint_sprites", 2, "tint:b", "next", "screen"),
    (0x53, "tint_sprite_range", 4, "tint:b first:b last:b", "next", "screen"),
    (0x54, "colors_reset", 1, "", "next", "screen"),
    (0x55, "flash", 2, "color:b", "next", "screen"),
    (0x56, "color_add", 2, "v:b", "next", "screen"),
    (0x57, "color_sub", 2, "v:b", "next", "screen"),
    (0x58, "shake", 2, "mode:b", "next", "screen"),
    (0x59, "fade_in_speed", 2, "speed:b", "next", "screen"),
    (0x5A, "fade_out_speed", 2, "speed:b", "next", "screen"),
    (0x5B, "fade_stop", 1, "", "next", "screen"),
    (0x5C, "fade_wait", 1, "", "next", "screen"),
    (0x5D, "scroll_bg1", 3, "x:b y:b", "next", "camera"),
    (0x5E, "scroll_bg2", 3, "x:b y:b", "next", "camera"),
    (0x5F, "scroll_bg3", 3, "x:b y:b", "next", "camera"),
    (0x60, "bg_palette", 3, "layer:b pal:b", "next", "screen"),
    (0x61, "color_range", 4, "color:b first:b last:b", "next", "screen"),
    (0x62, "mosaic", 2, "v:b", "next", "screen"),
    (0x63, "spotlight", 2, "r:b", "next", "screen"),
    (0x64, "bg_anim_frame", 3, "anim:b frame:b", "next", "screen"),
    (0x65, "bg_anim_speed", 3, "anim:b speed:b", "next", "screen"),
    (0x6A, "map_fade", 6, "map:m x:b y:b flags:b", "next", "map"),
    (0x6B, "map", 6, "map:m x:b y:b flags:b", "next", "map"),
    (0x6C, "parent_map", 6, "map:m x:b y:b dir:b", "next", "map"),
    (0x70, "scroll_bg1_to", 3, "x:b y:b", "next", "camera"),
    (0x71, "scroll_bg2_to", 3, "x:b y:b", "next", "camera"),
    (0x72, "scroll_bg3_to", 3, "x:b y:b", "next", "camera"),
    (0x73, "tiles_set", None, "x:b y:b w:b h:b", "next", "map"),
    (0x74, "tiles_set_later", None, "x:b y:b w:b h:b", "next", "map"),
    (0x75, "tiles_refresh", 1, "", "next", "map"),
    (0x77, "char_level_avg", 2, "char:b", "next", "party"),
    (0x78, "obj_pass_on", 2, "obj:b", "next", "object"),
    (0x79, "party_map", 4, "party:b map:w", "next", "party"),
    (0x7A, "obj_event", 5, "obj:b event:a", "next", "object"),
    (0x7B, "party_restore", 1, "", "next", "party"),
    (0x7C, "obj_touch_on", 2, "obj:b", "next", "object"),
    (0x7D, "obj_touch_off", 2, "obj:b", "next", "object"),
    (0x7E, "party_pos", 3, "x:b y:b", "next", "map"),
    (0x7F, "char_name", 3, "char:b name:b", "next", "party"),
    (0x80, "item_add", 2, "item:b", "next", "item"),
    (0x81, "item_remove", 2, "item:b", "next", "item"),
    (0x82, "party_reset", 1, "", "next", "party"),
    (0x84, "gil_add", 3, "gil:w", "next", "item"),
    (0x85, "gil_remove", 3, "gil:w", "next", "item"),
    (0x86, "esper_add", 2, "esper:b", "next", "item"),
    (0x87, "esper_remove", 2, "esper:b", "next", "item"),
    (0x88, "status_remove", 4, "char:b status:W", "next", "party"),
    (0x89, "status_add", 4, "char:b status:W", "next", "party"),
    (0x8A, "status_toggle", 4, "char:b status:W", "next", "party"),
    (0x8B, "hp_restore", 3, "char:b amount:b", "next", "party"),
    (0x8C, "mp_restore", 3, "char:b amount:b", "next", "party"),
    (0x8D, "char_unequip", 2, "char:b", "next", "party"),
    (0x8E, "battle_monster_box", 1, "", "next", "battle"),
    (0x8F, "learn_bushido", 1, "", "next", "party"),
    (0x90, "learn_bum_rush", 1, "", "next", "party"),
    (0x91, "wait_15", 1, "", "next", "wait"),
    (0x92, "wait_30", 1, "", "next", "wait"),
    (0x93, "wait_45", 1, "", "next", "wait"),
    (0x94, "wait_60", 1, "", "next", "wait"),
    (0x95, "wait_120", 1, "", "next", "wait"),
    (0x96, "fade_in", 1, "", "next", "screen"),
    (0x97, "fade_out", 1, "", "next", "screen"),
    (0x98, "name_menu", 2, "char:b", "next", "menu"),
    (0x99, "party_menu", 4, "parties:b fixed:w", "next", "menu"),
    (0x9A, "colosseum_menu", 1, "", "next", "menu"),
    (0x9B, "shop", 2, "shop:b", "next", "menu"),
    (0x9C, "optimize", 2, "char:b", "next", "party"),
    (0x9D, "final_lineup", 1, "", "next", "menu"),
    (0xA0, "timer_start", 6, "frames:w event:t", "next", "flow"),
    (0xA1, "timer_reset", 2, "timer:b", "next", "flow"),
    (0xA2, "a2", 1, "", "next", "misc"),
    (0xA6, "pyramids_off", 1, "", "next", "cutscene"),
    (0xA7, "pyramid_on", 2, "obj:b", "next", "cutscene"),
    (0xA8, "cut_floating_continent", 1, "", "next", "cutscene"),
    (0xA9, "cut_title", 1, "", "next", "cutscene"),
    (0xAA, "cut_magitek_march", 1, "", "next", "cutscene"),
    (0xAB, "game_load_menu", 1, "", "next", "menu"),
    (0xAC, "ac", 1, "", "next", "misc"),
    (0xAD, "cut_world_end", 1, "", "next", "cutscene"),
    (0xAE, "cut_mine_cart", 1, "", "next", "cutscene"),
    (0xAF, "colosseum_battle", 1, "", "next", "battle"),
    (0xB0, "repeat", 2, "count:b", "next", "flow"),
    (0xB1, "repeat_end", 1, "", "next", "flow"),
    (0xB2, "call", 4, "event:a", "call", "flow"),
    (0xB3, "call_times", 5, "count:b event:a", "call", "flow"),
    (0xB4, "wait_frames", 2, "frames:b", "next", "wait"),
    (0xB5, "wait_quarters", 2, "quarters:b", "next", "wait"),
    (0xB6, "choice", None, "", "choice", "dialog"),
    (0xB7, "if_battle_bit_clear", 5, "bit:b event:a", "cond", "flow"),
    (0xB8, "battle_bit_set", 2, "bit:b", "next", "flag"),
    (0xB9, "battle_bit_clear", 2, "bit:b", "next", "flag"),
    (0xBA, "ending", 2, "v:b", "next", "cutscene"),
    (0xBB, "ending2", 1, "", "next", "cutscene"),
    (0xBC, "bc", 3, "a:b b:b", "next", "misc"),
    (0xBD, "random_jump", 4, "event:a", "random", "flow"),
    (0xBE, "switch", None, "", "switch", "flow"),
    (0xBF, "cut_airship_ending", 1, "", "next", "cutscene"),
    (0xDE, "case_party", 1, "", "next", "flow"),
    (0xDF, "case_created", 1, "", "next", "flow"),
    (0xE0, "case_recruited", 1, "", "next", "flow"),
    (0xE1, "case_available", 1, "", "next", "flow"),
    (0xE2, "case_leader", 1, "", "next", "flow"),
    (0xE3, "case_parties", 1, "", "next", "flow"),
    (0xE4, "case_active_party", 1, "", "next", "flow"),
    (0xE7, "portrait", 2, "char:b", "next", "dialog"),
    (0xE8, "word_set", 4, "word:b value:w", "next", "flag"),
    (0xE9, "word_add", 4, "word:b value:w", "next", "flag"),
    (0xEA, "word_sub", 4, "word:b value:w", "next", "flag"),
    (0xEB, "word_cmp", 4, "word:b value:w", "next", "flag"),
    (0xEF, "song_volume", 3, "song:b volume:b", "next", "sound"),
    (0xF0, "song", 2, "song:b", "next", "sound"),
    (0xF1, "song_fade_in", 3, "song:b speed:b", "next", "sound"),
    (0xF2, "song_fade_out", 2, "speed:b", "next", "sound"),
    (0xF3, "song_resume", 2, "speed:b", "next", "sound"),
    (0xF4, "sound", 2, "sound:b", "next", "sound"),
    (0xF5, "sound_pan", 4, "sound:b pan:b speed:b", "next", "sound"),
    (0xF6, "song_ctrl", 4, "a:b b:b c:b", "next", "sound"),
    (0xF7, "song_jump", 1, "", "next", "sound"),
    (0xF8, "f8", 1, "", "next", "sound"),
    (0xF9, "song_ctrl2", 2, "v:b", "next", "sound"),
    (0xFA, "song_wait", 1, "", "next", "sound"),
    (0xFB, "sound_wait", 1, "", "next", "sound"),
    (0xFD, "nop", 1, "", "next", "misc"),
    (0xFE, "return", 1, "", "end", "flow"),
    (0xFF, "end", 1, "", "end", "flow"),
]
for _k, _n in enumerate(("set", "clear")):
    for _r in range(7):
        VANILLA.append((0xD0 + 2 * _r + _k, f"bit_{_n}", 2, f"bit:{_r}", "next", "flag"))
for _k in range(8):
    VANILLA.append((0xC0 + _k, f"if_all{_k + 1}" if _k else "if", None, "", "cond", "flow"))
    VANILLA.append((0xC8 + _k, f"if_any{_k + 1}", None, "", "cond", "flow"))

# object action codes: (name, argument bytes)
OBJ_ACTIONS = {0xC6: ("walk_anim_on", 0), 0xC7: ("walk_anim_off", 0), 0xC8: ("layer", 1),
               0xC9: ("c9", 0), 0xCA: ("ca", 0), 0xCB: ("cb", 0),
               0xCC: ("face_up", 0), 0xCD: ("face_right", 0), 0xCE: ("face_down", 0), 0xCF: ("face_left", 0),
               0xD0: ("show", 0), 0xD1: ("hide", 0), 0xD2: ("d2", 0), 0xD3: ("d3", 0), 0xD4: ("d4", 0),
               0xD5: ("pos", 2), 0xD6: ("d6", 0), 0xD7: ("camera_center", 0), 0xD8: ("d8", 0),
               0xD9: ("d9", 0), 0xDA: ("da", 0), 0xDB: ("db", 0),
               0xDC: ("jump_low", 0), 0xDD: ("jump_high", 0),
               0xE0: ("wait", 1), 0xE1: ("e1", 0), 0xE2: ("e2", 1), 0xE5: ("e5", 1),
               0xF9: ("f9", 3), 0xFA: ("rand_back", 1), 0xFB: ("rand_fwd", 1), 0xFC: ("back", 1),
               0xFD: ("fwd", 1), 0xFE: ("fe", 0), 0xFF: ("end", 0)}
for _s in range(6):
    OBJ_ACTIONS[0xC0 + _s] = (f"speed{_s}", 0)
DIRS = ("up", "right", "down", "left")
DIAG = ("up_right", "down_right", "down_left", "up_left")


def obj_actions(raw):
    """An object queue's action bytes -> [(name, args)] (unknown codes as ("?XX", ()))."""
    out, k = [], 0
    while k < len(raw):
        c = raw[k]
        if c < 0x80:
            out.append(("pose", (c,)))
            k += 1
        elif c < 0xA0:
            out.append(("move", (DIRS[c & 3], ((c - 0x80) >> 2) + 1)))
            k += 1
        elif c < 0xC0:
            out.append(("diag", (c,)))
            k += 1
        else:
            name, n = OBJ_ACTIONS.get(c, (f"?{c:02X}", 0))
            out.append((name, tuple(raw[k + 1:k + 1 + n])))
            k += 1 + n
    return out


class Dialect:
    """One ROM's command set: VANILLA, plus a mod's added or changed commands (ted_events)."""

    map_sensitive = frozenset()     # opcodes whose meaning depends on the map (decoded per map)

    def __init__(self, name, extra=(), remove=()):
        self.name = name
        self.ops = {}
        for row in VANILLA:
            self.ops[row[0]] = Op(*row)
        for code in remove:
            self.ops.pop(code, None)
        for row in extra:
            self.ops[row[0]] = Op(*row)

    def special(self, ins, rom, ctx):
        """A mod's hook for commands whose meaning depends on context (T-Edition's CB on map 104).
        Returns an Op to use instead, or None."""
        return None


US_DIALECT = Dialect("us")
JP_DIALECT = Dialect("jp")


# --- ROMs and their tables --------------------------------------------------------------------------
class Tables:
    """Where a ROM keeps its maps' event entry points."""

    def __init__(self, maps=415, entrance=0x11FA00, tile_ptrs=0x040000, tile_data=0x040000,
                 npc_ptrs=0x041A10, npc_data=0x041A10, code_end=0x2E600, code_ranges=None):
        self.maps, self.entrance, self.code_end = maps, entrance, code_end
        self.code_ranges = code_ranges or [(0, code_end)]   # event addresses that can hold code
        self.tile_ptrs, self.tile_data, self.npc_ptrs, self.npc_data = tile_ptrs, tile_data, npc_ptrs, npc_data

    def is_code(self, off):
        return any(a <= off < b for a, b in self.code_ranges)


class Rom:
    def __init__(self, path, dialect, tables=None, name=None):
        self.path, self.name = path, name or dialect.name
        with open(path, "rb") as f:
            self.data = f.read()
        if len(self.data) % 0x8000 == 0x200:
            self.data = self.data[0x200:]
        self.dialect, self.tables = dialect, tables or Tables()
        self.size = len(self.data)
        self.dialog_choices = None      # dialogue number -> choice count (set by load())

    def ev(self, off, n=1):
        a = event_file(off, self.size)
        return self.data[a:a + n]

    def byte(self, off):
        a = event_file(off, self.size)
        return self.data[a] if 0 <= a < self.size else None


# A mod's ROMs, by name: fn(name) -> Rom. The mod's own module fills it when imported (T-Edition:
# `import ted_events` registers "ted" and "ted-ex"); the kit never imports a mod's module itself.
LOADERS = {}


def load(name="us"):
    """'us' (the US v1.0 ROM), 'jp' (rom/vanilla's Japanese v1.0), or a name a mod registered in
    LOADERS (T-Edition's "ted": import ted_events first)."""
    if name == "us":
        rom = Rom(US_ROM, US_DIALECT, name="us")
        rom.dialog_choices = _choices_us(rom)
    elif name == "jp":
        rom = Rom(JP_ROM, JP_DIALECT, name="jp")
        rom.dialog_choices = _choices_us(rom, kanji=(0x1C, 0x1D, 0x1E, 0x1F))
    elif name in LOADERS:
        return LOADERS[name](name)
    else:
        raise ValueError(f"no SNES ROM {name!r}: 'us', 'jp', or a name a mod's module registers in "
                         f"snes_events.LOADERS when imported (registered now: {sorted(LOADERS) or 'none'}; "
                         f"T-Edition's 'ted': import ted_events, or --module ted_events on the command line)")
    return rom


def cli_modules(argv):
    """Imports each `--module NAME` in argv (a mod's module that registers its ROMs in LOADERS) and
    returns the other arguments."""
    import importlib
    rest, i = [], 0
    while i < len(argv):
        if argv[i] == "--module" and i + 1 < len(argv):
            importlib.import_module(argv[i + 1])
            i += 2
        else:
            rest.append(argv[i])
            i += 1
    return rest


CHOICE = 0x15   # the dialogue code that draws a choice (both ROMs)


def _choices_us(rom, kanji=()):
    """Dialogue number -> number of choices in it (pointers CC/E602, text CD/0000 and CE/0000; the
    JP ROM's 1C-1F + a byte are kanji)."""
    d = rom.data
    split = d[0x0CE600] | d[0x0CE601] << 8
    out = {}
    for i in range(3084):
        p = d[0x0CE602 + 2 * i] | d[0x0CE602 + 2 * i + 1] << 8
        k = (0x0D0000 if i < split else 0x0E0000) + p
        out[i] = _count_choices(d, k, kanji=kanji)
    return out


def _count_choices(d, k, args=(0x11, 0x14, 0x16), kanji=()):
    n = 0
    for _ in range(4000):
        if k >= len(d):
            break
        c = d[k]
        k += 1
        if c == 0:
            break
        if c == CHOICE:
            n += 1
        elif c in args or c in kanji:
            k += 1
    return n


# --- decoding ---------------------------------------------------------------------------------------
class Instr:
    __slots__ = ("off", "op", "size", "name", "args", "targets", "flow", "cls", "raw", "actions", "mode",
                 "next_mode")

    def __str__(self):
        a = " ".join(f"{k}={_show(k, v)}" for k, v in self.args.items())
        t = " -> " + ", ".join(fmt(x) for _, x in self.targets) if self.targets else ""
        v = "v " if self.mode == "vehicle" else ""
        return f"{fmt(self.off)}  {self.raw.hex(' ').upper():<24.24} {v}{self.name} {a}{t}".rstrip()


def _show(k, v):
    if k in ("bit", "bits") and not isinstance(v, int):     # an int bit: a battle bit (B7-B9)
        return " ".join(f"{'+' if s else '-'}{b:03X}" for b, s in (v if k == "bits" else [v]))
    if k == "actions":
        return "[" + ", ".join(n + ("(" + ",".join(map(str, a)) + ")" if a else "") for n, a in v) + "]"
    if isinstance(v, int):
        return hex(v) if v > 9 else str(v)
    return str(v)


WORLD_MAPS = (0, 1, 2)    # World of Balance, World of Ruin, the Serpent Trench (the world map's engine)
PARENT_MAP = 0x1FF        # back to the parent map: a world map when a town is left by an event (vehicle
                          # code follows), a field map otherwise; the walk tells them apart by look-ahead
MAX_BIT = 0x6FF           # event bits 7E/1E80-1F3F


def _new(off, op, mode):
    ins = Instr()
    ins.off, ins.op, ins.targets, ins.args, ins.actions, ins.mode, ins.next_mode = off, op, [], {}, None, mode, mode
    return ins


def _bits(b, k, at):
    bits = []
    for j in range(k):
        v = b[at + 2 * j] | b[at + 1 + 2 * j] << 8
        bits.append((v & 0x7FFF, bool(v & 0x8000)))
    a = at + 2 * k
    return bits, b[a] | b[a + 1] << 8 | b[a + 2] << 16


def decode(rom, off, ctx=None, last_dialog=None, mode="field"):
    """The instruction at `off`, or None when it isn't a known command (or off the ROM). `mode`
    "vehicle" reads the world map's vehicle-script commands (after a load of a world map)."""
    b = rom.ev(off, 64)
    if len(b) < 8:
        return None
    if mode == "vehicle":
        return decode_vehicle(rom, off, b)
    op = b[0]
    ins = _new(off, op, mode)
    if op <= 0x34:
        n = b[1] & 0x7F
        raw = rom.ev(off + 2, n)
        ins.size, ins.name, ins.flow, ins.cls = 2 + n, "obj", "next", "object"
        ins.args = {"obj": op, "wait": bool(b[1] & 0x80), "actions": obj_actions(raw)}
        ins.raw = rom.ev(off, ins.size)
        return ins
    o = rom.dialect.ops.get(op)
    if o is None:
        return None
    spec = rom.dialect.special(ins, rom, ctx)
    if spec is not None:
        o = spec
    ins.name, ins.flow, ins.cls = o.name, o.flow, o.cls
    if o.size is not None:
        ins.size = o.size
        k = 1
        for a in o.args:
            key, kind = a.split(":")
            if kind == "b":
                ins.args[key] = b[k]
                k += 1
            elif kind in ("w", "W"):
                ins.args[key] = b[k] | b[k + 1] << 8 if kind == "w" else b[k] << 8 | b[k + 1]
                k += 2
            elif kind == "m":
                w = b[k] | b[k + 1] << 8
                ins.args[key] = w & 0x1FF
                ins.args["dir"] = w >> 12 & 3
                ins.args["mapflags"] = w & 0xE00
                k += 2
            elif kind in ("a", "t"):
                t = b[k] | b[k + 1] << 8 | b[k + 2] << 16
                if kind == "t":        # timer: 18-bit address + flags
                    ins.args["timer_flags"] = t >> 18
                    t &= 0x3FFFF
                ins.args[key] = t
                ins.targets.append(("timer" if kind == "t" else ins.flow, t))
                k += 3
            elif kind.isdigit():      # bit set/clear: the range
                ins.args["bit"] = (int(kind) << 8 | b[k], ins.name == "bit_set")
                k += 1
        if op in (0x6A, 0x6B) and ins.args.get("map") in WORLD_MAPS:
            ins.next_mode = "vehicle?"     # a vehicle script, or the event ends with the load
        elif op in (0x6A, 0x6B) and ins.args.get("map") == PARENT_MAP:
            ins.next_mode = "either"
    elif op in (0x73, 0x74):
        ins.size = 5 + b[3] * b[4]
        ins.args = {"x": b[1], "y": b[2], "w": b[3], "h": b[4]}
    elif 0xC0 <= op <= 0xCF:
        bits, t = _bits(b, (op & 7) + 1, 1)
        ins.size = 1 + 2 * len(bits) + 3
        ins.args = {"bits": bits, "event": t}
        ins.targets = [("cond", t)]
    elif op == 0xBE:
        n = b[1]
        ins.size = 2 + 3 * n
        cases = []
        raw = rom.ev(off + 2, 3 * n)
        for j in range(n):
            v = raw[3 * j] | raw[3 * j + 1] << 8 | raw[3 * j + 2] << 16
            cases.append((v >> 20, v & 0xFFFFF))
            ins.targets.append(("switch", v & 0xFFFFF))
        ins.args = {"cases": cases}
    elif op == 0xB6:
        n = None
        if last_dialog is not None and rom.dialog_choices:
            n = rom.dialog_choices.get(last_dialog)
        if not n:
            n = _guess_choices(rom, off)
        ins.size = 1 + 3 * n
        raw = rom.ev(off + 1, 3 * n)
        for j in range(n):
            t = raw[3 * j] | raw[3 * j + 1] << 8 | raw[3 * j + 2] << 16
            ins.targets.append(("choice", t))
        ins.args = {"dialog": last_dialog, "n": n}
    else:
        return None
    if not _valid(rom, ins):
        return None
    ins.raw = rom.ev(off, ins.size)
    return ins


def _valid(rom, ins):
    """Rejects what can't be code: a target outside the ROM's event code, a bit past 0x6FF."""
    for _, t in ins.targets:
        if not rom.tables.is_code(t):
            return False
    for b, _ in ins.args.get("bits", ()):
        if b > MAX_BIT:
            return False
    if isinstance(ins.args.get("bit"), tuple) and ins.args["bit"][0] > MAX_BIT:
        return False
    return True


# the world map's vehicle-script commands (EE/76FB, US; the JP ROM's world code is the same):
# 00-7F move (+ frames), 80-B7 / B8-BF if all / any of n bits (as field C0-CF), C8/C9 set/clear a bit,
# CA-CF battle (pack, background), D2/D3 load a map (field code follows when it isn't a world map),
# E0 wait, FF end
VEHICLE_SIZES = {0xC0: 2, 0xC8: 3, 0xC9: 3, 0xD0: 1, 0xD1: 1, 0xD2: 6, 0xD3: 6, 0xDE: 3, 0xDF: 1, 0xE0: 2, 0xFF: 1}
VEHICLE_SIZES.update({c: 3 for c in range(0xC1, 0xC8)})
VEHICLE_SIZES.update({c: 3 for c in range(0xCA, 0xD0)})
VEHICLE_SIZES.update({c: 1 for c in range(0xD4, 0xDE)})
VEHICLE_SIZES.update({c: 1 for c in range(0xE1, 0xFF)})
VEHICLE_NAMES = {0xC8: "v_bit_set", 0xC9: "v_bit_clear", 0xD0: "v_show", 0xD1: "v_hide", 0xD2: "v_map",
                 0xD3: "v_map2", 0xE0: "v_wait", 0xFF: "v_end"}
VEHICLE_NAMES.update({c: "v_battle" for c in range(0xCA, 0xD0)})


def decode_vehicle(rom, off, b):
    op = b[0]
    ins = _new(off, op, "vehicle")
    ins.flow, ins.cls = "next", "vehicle"
    if op < 0x80:
        ins.size, ins.name = 2, "v_move"
        ins.args = {"dir": op, "frames": b[1]}
    elif op < 0xC0:
        bits, t = _bits(b, (op & 7) + 1, 1)
        ins.size, ins.name, ins.flow, ins.cls = 1 + 2 * len(bits) + 3, "v_if_any" if op >= 0xB8 else "v_if_all", "cond", "flow"
        ins.args = {"bits": bits, "event": t}
        ins.targets = [("cond", t)]
    else:
        ins.size = VEHICLE_SIZES[op]
        ins.name = VEHICLE_NAMES.get(op, f"v_{op:02X}")
        if op in (0xC8, 0xC9):
            ins.args = {"bit": ((b[1] | b[2] << 8) & 0x7FFF, op == 0xC8)}
            ins.cls = "flag"
        elif 0xCA <= op <= 0xCF:
            ins.args = {"pack": b[1], "bg": b[2]}
            ins.cls = "battle"
        elif op in (0xD2, 0xD3):
            w = b[1] | b[2] << 8
            ins.args = {"map": w & 0x1FF, "dir": w >> 12 & 3, "mapflags": w & 0xE00, "x": b[3], "y": b[4], "flags": b[5]}
            ins.cls = "map"
            if ins.args["map"] not in WORLD_MAPS:
                ins.next_mode = "field"
        elif op == 0xFF:
            ins.flow = "end"
        elif ins.size > 1:
            ins.args = {"v": list(b[1:ins.size])}
        if op in (0xD2, 0xD3) and ins.args["map"] == PARENT_MAP:
            ins.next_mode = "either"
    if not _valid(rom, ins):
        return None
    ins.raw = rom.ev(off, ins.size)
    return ins


def dialog_key(ins):
    """The dialogue a command shows, as rom.dialog_choices keys it: its number (4B/48: the low 13
    bits; the top ones place the window), or ("EE", n) for T-Edition's second table."""
    n = ins.args["dlg"] & 0x1FFF
    return ("EE", n) if ins.op == 0xEE else n


def _guess_choices(rom, off):
    """B6 without a known dialogue: count 3-byte targets that decode as commands (2-4)."""
    n = 0
    for j in range(4):
        t = rom.ev(off + 1 + 3 * j, 3)
        v = t[0] | t[1] << 8 | t[2] << 16
        if v >= 0x400000 or decode(rom, v) is None:
            break
        n += 1
    return max(n, 2)


def script(rom, off, limit=4000, ctx=None, mode="field"):
    """A straight-line listing from `off` until a return/end (branch targets not followed)."""
    out, last = [], None
    for _ in range(limit):
        ins = decode(rom, off, ctx, last, mode)
        if ins is None:
            break
        out.append(ins)
        if ins.cls == "dialog" and "dlg" in ins.args:
            last = dialog_key(ins)
        if ins.flow in ("end", "choice"):
            break
        off += ins.size
        mode = ins.next_mode
    return out


# --- entry points ------------------------------------------------------------------------------------
def entry_points(rom):
    """[(event address, kind, map, detail)] from every map's entrance event, event tiles and NPCs."""
    t, d = rom.tables, rom.data
    w = lambda a: d[a] | d[a + 1] << 8
    out = []
    for m in range(t.maps + 1):
        a = t.entrance + 3 * m
        e = d[a] | d[a + 1] << 8 | d[a + 2] << 16
        out.append((e, "entrance", m, None))
        for o in range(w(t.tile_ptrs + 2 * m), w(t.tile_ptrs + 2 * m + 2), 5):
            r = d[t.tile_data + o:t.tile_data + o + 5]
            out.append((r[2] | r[3] << 8 | r[4] << 16, "tile", m, (r[0], r[1])))
        for n, o in enumerate(range(w(t.npc_ptrs + 2 * m), w(t.npc_ptrs + 2 * m + 2), 9)):
            r = d[t.npc_data + o:t.npc_data + o + 9]
            ev = r[0] | r[1] << 8 | (r[2] & 3) << 16
            bit = 0x300 + ((r[3] >> 1) << 3 | (r[2] >> 6) | (r[3] & 1) << 2)
            det = {"npc": n, "x": r[4] & 0x7F, "y": r[5] & 0x3F, "sprite": r[6], "bit": bit}
            # an address past the event code (CD/xxxx in vanilla: dialogue) marks a decoration
            # (animated multi-part objects reuse those bytes): no event
            out.append((ev, "npc" if ev < t.code_end else "npc_object", m, det))
    return out


class Program:
    """Every instruction reachable from a ROM's entry points."""

    def __init__(self, rom):
        self.rom = rom
        self.code = {}                       # off -> Instr
        self.unknown = collections.Counter()  # first byte of undecodable instructions
        self.unknown_at = {}
        self.obj_unknown = collections.Counter()
        self.entries = []
        self.callers = collections.defaultdict(set)
        self.maps_of = collections.defaultdict(set)   # code address -> maps it was reached from
        self.dead = {}                                 # conditionals whose fall-through isn't code
        self.map_ends = {}                             # map loads that end their event
        self.bad_entries = []                          # NPC addresses that aren't code

    def walk(self, entries):
        """Follow every path from [(address, kind, map, detail)]: world-map entries (maps 0-2) start in
        vehicle mode. A conditional's fall-through is followed only when it decodes as code (FF6 uses
        "if bit X clear" on bits nothing sets as a goto, with data or the next script after it):
        `dead` keeps those branches, `always` the bits they test."""
        todo = []
        for off, kind, m, det in entries:
            mode = "vehicle" if m in WORLD_MAPS and kind != "npc" else "field"
            if kind == "npc_object":
                continue
            # an NPC that is a decoration keeps a leftover address (mid-script or data): its "talk
            # event" never runs; such entries (and the odd unused tile) are listed, not walked
            if not self._falls_into_code(off, m, None, mode, depth=400, strict=True):
                self.bad_entries.append((off, kind, m, det))
                continue
            todo.append((off, m, None, mode))
        seen = set()
        while todo:
            off, m, last, mode = todo.pop()
            while True:
                key = (off, mode, m if self._map_sensitive(off) else None)
                if key in seen:
                    break
                seen.add(key)
                self.maps_of[off].add(m)
                ins = self.code.get((off, mode)) or decode(self.rom, off, {"map": m}, last, mode)
                if ins is None:
                    b = self.rom.byte(off)
                    self.unknown[(mode, b)] += 1
                    self.unknown_at.setdefault((mode, b), []).append(off)
                    break
                self.code[(off, mode)] = ins
                if ins.name == "obj":
                    for name, _ in ins.args["actions"]:
                        if name.startswith("?"):
                            self.obj_unknown[name] += 1
                if ins.cls == "dialog" and "dlg" in ins.args:
                    last = dialog_key(ins)
                for kind, t in ins.targets:
                    self.callers[t].add(off)
                    todo.append((t, m, last, mode))
                if ins.flow in ("end", "choice"):
                    break
                if ins.flow == "cond" and not self._falls_into_code(off + ins.size, m, last, ins.next_mode):
                    self.dead[off] = ins
                    break
                off += ins.size
                mode = self._next_mode(ins, off, m, last)
                if mode is None:
                    self.map_ends[ins.off] = ins
                    break

    def _next_mode(self, ins, off, m, last):
        """What follows a map load: field code, a vehicle script, or nothing (None: the event ends
        there and the bytes after it are another script or data)."""
        nm = ins.next_mode
        if nm in ("field", "vehicle"):
            return nm
        tries = ("field", "vehicle") if nm == "either" else ("vehicle",)
        for t in tries:
            if self._falls_into_code(off, m, last, t, strict=True):
                return t
        return None

    def _falls_into_code(self, off, m, last, mode, depth=48, strict=False, _nest=0):
        """Whether straight-line decoding from `off` reaches an end, a return or `depth` commands
        without an unknown opcode (the look-ahead that tells a conditional from a goto). `strict`:
        it must reach an end or return (vehicle scripts decode from nearly any bytes); a
        conditional on the way passes when either of its paths does."""
        for _ in range(depth):
            if (off, mode) in self.code:
                return True
            ins = decode(self.rom, off, {"map": m}, last, mode)
            if ins is None:
                return False
            if ins.name == "obj" and any(n.startswith("?") for n, _ in ins.args["actions"]):
                return False
            if ins.flow in ("end", "choice"):
                return True
            if ins.cls == "dialog" and "dlg" in ins.args:
                last = dialog_key(ins)
            if strict and ins.flow == "cond" and _nest < 4:
                nm = {"either": "field", "vehicle?": "vehicle"}.get(ins.next_mode, ins.next_mode)
                if self._falls_into_code(off + ins.size, m, last, nm, depth, True, _nest + 1):
                    return True
                return self._falls_into_code(ins.targets[0][1], m, last, mode, depth, True, _nest + 1)
            off += ins.size
            mode = {"either": "field", "vehicle?": "vehicle"}.get(ins.next_mode, ins.next_mode)
        return not strict

    def always_bits(self):
        """Bits tested by the conditionals whose fall-through isn't code: {bit: (is_set, count)}."""
        c = collections.Counter()
        for ins in self.dead.values():
            for b, s in ins.args.get("bits", []):
                c[(b, s)] += 1
        return c

    def _map_sensitive(self, off):
        return self.rom.byte(off) in self.rom.dialect.map_sensitive

    def walk_all(self):
        self.entries = entry_points(self.rom)
        self.walk(self.entries)
        return self

    def coverage(self):
        by_cls = collections.Counter()
        by_op = self.by_op = collections.Counter()
        for ins in self.code.values():
            by_cls[ins.cls] += 1
            by_op[ins.name] += 1
        return {"rom": self.rom.name, "entries": len(self.entries),
                "distinct_entries": len({e[0] for e in self.entries}),
                "instructions": len(self.code), "bytes": sum(i.size for i in self.code.values()),
                "unknown": {f"{m} {b if b is None else hex(b)}": n for (m, b), n in self.unknown.most_common()},
                "unknown_at": {f"{m} {b if b is None else hex(b)}": [fmt(x) for x in v[:6]] for (m, b), v in self.unknown_at.items()},
                "obj_unknown": dict(self.obj_unknown), "by_class": dict(by_cls),
                "gotos": len(self.dead), "map_ends": len(self.map_ends),
                "entries_not_code": [f"map {m} {k} {d} {fmt(o)}" for o, k, m, d in self.bad_entries], "goto_bits": {f"{'+' if st else '-'}{b:03X}": n for (b, st), n in self.always_bits().most_common(12)}}


def listing(prog, start, mode="field"):
    """The decoded instructions of one script region (from `start`, following fall-through) as text."""
    out, off = [], start
    while (off, mode) in prog.code:
        ins = prog.code[(off, mode)]
        out.append(str(ins))
        if ins.flow in ("end", "choice"):
            break
        off += ins.size
        mode = ins.next_mode
    return "\n".join(out)


def _main(argv):
    argv = cli_modules(argv)
    cmd = argv[0] if argv else "coverage"
    if cmd == "coverage":
        names = ["us", "jp"] + sorted(LOADERS) if len(argv) < 2 or argv[1] == "all" else [argv[1]]
        for n in names:
            prog = Program(load(n)).walk_all()
            c = prog.coverage()
            print(json.dumps(c, indent=1, default=str))
    elif cmd == "dump":
        rom = load(argv[2] if len(argv) > 2 else "us")
        for ins in script(rom, parse_addr(argv[1])):
            print(ins)
    elif cmd == "map":
        rom = load(argv[2] if len(argv) > 2 else "us")
        m = int(argv[1], 0)
        prog = Program(rom)
        es = [e for e in entry_points(rom) if e[2] == m]
        prog.walk(es)
        for off, kind, _, det in es:
            print(f"== {kind} {det or ''} {fmt(off)}")
            print(listing(prog, off))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    # through the importable module: a mod's module (--module) registers in snes_events.LOADERS, not
    # in this __main__ copy's
    import snes_events
    snes_events._main(sys.argv[1:])
