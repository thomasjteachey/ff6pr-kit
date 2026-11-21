"""The Pixel Remaster's RGBA32 textures (battle monster images) read with the standard library alone,
the way BnwPlugin's MonsterImages.cs reads them on a player's machine (plugin/Rules/MonsterImages.cs;
both checked against each other and against UnityPy by tests).

    from pr_images import textures, bundle_for
    for name, (w, h, rgba) in textures(bundle_for(game_dir, "mn_ff6_033")).items(): ...

A Texture2D (class 28) of Unity 2019.4 (serialized file version 21): m_Name, fallback format, two
flags, width, height, complete image size, format (4 = RGBA32), ..., the image bytes inline (an int
length and the bytes) or, when that length is 0, in the bundle's .resS file (m_StreamData: offset,
size, path). Rows are stored bottom-up; returned top-down (as a PNG has them).
"""
import glob
import os
import struct

import pr_bundle

BUNDLES = os.path.join("FINAL FANTASY VI_Data", "StreamingAssets", "aa", "StandaloneWindows64")
RGBA32, RGB24 = 4, 3


def bundle_for(game_dir, group):
    hits = glob.glob(os.path.join(game_dir, BUNDLES, f"{group}_assets_all_*.bundle"))
    if not hits:
        raise FileNotFoundError(f"no bundle for {group} in {game_dir}")
    return hits[0]


def texture(sf, bundle, at, end):
    """(name, w, h, rgba top-down) of the Texture2D at data offset `at`, or None if it isn't RGBA32 or RGB24."""
    d = sf.data
    (n,) = struct.unpack_from("<i", d, at)
    name = d[at + 4:at + 4 + n].decode("utf-8", "replace")
    i = at + 4 + ((n + 3) & ~3)
    _fallback, _flags, w, h, size = struct.unpack_from("<iiiii", d, i)
    bpp = size // (w * h) if w > 0 and h > 0 else 0
    if bpp not in (3, 4) or size != w * h * bpp:
        return None
    i += 20
    # the format: the next int (2019.4), or the one after m_MipsStripped (2020.1+)
    want = RGBA32 if bpp == 4 else RGB24
    fmt = struct.unpack_from("<i", d, i)[0]
    if fmt != want:
        fmt = struct.unpack_from("<i", d, i + 4)[0]
        if fmt != want:
            return None
    # the image: an inline blob of `size` bytes, or an empty one followed by the stream data
    j = i + 8
    while j + 16 <= end:
        (length,) = struct.unpack_from("<i", d, j)
        if length == size and j + 4 + size <= end:
            raw = bytes(d[j + 4:j + 4 + size])
            break
        if length == 0:
            for wide in (False, True):              # offset: UInt32 (2019.4) or UInt64 (2020.1+)
                k = j + 4
                off = struct.unpack_from("<Q" if wide else "<I", d, k)[0]
                k += 8 if wide else 4
                ssize, plen = struct.unpack_from("<Ii", d, k)
                path = d[k + 8:k + 8 + max(0, plen)]
                if ssize == size and path.startswith(b"archive:"):
                    node = path.decode("utf-8", "replace").rsplit("/", 1)[-1]
                    raw = bundle.read(bundle.nodes[node][0] + off, size)
                    break
            else:
                j += 4
                continue
            break
        j += 4
    else:
        return None
    if bpp == 3:            # RGB24 -> RGBA, opaque
        raw = b"".join(raw[k:k + 3] + bytes([255]) for k in range(0, len(raw), 3))
    rows = [raw[y * w * 4:(y + 1) * w * 4] for y in range(h)]
    return name, w, h, b"".join(reversed(rows))


def textures(path):
    """{texture name: (w, h, rgba top-down)} for every RGBA32 or RGB24 Texture2D in the bundle."""
    bundle = pr_bundle.Bundle(path)
    out = {}
    for node in bundle.serialized_files():
        sf = pr_bundle.SerializedFile(bundle.file(node))
        for pid, (cid, start, size) in sf.objects.items():
            if cid != 28:
                continue
            t = texture(sf, bundle, start, start + size)
            if t:
                out[t[0]] = t[1:]
    return out


def png(w, h, rgba):
    """PNG bytes (RGBA, 8 bits, no filter) for top-down RGBA pixels."""
    import zlib
    raw = b"".join(b"\0" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))

    def chunk(kind, data):
        c = kind + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
