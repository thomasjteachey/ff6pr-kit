"""The final battle's statue tiers as the SNES draws them, captured in the windowless harness
(snes_harness.py): vanilla's and a mod's, for porting the tower image (the PR draws the three tiers as
one 240x456 picture, MN_FF6_147_C00; BNW redrew them).

    .venv/Scripts/python tools/snes_final_tiers.py [--rom <sfc>] [--out build/sprites/tiers] [--sprites]

A New Game is played to its first battle (A mashed, up held, as snes_status_ticks.to_battle), with the
battle's formation ($11E0) and background ($11E2) written every frame until the battle starts: tier 1 =
formation 471 on background $33, tier 2 = 512 on $34, tier 3 = 513 on $35 (the final battle: pack $165,
WC's kefka_tower.py). Snes9x's layer options hide the sprites (the party stands in front of the statue)
unless --sprites. One PNG per tier (256x224, the whole screen). Reads the ROM only; dev PC only.
"""
import argparse
import ctypes
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prdata as P  # noqa: E402
from snes_harness import Snes  # noqa: E402

TIERS = [(1, 471, 0x33), (2, 512, 0x34), (3, 513, 0x35)]
BNW = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                   "build", "brave-new-world", "Brave New World 3.0 FRC.sfc")


class RetroVariable(ctypes.Structure):
    _fields_ = [("key", ctypes.c_char_p), ("value", ctypes.c_char_p)]


class LayerSnes(Snes):
    """The harness with Snes9x's layer options answered: layers in `hidden` are drawn off."""

    def __init__(self, rom, hidden=()):
        self.hidden = set(hidden)
        self._vals = {}
        super().__init__(rom)

    def _env(self, cmd, data):
        c = cmd & 0xFFFF
        if c == 15:                         # GET_VARIABLE
            v = ctypes.cast(data, ctypes.POINTER(RetroVariable))[0]
            key = (v.key or b"").decode()
            if key.startswith("snes9x_layer_"):
                val = b"disabled" if key in self.hidden else b"enabled"
                self._vals[key] = ctypes.c_char_p(val)
                ctypes.cast(data, ctypes.POINTER(RetroVariable))[0].value = self._vals[key].value
                return True
            return False
        return super()._env(cmd, data)


def capture(rom, out, formation, bg, tag, sprites=False, settle=420):
    s = LayerSnes(rom, () if sprites else ("snes9x_layer_5",))
    try:
        rd, wr = s.rd, s.wr
        while rd(0x1503) != 0xC1:           # the NMI's jump: bank C1 = battle
            wr(0x11E0, formation & 0xFF)
            wr(0x11E1, formation >> 8)
            wr(0x11E2, bg)
            k = s.frame % 40
            if k < 2:
                s.press("a")
            elif 10 <= k < 30 and (s.frame // 2000) % 2:
                s.press("up")
            else:
                s.release()
            s.run(1)
            if s.frame > 200000:
                raise RuntimeError("no battle by frame 200000")
        s.release()
        s.run(settle)
        path = os.path.join(out, f"{tag}.png")
        s.screenshot(path, scale=1)
        return path, rd(0x11E0) | rd(0x11E1) << 8, rd(0x11E2)
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", default=BNW)
    ap.add_argument("--vanilla", action="store_true", help="the US ROM instead")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "sprites", "tiers"))
    ap.add_argument("--sprites", action="store_true")
    ap.add_argument("--tiers", default="1,2,3")
    a = ap.parse_args()
    rom = P.VANILLA_ROM if a.vanilla else a.rom
    os.makedirs(a.out, exist_ok=True)
    name = "vanilla" if a.vanilla else "mod"
    for t, f, bg in TIERS:
        if str(t) not in a.tiers.split(","):
            continue
        path, got_f, got_bg = capture(rom, a.out, f, bg, f"{name}_tier{t}" + ("_sprites" if a.sprites else ""), a.sprites)
        print(f"tier {t}: formation {got_f} bg {got_bg:#x} -> {path}")


if __name__ == "__main__":
    main()
