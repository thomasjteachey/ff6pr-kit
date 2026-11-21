"""FF6 SNES songs (its sound driver's format) -> a song pack the kit's SNES music player plays.

  python tools/snes_songs.py read ROM [--slots 24,2f] [--out DIR]   # songs + samples from an FF6-layout ROM
  python tools/snes_songs.py check DIR                                # a pack's songs: commands, programs, sizes
  python tools/snes_songs.py summary ROM                              # one line a song

FF6's driver keeps its tables in bank C5 (US v1.0 layout; mods that expand the ROM relocate them and
leave pointers at the same places, as mfvitools/johnnydmad do):
  C5/3C5E   number of songs
  C5/0539   pointer to the song pointer table (3-byte ROM addresses; a song = 2-byte size + the bytes
            the driver keeps at SPC $1C00: base address, "no voice" marker, 8 + 8 voice pointers, script)
  C5/01E3   pointer to the instrument table (32 bytes a song: 16 sample ids, programs $20-$2F)
  C5/0222   pointer to the BRR pointer table (3-byte addresses; a sample = 2-byte size + BRR blocks)
  C5/041C, 049C, 04DE   pointers to the loop (2 bytes: byte offset), pitch (2 bytes) and ADSR tables
The pack (plugin/PrKit/Snes/SongPack.cs reads it): songs.json + songs.bin, the samples a pack's songs
use and the songs' bytes. Nothing of the driver itself is read or written: only song data.

A pack is made on the player's machine from their own seed (Beyond Chaos: tools/bc_music.py); it is
never shipped. Samples in a Beyond Chaos seed are BC's own BRR files (MIT); a vanilla ROM's songs use
the game's samples, so a pack from one is for testing only.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

PACK_FORMAT = "prkit-snes-songs/1"
OFF_COUNT = 0x53C5E
OFF_SONG_PTR, OFF_INST_PTR, OFF_BRR_PTR = 0x50539, 0x501E3, 0x50222
OFF_LOOP_PTR, OFF_PITCH_PTR, OFF_ADSR_PTR = 0x5041C, 0x5049C, 0x504DE
# command parameter counts ($C4-$FF), as the driver reads them
CMD_BYTES = [1, 2, 1, 2, 2, 3, 0, 3, 0, 2, 0, 1,
             0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 1, 1, 1, 1, 1, 1,
             1, 0, 1, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0,
             1, 2, 1, 2, 1, 3, 2, 2, 2, 0, 0, 0, 2, 0, 0, 0]


# FF6's SNES songs (US v1.0 ids, the disassembly's names) -> the Pixel Remaster's bgm_asset id that is
# the same piece (its track there: map.csv / scripts' PlayBGM / monster_party.battle_bgm_asset_id).
# Checked against the porter's map pairs (data/snes_pr_maps.json) and the event translator's votes;
# by name where those are thin. Songs the PR plays as environment sounds (waterfall, wind, trains,
# chocobos, cranes, fire, crowd) have none. Multi-part songs map to their first part.
FF6_SONG_PR_BGM = {
    0x01: 69,   # prelude
    0x02: 73, 0x03: 1, 0x04: 2,            # opening theme 1-3 (Omen 01a/b/c)
    0x05: 4, 0x06: 27, 0x07: 12, 0x08: 49, 0x09: 19, 0x0A: 8, 0x0B: 28, 0x0C: 14, 0x0D: 5,
    0x0E: 30, 0x0F: 50, 0x10: 42, 0x11: 60, 0x12: 23, 0x13: 29, 0x14: 25, 0x15: 43, 0x16: 9,
    0x17: 3, 0x18: 16, 0x19: 18, 0x1A: 24, 0x1B: 44, 0x1C: 13, 0x1D: 22, 0x1F: 26, 0x20: 17,
    0x21: 51, 0x22: 41, 0x23: 10, 0x24: 6, 0x26: 37, 0x27: 36, 0x28: 20, 0x29: 31, 0x2A: 21,
    0x2B: 47, 0x2D: 59, 0x2E: 11, 0x2F: 7, 0x30: 62, 0x31: 48, 0x32: 15, 0x33: 54, 0x34: 57,
    0x35: 46, 0x36: 53, 0x37: 61, 0x38: 74, 0x3B: 65, 0x3D: 32, 0x3E: 55,
    0x41: 33, 0x42: 34, 0x43: 35, 0x44: 38, 0x45: 39, 0x46: 40,   # overture 1-3, wedding waltz 2-4
    0x47: 45, 0x4B: 52, 0x4C: 58, 0x4D: 63, 0x4E: 64, 0x4F: 56, 0x50: 70, 0x52: 68,
    0x53: 71, 0x54: 72,                    # ending 1, 2 (Balance Is Restored 60a/b)
}
# PR tracks that are another form of one of those songs (whole pieces, language versions, the last
# battle's later parts: the SNES plays parts 2 and 3 of Dancing Mad by a jump inside song $3B)
PR_BGM_EXTRA = {76: 0x02, 105: 0x02, 77: 0x41, 78: 0x26, 79: 0x3B, 66: 0x3B, 67: 0x3B, 80: 0x53, 81: 0x53,
                82: 0x53, 83: 0x4F, **{b: 0x42 for b in range(84, 91)}, **{b: 0x27 for b in range(91, 98)},
                **{b: 0x45 for b in range(98, 105)}}


def pr_bgm_to_song():
    """The PR's bgm id -> FF6's SNES song id (the inverse of FF6_SONG_PR_BGM, plus PR_BGM_EXTRA)."""
    m = {b: s for s, b in FF6_SONG_PR_BGM.items()}
    m.update(PR_BGM_EXTRA)
    return m


def unheader(rom):
    return rom[0x200:] if len(rom) % 0x8000 == 0x200 else rom


def rom_offset(addr):
    """A SNES HiROM/ExHiROM address -> file offset (as mfvitools does)."""
    if addr >= 0xC00000:
        return addr - 0xC00000
    if 0x3E0000 <= addr < 0x400000:
        return addr + 0x400000
    return addr


def _ptr(rom, off):
    return rom_offset(int.from_bytes(rom[off:off + 3], "little"))


def read_ff6_songs(rom, slots=None):
    """{"songs": {slot: {"data": bytes, "instruments": [16 ids]}}, "samples": {id: {...}}} from an
    FF6-layout ROM; only the samples the read songs use."""
    rom = unheader(bytes(rom))
    count = rom[OFF_COUNT]
    song_tbl, inst_tbl = _ptr(rom, OFF_SONG_PTR), _ptr(rom, OFF_INST_PTR)
    brr_tbl, loop_tbl = _ptr(rom, OFF_BRR_PTR), _ptr(rom, OFF_LOOP_PTR)
    pitch_tbl, adsr_tbl = _ptr(rom, OFF_PITCH_PTR), _ptr(rom, OFF_ADSR_PTR)
    songs, used = {}, set()
    for slot in range(count):
        if slots is not None and slot not in slots:
            continue
        a = _ptr(rom, song_tbl + 3 * slot)
        size = int.from_bytes(rom[a:a + 2], "little")
        if a == 0 or size == 0 or a + 2 + size > len(rom):
            continue
        # the size field is the song's length - 1 (mfvitools: len - 3 with the 2-byte field); the driver
        # copies one byte more, past the song: not part of it (whatever lies there in the ROM)
        data = rom[a + 2:a + 2 + size + 1]
        inst = [int.from_bytes(rom[inst_tbl + 32 * slot + 2 * i:inst_tbl + 32 * slot + 2 * i + 2], "little")
                for i in range(16)]
        songs[slot] = {"data": data, "instruments": inst}
        used.update(i for i in inst if i)
    samples = {}
    for sid in sorted(used):
        a = _ptr(rom, brr_tbl + 3 * (sid - 1))
        size = int.from_bytes(rom[a:a + 2], "little")
        brr = rom[a + 2:a + 2 + size]
        brr = brr[:len(brr) - len(brr) % 9]
        loop = int.from_bytes(rom[loop_tbl + 2 * (sid - 1):loop_tbl + 2 * (sid - 1) + 2], "little")
        samples[sid] = {"brr": brr, "loop": loop,
                        "tune": list(rom[pitch_tbl + 2 * (sid - 1):pitch_tbl + 2 * (sid - 1) + 2]),
                        "adsr": list(rom[adsr_tbl + 2 * (sid - 1):adsr_tbl + 2 * (sid - 1) + 2])}
    return {"songs": songs, "samples": samples, "count": count}


def write_pack(out_dir, songs, samples, meta=None, sample_names=None):
    """songs: {slot: {"data", "instruments", optional "name", "title"}}; samples: {id: {"brr", "loop",
    "tune", "adsr"}} -> out_dir/songs.json + songs.bin."""
    os.makedirs(out_dir, exist_ok=True)
    blob = bytearray()
    sample_rows, song_rows = [], []
    for sid in sorted(samples):
        s = samples[sid]
        row = {"id": sid, "offset": len(blob), "length": len(s["brr"]), "loop": s["loop"],
               "tune": list(s["tune"]), "adsr": list(s["adsr"])}
        if sample_names and sid in sample_names:
            row["name"] = sample_names[sid]
        blob += s["brr"]
        sample_rows.append(row)
    for slot in sorted(songs):
        s = songs[slot]
        row = {"slot": slot, "offset": len(blob), "length": len(s["data"]), "instruments": list(s["instruments"])}
        for k in ("name", "title", "file"):
            if s.get(k):
                row[k] = s[k]
        blob += s["data"]
        song_rows.append(row)
    pack = {"format": PACK_FORMAT, "driver": "ff6", "lookahead_patch": True, "echo_delay": 5, "blob": "songs.bin"}
    pack.update(meta or {})
    pack["samples"], pack["songs"] = sample_rows, song_rows
    with open(os.path.join(out_dir, "songs.bin"), "wb") as f:
        f.write(blob)
    with open(os.path.join(out_dir, "songs.json"), "w", encoding="utf-8") as f:
        json.dump(pack, f, indent=1)
    return pack


def scan_song(data):
    """What a song's script uses: {"voices", "programs", "commands", "sfx", "bad"} (a static walk of
    each voice's bytes from its pointer, following jumps once)."""
    base = int.from_bytes(data[0:2], "little")
    marker = int.from_bytes(data[2:4], "little")
    off = (0x1C24 - base) & 0xFFFF
    voices, programs, cmds, sfx, bad = [], set(), set(), [], []
    for v in range(16):
        p = int.from_bytes(data[4 + 2 * v:6 + 2 * v], "little")
        if p == marker:
            continue
        if v < 8:
            voices.append(v)
        i = ((p + off) & 0xFFFF) - 0x1C00
        seen = set()
        while 0 <= i < len(data) and i not in seen:
            seen.add(i)
            b = data[i]
            if b < 0xC4:
                i += 1
                continue
            n = CMD_BYTES[b - 0xC4]
            cmds.add(b)
            if b == 0xDC and i + 1 < len(data):
                programs.add(data[i + 1])
            if b in (0xE9, 0xEA):
                sfx.append((v, data[i + 1] if i + 1 < len(data) else None))
            if b in (0xEB, 0xEC, 0xED, 0xEE, 0xEF, 0xFD, 0xFE, 0xFF):
                break
            if b == 0xF6 and i + 2 < len(data):
                i = ((int.from_bytes(data[i + 1:i + 3], "little") + off) & 0xFFFF) - 0x1C00
                continue
            i += 1 + n
        if not 0 <= i < len(data):
            bad.append(v)
    return {"voices": voices, "programs": sorted(programs), "commands": sorted(cmds), "sfx": sfx, "bad": bad}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("read")
    r.add_argument("rom")
    r.add_argument("--slots", default="")
    r.add_argument("--out", default="")
    c = sub.add_parser("check")
    c.add_argument("dir")
    s = sub.add_parser("summary")
    s.add_argument("rom")
    a = ap.parse_args()
    if a.cmd in ("read", "summary"):
        sys.path.insert(0, HERE)
        import ff6snes as S
        rom = S.rom_bytes(a.rom)
        slots = {int(x, 16) for x in a.slots.split(",") if x} if getattr(a, "slots", "") else None
        got = read_ff6_songs(rom, slots)
        for slot, song in sorted(got["songs"].items()):
            sc = scan_song(song["data"])
            print(f"{slot:02X}: {len(song['data']):5d} bytes, voices {sc['voices']}, programs "
                  f"{' '.join(f'{p:02X}' for p in sc['programs'])}"
                  + (f", game sound effects {sc['sfx']}" if sc["sfx"] else "")
                  + (f", runs off the end: {sc['bad']}" if sc["bad"] else ""))
        print(f"{len(got['songs'])} of {got['count']} songs, {len(got['samples'])} samples "
              f"({sum(len(x['brr']) for x in got['samples'].values())} BRR bytes)")
        if a.cmd == "read" and a.out:
            write_pack(a.out, got["songs"], got["samples"])
            print(f"-> {a.out}")
    else:
        pack = json.load(open(os.path.join(a.dir, "songs.json"), encoding="utf-8"))
        blob = open(os.path.join(a.dir, pack.get("blob", "songs.bin")), "rb").read()
        ids = {s["id"] for s in pack["samples"]}
        problems = 0
        for row in pack["songs"]:
            data = blob[row["offset"]:row["offset"] + row["length"]]
            sc = scan_song(data)
            missing = [i for i in row["instruments"] if i and i not in ids]
            low = [p for p in sc["programs"] if p < 0x20]
            if missing or low or sc["sfx"] or sc["bad"]:
                problems += 1
                print(f"{row['slot']:02X} {row.get('name', '')}: missing samples {missing}, programs below $20 {low}, "
                      f"game sound effects {sc['sfx']}, off the end {sc['bad']}")
        print(f"{len(pack['songs'])} songs, {len(pack['samples'])} samples, {problems} with problems")


if __name__ == "__main__":
    main()
