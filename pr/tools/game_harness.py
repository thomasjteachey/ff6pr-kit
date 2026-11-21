"""Talk to a plugin's test harness in a headless game run: the modding kit's (plugin/PrKit/Harness.cs),
which BNW's probe run starts (BnwPlugin/GameHarness.cs adds party, skipmsg, quit) and any kit plugin's
test run starts in any Pixel Remaster (tools/kit.py run <game> --harness; pr/MODDING.md).

Start the run (no window, no sound, saves blocked; it stops on "quit" or after -Minutes):

    powershell -NoProfile -ExecutionPolicy Bypass -File pr\\tools\\probe_headless.ps1 -Mods Magicite `
        -Minutes 30 -Extra "harness=1" -Until "\\[probe\\] done"
    .venv/Scripts/python tools/kit.py run ff5 --harness --minutes 30        (a kit plugin's game)

then send commands (each argument one command, replies printed in order):

    .venv/Scripts/python tools/game_harness.py state party "press action" "wait 60"
    .venv/Scripts/python tools/game_harness.py --until "scene battle" --timeout 120 state
    .venv/Scripts/python tools/game_harness.py --repeat "press action" --until "scene field" --timeout 300

Commands: ping, help, state, newgame, slots, load [slot|party] [goto], skipmsg on|off, press <key> [hold frames],
wait <frames>, warp <map> [point], script <name>, battle <party>, encount <party>, log,
shot <file.png> [width [height]] [layers], shotinfo, title, idle <minutes>, quit, and a mod's own (BNW: party).
newgame answers once the title took it (asked again every 1.5 s through the title's intro); title goes back to
the title screen (the game's own MainGame.GotoTitle); idle <minutes> makes a game with no client quit by itself
(tools/test_batch.py keeps a "warm" game up between batches that way). Any number of clients may be connected at
once (their commands run one at a time): this client works while the test runner is connected too.
shot needs a run with a graphics device, still windowless: probe_headless.ps1 -Graphics, or
kit.py run <game> --harness --graphics. It draws the frame from the game's cameras (a windowless
run draws nothing by itself) to a PNG at the path given (absolute, no spaces; a width alone keeps
the screen's shape); 'layers' also writes each off-screen layer (field, UI...). shotinfo lists the
cameras, images and canvases it works from:

    .venv/Scripts/python tools/game_harness.py "shot C:/tmp/shots/01.png 1280" Keys: action cancel menu up down left right pageup pagedown switchleft
switchright start select shortcut.
--until REGEX: send the commands again (every --every seconds) until a reply matches.
--repeat CMD: with --until, the command sent between checks (e.g. a press), the checks being
the other commands (default: state).
"""
import argparse
import re
import socket
import sys
import time

PORT = 47811


def connect(timeout):
    end = time.time() + timeout
    while True:
        try:
            s = socket.create_connection(("127.0.0.1", PORT), timeout=5)
            s.settimeout(130)
            return s
        except OSError:
            if time.time() > end:
                raise
            time.sleep(1)


def ask(sock, f, line):
    sock.sendall((line + "\n").encode("utf-8"))
    reply = f.readline()
    if not reply:
        raise ConnectionError("the game closed the connection")
    return reply.rstrip("\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("commands", nargs="*", default=["state"])
    ap.add_argument("--until", help="repeat until a reply matches this regex")
    ap.add_argument("--repeat", help="a command sent between the checks (with --until)")
    ap.add_argument("--every", type=float, default=1.0)
    ap.add_argument("--timeout", type=float, default=120)
    ap.add_argument("--connect", type=float, default=90, help="seconds to wait for the game to listen")
    a = ap.parse_args()
    sock = connect(a.connect)
    f = sock.makefile("r", encoding="utf-8", newline="\n")
    if not a.until:
        for c in a.commands:
            print(f"> {c}\n{ask(sock, f, c)}", flush=True)
        return 0
    end = time.time() + a.timeout
    last = None
    while True:
        for c in a.commands:
            r = ask(sock, f, c)
            if r != last:
                print(f"[{time.strftime('%H:%M:%S')}] {c}: {r}", flush=True)
                last = r
            if re.search(a.until, r):
                print(f"matched: {a.until}", flush=True)
                return 0
        if time.time() > end:
            print(f"timed out waiting for: {a.until}", flush=True)
            return 1
        if a.repeat:
            r = ask(sock, f, a.repeat)
            if r.startswith("error"):
                print(f"{a.repeat}: {r}", flush=True)
                return 2
        else:
            time.sleep(a.every)


if __name__ == "__main__":
    sys.exit(main())
