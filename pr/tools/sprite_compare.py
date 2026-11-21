"""How a mod's monster sprites differ from vanilla's, as the SNES draws them (port_sprites.classify).

    .venv/Scripts/python tools/sprite_compare.py [<mod.sfc>]      (default: BNW 3.0)

Each monster: same (or a pixel touch-up in vanilla's colors), swap (looks like another vanilla
monster), recolor (a vanilla shape in new colors), new (the mod's own art) or empty. Sprites are
compared cropped to their opaque box with palette slots matched by content: an earlier version
compared graphics pointers and palette slots and counted ~220 BNW "recolors" that were palette
moves with the same colors (BNW 3.0: 15 recolors, 2 swaps, 11 new art, 2026-11-20).
"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ff6snes as S  # noqa: E402
import prdata as P  # noqa: E402
import port_sprites  # noqa: E402
from snes_sprites import Sprites  # noqa: E402

BNW = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                   "build", "brave-new-world", "Brave New World 3.0 FRC.sfc")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else BNW
    van, mod = S.Rom(P.VANILLA_ROM), S.Rom(path)
    vn = {e.id: e.name.strip() for e in S.enemies(van)}
    mn = {e.id: e.name.strip() for e in S.enemies(mod)}
    rows, _, _ = port_sprites.classify(Sprites(van), Sprites(mod))
    print(dict(collections.Counter(k for _, k, _, _ in rows)))
    for kind in ("swap", "recolor", "new"):
        items = [f"{i} {mn[i] or '?'}" + (f" ({vn[j]}'s shape)" if j is not None and j != i else "")
                 for i, k, j, _ in rows if k == kind]
        print(f"{kind}: {', '.join(items) or 'none'}")
    touch = [f"{i} {mn[i] or '?'}" for i, k, _, d in rows if k == "same" and d > 0]
    print(f"touch-ups (same colors, a few pixels): {', '.join(touch)}")


if __name__ == "__main__":
    main()
