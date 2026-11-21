"""Library art for the mod switcher's Steam tiles: FF6's own art with a band naming the mod.

    make_art.py <FF6 art dir> <out dir>

<FF6 art dir> holds Steam's cached art for app 1173820 (appcache/librarycache/1173820:
library_600x900.jpg, header.jpg, library_hero.jpg, logo.png). Writes, per mod (wc, bnw, bc, ted),
<mod>p.jpg (portrait, 600x900), <mod>.jpg (wide, 920x430), <mod>_hero.jpg and <mod>_logo.png,
which install.sh copies to Steam's grid folder under each tile's app id. The game's art comes
from the player's own Steam cache; none of it is kept in the repository.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

MODS = {"wc": "WORLDS COLLIDE", "bnw": "BRAVE NEW WORLD", "bc": "BEYOND CHAOS", "ted": "T-EDITION"}
GOLD = (214, 176, 92)


def font(size):
    for name in ("georgiab.ttf", "timesbd.ttf", "DejaVuSerif-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def band(img, top, height, text):
    """A black band across img from top, gold rules at its edges, text centred in it."""
    d = ImageDraw.Draw(img)
    w = img.width
    d.rectangle([0, top, w, top + height], fill=(10, 10, 12))
    d.rectangle([0, top, w, top + 3], fill=GOLD)
    d.rectangle([0, top + height - 3, w, top + height], fill=GOLD)
    size = int(height * 0.48)
    f = font(size)
    while d.textlength(text, font=f) > w * 0.9 and size > 10:
        size -= 2
        f = font(size)
    l, t, r, b = d.textbbox((0, 0), text, font=f)
    d.text(((w - (r - l)) / 2 - l, top + (height - (b - t)) / 2 - t), text, font=f, fill=(245, 240, 228))


def main(src, out):
    src, out = Path(src), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for key, title in MODS.items():
        p = Image.open(src / "library_600x900.jpg").convert("RGB").resize((600, 900), Image.LANCZOS)
        band(p, 772, 96, title)
        p.save(out / f"{key}p.jpg", quality=92)

        h = Image.open(src / "header.jpg").convert("RGB")
        wide = Image.new("RGB", (920, 430), (255, 255, 255))
        hs = h.resize((736, 344), Image.LANCZOS)
        wide.paste(hs, ((920 - 736) // 2, 0))
        band(wide, 344, 86, title)
        wide.save(out / f"{key}.jpg", quality=92)

        Image.open(src / "library_hero.jpg").save(out / f"{key}_hero.jpg", quality=92)
        Image.open(src / "logo.png").save(out / f"{key}_logo.png")
    print(f"art for {', '.join(MODS)} in {out}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
