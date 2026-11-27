"""SNES FF6 battle events (the AI's F7 nn): which battle dialogues each one shows.

The battle event scripts' pointers are at D0/9800 (33 events, 0x00-0x20, offsets into bank D0). An
event's opcodes, as far as reading its dialogue needs: 01 nn shows battle dialogue nn (the long
battle messages, dialog_map's BATTLE + nn), 11 opens the window, 10 closes it, 0E starts a group of
4-byte animation entries that 0F ends, FF ends the event. Any other opcode stops the reading there
(the same bytes read the same way in both ROMs, so a comparison is still sound).

Used to find the battle dialogues a mod took for something else: BNW rewrote events 08 (Wrexsoul),
0B (Kaiser), 13 (Ziegfried's heart attack, formerly Kefka at the Sealed Gate) and 19 (Wrexsoul), so
the slots of vanilla's Blitz tutorial and Sealed Gate talk now hold BNW's own lines (bnw_dialog).

    .venv/Scripts/python tools/snes_battle_events.py <vanilla.sfc> <mod.sfc>
"""
import sys

TABLE = 0x109800   # D0/9800
COUNT = 33


def rom_bytes(path):
    d = open(path, "rb").read()
    return d[0x200:] if len(d) % 0x8000 == 0x200 else d


def dialogues(d):
    """{event: [battle dialogue, ...]} in the order the event shows them."""
    out = {}
    for e in range(COUNT):
        k = 0x100000 | d[TABLE + 2 * e] | d[TABLE + 2 * e + 1] << 8
        seq = []
        for _ in range(500):
            op = d[k]
            if op == 0x01:
                seq.append(d[k + 1])
                k += 2
            elif op in (0x10, 0x11):
                k += 1
            elif op == 0x0E:
                k += 1
                while d[k] != 0x0F:
                    k += 4
                k += 1
            else:
                break   # FF (the end) or an opcode this reader doesn't know
        out[e] = seq
    return out


def shown_by(events):
    """{battle dialogue: set of events showing it}"""
    by = {}
    for e, seq in events.items():
        for n in seq:
            by.setdefault(n, set()).add(e)
    return by


def repurposed(van, mod):
    """Battle dialogues a mod's events show from other events than vanilla's (or no longer show): its
    text in that slot belongs to another scene than vanilla's. van/mod: ROM bytes."""
    v, m = shown_by(dialogues(van)), shown_by(dialogues(mod))
    return {n for n in set(v) | set(m) if v.get(n, set()) != m.get(n, set())}


if __name__ == "__main__":
    a, b = rom_bytes(sys.argv[1]), rom_bytes(sys.argv[2])
    ev_a, ev_b = dialogues(a), dialogues(b)
    for e in range(COUNT):
        if ev_a[e] != ev_b[e]:
            print(f"event {e:02x}: vanilla {ev_a[e]} -> mod {ev_b[e]}")
    print("repurposed:", sorted(repurposed(a, b)))
