"""FF6-driver songs from tables at any address (a mod's relocated tables, a second copy of the driver),
into a song pack, several tables into one pack.

  python tools/snes_songs_at.py read ROM [--pointers song=0x50539,inst=...] [--tables song=0x5F0000,...,count=255]
                                [--slot-offset 0x100] [--sample-offset 0x100] [--slots 24,2F] --out DIR [--merge]

The same reader as tools/snes_songs.py (read_ff6_songs: the C5 pointer locations FF6's sound code uses), with
the places given:
  pointers: where the 3-byte pointers to the tables are (keys song, inst, brr, loop, pitch, adsr; count: where
            the song count byte is). Default FF6's (C5/0539, 01E3, 0222, 041C, 049C, 04DE; count C5/3C5E).
  tables:   the tables themselves (same keys, SNES or file addresses; count: the number of songs), over pointers.
  slot_offset / sample_offset: added to the slots and sample ids read, so a second table (T-Edition's bank-$43
            driver copy) sits beside the first in one pack (`--merge` adds to the pack in --out).
Addresses: $C0-$FF banks (HiROM), $40-$7D (a 6 MB ExHiROM's upper half: file offset = address), $3E-$3F
(mirrors), or plain file offsets. Folded into snes_songs.py after the WC 0.6.9 release (kit freeze).
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import snes_songs as SS  # noqa: E402

FF6_POINTERS = {"song": SS.OFF_SONG_PTR, "inst": SS.OFF_INST_PTR, "brr": SS.OFF_BRR_PTR, "loop": SS.OFF_LOOP_PTR,
                "pitch": SS.OFF_PITCH_PTR, "adsr": SS.OFF_ADSR_PTR, "count": SS.OFF_COUNT}
KEYS = ("song", "inst", "brr", "loop", "pitch", "adsr")


def rom_offset(addr):
    """A SNES address (HiROM / 6 MB ExHiROM) or a file offset -> file offset."""
    if addr >= 0xC00000:
        return addr - 0xC00000
    if 0x400000 <= addr < 0x7E0000:
        return addr                      # ExHiROM $40-$7D: the file's upper 4 MB, address = offset
    if 0x3E0000 <= addr < 0x400000:
        return addr + 0x400000
    return addr


def _ptr(rom, off):
    return rom_offset(int.from_bytes(rom[off:off + 3], "little"))


def read_songs(rom, pointers=None, tables=None, slots=None, slot_offset=0, sample_offset=0):
    """{"songs": {slot: {"data", "instruments"}}, "samples": {id: {"brr", "loop", "tune", "adsr"}}, "count"}
    from the tables found through `pointers` (FF6's by default) or given as `tables`; slots and sample ids
    shifted by the offsets (instrument lists follow)."""
    rom = SS.unheader(bytes(rom))
    p = dict(FF6_POINTERS)
    p.update(pointers or {})
    t = {k: _ptr(rom, rom_offset(p[k])) for k in KEYS}
    count = rom[rom_offset(p["count"])]
    for k, v in (tables or {}).items():
        if k == "count":
            count = v
        else:
            t[k] = rom_offset(v)
    songs, used = {}, set()
    for slot in range(count):
        if slots is not None and slot not in slots:
            continue
        a = _ptr(rom, t["song"] + 3 * slot)
        size = int.from_bytes(rom[a:a + 2], "little")
        if a == 0 or size == 0 or a + 2 + size > len(rom):
            continue
        data = rom[a + 2:a + 2 + size + 1]
        inst = [int.from_bytes(rom[t["inst"] + 32 * slot + 2 * i:t["inst"] + 32 * slot + 2 * i + 2], "little") for i in range(16)]
        songs[slot + slot_offset] = {"data": data, "instruments": [i + sample_offset if i else 0 for i in inst]}
        used.update(i for i in inst if i)
    samples = {}
    for sid in sorted(used):
        a = _ptr(rom, t["brr"] + 3 * (sid - 1))
        size = int.from_bytes(rom[a:a + 2], "little")
        brr = rom[a + 2:a + 2 + size]
        brr = brr[:len(brr) - len(brr) % 9]
        k = 2 * (sid - 1)
        samples[sid + sample_offset] = {"brr": brr, "loop": int.from_bytes(rom[t["loop"] + k:t["loop"] + k + 2], "little"),
                                        "tune": list(rom[t["pitch"] + k:t["pitch"] + k + 2]),
                                        "adsr": list(rom[t["adsr"] + k:t["adsr"] + k + 2])}
    return {"songs": songs, "samples": samples, "count": count}


# FF6's resident waveforms (programs $00-$07: its sound effects' waves, which some songs use): the BRR block
# the sound code loads at SPC $4800 and its start/loop, ADSR and pitch tables (US v1.0 layout; T-Edition's
# copies are the same). The user may ship these (2026-11-20); made from the ROM on the developer's PC.
RES_BRR, RES_LOOPS, RES_ADSR, RES_TUNE, RES_BASE = 0x51EC7, 0x52018, 0x5203A, 0x5204C, 0x4800


def read_resident(rom):
    """{program: {"brr", "loop", "tune", "adsr"}} for programs 0-7."""
    rom = SS.unheader(bytes(rom))
    size = int.from_bytes(rom[RES_BRR:RES_BRR + 2], "little")
    blob = rom[RES_BRR + 2:RES_BRR + 2 + size]
    starts = [int.from_bytes(rom[RES_LOOPS + 4 * i:RES_LOOPS + 4 * i + 2], "little") for i in range(8)]
    loops = [int.from_bytes(rom[RES_LOOPS + 4 * i + 2:RES_LOOPS + 4 * i + 4], "little") for i in range(8)]
    out = {}
    for i in range(8):
        a = starts[i] - RES_BASE
        e = (starts[i + 1] - RES_BASE) if i < 7 else len(blob)
        brr = blob[a:e]
        brr = brr[:len(brr) - len(brr) % 9]
        out[i] = {"brr": brr, "loop": loops[i] - starts[i], "tune": list(rom[RES_TUNE + 2 * i:RES_TUNE + 2 * i + 2]),
                  "adsr": list(rom[RES_ADSR + 2 * i:RES_ADSR + 2 * i + 2])}
    return out


def write_resident_file(rom, path):
    """The resident waveforms (from a ROM, or read_resident()'s dict) as a small JSON file (hex BRR) a mod's bundle
    carries; add_resident() puts them in a pack."""
    res = rom if isinstance(rom, dict) else read_resident(rom)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"resident": [{"program": p, "brr": r["brr"].hex(), "loop": r["loop"], "tune": r["tune"], "adsr": r["adsr"]}
                                for p, r in sorted(res.items())]}, f, indent=1)
    return path


def add_resident(pack_dir, res):
    """Append resident waveforms ({program: {...}}, or a write_resident_file path) to a pack: songs.json "resident"
    rows (program, offset, length, loop, tune, adsr) over songs.bin. The player uses them for programs $00-$07
    instead of its synthesized stand-ins."""
    if isinstance(res, str):
        rows = json.load(open(res, encoding="utf-8"))["resident"]
        res = {r["program"]: {"brr": bytes.fromhex(r["brr"]), "loop": r["loop"], "tune": r["tune"], "adsr": r["adsr"]} for r in rows}
    jpath = os.path.join(pack_dir, "songs.json")
    pack = json.load(open(jpath, encoding="utf-8"))
    bpath = os.path.join(pack_dir, pack.get("blob", "songs.bin"))
    blob = bytearray(open(bpath, "rb").read())
    pack["resident"] = []
    for p, r in sorted(res.items()):
        pack["resident"].append({"program": p, "offset": len(blob), "length": len(r["brr"]), "loop": r["loop"],
                                 "tune": list(r["tune"]), "adsr": list(r["adsr"])})
        blob += r["brr"]
    open(bpath, "wb").write(blob)
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(pack, f, indent=1)
    return len(res)


def load_pack(pack_dir):
    """A pack (songs.json + songs.bin) back into write_pack's dicts: (songs, samples, meta)."""
    pack = json.load(open(os.path.join(pack_dir, "songs.json"), encoding="utf-8"))
    blob = open(os.path.join(pack_dir, pack.get("blob", "songs.bin")), "rb").read()
    samples = {s["id"]: {"brr": blob[s["offset"]:s["offset"] + s["length"]], "loop": s["loop"], "tune": s["tune"],
                         "adsr": s["adsr"]} for s in pack["samples"]}
    songs = {}
    for r in pack["songs"]:
        songs[r["slot"]] = {"data": blob[r["offset"]:r["offset"] + r["length"]], "instruments": r["instruments"],
                            **{k: r[k] for k in ("name", "title", "file") if k in r}}
    meta = {k: v for k, v in pack.items() if k not in ("samples", "songs", "format", "blob", "resident")}
    return songs, samples, meta


def _addrs(text):
    out = {}
    for part in (text or "").split(","):
        if part.strip():
            k, v = part.split("=")
            out[k.strip()] = int(v, 0)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("read")
    r.add_argument("rom")
    r.add_argument("--pointers", default="")
    r.add_argument("--tables", default="")
    r.add_argument("--slot-offset", default="0")
    r.add_argument("--sample-offset", default="0")
    r.add_argument("--slots", default="")
    r.add_argument("--out", default="")
    r.add_argument("--merge", action="store_true", help="add to the pack already in --out")
    r.add_argument("--no-lookahead-patch", action="store_true", help="an unpatched FF6 driver (not mfvitools')")
    rs = sub.add_parser("resident", help="FF6's resident waveforms: into a pack (--pack) and/or a file (--file)")
    rs.add_argument("rom")
    rs.add_argument("--pack", default="")
    rs.add_argument("--file", default="")
    a = ap.parse_args()
    import ff6snes as S
    rom = S.rom_bytes(a.rom)
    if a.cmd == "resident":
        if a.file:
            print("->", write_resident_file(rom, a.file))
        if a.pack:
            print(f"{add_resident(a.pack, read_resident(rom))} resident waveforms -> {a.pack}")
        return
    slots = {int(x, 16) for x in a.slots.split(",") if x} or None
    got = read_songs(rom, _addrs(a.pointers), _addrs(a.tables), slots, int(a.slot_offset, 0), int(a.sample_offset, 0))
    for slot, song in sorted(got["songs"].items()):
        sc = SS.scan_song(song["data"])
        print(f"{slot:03X}: {len(song['data']):5d} bytes, voices {sc['voices']}, programs "
              f"{' '.join(f'{x:02X}' for x in sc['programs'])}"
              + (f", game sound effects {sc['sfx']}" if sc["sfx"] else "") + (f", runs off the end: {sc['bad']}" if sc["bad"] else ""))
    print(f"{len(got['songs'])} of {got['count']} songs, {len(got['samples'])} samples")
    if a.out:
        songs, samples, meta = ({}, {}, {})
        if a.merge and os.path.exists(os.path.join(a.out, "songs.json")):
            songs, samples, meta = load_pack(a.out)
            # a sample both tables share (the same id and bytes) is one sample
            same = {i for i in set(samples) & set(got["samples"]) if bytes(samples[i]["brr"]) == bytes(got["samples"][i]["brr"])
                    and samples[i]["loop"] == got["samples"][i]["loop"] and list(samples[i]["tune"]) == list(got["samples"][i]["tune"])
                    and list(samples[i]["adsr"]) == list(got["samples"][i]["adsr"])}
            clash = sorted(set(songs) & set(got["songs"])) + sorted((set(samples) & set(got["samples"])) - same)
            if clash:
                raise SystemExit(f"slots/sample ids already in {a.out}: {clash[:10]} (use --slot-offset / --sample-offset)")
        songs.update(got["songs"])
        samples.update(got["samples"])
        if a.no_lookahead_patch:
            meta["lookahead_patch"] = False
        SS.write_pack(a.out, songs, samples, meta)
        print(f"-> {a.out}: {len(songs)} songs, {len(samples)} samples")


if __name__ == "__main__":
    main()
