"""Reference recordings of FF6-driver songs from a real SNES emulator, and comparisons with the kit's player.

  python tools/snes_song_ref.py record ROM --slots 24,14 --seconds 30 --out DIR     # DIR/ref_24.wav ...
  python tools/snes_song_ref.py compare REF.wav OURS.wav [--json]                     # envelope + spectrum
  python tools/snes_song_ref.py check ROM PACKDIR --slots 24,14 [--seconds 30]       # both, a table

Testing only (the user's own ROM, never shipped): the song under test is put in the slot the game plays
at power-on (song $02, the title) of a copy of ROM in build/snes-test, tools/snes_harness.py (Snes9x,
windowless) runs it from power-on and keeps the sound from the song's first sample. The core outputs one
sample per S-DSP sample (it calls the rate 32040 Hz, the console's real clock), so recordings are
compared sample for sample with the kit's player, which renders at the nominal 32000.

compare (plugin/Snes.Tests' compare command; no Python packages needed): both are aligned on their
first sound, then
  envelope: RMS in 50 ms windows in dB (silence floored at -60 dB); the mean absolute difference and the
            correlation of the two curves
  spectrum: the average magnitude spectrum in 48 log-spaced bands 40 Hz-15 kHz, mean absolute dB difference
  samples:  the best correlation of the waveforms within +-64 samples, per 1 s block (1.0 = the same)
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import wave

import array

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
TEST_DIR = os.path.join(ROOT, "build", "snes-test")
BOOT_SLOT = 0x02
TESTS = os.path.join(ROOT, "plugin", "Snes.Tests")


def redirected_rom(rom, slot):
    """ROM bytes with the power-on song (slot $02) replaced by `slot`'s song and instruments."""
    import snes_songs as SS
    rom = bytearray(SS.unheader(bytes(rom)))
    song_tbl = SS._ptr(rom, SS.OFF_SONG_PTR)
    inst_tbl = SS._ptr(rom, SS.OFF_INST_PTR)
    rom[song_tbl + 3 * BOOT_SLOT:song_tbl + 3 * BOOT_SLOT + 3] = rom[song_tbl + 3 * slot:song_tbl + 3 * slot + 3]
    rom[inst_tbl + 32 * BOOT_SLOT:inst_tbl + 32 * BOOT_SLOT + 32] = rom[inst_tbl + 32 * slot:inst_tbl + 32 * slot + 32]
    return bytes(rom)


def record(rom_path, slot, seconds, out_wav, threshold=8):
    import ff6snes as S
    from snes_harness import Snes
    os.makedirs(TEST_DIR, exist_ok=True)
    test_rom = os.path.join(TEST_DIR, f"songref_{slot:02X}.sfc")
    with open(test_rom, "wb") as f:
        f.write(redirected_rom(S.rom_bytes(rom_path), slot))
    snes = Snes(test_rom)
    want = int(seconds * 32040)
    try:
        snes.capture_audio()
        start, frames = None, 0
        while frames < 60 * 60:
            snes.run(30)
            frames += 30
            if start is None:
                start = first_sound(snes.audio, threshold)
            if start is not None and len(snes.audio) // 4 - start >= want:
                break
        a = bytes(snes.audio)
    finally:
        snes.close()
        os.remove(test_rom)
    start = start or 0
    pcm = a[start * 4:(start + want) * 4]
    write_wav(out_wav, pcm)
    return len(pcm) // 4


def first_sound(buf, threshold=8):
    """The first stereo frame with a sample above threshold, or None."""
    a = array.array("h")
    a.frombytes(bytes(buf[:len(buf) // 4 * 4]))
    for i, v in enumerate(a):
        if v > threshold or v < -threshold:
            return i // 2
    return None


def write_wav(path, pcm, rate=32000):
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def compare(ref_wav, ours_wav):
    exe = tests_exe()
    r = subprocess.run(["dotnet", exe, "compare", ref_wav, ours_wav], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stdout + r.stderr)
    return json.loads(r.stdout.strip().splitlines()[-1])


def tests_exe():
    exe = os.path.join(TESTS, "bin", "Release", "net6.0", "Snes.Tests.dll")
    if not os.path.exists(exe):
        subprocess.run(["dotnet", "build", "-c", "Release", "-nologo", "-v", "q"], cwd=TESTS, check=True)
    return exe


def render_ours(pack_dir, slot, seconds, out_wav):
    r = subprocess.run(["dotnet", tests_exe(), "render", pack_dir, f"{slot:02X}", str(seconds), out_wav],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stdout + r.stderr)
    return r.stdout.strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("rom")
    r.add_argument("--slots", required=True)
    r.add_argument("--seconds", type=float, default=30)
    r.add_argument("--out", required=True)
    c = sub.add_parser("compare")
    c.add_argument("ref")
    c.add_argument("ours")
    c.add_argument("--json", action="store_true")
    k = sub.add_parser("check")
    k.add_argument("rom")
    k.add_argument("pack")
    k.add_argument("--slots", required=True)
    k.add_argument("--seconds", type=float, default=30)
    k.add_argument("--out", default=os.path.join(ROOT, "build", "snes-test", "songref"))
    k.add_argument("--keep", action="store_true", help="re-use recordings already in --out")
    a = ap.parse_args()
    if a.cmd == "record":
        os.makedirs(a.out, exist_ok=True)
        for s in a.slots.split(","):
            slot = int(s, 16)
            n = record(a.rom, slot, a.seconds, os.path.join(a.out, f"ref_{slot:02X}.wav"))
            print(f"{slot:02X}: {n / 32040:.1f} s")
    elif a.cmd == "compare":
        m = compare(a.ref, a.ours)
        print(json.dumps(m) if a.json else m)
    else:
        os.makedirs(a.out, exist_ok=True)
        rows = []
        for s in a.slots.split(","):
            slot = int(s, 16)
            ref = os.path.join(a.out, f"ref_{slot:02X}.wav")
            ours = os.path.join(a.out, f"ours_{slot:02X}.wav")
            if not (a.keep and os.path.exists(ref)):
                record(a.rom, slot, a.seconds, ref)
            render_ours(a.pack, slot, a.seconds + 2, ours)
            m = compare(ref, ours)
            m["slot"] = f"{slot:02X}"
            rows.append(m)
            print(json.dumps(m), flush=True)
        with open(os.path.join(a.out, "check.json"), "w") as f:
            json.dump(rows, f, indent=1)


if __name__ == "__main__":
    main()
