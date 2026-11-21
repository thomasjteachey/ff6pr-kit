"""A PR SpriteAtlas's frames (kit tool, standard library only): the field NPC groups (mo_ff6_nNNN_cMM) and other
atlas-packed sprite groups keep one packed texture plus a Sprite per frame; this cuts the frames back out.

    import pr_atlas
    fr = pr_atlas.frames(bundle_path)          # {frame name: (w, h, rgba top-down)}
    info = pr_atlas.sprites(bundle_path)       # {frame name: {"rect": [x, y_top, w, h], "pivot": [px, py], "texture": name}}

Unity 2019.4's layouts, read without type trees (the PR's bundles):
  Sprite (213): m_Name, m_Rect (4 f), m_Offset (2 f), m_Border (4 f), m_PixelsToUnits, m_Pivot (2 f), m_Extrude (u32),
    m_IsPolygon (bool, aligned), m_RenderDataKey (GUID 16 B + i64), ...
  SpriteAtlas (687078895): m_Name, m_PackedSprites (PPtr[]), m_PackedSpriteNamesToIndex (string[]), m_RenderDataMap:
    count, then per entry (104 B) the key (GUID + i64), SpriteAtlasData: texture PPtr (i32 + i64), alphaTexture PPtr,
    textureRect (4 f: x, y from the bottom, w, h), textureRectOffset (2 f), atlasRectOffset (2 f), uvTransform (4 f),
    downscaleMultiplier (f), settingsRaw (u32).
Checked on mo_ff6_n048_c00 (10 frames, 256x128 texture).
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pr_bundle  # noqa: E402
import pr_images  # noqa: E402

SPRITE, ATLAS, TEXTURE = 213, 687078895, 28


def _blob(d, i):
    (n,) = struct.unpack_from("<i", d, i)
    s = bytes(d[i + 4:i + 4 + n])
    return s, (i + 4 + n + 3) & ~3


def _sprite(d, st):
    name, i = _blob(d, st)
    i = st + ((i - st + 3) & ~3)
    i += 16 + 8 + 16 + 4                       # rect, offset, border, pixels to units
    px, py = struct.unpack_from("<2f", d, i)
    i += 8 + 4                                 # pivot, extrude
    i = st + ((i + 1 - st + 3) & ~3)           # isPolygon, aligned
    key = bytes(d[i:i + 24])
    return name.decode("utf-8", "replace"), key, (px, py)


def _atlas(d, st):
    _, i = _blob(d, st)
    (n,) = struct.unpack_from("<i", d, i)
    i += 4 + 12 * n                            # packed sprites
    (n,) = struct.unpack_from("<i", d, i)
    i += 4
    for _ in range(n):
        _, i = _blob(d, i)
    (n,) = struct.unpack_from("<i", d, i)
    i += 4
    out = {}
    for _ in range(n):
        key = bytes(d[i:i + 24])
        (tex,) = struct.unpack_from("<q", d, i + 28)
        x, y, w, h = struct.unpack_from("<4f", d, i + 48)
        out[key] = (tex, x, y, w, h)
        i += 104
    return out


def _read(path):
    b = pr_bundle.Bundle(path)
    sprites, rects, texs = [], {}, {}
    for node in b.serialized_files():
        sf = pr_bundle.SerializedFile(b.file(node))
        d = sf.data
        for pid, (cid, st, size) in sf.objects.items():
            if cid == SPRITE:
                sprites.append(_sprite(d, st))
            elif cid == ATLAS:
                rects.update(_atlas(d, st))
            elif cid == TEXTURE:
                t = pr_images.texture(sf, b, st, st + size)
                if t:
                    texs[pid] = t
    return sprites, rects, texs


def sprites(path):
    """{frame name: {"rect": [x, y from the top, w, h], "pivot": [x, y], "texture": its texture's name}}."""
    sp, rects, texs = _read(path)
    out = {}
    for name, key, piv in sp:
        r = rects.get(key)
        if not r or r[0] not in texs:
            continue
        tex, x, y, w, h = r
        th = texs[tex][2]
        out[name] = {"rect": [int(x), int(th - y - h), int(w), int(h)], "pivot": list(piv), "texture": texs[tex][0]}
    return out


def frames(path):
    """{frame name: (w, h, rgba top-down)}, cut from the atlas texture."""
    sp, rects, texs = _read(path)
    out = {}
    for name, key, _ in sp:
        r = rects.get(key)
        if not r or r[0] not in texs:
            continue
        tex, x, y, w, h = r
        _, tw, th, rgba = texs[tex]
        x, w, h = int(x), int(w), int(h)
        top = int(th - y - h)
        rows = [rgba[((top + k) * tw + x) * 4:((top + k) * tw + x + w) * 4] for k in range(h)]
        out[name] = (w, h, b"".join(rows))
    return out
