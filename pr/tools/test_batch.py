"""The PC test runner's batches: one build check, one install and as few game launches as possible
for many sessions' test requests, each answered with pass/fail and its decisive log lines.

    .venv/Scripts/python tools/test_batch.py <batch.json> [--no-build] [--no-install] [--only RUN] [--part A-B]
                                                          [--defer-restore] [--no-warm]
    .venv/Scripts/python tools/test_batch.py --build bnw|wc|bc     (the pre-flight build alone)
    .venv/Scripts/python tools/test_batch.py --check               (may a run start now? Wow.exe / the game / a warm game)
    .venv/Scripts/python tools/test_batch.py --cool                (stop the warm game, if one is up)
    .venv/Scripts/python tools/test_batch.py --restore             (BC's test install restored, BNW back active)
    .venv/Scripts/python tools/test_batch.py --next QUEUE.txt      (take the queue's next line and print it: queue4.sh)
    .venv/Scripts/python tools/test_batch.py --estimate BATCH.json [--part A-B]   (seconds it should take)

A batch (JSON):
    {"name": "bnw-1", "mod": "bnw",                         bnw | wc | bc | none (installed as is)
     "runs": [
       {"name": "selftests", "kind": "probe", "extra": "slot=new;sweep=0", "minutes": 8,
        "requests": [{"id": "cover", "from": "bnw-engine", "pass": ["covered-hit self-test ok"], "fail": "..."}]},
       {"name": "shots", "kind": "harness", "graphics": true, "minutes": 30,
        "requests": [{"id": "monster-images", "from": "bnw-sprites",
                      "steps": ["boot", "battle 367", "until scene battle 120", "wait 300", "shot C:/x/a.png 1280"],
                      "pass": ["..."], "fail": "..."}]},
       {"name": "wc", "kind": "wctest", "wctest": "seed=a;preset=moogle cup;check=snes_rules", "minutes": 10, "requests": [...]},
       {"name": "bc", "kind": "kit", "game": "ff6", "minutes": 15, "requests": [{"steps": [...]}]}]}

kinds: probe (probe_headless.ps1 -Extra; "until" optional), harness (probe_headless.ps1 -Extra harness=1, BNW's;
the requests' steps in order), wctest (probe_headless.ps1 -WcTest), live (-Live <dir>), kit (kit.py run
<game> --harness: BC and other kit plugins; steps). "graphics": a graphics device (still no window).
Steps are game_harness.py commands, plus "until <regex> [timeout s] [check <cmd>|logfile] [repeat <cmd>]": send
"state" (or <cmd>; or read the BepInEx log) until a reply matches (pressing <repeat> between checks), and the
macros boot, tofield, totitle, freefield, warpfree, killall, loadfield, sleep <s>. A step whose reply starts with
"error" or an "until" that times out fails its request; its remaining steps are skipped (the next request's steps
still run). Request options: keep_going, skip_to, fast_sleep (a "sleep N" ends once the log has a line for one of
the request's pass regexes it hadn't matched yet, plus 1.5 s).
A request passes when every "pass" regex matches the run's log or its harness replies and its "fail" regex
(default Exception|\\[Error, minus known noise) matches nothing.

Every launch: refused while Wow.exe or the game runs; the save folder is checksummed before and after (a test run
never saves: a change is reported loudly). Logs: pr/build/test_logs/<stamp>_<run>.log; results:
pr/build/test_logs/<stamp>_<batch>.json; summary prepended to pr/build/test_runs.md (newest first).

Speed (2026-11-20, "it shouldn't be lasting this long"):
- warm games: a harness/kit launch stays up after its run (the harness's "idle 10": the game quits by itself
  after 10 minutes with no client, or as soon as Wow.exe starts) and the next harness/kit run with the same
  kind, settings and installed files reuses it: "title" (back to the title), then its steps (a New Game: ~20 s
  instead of a ~90 s launch). build/test_logs/warm_game.json says which game; anything else (a probe, WcTest,
  an install that changes files, setup/undo) stops it first. A game that dies mid-run is relaunched for the
  requests left (twice at most).
- boot polls: New Game from the moment the title is up (the harness asks again until the title takes it), the
  opening's warp watched, not slept on; polls every 0.25 s.
- BNW installs only when something changed: active already, with the built DLL, its data files and the Magicite
  folder the same as the installed ones, nothing is deployed (and a warm game stays up). WC's bundle and the mod
  switch skip unchanged work inside deploy.sh / wc_bundle.py. --defer-restore (queue4.sh): WC/BC stay installed
  for the next batch, the queue's end puts BNW back (--restore).
- probes: "slot=new" (BNW probe) starts a New Game at once instead of slot=party's wait for the title's demo
  (~60 s sooner while no save loads headless); the probe's selftestmax default is 30 s.
- the queue (build/batches/queue4.sh, --next): one mod's turn at a time (BNW, WC, BC, T-Edition: every queued batch
  of that mod, its install once, its warm game for all; no time limit, a batch of the mod queued meanwhile joins);
  within a turn the shortest batch first (a line passed over 3 times goes next). --part A-B runs requests A..B.
- pre-flight (after the build, before any install or launch): the mod's offline suites (Rules.Tests + test_mod for
  BNW, Wc.Tests + WcAi.Tests, Bc.Tests + test_bc, Ted.Tests + test_mod + test_snes_events; PrKit.Tests when the kit
  changed), run when what they read changed, blocking only on failures not in their baseline; a request's
  "offline": [commands] instead; tools/magicite_check.py on the Magicite folders to be installed or copied in, and
  the installed folders checked for files two of them ship before each launch. A failure: nothing installed or
  launched, "failed (pre-flight)" in test_runs.md, exit 5.
"""
import argparse
import csv
import datetime
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time

# (TEST_BATCH_PR: a copy of this file run from elsewhere against the project, e.g. while testing a new version)
PR = os.environ.get("TEST_BATCH_PR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.join(PR, "tools") not in sys.path:
    sys.path.insert(0, os.path.join(PR, "tools"))
GAME = r"D:\SteamLibrary\steamapps\common\FINAL FANTASY VI PR"
BEP = os.path.join(GAME, "BepInEx")
LOG = os.path.join(BEP, "LogOutput.log")
MAGICITE_DIR = os.path.join(GAME, "FINAL FANTASY VI_Data", "StreamingAssets", "Magicite")
SHELF = os.path.join(BEP, "mod-shelf")
MAGICITE_CFG = os.path.join(BEP, "config", "silvris.magicite.cfg")


def _saves_dir():
    """the game's save folder (Documents/My Games/FINAL FANTASY VI PR/Steam/<the Steam account's id>): FF6PR_SAVES, else
    the account folder there (the newest, if several), else the Steam folder itself. No user name or account id in
    the code: the kit is public (repo_publish refuses local user folders)."""
    if os.environ.get("FF6PR_SAVES"):
        return os.environ["FF6PR_SAVES"]
    steam = os.path.join(os.environ.get("USERPROFILE") or os.path.expanduser("~"), "Documents", "My Games",
                         "FINAL FANTASY VI PR", "Steam")
    try:
        ids = [d for d in os.listdir(steam) if d.isdigit() and os.path.isdir(os.path.join(steam, d))]
    except OSError:
        return steam
    return max((os.path.join(steam, d) for d in ids), key=os.path.getmtime) if ids else steam


SAVES = _saves_dir()
PY = os.path.join(PR, ".venv", "Scripts", "python.exe")
# (TEST_BATCH_LOGS: logs, summary and runner state elsewhere: an experiment that mustn't touch the real ones)
LOGS = os.environ.get("TEST_BATCH_LOGS") or os.path.join(PR, "build", "test_logs")
RUNS_MD = os.path.join(LOGS, "test_runs.md") if os.environ.get("TEST_BATCH_LOGS") else os.path.join(PR, "build", "test_runs.md")
BASH = r"C:\Program Files\Git\bin\bash.exe"
PORT = 47811
PLUGINS = {"bnw": ("plugin/BnwPlugin", "BraveNewWorld.PR.dll", "BraveNewWorld"),
           "wc": ("plugin/WcPlugin", "WorldsCollide.PR.dll", "WorldsCollide"),
           "bc": ("plugin/BcPlugin", "BeyondChaos.PR.dll", "BeyondChaos")}
ACTIVE_MODS = ("BraveNewWorld", "WorldsCollide", "BeyondChaos", "TEdition")   # one plugin folder active at a time
DEFAULT_FAIL = r"Exception|\[Error"
# lines every run logs (not failures): Magicite's exporter signature warning
NOISE = re.compile(r"OnExportError\(System\.String, System\.Exception|unsupported parameter System\.Exception")

WARM_FILE = os.path.join(LOGS, "warm_game.json")
WARM_KINDS = ("harness", "kit")
WARM_IDLE_MIN = 10    # a warm game quits by itself after this long with no client
WARM_CAP_MIN = 120    # a warm launch's own limit (probe_headless.ps1 -Minutes / kit.py --minutes)
IDLE_MARK = "idle <minutes>".encode("utf-16-le")        # in a plugin DLL whose kit harness has "idle"
# ... and a "title" that works (the field's GotoTitle state behind a fade: the first one did nothing, 2026-11-20)
TITLE_MARK = "the field's GotoTitle".encode("utf-16-le")
HARNESS_MARK = "prkit-harness".encode("utf-16-le")      # in every plugin DLL with the kit harness
CREATE_BREAKAWAY_FROM_JOB, CREATE_NEW_PROCESS_GROUP, CREATE_NO_WINDOW = 0x01000000, 0x00000200, 0x08000000
POLL = 0.25           # seconds between an "until"'s checks


def say(*a):
    print(*a, flush=True)


# --- processes ----------------------------------------------------------------------------------------

def tasks(image):
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    return [l for l in out.splitlines() if image.lower() in l.lower()]


def game_pids():
    pids = []
    for row in csv.reader(tasks("FINAL FANTASY VI.exe")):
        if len(row) > 1 and row[1].strip().isdigit():
            pids.append(int(row[1]))
    return pids


def pid_alive(pid):
    if not pid:
        return False
    out = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    return any(len(r) > 1 and r[1].strip() == str(int(pid)) for r in csv.reader(out.splitlines()))


def pid_started(pid):
    """when a live process started (epoch seconds), or None where that can't be told (tools/port.py's _pid_started)"""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    h = k.OpenProcess(0x1000, False, int(pid))   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        t = [wintypes.FILETIME() for _ in range(4)]   # creation, exit, kernel, user
        if not k.GetProcessTimes(h, *[ctypes.byref(x) for x in t]):
            return None
        return (t[0].dwHighDateTime << 32 | t[0].dwLowDateTime) / 1e7 - 11644473600
    finally:
        k.CloseHandle(h)


def holds(pid, taken):
    """a lock taken at `taken` (epoch) by pid is still held: pid alive, not this process, and started no later than
    the lock was taken (+5 s): a pid reused after its holder died doesn't count (tools/port.py's _holds)"""
    if not pid or int(pid) == os.getpid() or not pid_alive(pid):
        return False
    started = pid_started(pid)
    if started is None:
        # Windows: a live pid this user can't open (System, csrss, services...) is no holder: a real one is this
        # user's python.exe (port.py's rule, 18:3x)
        return os.name != "nt"
    return taken is None or started <= taken + 5


def replace_retry(tmp, dst, tries=40):
    """os.replace, again for ~10 s while another process has dst open (Windows: PermissionError; two batches at
    once at 18:06 died on the pre-flight state file)"""
    for i in range(tries):
        try:
            os.replace(tmp, dst)
            return True
        except PermissionError:
            time.sleep(0.25)
    try:
        os.remove(tmp)
    except OSError:
        pass
    say(f"[batch] {dst} stayed busy: not written")
    return False


def kill_pid(pid):
    subprocess.run(["taskkill", "/PID", str(int(pid)), "/F"], capture_output=True)


def blocked():
    if tasks("Wow.exe"):
        return "Wow.exe is running (the user plays): wait"
    if tasks("FINAL FANTASY VI.exe"):
        return "FINAL FANTASY VI.exe is running"
    return None


def wait_free(game_wait=90, wow_wait=4 * 3600, warm=None):
    """None once nothing blocks a launch: a game still closing (the previous launch's: ~20 s) gets game_wait
    seconds; while Wow.exe runs (the user plays) the queue holds, checking every 30 s, up to wow_wait.
    warm: the warm game this run reuses (it doesn't block); any other warm game is stopped."""
    t = time.time()
    said = None
    while True:
        why = blocked()
        if not why:
            return None
        w = warm_load()
        if why.startswith("Wow") and w:
            cool("Wow.exe is running (the user plays)", w)
        elif w and game_pids() == [w["pid"]]:
            if warm and warm.get("pid") == w["pid"]:
                return None
            cool("a launch needs the game closed", w)
            continue
        waited = time.time() - t
        if why.startswith("Wow") and waited < wow_wait or not why.startswith("Wow") and waited < game_wait:
            if why != said:
                say(f"[batch] waiting: {why} ({time.strftime('%H:%M:%S')})")
                said = why
            time.sleep(30 if why.startswith("Wow") else 3)
            continue
        return why


# --- files --------------------------------------------------------------------------------------------

def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_stat(root, skip_dirs=("__pycache__",)):
    """{relative path: (size, mtime_ns)} of every file under root (scandir: no extra stat call on Windows)"""
    out = {}
    if not os.path.isdir(root):
        return out
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if e.name not in skip_dirs:
                                stack.append(e.path)
                        else:
                            st = e.stat(follow_symlinks=False)
                            out[os.path.relpath(e.path, root).replace(os.sep, "/")] = (st.st_size, st.st_mtime_ns)
                    except OSError:
                        continue
        except OSError:
            continue
    return out


def tree_fp(*roots):
    h = hashlib.sha1()
    for root in roots:
        h.update(f"#{root}\n".encode("utf-8"))
        for k, (s, m) in sorted(tree_stat(root).items()):
            h.update(f"{k}|{s}|{m}\n".encode("utf-8"))
    return h.hexdigest()


def plugins_fp():
    """what a running game loaded: the plugin folders and the Magicite folder (sizes and times)"""
    return tree_fp(os.path.join(BEP, "plugins"), MAGICITE_DIR)


def mirror_same(src, dst):
    """Would robocopy /MIR src dst change nothing that matters? The same files with the same sizes, and the same
    content where the times differ (a porter run rewrites unchanged files). __pycache__ left out."""
    a, b = tree_stat(src), tree_stat(dst)
    if not a or a.keys() != b.keys():
        return False
    for k, (s, m) in a.items():
        s2, m2 = b[k]
        if s != s2:
            return False
        if abs(m - m2) > 2_000_000_000 and md5(os.path.join(src, k)) != md5(os.path.join(dst, k)):
            return False
    return True


def same_file(a, b):
    return os.path.exists(a) and os.path.exists(b) and os.path.getsize(a) == os.path.getsize(b) and md5(a) == md5(b)


def save_digest():
    d = {}
    for root, _, files in os.walk(SAVES):
        for n in files:
            p = os.path.join(root, n)
            st = os.stat(p)
            d[os.path.relpath(p, SAVES)] = (st.st_size, st.st_mtime_ns, md5(p))
    return d


def log_size():
    try:
        return os.path.getsize(LOG)
    except OSError:
        return 0


def read_log(start=0):
    try:
        with open(LOG, encoding="utf-8", errors="replace", newline="") as f:
            f.seek(start)
            return f.read()
    except OSError:
        return ""


def read_log_lines(pos):
    """(complete new lines of the BepInEx log from byte pos, the position after them)"""
    try:
        with open(LOG, "rb") as f:
            f.seek(pos)
            data = f.read()
    except OSError:
        return [], pos
    end = data.rfind(b"\n")
    if end < 0:
        return [], pos
    return data[:end].decode("utf-8", errors="replace").splitlines(), pos + end + 1


ERR = re.compile(r"^\s*(?P<file>[^\s(][^(]*\.cs)\((?P<line>\d+),(?P<col>\d+)\): error (?P<code>\w+): (?P<msg>.*?)(?: \[.*\])?$")


def build(mod, deploy=False):
    """dotnet build -c Release of the mod's plugin (deploy: -p:Deploy=true, the csproj copies it into the
    game's plugin folder). -> (ok, [error lines], seconds)."""
    rel = PLUGINS[mod][0]
    t = time.time()
    args = ["dotnet", "build", "-c", "Release", "-nologo", "-v", "q"] + (["-p:Deploy=true"] if deploy else [])
    p = subprocess.run(args, cwd=os.path.join(PR, rel),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    errs = []
    for line in (p.stdout + p.stderr).splitlines():
        m = ERR.match(line)
        if m:
            f = os.path.relpath(m["file"], PR) if os.path.isabs(m["file"]) else m["file"]
            e = f"{f.replace(os.sep, '/')}:{m['line']}: {m['code']} {m['msg']}"
            if e not in errs:
                errs.append(e)
    ok = p.returncode == 0 and not errs
    if not ok and not errs:
        errs = [l for l in (p.stdout + p.stderr).splitlines() if "error" in l.lower()][:10] or ["build failed (no error lines)"]
    return ok, errs, time.time() - t


def installed_mod():
    for m in ("bnw", "wc", "bc"):
        if os.path.isdir(os.path.join(BEP, "plugins", PLUGINS[m][2])):
            return m
    return None


def bc_installed():
    return os.path.exists(os.path.join(BEP, "bc_testinstall.json"))


def run_cmd(args, cwd=PR, timeout=900, env=None):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                       env=dict(os.environ, **env) if env else None,
                       stdin=subprocess.DEVNULL)
    return p.returncode, (p.stdout + p.stderr)


def bc_restore_if_installed():
    if bc_installed():
        rc, out = run_cmd([PY, "tools/bc_testinstall.py", "restore"])
        say(f"[batch] BC test install restored (rc {rc})")
        return out
    return ""


def wait_quiet(folder, quiet=20, max_wait=300, must=()):
    """Wait until nothing under folder changed for `quiet` seconds and the `must` files exist (a porter run
    rewrites mods/BraveNewWorld in ~30 s; an install meanwhile mirrors half of it). -> None or a reason."""
    t = time.time()
    said = False
    while True:
        newest = max((m for _, m in tree_stat(folder).values()), default=0) / 1e9
        missing = [m for m in must if not os.path.exists(os.path.join(folder, m))]
        if not missing and time.time() - newest >= quiet:
            return None
        if time.time() - t > max_wait:
            return f"{folder} kept changing for {max_wait} s" + (f" (missing {missing})" if missing else "")
        if not said:
            say(f"[batch] waiting for {os.path.relpath(folder, PR)} to settle (a porter run?)")
            said = True
        time.sleep(5)


def game_gone(quiet=10, max_wait=300):
    """None once no FINAL FANTASY VI.exe, no UnityCrashHandler64.exe and no BepInEx/probe_run.lock for `quiet` s
    straight (a closing game, its crash handler or the launcher's cleanup still held Magicite/BraveNewWorld when
    wc-4's install moved it, 17:04, 2026-11-20), else why not"""
    t0, since = time.time(), None
    while time.time() - t0 < max_wait:
        busy = tasks("FINAL FANTASY VI.exe") or tasks("UnityCrashHandler64.exe") or os.path.exists(os.path.join(BEP, "probe_run.lock"))
        if busy:
            since = None
        else:
            since = since or time.time()
            if time.time() - since >= quiet:
                return None
        time.sleep(1)
    return f"the game (or its crash handler / the probe's lock) didn't go for {max_wait} s"


PORT_LOCKS = {"bnw": ["mods/BraveNewWorld.porting", "build/bnw_port.lock"], "bc": ["mods/BeyondChaos.porting"],
              "wc": [], "ted": ["mods/TEdition.porting"]}


def port_busy(mod):
    """a port of the mod's folder under way (tools/port.py's mods/<Mod>.porting, its owner.txt's pid alive; the BNW
    lead's build/bnw_port.lock): the folder's next state isn't there yet"""
    for rel in PORT_LOCKS.get(mod, []):
        p = os.path.join(PR, *rel.split("/"))
        if not os.path.exists(p):
            continue
        owner = os.path.join(p, "owner.txt") if os.path.isdir(p) else p
        try:
            with open(owner, encoding="utf-8", errors="replace") as f:
                m = re.search(r"^pid (\d+)", f.read(), re.M)
            taken = os.path.getmtime(owner)
        except OSError:
            m, taken = None, None
        if m and not holds(int(m[1]), taken):
            continue   # its holder is gone, or its pid is another process's now (port.py takes such a lock over)
        return rel
    return None


def wait_port(mod, max_wait=1800):
    t0, said = time.time(), False
    while time.time() - t0 < max_wait:
        held = port_busy(mod)
        if not held:
            return None
        if not said:
            say(f"[batch] waiting: {held} (a port of {mod} is under way)")
            said = True
        time.sleep(5)
    return f"{port_busy(mod)} held for {max_wait} s"


def built_dll(mod):
    return os.path.join(PR, PLUGINS[mod][0], "bin", "Release", "net6.0", PLUGINS[mod][1])


def magicite_cfg_ok():
    try:
        with open(MAGICITE_CFG, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return True   # deploy.sh only edits one that exists
    return not re.search(r"^Import Directory", text, re.M) or \
        re.search(r"^Import Directory = %StreamingAssets%/Magicite\s*$", text, re.M) is not None


def install_state(mod):
    """-> ("active" | None, why): Brave New World is the active mod and what an install would put there is there
    already (the built DLL, bnw_data.json / bnw_dialog.json, the Magicite folder): nothing to deploy. WC and BC
    always go through their installers (deploy.sh / wc_bundle.py skip unchanged work themselves)."""
    if mod != "bnw":
        return None, f"{mod}: its installer decides"
    if bc_installed():
        return None, "BC's test install is in place"
    _, dll, name = PLUGINS[mod]
    plug = os.path.join(BEP, "plugins", name)
    if not os.path.isdir(plug):
        return None, f"{name} isn't the active mod"
    others = [o for o in ACTIVE_MODS if o != name and os.path.isdir(os.path.join(BEP, "plugins", o))]
    if others:
        return None, f"{', '.join(others)} active too"
    if not same_file(built_dll(mod), os.path.join(plug, dll)):
        return None, "the DLL changed"
    for f in ("bnw_data.json", "bnw_dialog.json"):
        src = os.path.join(PR, "mods", "BraveNewWorld", f)
        if os.path.exists(src) and not same_file(src, os.path.join(plug, f)):
            return None, f"{f} changed"
    if not mirror_same(os.path.join(PR, "mods", "BraveNewWorld"), os.path.join(MAGICITE_DIR, name)):
        return None, "the Magicite folder differs"
    if not magicite_cfg_ok():
        return None, "Magicite's import directory isn't the standard one"
    return "active", "unchanged"


def deploy(mod):
    # a snapshot of deploy.sh beside it (its paths come from its own folder): bash reads a script as it runs,
    # and an edit to deploy.sh mid-install broke one ("syntax error near unexpected token", 2026-11-20)
    snap = os.path.join(PR, "tools", ".deploy_test_batch.sh")
    shutil.copyfile(os.path.join(PR, "tools", "deploy.sh"), snap)
    return run_cmd([BASH, "tools/.deploy_test_batch.sh", f"--{mod}", "--pc"], env={"DEPLOY_NO_BUILD": "1"})


def copy_built(mod):
    """the batch's build into the game's plugin folder, as the csproj's Deploy target copies it (the DLL; BNW:
    bnw_data.json, bnw_dialog.json; WC: wc_flags.json): the install is the build the batch checked, without a second
    build (11-20 s, runner-wc-cache 2026-11-20). -> None or why not"""
    _, dll, name = PLUGINS[mod]
    dst = os.path.join(BEP, "plugins", name)
    built = built_dll(mod)
    if not os.path.exists(built):
        return f"no built {dll} ({built})"
    files = [built]
    if mod == "bnw":
        files += [os.path.join(PR, "mods", "BraveNewWorld", f) for f in ("bnw_data.json", "bnw_dialog.json")]
    elif mod == "wc":
        files.append(os.path.join(PR, "plugin", "WcPlugin", "wc_flags.json"))
    os.makedirs(dst, exist_ok=True)
    for f in files:
        if os.path.exists(f):
            shutil.copy2(f, dst)
    return None if md5(built) == md5(os.path.join(dst, dll)) else "the installed DLL differs from the build's"


def install(mod, built=True):
    """Install the mod on the PC (the others set aside), unless what it would install is there already.
    -> (ok, text); text starts with "[batch] blocked:" when the game couldn't be closed for it."""
    why = wait_port(mod)
    if why:
        return False, f"[batch] blocked: {why}"
    if mod == "bnw":
        why = wait_quiet(os.path.join(PR, "mods", "BraveNewWorld"), quiet=3, must=("bnw_data.json", "port_report.txt"))
        if why:
            return False, why
    where, why = install_state(mod)
    if where == "active":
        return True, f"[batch] {mod}: the installed files are the build's: nothing to install"
    # something to change: the game must be closed (a warm game is stopped), and gone for 10 s
    blocked_why = wait_free() or game_gone()
    if blocked_why:
        return False, f"[batch] blocked: {blocked_why}"
    out = bc_restore_if_installed() if mod != "bc" else ""
    if mod in ("bnw", "wc"):
        where, why2 = install_state(mod)
        if where == "active":
            return True, out + f"\n[batch] {mod}: unchanged after BC's restore"
        out += f"[batch] {mod}: installing ({why2})\n"
        # deploy.sh switches the mods' folders and mirrors the data without building (DEPLOY_NO_BUILD); then the
        # batch's own build is copied in (a batch run --no-build builds here first): what the batch checked is what
        # runs, and a file saved since can't slip in (before 2026-11-20 18:3x: a second, -p:Deploy=true build)
        if not built:
            bok, errs, _ = build(mod)
            if not bok:
                return False, out + "\n[batch] build FAILED:\n  " + "\n  ".join(errs)
        rc, o = deploy(mod)
        out += o
        ok = rc == 0 and " error " not in o
        if ok:
            why = copy_built(mod)
            if why:
                ok = False
                out += f"\n[batch] {why}"
            else:
                out += f"\n[batch] {mod}: the batch's build installed (DLL {md5(built_dll(mod))[:8]})"
        return ok, out
    if mod == "bc":
        # --dev: the baselines and the Magicite folder only (seconds), all bc_testinstall uses; a bare bc_bundle.py builds
        # the whole player bundle (Python + Pillow, 2-3 min), which a launch that needs it builds in its own setup
        rc1, o1 = run_cmd([PY, "tools/bc_bundle.py", "--dev"])
        rc2, o2 = run_cmd([PY, "tools/bc_testinstall.py", "install"])
        return rc1 == 0 and rc2 == 0, out + o1 + o2
    return True, out


def restore():
    """The PC's usual state: BC's test install restored, BNW active (after WC/BC batches; queue.sh at its end)."""
    if not bc_installed() and installed_mod() == "bnw":
        return True, "[batch] BNW is active already"
    ok, text = install("bnw", built=os.path.exists(built_dll("bnw")))
    if bc_installed():   # (install restores BC first only when it has something to change)
        why = wait_free()
        if why:
            return False, f"[batch] blocked: {why}"
        text += bc_restore_if_installed()
        ok, t2 = install("bnw", built=os.path.exists(built_dll("bnw")))
        text += t2
    return ok and installed_mod() == "bnw", text


def data_hash(mod):
    """the installed Magicite folder of the mod (sizes and times), short: with the DLL's md5 it names the install"""
    if mod not in PLUGINS:
        return "-"
    d = os.path.join(MAGICITE_DIR, PLUGINS[mod][2])
    return tree_fp(d)[:8] if os.path.isdir(d) else "-"


def dll_md5(mod):
    if mod not in PLUGINS or not PLUGINS[mod][1]:
        return "-"
    p = os.path.join(BEP, "plugins", PLUGINS[mod][2], PLUGINS[mod][1])
    return md5(p)[:8] if os.path.exists(p) else "-"


# --- the warm game -------------------------------------------------------------------------------------

def warm_load():
    """The warm game's state (build/test_logs/warm_game.json) while its process lives, else None."""
    try:
        with open(WARM_FILE, encoding="utf-8") as f:
            w = json.load(f)
    except (OSError, ValueError):
        return None
    if not w.get("pid") or w["pid"] not in game_pids():
        warm_clear()
        return None
    return w


def warm_save(w):
    tmp = WARM_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(w, f, indent=1)
    replace_retry(tmp, WARM_FILE)


def warm_clear():
    try:
        os.remove(WARM_FILE)
    except OSError:
        pass


def warm_allowed(run, opts=None):
    return (run["kind"] in WARM_KINDS and not getattr(opts, "no_warm", False) and not run.get("no_warm")
            and not run.get("setup") and not run.get("undo") and os.environ.get("TEST_BATCH_NO_WARM") != "1")


def warm_mismatch(w, run, fp=None):
    """None when the warm game can take this run, else why not"""
    if run["kind"] != w.get("kind"):
        return f"a {run['kind']} run (the warm game is a {w.get('kind')} launch)"
    if run["kind"] == "kit" and run.get("game", "ff6") != w.get("game", "ff6"):
        return f"another game ({run.get('game')})"
    if run.get("graphics") and not w.get("graphics"):
        return "the run needs graphics"
    if (run.get("extra") or "") != (w.get("extra") or "") or (run.get("set") or {}) != (w.get("set") or {}):
        return "other launch settings"
    if run.get("setup") or run.get("undo"):
        return "the run has setup/undo"
    if installed_mod() != w.get("mod"):
        return "another mod is installed"
    if (fp or plugins_fp()) != w.get("fp"):
        return "the installed plugins or Magicite folder changed"
    if time.time() + int(run.get("minutes", 15)) * 60 > w.get("deadline", 0):
        return "not enough time left in its launch"
    return None


def cool(why, w=None):
    """Stop the warm game (its "quit", then the process), and let its launcher clean up (steam_appid.txt, lock)."""
    w = w or warm_load()
    if not w:
        warm_clear()
        return
    say(f"[batch] stopping the warm game (pid {w['pid']}): {why}")
    try:
        h = Harness(connect_timeout=5, timeout=15)
        try:
            h.ask("quit")
        finally:
            h.close()
    except (OSError, ConnectionError):
        pass
    end = time.time() + 30
    while time.time() < end and w["pid"] in game_pids():
        time.sleep(1)
    if w["pid"] in game_pids():
        kill_pid(w["pid"])
    end = time.time() + 20
    while time.time() < end and pid_alive(w.get("launcher_pid")):
        time.sleep(0.5)
    warm_clear()


def harness_has_idle(kind):
    """Does the harness that will answer support "idle" (so a game may be kept warm)? The plugin DLLs say:
    BNW's for its harness runs; any kit plugin's for kit runs (the reply to "idle" decides in the end)."""
    if kind == "harness":
        dlls = [os.path.join(BEP, "plugins", "BraveNewWorld", PLUGINS["bnw"][1])]
    else:
        dlls = [os.path.join(r, n) for r, _, fs in os.walk(os.path.join(BEP, "plugins")) for n in fs if n.endswith(".PR.dll")]
    for p in dlls:
        try:
            with open(p, "rb") as f:
                data = f.read()
        except OSError:
            continue
        if HARNESS_MARK in data and IDLE_MARK in data and TITLE_MARK in data:
            return True
    return False


# --- the harness -------------------------------------------------------------------------------------

class Harness:
    def __init__(self, connect_timeout, timeout=150, alive=None):
        """alive: a function that says False once waiting is pointless (the launcher ended)"""
        end = time.time() + connect_timeout
        while True:
            try:
                self.s = socket.create_connection(("127.0.0.1", PORT), timeout=5)
                break
            except OSError:
                if time.time() > end or (alive and not alive()):
                    raise
                time.sleep(1)
        self.s.settimeout(timeout)
        self.f = self.s.makefile("r", encoding="utf-8", newline="\n")

    def ask(self, line):
        self.s.sendall((line + "\n").encode("utf-8"))
        r = self.f.readline()
        if not r:
            raise ConnectionError("the game closed the connection")
        return r.rstrip("\n")

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass


# until <regex> [timeout s] [check <cmd>] [every <s>] [repeat <cmd>]: send <check> (default "state") until a reply
# matches; "every": seconds between checks (and repeats: e.g. a press every 2 s)
UNTIL = re.compile(r"^until\s+(?P<re>.+?)(?:\s+(?P<t>\d+))?(?:\s+check\s+(?P<chk>.+?))?(?:\s+every\s+(?P<ev>[\d.]+))?(?:\s+repeat\s+(?P<rep>.+))?$")
# "boot": from the run's start to a free field with a party (messages skipped): a NEW GAME, warped off the
# opening to map 112 (BNW's AI tests' quiet map). On this PC no save got past the title headless (2026-11-20:
# "load" = the in-game load does nothing there, "load <slot> title" = the title's LoadAsync reads the save and
# stalls); ~74 s after the title its idle demo plays the opening on map 609 and looks like a loaded field.
# "loadfield" (the newest party save, 3 tries) is kept for a machine whose saves load.
# (the title screen's idle demo runs on a field: "state" says "title window" while the title is up)
# Since 2026-11-20 (speed): "newgamego" asks from the moment the title is up (no fixed 25 s), "warpfree" watches
# the opening carry the party off instead of sleeping, "freefield" wants 1.5 s of free field.
FREE_RX = r"scene field(?!.*title window)(?!.*; script )"
FREE_FIELD = rf"until {FREE_RX} 120"   # (kept for batch files that name it)
QUIET_MAP = (112, 1)
# a battle ended and the party back on the quiet map, settled (after a battle the New Game's opening can
# move the party on: the next "battle" right at the victory's field threw an NRE, 2026-11-20: warpfree watches)
END_BATTLE = ["killall", "until scene field 180 repeat press action", "warpfree"]
# (from anywhere: "totitle" waits for a starting game's title, or takes a game on a field or in a battle back to it;
# a request starting with "boot" after another one in the same launch used to wait 240 s for a title that never came)
BOOT = ["totitle", "newgamego", "skipmsg on", "newfield", "warpfree", "freefield"]
# a run's "boot": "save": the newest save with 3+ in its party loaded at the title instead (PrKit ModSaves.LoadAtTitle,
# runner-saveload 2026-11-20: a free field 15-25 s after the title with a Lv 46-66 party; the run's extra may point
# the save folder at a copy: "savesandbox=<dir>")
BOOT_SAVE = ["totitle", "titlesettle", "skipmsg on", "load party",
             r"until scene field; map [1-9]\d*;(?!.*title window) 60", "freefield"]
FRAME = re.compile(r"^frame \d+; ")


class GameStuck(Exception):
    """the game can't be brought back to a free field (a battle that never ends: a boss its script holds at 0 HP):
    this launch is given up and the requests left get a new one"""


def stamp_key(ts):
    """A save's TimeStamp ("03/06/2022 04:55:32", "6/11/2022 11:07:07 AM") as a sortable tuple."""
    m = re.match(r"(\d+)/(\d+)/(\d+) (\d+):(\d+):(\d+)(?: ([AP]M))?", ts)
    if not m:
        return (0,)
    mo, d, y, h, mi, s = (int(x) for x in m.groups()[:6])
    if m[7] == "PM" and h < 12:
        h += 12
    if m[7] == "AM" and h == 12:
        h = 0
    return (y, mo, d, h, mi, s)


OPENING = re.compile(r"(Wedge|Biggs)")   # the opening's party (its event scripts start on load)


def party_slot(slots):
    """The newest save with 3+ in its party, not the opening's (Terra, Biggs, Wedge: an event script
    starts as soon as it loads), from the harness's "slots" reply."""
    best = None
    for part in slots.split(" | "):
        m = re.match(r"(\d+): (\S+ \S+(?: [AP]M)?) .*\[(.*)\]$", part.strip())
        if not m:
            continue
        members = [x for x in m[3].split(", ") if x.strip()]
        if OPENING.search(m[3]):
            continue
        if len(members) >= 3 and (best is None or stamp_key(m[2]) > best[1]):
            best = (int(m[1]), stamp_key(m[2]))
    return best[0] if best else None


def to_field(h, transcript, boot=None):
    """"tofield": from wherever the run is (title, a battle, the field) to a free field."""
    boot = boot or BOOT
    r = h.ask("state")
    transcript.append(f"  ~ tofield from: {r}")
    if "title window" in r or r.startswith("error") or "scene field" not in r and "scene battle" not in r:
        return boot
    if "map 609;" in r and "script sc_e_0001" in r:
        # the title's idle demo (or the opening): back to the title (a press ends the demo), then the boot
        return ["until title window 60 repeat press action"] + boot[1:]
    if "scene battle" in r:
        # once: a battle that doesn't end here won't end for the next request either (bnw-2, 2026-11-20: every later
        # request spent 3 minutes pressing at the same boss)
        for st in ("killall", "until scene field 90 repeat press action"):
            ok, fail = run_step(h, st, transcript)
            if not ok:
                raise GameStuck(f"the battle doesn't end ({fail})")
        return ["warpfree"]
    return ["skipmsg on", "freefield"]


def to_title(h, transcript):
    """"totitle": back to the title screen (a warm game's next request starts there, as a launch's would)"""
    r = h.ask("state")
    transcript.append(f"  ~ totitle from: {r}")
    if "title window" in r:
        return True, None
    if "scene field" not in r and "scene battle" not in r:
        # still starting (or between scenes): the title comes by itself
        return run_step(h, "until title window 240", transcript)
    if "scene battle" in r:
        for st in ("killall", "until scene field 90 repeat press action"):
            ok, fail = run_step(h, st, transcript)
            if not ok:
                return False, fail
    r = h.ask("title")
    transcript.append(f"> title\n{r}")
    if r.startswith("error"):
        return False, f"'title': {r}"
    return run_step(h, "until title window 60", transcript)


TITLE_SETTLE = 12   # seconds after the title appears before New Game (the probe's proven delay; 25 s worked too)


def new_game_go(h, transcript, ctx=None):
    """New Game from the title: TITLE_SETTLE s after the title window appeared (asked in its first seconds, the
    title holds it unanswered until its attract demo ~74 s later: live, 2026-11-20, "2 tries, 75.1 s"; at 25 s:
    "1 try, 1.6 s"), before that demo (a title state of NewGame or the opening's field before we asked: a press ends
    it, then the wait again). A harness that answers at once (older ones) is asked again after 5 s."""
    t0 = time.time()
    seen, sent, last = None, 0.0, None
    while time.time() - t0 < 180:
        st = h.ask("state")
        if FRAME.sub("", st) != last:
            transcript.append(f"  ~ state: {st}")
            last = FRAME.sub("", st)
        title = "title window" in st
        if sent and not title and re.search(r"scene (other|field|battle)", st):
            transcript.append(f"  ~ new game under way ({time.time() - t0:.1f} s)")
            return True, None
        if not sent and (re.search(r"title window \(NewGame\)", st) or (not title and "map 609;" in st)):
            # the title's attract demo: a press ends it, then the title's wait again
            transcript.append(f"> press action\n{h.ask('press action')}  (the title's demo)")
            seen = None
            time.sleep(1)
            continue
        if not title:
            time.sleep(POLL)
            continue
        seen = seen or time.time()
        apply_fast(h, ctx, transcript)   # (the config exists from the title on)
        if time.time() - seen < TITLE_SETTLE or time.time() - sent < 5:
            time.sleep(POLL)
            continue
        if ctx is not None and not sent:
            ctx["stale_map"] = map_of(st)
        r = h.ask("newgame")
        sent = time.time()
        transcript.append(f"> newgame\n{r}")
        if r.startswith("error") and "didn't take" in r:
            return False, f"'newgame': {r}"
        if r.startswith("error"):
            # "no title window": the title's demo started meanwhile (QA, bc-5, 2026-11-20): end it, the wait again
            transcript.append(f"> press action\n{h.ask('press action')}  (the title's demo?)")
            sent, seen = 0.0, None
            time.sleep(1)
    return False, "the title didn't take New Game (180 s)"


MAP_RX = re.compile(r"; map (\d+);")


def map_of(state):
    m = MAP_RX.search(state)
    return int(m[1]) if m else -1


def new_field(h, transcript, ctx, timeout=240):
    """"newfield": the New Game's first field. A warm game back at the title still says the last game's map until
    the new one loads (live, 2026-11-20: "map 112" at once, a warp then, and the battle after it found no field):
    a field whose map differs from the one shown before New Game, or any field after 20 s."""
    stale = (ctx or {}).get("stale_map", 0)
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        r = h.ask("state")
        if FRAME.sub("", r) != last:
            transcript.append(f"  ~ state: {r}")
            last = FRAME.sub("", r)
        if "scene field" in r and "title window" not in r and map_of(r) > 0 and (map_of(r) != stale or time.time() - t0 >= 20):
            transcript.append(f"  ~ the new game's field (map {map_of(r)}, {time.time() - t0:.1f} s)")
            return True, None
        time.sleep(POLL)
    return False, f"no new game's field in {timeout} s (last state: {last[:300] if last else '-'})"


def watch_map(h, m, secs, transcript):
    """Stays the party on map m with no script for secs? -> (True, None) or (False, the state that says not)"""
    end = time.time() + secs
    last = None
    while time.time() < end:
        r = h.ask("state")
        if FRAME.sub("", r) != last:
            transcript.append(f"  ~ state: {r}")
            last = FRAME.sub("", r)
        if f"map {m};" not in r or "; script " in r or "scene field" not in r:
            return False, r
        time.sleep(POLL)
    return True, None


def warp_free(h, transcript, ctx=None):
    """off the opening to the quiet map; the opening's script carries the party off once, a moment after the
    first landing (2026-11-20 transcripts: within 4 s): watched 5 s, then 2 s after a pull. At speed 4 meanwhile
    (the opening's and the map's arrival scripts), speed 1 after."""
    m, p = QUIET_MAP
    sped = False
    try:
        r = h.ask("speed 4")
        sped = r.startswith("time scale")
        transcript.append(f"> speed 4\n{r}")
        pulled = False
        for attempt in range(5):
            before = map_of(h.ask("state"))
            ok, fail = run_step(h, f"warp {m} {p}", transcript)
            if ok and before == m:
                # on the quiet map already (or a stale reading): the warp must show (a load, a script) first
                run_step(h, r"until scene other|; script  10", transcript)
            if ok:
                ok, fail = run_step(h, rf"until scene field; map {m};(?!.*; script ) 40", transcript)
            if ok:
                stay, r = watch_map(h, m, 2 if pulled else 5, transcript)
                if stay:
                    return True, None
                pulled = True
                transcript.append(f"  warp try {attempt + 1}: carried off map {m}")
            else:
                transcript.append(f"  warp try {attempt + 1}: {fail}")
                time.sleep(1)
        return False, f"couldn't settle on map {m} (5 warps)"
    finally:
        if sped:
            back = f"speed {(ctx or {}).get('speed', 1):g}"   # the request's own speed (1 unless it asked for more)
            try:
                transcript.append(f"> {back}\n{h.ask(back)}")
            except (OSError, ConnectionError):
                pass


def free_field(h, transcript, timeout=120, hold=1.5):
    """a free field (no script, not the title) for `hold` seconds on end (an event script can start a moment
    after the field appears)"""
    end = time.time() + timeout
    since, last = None, None
    rx = re.compile(FREE_RX)
    while True:
        r = h.ask("state")
        if FRAME.sub("", r) != last:
            transcript.append(f"  ~ state: {r}")
            last = FRAME.sub("", r)
        if rx.search(r):
            since = since or time.time()
            if time.time() - since >= hold:
                transcript.append("  ~ free field")
                return True, None
        else:
            since = None
        if time.time() > end:
            return False, f"no free field in {timeout} s (last state: {r[:300]})"
        time.sleep(POLL)


def apply_fast(h, ctx, transcript):
    """the harness's "fast on" (Active battles, the fastest battle and battle-message speeds, no frame cap) or
    "fast off", as the request's run wants it, once the game has its config (the title or later); a harness
    without "fast" (older builds): nothing"""
    if not ctx or ctx.get("fast_done") or ctx.get("fast") is None:
        return
    cmd = "fast on" if ctx["fast"] else "fast off"
    r = h.ask(cmd)
    if r.startswith("error: no config"):
        return   # still starting: asked again once the title is up
    ctx["fast_done"] = True
    transcript.append(f"> {cmd}\n{r}")


def first_step(req):
    return next((s.strip() for s in req.get("steps", []) if s.strip()), "")


def run_steps(h, steps, transcript, keep_going=False, skip_to=None, ctx=None):
    """-> (ok, failure); keep_going: a failed step is noted and the rest still run; skip_to (a step
    prefix, e.g. "battle "): after a failed step, go on from the next step starting with it (via tofield)"""
    failures = []
    expanded = []
    boot = (ctx or {}).get("boot") or BOOT
    for st in steps:
        if st.strip() != "quit":   # the runner ends the run itself
            expanded += boot if st.strip() == "boot" else [st]
    i = 0
    while i < len(expanded):
        st = expanded[i].strip()
        i += 1
        if not st:
            continue
        if st == "tofield":
            expanded[i:i] = to_field(h, transcript, boot)
            continue
        if ctx is not None:
            ctx["steps_done"] = ctx.get("steps_done", 0) + 1
        try:
            ok, fail = run_step(h, st, transcript, ctx)
        except (OSError, ConnectionError, GameStuck):
            raise
        except Exception as e:   # a bad regex, a reply the runner can't read: this step fails, the batch goes on
            ok, fail = False, f"'{st}': runner error: {type(e).__name__}: {e}"
        if not ok:
            failures.append(fail)
            transcript.append(f"  STEP FAILED: {fail}")
            if skip_to:
                nxt = next((j for j in range(i, len(expanded)) if expanded[j].strip().startswith(skip_to)), None)
                if nxt is None:
                    break
                transcript.append(f"  skipping to step {nxt + 1}: {expanded[nxt]}")
                expanded[nxt:nxt] = ["tofield"]
                i = nxt
                continue
            if not keep_going:
                return False, fail
    return (not failures), ("; ".join(failures) if failures else None)


def fast_sleep(secs, ctx, transcript):
    """A request's "sleep N" with fast_sleep: over once the BepInEx log has a line for one of the request's pass
    regexes it hadn't matched yet (since the request began), 1.5 s later; else after the whole N."""
    t0 = time.time()
    end = t0 + secs
    # lines written before this sleep: their regexes count as matched already
    lines, ctx["log_pos"] = read_log_lines(ctx["log_pos"])
    for l in lines:
        ctx["pending"] = [rx for rx in ctx["pending"] if not rx.search(l)]
    while time.time() < end:
        lines, ctx["log_pos"] = read_log_lines(ctx["log_pos"])
        hit = next((rx for l in lines for rx in ctx["pending"] if rx.search(l)), None)
        for l in lines:
            ctx["pending"] = [rx for rx in ctx["pending"] if not rx.search(l)]
        if hit:
            transcript.append(f"  ~ sleep {secs:g}: /{hit.pattern}/ in the log after {time.time() - t0:.1f} s")
            time.sleep(max(0.0, min(1.5, end - time.time())))
            return True, None
        if not ctx["pending"]:
            break   # every pass regex matched: nothing left to wait for, the whole sleep then
        time.sleep(0.5)
    time.sleep(max(0.0, end - time.time()))
    return True, None


def run_step(h, st, transcript, ctx=None):
    """one step -> (ok, failure)"""
    if st.startswith("sleep "):
        secs = float(st.split()[1])
        if ctx and ctx.get("fast_sleep") and secs >= 4 and ctx.get("pending"):
            return fast_sleep(secs, ctx, transcript)
        time.sleep(secs)
        return True, None
    if st == "newgamego":
        return new_game_go(h, transcript, ctx)
    if st.startswith("newfield"):
        return new_field(h, transcript, ctx)
    if st == "titlesettle":
        # TITLE_SETTLE s since the title window appeared (a load or New Game asked earlier waits or stalls)
        t0, seen = time.time(), None
        while time.time() - t0 < 120:
            if "title window" in h.ask("state"):
                seen = seen or time.time()
                if time.time() - seen >= TITLE_SETTLE:
                    return True, None
            else:
                seen = None
            time.sleep(POLL)
        return False, "no title window to wait at (120 s)"
    if st == "totitle":
        return to_title(h, transcript)
    if st.startswith("freefield"):
        parts = st.split()
        return free_field(h, transcript, int(parts[1]) if len(parts) > 1 else 120)
    if st == "killall":
        # not while the battle is still being set up (live, 2026-11-20: an endfight in phase CreateObj killed the
        # monster, the setup brought it back at 1 HP "Dying", and the battle never ended)
        end = time.time() + 20
        while time.time() < end:
            r = h.ask("state")
            if "scene battle" not in r or not re.search(r"battle phase (CreateObj|Init\w*|Load\w*|None|Start\w*)\b", r):
                break
            time.sleep(POLL)
        # every enemy down: BNW's "endfight" (the game's own death check), else the kit's "enemyhp 1" (a hit is
        # still needed then: the presses that follow)
        # BNW's aikeep first (Active, auto): the game judges a battle's end after an act, and with the party
        # stopped or waiting on menus none comes (2026-11-20: endfight, then 3 minutes of presses, still Play)
        transcript.append(f"> aikeep on\n{h.ask('aikeep on')}")
        r = h.ask("endfight")
        transcript.append(f"> endfight\n{r}")
        if r.startswith("error"):
            return run_step(h, "enemyhp 1", transcript)
        return True, None
    if st == "warpfree":
        return warp_free(h, transcript, ctx)
    if st == "loadfield":
        for attempt in range(3):
            ok, fail = run_step(h, "loadparty", transcript)
            if not ok:
                return ok, fail
            # the save's field, not the title's idle demo (map 609 + the opening's script, ~74 s after the title)
            ok, fail = run_step(h, r"until scene field; map (?!609;)\d+(?!.*title window) 40", transcript)
            if ok:
                return True, None
            transcript.append(f"  load try {attempt + 1}: no field yet, loading again")
        return False, "the save didn't load (3 tries)"
    if st == "loadparty":
        sl = h.ask("slots")
        transcript.append(f"> slots\n{sl}")
        sid = party_slot(sl)
        if sid is None:
            return False, f"no save with a party of 3+ ({sl[:200]})"
        st = f"load {sid} title"
    m = UNTIL.match(st)
    if m:
        rx, timeout, rep, chk = re.compile(m["re"]), int(m["t"] or 120), m["rep"], m["chk"] or "state"
        end, last = time.time() + timeout, None
        # "check logfile": the BepInEx log's lines written since this step began (a plugin's log line)
        log_from = log_size() if chk == "logfile" else 0
        while True:
            if chk == "logfile":
                lines, _ = read_log_lines(log_from)
                new = [l for l in lines if rx.search(l)]
                r = new[0] if new else "(no matching log line yet)"
            else:
                r = h.ask(chk)
            if FRAME.sub("", r) != last:
                transcript.append(f"  ~ {chk}: {r}")   # "  ~": a poll (its replies count for pass, not fail)
                last = FRAME.sub("", r)
            if rx.search(r):
                transcript.append(f"  ~ matched: {m['re']}")
                return True, None
            if time.time() > end:
                return False, f"'{st}' timed out (last state: {r[:300]})"
            if rep:
                rr = h.ask(rep)
                if rr.startswith("error"):
                    return False, f"'{rep}': {rr}"
                if m["ev"]:
                    time.sleep(float(m["ev"]))   # "every <s>": the pace of the repeats (e.g. a press every 2 s)
            else:
                time.sleep(float(m["ev"]) if m["ev"] else POLL)
    r = h.ask(st)
    if r.startswith("error") and "NullReferenceException" in r and st.split()[0] in ("battle", "encount"):
        # the field a moment after a warp isn't ready for a battle (bnw-2, 2026-11-20: FieldController
        # .ScreenShotMainView): 2 s, a free field, then once more ("  ~": the first reply isn't a failure line)
        transcript.append(f"  ~ {st}: {r[:200]} (the field wasn't ready: again in 2 s)")
        time.sleep(2)
        free_field(h, transcript, timeout=30, hold=1.0)
        r = h.ask(st)
    transcript.append(f"> {st}\n{r}")
    if r.startswith("error"):
        return False, f"'{st}': {r}"
    return True, None


class LiveLog(list):
    """The harness transcript, also written to its file as it grows (follow a long run with tail -f)."""
    def __init__(self, path):
        super().__init__()
        self.path = path

    def append(self, line):
        super().append(line)
        stamp = time.strftime("%H:%M:%S")
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {line}\n")


# --- one launch ---------------------------------------------------------------------------------------

def launcher(run, warm=False):
    """the launch command; warm: a launch that may be kept up after the run (its own limit WARM_CAP_MIN)"""
    kind = run["kind"]
    minutes = str(max(int(run.get("minutes", 15)), WARM_CAP_MIN) if warm else run.get("minutes", 15))
    if kind == "kit":
        args = [PY, "tools/kit.py", "run", run.get("game", "ff6"), "--harness", "--minutes", minutes]
        if run.get("graphics"):
            args.append("--graphics")
        for k, v in (run.get("set") or {}).items():
            args += ["--set", f"{k}={v}"]
        return args
    args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(PR, "tools", "probe_headless.ps1"),
            "-Minutes", minutes]
    if run.get("graphics"):
        args.append("-Graphics")
    if kind == "probe":
        extra = run.get("extra") or ""
        if extra:
            args += ["-Extra", extra]
        if run.get("until"):
            args += ["-Until", run["until"]]
    elif kind == "harness":
        extra = "harness=1" + (";" + run["extra"] if run.get("extra") else "")
        args += ["-Extra", extra, "-Until", r"\[probe\] done"]
    elif kind == "wctest":
        args += ["-WcTest", run["wctest"]]
        if run.get("until"):
            args += ["-Until", run["until"]]
    elif kind == "live":
        args += ["-Live", run["live"]]
    return args


def regex_error(rx):
    try:
        re.compile(rx)
        return None
    except (re.error, TypeError) as e:
        return str(e)


def request_errors(req, run=None):
    """what's wrong with a request before anything runs: an "until" step, a pass or a fail regex that doesn't compile
    (bnw-11, 18:31: a ";" split cut "until scene field(?!.*; script ) 60" in two, and the batch died 24 min in)"""
    errs = []
    for st in req.get("steps", []):
        st = st.strip() if isinstance(st, str) else ""
        if st.startswith("until "):
            m = UNTIL.match(st)
            if not m:
                errs.append(f"step {st[:80]!r}: not an until step")
            elif regex_error(m["re"]):
                errs.append(f"step {st[:80]!r}: {regex_error(m['re'])}")
    for rx in req.get("pass", []):
        if regex_error(rx):
            errs.append(f"pass /{rx[:80]}/: {regex_error(rx)}")
    if req.get("fail") and regex_error(req["fail"]):
        errs.append(f"fail /{req['fail'][:80]}/: {regex_error(req['fail'])}")
    if "speed" in req:
        try:
            sp = float(req["speed"])
        except (TypeError, ValueError):
            sp = None
        if sp is None or not 1 <= sp <= 10:
            errs.append(f"speed {req['speed']!r}: a number from 1 to 10")
        elif sp != 1 and req.get("timing"):
            errs.append('speed: not on a timing check ("timing": true)')
        elif sp != 1 and any(isinstance(x, str) and x.strip().split(" ", 1)[0] in ("battle", "encount") for x in req.get("steps", [])):
            errs.append("speed: not on a request with a battle (at 3x BNW's boss 446 ended at once, no act, nothing "
                        "defeated: 2026-11-20)")
        elif sp != 1 and run is not None and run.get("kind") not in WARM_KINDS:
            errs.append(f"speed: only on harness/kit runs (this one is {run.get('kind')}: WcTest timing, the formula probe)")
    return errs


def check_batch(batch):
    """-> (the batch without its broken requests (runs left empty dropped), [(run, request id, from, [errors])])"""
    bad = []
    for run in batch.get("runs", []):
        keep = []
        for req in run.get("requests", []):
            errs = request_errors(req, run)
            if errs:
                bad.append((run["name"], req.get("id"), req.get("from"), errs))
            else:
                keep.append(req)
        run["requests"] = keep
    batch["runs"] = [r for r in batch.get("runs", []) if r.get("requests")]
    return batch, bad


def evaluate(req, text, step_fail):
    res = {"id": req.get("id"), "from": req.get("from"), "pass": [], "fail": [], "ok": True}
    if step_fail:
        res["ok"] = False
        res["step_failure"] = step_fail
    lines = text.splitlines()
    for rx in req.get("pass", []):
        if regex_error(rx):
            res["ok"] = False
            res["pass"].append({"re": rx, "hits": [f"bad regex: {regex_error(rx)}"], "count": 0})
            continue
        r = re.compile(rx)
        hits = [l for l in lines if r.search(l)]
        res["pass"].append({"re": rx, "hits": hits[:4], "count": len(hits)})
        if not hits:
            res["ok"] = False
    frx = re.compile(req.get("fail") or DEFAULT_FAIL) if not regex_error(req.get("fail") or DEFAULT_FAIL) else re.compile(DEFAULT_FAIL)
    for i, l in enumerate(lines):
        if l.startswith("  ~ "):   # an "until" poll: early replies ("not loaded yet") are expected
            continue
        if frx.search(l) and not NOISE.search(l):
            # the line plus its stack head
            head = [l] + [x for x in lines[i + 1:i + 4] if x.startswith((" ", "\t", "  at ", "at "))]
            res["fail"].append(" | ".join(x.strip() for x in head)[:600])
    if res["fail"]:
        res["ok"] = False
    return res


def launch(run, stamp, opts=None):
    reuse = None
    w = warm_load()
    if w:
        why = warm_mismatch(w, run) if warm_allowed(run, opts) else f"a {run['kind']} run can't use it"
        if why is None:
            reuse = w
        else:
            cool(why, w)
    why = wait_free(warm=reuse)
    if why:
        return {"run": run["name"], "skipped": why}
    if reuse and not warm_load():
        reuse = None   # (stopped meanwhile: Wow.exe)
    if reuse:
        OUR_GAMES.add(reuse["pid"])   # this batch uses it now: a crash stops it too
    if not reuse:
        for name in ("probe_run.lock", "prkit_run.lock"):
            lock = os.path.join(BEP, name)
            if os.path.exists(lock):
                try:
                    with open(lock, encoding="ascii", errors="replace") as f:
                        other = int((f.read().strip() or "0").split()[0])
                except (OSError, ValueError):
                    other = 0
                if other and pid_alive(other):
                    return {"run": run["name"], "skipped": f"BepInEx/{name} is held by pid {other} (another run?)"}
    before = save_digest()
    # "setup" / "undo": commands (argv lists, run in pr/) before the launch and after it, e.g. a test-only
    # Magicite folder copied in and removed again
    for cmd in run.get("setup", []):
        rc, o = run_cmd(cmd)
        if rc != 0:
            for u in run.get("undo", []):
                run_cmd(u)
            return {"run": run["name"], "skipped": f"setup failed ({' '.join(cmd)}): {o.strip()[-300:]}"}
    try:
        if not reuse:
            conflicts = magicite_conflicts()
            if conflicts:
                return {"run": run["name"], "skipped": "pre-flight: two installed Magicite folders ship the same files (the game "
                        f"reads one): {'; '.join(conflicts[:3])}" + (f" (+{len(conflicts) - 3})" if len(conflicts) > 3 else "")}
        return launch_inner(run, stamp, before, reuse, opts)
    finally:
        for cmd in run.get("undo", []):
            rc, o = run_cmd(cmd)
            if rc != 0:
                say(f"[batch] UNDO FAILED ({' '.join(cmd)}): {o.strip()[-300:]}")


OUR_GAMES, OUR_LAUNCHERS = set(), []   # this process's launches: a crash stops these, never another game


def stop_ours(why):
    """A crash (bnw-11, 18:31: one bad step ended the batch and its game ran on under a 120-min launcher until a person
    killed it): this batch's games, then their launchers (each gets 5 s to clean up after its game: steam_appid.txt,
    the probe's lock), and the warm game's record."""
    w = warm_load()
    pids = set(OUR_GAMES) | ({w["pid"]} if w and w.get("pid") in OUR_GAMES else set())
    alive = [pid for pid in pids if pid in game_pids()]
    for pid in alive:
        kill_pid(pid)
    if alive:
        say(f"[batch] {why}: stopped this batch's game(s) {sorted(alive)}")
    end = time.time() + 5
    for proc in OUR_LAUNCHERS:
        while proc.poll() is None and time.time() < end:
            time.sleep(0.25)
        if proc.poll() is None:
            proc.kill()
    if w and w.get("pid") in pids:
        warm_clear()


def start_launcher(args, out_path, detach):
    """the launcher, its output appended to out_path; detach (a game that may stay warm): out of this process's
    job and console group where Windows allows, so it outlives this batch and the queue's shell"""
    # (CREATE_NO_WINDOW: a console of its own, never shown: the queue's console closing doesn't end it)
    detached = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    with open(out_path, "a", encoding="utf-8") as out:
        for flags in ((CREATE_BREAKAWAY_FROM_JOB | detached, detached, 0) if detach else (0,)):
            try:
                proc = subprocess.Popen(args, cwd=PR, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                        creationflags=flags)
                OUR_LAUNCHERS.append(proc)
                return proc
            except OSError:
                if flags == 0:
                    raise


def harness_requests(run, t, transcript, out_path, reuse, opts):
    """the requests of a harness/kit run on one game: the warm one, or a launch (another one when the game dies
    with requests left, twice at most). -> (step results, transcript segments, log text, notes)"""
    reqs = run.get("requests", [])
    # "fast": true on a run: the harness's quick game settings (opt-in: measured on BNW's boss 446, its turns in 30 s
    # stayed 4 -> 4 and the fight went differently: the party fell). Otherwise "fast off" (a warm game may have it on)
    run_fast = bool(run.get("fast", False)) and not any(r.get("timing") for r in reqs)
    step_results, segments, log_parts, notes = {}, {}, [], []
    req_logs, in_launch = {}, []   # each request's launch's log (a crash's lines stay with the requests it hit)
    allow_warm = warm_allowed(run, opts)

    def close_part(log_from):
        text = read_log(log_from)
        log_parts.append(text)
        for rid in in_launch:
            req_logs[rid] = text
        in_launch.clear()

    w, proc = reuse, None
    i, relaunches, prev_pid = 0, 0, None
    while True:
        cold = w is None
        if cold:
            if proc is not None or relaunches:
                # a launch of this run died (or a warm game was given up): its game gone first, then a new one
                if proc is not None:
                    try:
                        proc.wait(timeout=60)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                if prev_pid and prev_pid in game_pids():
                    kill_pid(prev_pid)
                why = wait_free(game_wait=60)
                if why:
                    for r in reqs[i:]:
                        step_results[r.get("id")] = f"no new launch: {why}"
                    break
            capable = allow_warm and harness_has_idle(run["kind"])
            proc = start_launcher(launcher(run, warm=capable), out_path, capable)
            launched = time.time()
            minutes = max(int(run.get("minutes", 15)), WARM_CAP_MIN) if capable else int(run.get("minutes", 15))
            w = {"kind": run["kind"], "game": run.get("game", "ff6"), "graphics": bool(run.get("graphics")),
                 "extra": run.get("extra") or "", "set": run.get("set") or {}, "mod": installed_mod(),
                 "launcher_pid": proc.pid, "started": launched, "deadline": launched + minutes * 60 - 120, "runs": 0, "pid": None}
            log_from = 0   # the launcher set the old log aside
        else:
            log_from = log_size()
        launcher_proc = proc if cold else None
        try:
            h = Harness(connect_timeout=run.get("connect", 150) if cold else 15,
                        alive=(lambda: launcher_proc.poll() is None) if launcher_proc else None)
        except OSError as e:
            transcript.append(f"harness: no connection ({e})")
            if not cold and relaunches < 2:
                cool(f"no connection ({e})", w)
                w, relaunches = None, relaunches + 1
                continue
            for r in reqs[i:]:
                step_results[r.get("id")] = f"no harness connection ({e})"
            close_part(log_from)
            break
        if cold:
            pids = game_pids()
            w["pid"] = pids[0] if len(pids) == 1 else None
            if w["pid"]:
                OUR_GAMES.add(w["pid"])
        prev_pid = w.get("pid")
        w["runs"] += 1
        transcript.append(f"[{int(time.time() - t)} s] harness connected" +
                          ("" if cold else f" (the warm game, pid {w['pid']}, launched {time.strftime('%H:%M', time.localtime(w['started']))}, run {w['runs']})"))
        notes.append("warm game reused" if not cold else ("launched" if not relaunches else "relaunched"))
        idle_ok = False
        try:
            if allow_warm:
                r = h.ask(f"idle {WARM_IDLE_MIN}")
                transcript.append(f"> idle {WARM_IDLE_MIN}\n{r}")
                idle_ok = not r.startswith("error")
            # a reused game: back to the title first (as a launch starts), unless the run goes on from where it is
            if not cold and i < len(reqs) and first_step(reqs[i]) != "tofield" and reqs[i].get("needs") != "title":
                ok, fail = to_title(h, transcript)
                if not ok:
                    transcript.append(f"  the warm game: {fail}: a new launch instead")
                    h.close()
                    cool(f"no way back to the title ({fail})", w)
                    w, relaunches = None, relaunches + 1
                    continue
        except (OSError, ConnectionError) as e:
            transcript.append(f"harness: {e}")
            h.close()
            if relaunches < 2:
                cool(f"connection: {e}", w)
                w, relaunches = None, relaunches + 1
                continue
            for r in reqs[i:]:
                step_results[r.get("id")] = f"connection: {e}"
            break
        crashed = False
        while i < len(reqs):
            req = reqs[i]
            i += 1
            rt = time.time()
            seg_start = len(transcript)
            transcript.append(f"--- {req.get('id')}")
            in_launch.append(req.get("id"))
            ctx = {"fast_sleep": bool(req.get("fast_sleep")), "log_pos": log_size(), "speed": float(req.get("speed", 1) or 1),
                   "fast": run_fast,
                   "pending": [re.compile(x) for x in req.get("pass", []) if regex_error(x) is None],
                   "boot": BOOT_SAVE if run.get("boot") == "save" else BOOT}
            steps = req.get("steps", [])
            if req.get("needs") == "title":
                # "needs": "title": its steps at the title screen (no New Game, load or warp)
                steps = ["totitle"] + [x for x in steps if x.strip() not in ("boot", "tofield")]
            try:
                apply_fast(h, ctx, transcript)
                if ctx["speed"] != 1:
                    sp = f"speed {ctx['speed']:g}"
                    transcript.append(f"> {sp}\n{h.ask(sp)}")
                ok, fail = run_steps(h, steps, transcript, req.get("keep_going", False), req.get("skip_to"), ctx)
                if ctx["speed"] != 1:
                    transcript.append(f"> speed 1\n{h.ask('speed 1')}")
            except (OSError, ConnectionError) as e:
                ok, fail = False, f"connection: {e}"
            except Exception as e:
                if not isinstance(e, GameStuck):
                    ok, fail = False, f"runner error: {type(e).__name__}: {e}"
                    transcript.append(f"  {fail}")
                    step_results[req.get("id")] = fail
                    transcript.append(f"--- {req.get('id')}: FAILED: {fail} ({int(time.time() - rt)} s)")
                    segments[req.get("id")] = "\n".join(transcript[seg_start:])
                    continue
                ok, fail = False, f"connection: the game was given up: {e}"
                transcript.append(f"  {e}: this game is given up")
                h.close()
                if w.get("pid") and w["pid"] in game_pids():
                    kill_pid(w["pid"])
                if not ctx.get("steps_done") and relaunches < 2:
                    # none of the request's steps ran (bnw-11: a game reused in a battle that never ends, its first
                    # tofield gave it up): the request again, on a new launch, instead of failing it
                    transcript.append(f"  nothing of {req.get('id')} ran: it runs again on a new launch")
                    i -= 1
            step_results[req.get("id")] = fail
            transcript.append(f"--- {req.get('id')}: {'steps ok' if ok else 'FAILED: ' + fail} ({int(time.time() - rt)} s)")
            segments[req.get("id")] = "\n".join(transcript[seg_start:])
            if fail and fail.startswith("connection"):
                crashed = True
                break
        if crashed:
            h.close()
            if i < len(reqs) and relaunches < 2:
                transcript.append("  the game closed the connection: a new launch for the requests left")
                close_part(log_from)
                warm_clear()
                w, relaunches = None, relaunches + 1
                continue
            if cold:
                try:
                    proc.wait(timeout=120)
                except subprocess.TimeoutExpired:
                    proc.kill()
            warm_clear()
            close_part(log_from)
            break
        # every request done: keep the game warm for the next run, or quit it. Not a game left in a battle or with a
        # script running (bnw-11: dream's game ended in a battle that never ends; the next run reused it, lost 90 s)
        keep = bool(allow_warm and idle_ok and w.get("pid"))
        if keep:
            try:
                end_state = h.ask("state")
            except (OSError, ConnectionError):
                end_state = "scene battle (no answer)"
            if "scene battle" in end_state or "; script " in end_state:
                why_not = "in a battle" if "scene battle" in end_state else "with a script running"
                transcript.append(f"  ~ not kept warm: the run ended {why_not} ({end_state[:200]})")
                notes.append(f"not kept: ended {why_not}")
                keep = False
        if keep:
            try:
                h.ask("speed 1")
            except (OSError, ConnectionError):
                pass
            h.close()
            close_part(log_from)
            w["fp"] = plugins_fp()
            warm_save(w)
            transcript.append(f"> (kept warm: pid {w['pid']}; it quits by itself after {WARM_IDLE_MIN} idle minutes)")
            notes.append("kept warm")
            break
        try:
            transcript.append(f"> quit\n{h.ask('quit')}")
        except (OSError, ConnectionError):
            pass
        h.close()
        warm_clear()
        if cold:
            try:
                proc.wait(timeout=int(run.get("minutes", 15)) * 60 + 120)
            except subprocess.TimeoutExpired:
                proc.kill()
        else:
            cool("not kept for the next run", w)
        close_part(log_from)
        break
    return step_results, segments, "\n".join(log_parts), notes, req_logs


def launch_inner(run, stamp, before, reuse, opts=None):
    t = time.time()
    out_path = os.path.join(LOGS, f"{stamp}_{run['name']}.launcher.txt")
    open(out_path, "w").close()
    segments, step_results, notes, req_logs = {}, {}, [], {}
    transcript = LiveLog(os.path.join(LOGS, f"{stamp}_{run['name']}.harness.txt"))
    if run["kind"] in WARM_KINDS:
        step_results, segments, log, notes, req_logs = harness_requests(run, t, transcript, out_path, reuse, opts)
    else:
        proc = start_launcher(launcher(run), out_path, False)
        try:
            proc.wait(timeout=int(run.get("minutes", 15)) * 60 + 120)
        except subprocess.TimeoutExpired:
            proc.kill()
        log = read_log(0)
    secs = int(time.time() - t)
    log_copy = os.path.join(LOGS, f"{stamp}_{run['name']}.log")
    with open(log_copy, "w", encoding="utf-8", newline="") as f:
        f.write(log)
    with open(out_path, encoding="utf-8", errors="replace") as f:
        launcher_out = f.read()
    trans = "\n".join(transcript)
    after = save_digest()
    saves = "unchanged" if before == after else "CHANGED: " + ", ".join(
        sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k)))
    # each request: its launch's log (the run's), the launcher output, and its own part of the harness transcript
    results = [evaluate(r, req_logs.get(r.get("id"), log) + "\n" + segments.get(r.get("id"), trans if not segments else "") + "\n" +
                        launcher_out, step_results.get(r.get("id"))) for r in run.get("requests", [])]
    first = launcher_out.strip().splitlines()[:1] or ([f"warm game (pid {(warm_load() or {}).get('pid')})"] if "kept warm" in notes else [])
    return {"run": run["name"], "kind": run["kind"], "seconds": secs, "saves": saves, "log": log_copy,
            "launcher": first, "notes": notes, "results": results}


def md_summary(batch, stamp, mod, build_info, install_info, runs, install_note="", preflight_info=None):
    t = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    failed_pf = preflight_info is not None and not preflight_info[0]
    lines = [f"## {t} {batch['name']}{batch.get('part_note', '')} ({mod}, DLL {dll_md5(mod) if mod in PLUGINS else '-'}, "
             f"data {data_hash(mod)})"
             + (" failed (pre-flight)" if failed_pf else ""), ""]
    if build_info:
        lines.append(f"- build: {'ok' if build_info[0] else 'FAILED'} ({build_info[2]:.0f} s)" +
                     ("" if build_info[0] else ": " + "; ".join(build_info[1][:5])))
    for x in batch.get("invalid", []):
        lines.append(f"- not run: {x['id']} ({x.get('from')}) in {x['run']}: " + "; ".join(x["errors"])[:400])
    if preflight_info is not None:
        ok, pf_lines, secs = preflight_info
        lines.append(f"- pre-flight: {'ok' if ok else 'FAILED: nothing installed or launched'} ({secs:.0f} s)" +
                     ("" if ok else ": " + " || ".join(x[:400] for x in pf_lines[:4])))
    if install_info is not None:
        lines.append(f"- install: {'ok' if install_info else 'FAILED'}{install_note}")
    for r in runs:
        if "skipped" in r:
            lines.append(f"- run {r['run']}: skipped ({r['skipped']})")
            continue
        notes = f", {'; '.join(r['notes'])}" if r.get("notes") else ""
        lines.append(f"- run {r['run']} ({r['kind']}, {r['seconds']} s{notes}, saves {r['saves']}, log {os.path.relpath(r['log'], PR)})")
        for x in r["results"]:
            why = ""
            if not x["ok"]:
                miss = [p["re"] for p in x["pass"] if not p["count"]]
                why = (f" step: {x.get('step_failure')};" if x.get("step_failure") else "") + \
                      (f" missing: {miss};" if miss else "") + (f" fail lines: {len(x['fail'])}" if x["fail"] else "")
            lines.append(f"  - {x['id']} ({x.get('from')}): {'PASS' if x['ok'] else 'FAIL'}{why}")
    lines.append("")
    old = ""
    if os.path.exists(RUNS_MD):
        with open(RUNS_MD, encoding="utf-8") as f:
            old = f.read()
    head = "# PC test runs (tools/test_batch.py; newest first)\n\n"
    if old.startswith(head):
        old = old[len(head):]
    with open(RUNS_MD, "w", encoding="utf-8") as f:
        f.write(head + "\n".join(lines) + "\n" + old)


def print_results(runs):
    for r in runs:
        if "skipped" in r:
            say(f"== {r['run']}: SKIPPED: {r['skipped']}")
            continue
        notes = f" [{'; '.join(r['notes'])}]" if r.get("notes") else ""
        say(f"== {r['run']} ({r['kind']}): {r['seconds']} s, saves {r['saves']}; {r['launcher']}{notes}")
        say(f"   log: {r['log']}")
        for x in r["results"]:
            say(f"  [{'PASS' if x['ok'] else 'FAIL'}] {x['id']} ({x.get('from')})")
            if x.get("step_failure"):
                say(f"     step: {x['step_failure']}")
            for p in x["pass"]:
                say(f"     {'+' if p['count'] else '-'} /{p['re']}/ x{p['count']}" + (f": {p['hits'][0][:300]}" if p["hits"] else ""))
            for fl in x["fail"][:6]:
                say(f"     ! {fl[:400]}")
            if len(x["fail"]) > 6:
                say(f"     ! ... {len(x['fail']) - 6} more")


# --- the pre-flight gate: offline checks before an install or a launch ---------------------------------------
# (the user, through the cross-mod coordinator, 2026-11-20: "a broken request bounces back in seconds instead of
# costing a game launch"; that day 36 of 43 requests failed, some catchable without the game)
# Per mod: its offline suites (game-free, seconds each, three at a time), skipped while nothing they read changed
# since their last run; a suite blocks only with a failure that isn't in its baseline (build/test_logs/
# preflight_state.json: the failures it had when first run here, shrunk as they get fixed), so a suite that already
# fails today doesn't hold every batch. Then tools/magicite_check.py on the Magicite folders about to be installed
# or copied in by a run's setup. A request's "offline": [commands] (bash, in pr/) replaces its mod's suites; every
# command must pass ([] runs none).
PREFLIGHT_STATE = os.path.join(LOGS, "preflight_state.json")
SUITES = {
    "bnw": ["dotnet Rules.Tests", "py BraveNewWorld test_mod"],
    "wc": ["dotnet Wc.Tests", "dotnet WcAi.Tests"],
    "bc": ["dotnet Bc.Tests", "py - test_bc"],
    "ted": ["dotnet Ted.Tests", "py TEdition test_mod", "py - test_snes_events"],
}
PRKIT_SUITE = "dotnet PrKit.Tests"      # also, when the kit's sources changed since its last run
MAGICITE_SRC = {"bnw": ["mods/BraveNewWorld"], "bc": ["mods/BeyondChaos"], "wc": [], "ted": []}
BUILD_DIRS = ("__pycache__", "bin", "obj", ".git")


def mod_key(batch, name=""):
    """bnw / wc / bc / ted / none: whose suites, whose queue turn"""
    m = batch.get("mod", "none") if batch else "none"
    if m in PLUGINS:
        return m
    n = (batch or {}).get("name") or name or ""
    return "ted" if n.startswith("ted") or (batch or {}).get("preflight") == "ted" else "none"


def suite_inputs(suite):
    """what a suite reads (its fingerprint decides whether it runs again)"""
    kind, rest = suite.split(" ", 1)
    if kind == "dotnet":
        return [os.path.join(PR, "plugin"), os.path.join(PR, "mods", "BraveNewWorld", "bnw_data.json")]
    mod, _ = rest.split(" ", 1)
    roots = [os.path.join(PR, "tests"), os.path.join(PR, "tools"), os.path.join(PR, "data")]
    if mod != "-":
        roots.append(os.path.join(PR, "mods", mod))
    return roots


def inputs_fp(paths):
    h = hashlib.sha1()
    for p in paths:
        if os.path.isfile(p):
            st = os.stat(p)
            h.update(f"{p}|{st.st_size}|{st.st_mtime_ns}\n".encode("utf-8"))
            continue
        for k, (s, m) in sorted(tree_stat(p, BUILD_DIRS).items()):
            h.update(f"{k}|{s}|{m}\n".encode("utf-8"))
    return h.hexdigest()


FAIL_LINE = re.compile(r"^(?:FAIL|ERROR): (\S+) \(([\w.]+)\)(.*)$")
DOTNET_FAIL = re.compile(r"^FAIL\s+(.+?)(?::\s|$)")
CS_ERROR = re.compile(r"error CS\d+: .*")


def run_suite(suite):
    """-> (failures (a set of names), output tail, seconds)"""
    kind, rest = suite.split(" ", 1)
    t = time.time()
    if kind == "dotnet":
        rc, out = run_cmd(["dotnet", "run", "-c", "Debug"], cwd=os.path.join(PR, "plugin", rest), timeout=600)
        fails = {m[1].strip() for m in (DOTNET_FAIL.match(l) for l in out.splitlines()) if m}
        errs = sorted({m.group(0)[:200] for m in (CS_ERROR.search(l) for l in out.splitlines()) if m})
        fails |= {f"build: {e}" for e in errs[:3]}
    else:
        mod, test = rest.split(" ", 1)
        env = {"PYTHONIOENCODING": "utf-8"}
        if mod != "-":
            env["PR_MOD"] = mod
        rc, out = run_cmd([PY, "-m", "unittest", f"tests.{test}"], timeout=600, env=env)
        # (a subtest keeps its label: a new failing case of an already failing test counts as new)
        fails = {f"{m[2].split('.')[-2] if m[2].count('.') > 1 else m[2]}.{m[1]}{m[3].strip()[:120] and ' ' + m[3].strip()[:120]}"
                 for m in (FAIL_LINE.match(l) for l in out.splitlines()) if m}
    if rc != 0 and not fails:
        fails = {f"exit {rc}"}
    return fails, "\n".join(out.strip().splitlines()[-6:]), time.time() - t


def load_preflight_state():
    try:
        with open(PREFLIGHT_STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"suites": {}, "baseline": {}, "stats": {"blocked": 0, "minutes": 0.0}}


def save_preflight_state(st):
    tmp = PREFLIGHT_STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1)
    replace_retry(tmp, PREFLIGHT_STATE)


def setup_magicite_sources(batch):
    """folders a run's setup copies into the game's Magicite folder (cp -r SRC ".../Magicite/...")"""
    out = []
    for run in batch.get("runs", []):
        for cmd in run.get("setup", []):
            text = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            for m in re.finditer(r'cp -r "?([^"\s]+)"?\s+("[^"]*Magicite[^"]*"|\S*Magicite\S*)', text):
                out.append(m[1])
    return out


def preflight(batch, quiet=False):
    """-> (ok, lines for the summary and the requester, seconds)"""
    from concurrent.futures import ThreadPoolExecutor
    t = time.time()
    key = mod_key(batch)
    st = load_preflight_state()
    lines, blocking = [], []
    custom = [c for run in batch.get("runs", []) for r in run.get("requests", []) if "offline" in r for c in (r["offline"] or [])]
    has_custom = any("offline" in r for run in batch.get("runs", []) for r in run.get("requests", []))
    if has_custom:
        for c in dict.fromkeys(custom):
            rc, out = run_cmd([BASH, "-c", c], timeout=600, env={"PYTHONIOENCODING": "utf-8"})
            tail = " | ".join(out.strip().splitlines()[-4:])[:500]
            lines.append(f"offline `{c}`: {'ok' if rc == 0 else f'FAILED (rc {rc})'}" + ("" if rc == 0 else f": {tail}"))
            if rc != 0:
                blocking.append(lines[-1])
    else:
        suites = list(SUITES.get(key, []))
        kit_fp = inputs_fp([os.path.join(PR, "plugin", "PrKit")])
        if st.get("prkit_fp") != kit_fp and PRKIT_SUITE not in suites:
            suites.append(PRKIT_SUITE)
        todo = []
        for s in suites:
            fp = inputs_fp(suite_inputs(s))
            prev = st["suites"].get(s)
            if prev and prev.get("fp") == fp:
                lines.append(f"{s}: unchanged since {prev.get('when')} ({len(prev.get('fails', []))} known failures)")
                continue
            todo.append((s, fp))
        with ThreadPoolExecutor(max_workers=3) as ex:
            results = list(ex.map(lambda sf: (sf, run_suite(sf[0])), todo))
        for (s, fp), (fails, tail, secs) in results:
            base = st["baseline"].get(s)
            if base is None:
                base = sorted(fails)   # first run here: today's failures are the baseline
                st["baseline"][s] = base
            new = sorted(set(fails) - set(base))
            st["baseline"][s] = sorted(set(base) & set(fails)) if not new else base   # fixed ones leave it
            line = f"{s}: {len(fails)} failures ({len(new)} new) in {secs:.0f} s"
            if new:
                line += ": " + "; ".join(new[:5]) + f" | {tail[-400:]}"
                blocking.append(line)
            else:
                st["suites"][s] = {"fp": fp, "fails": sorted(fails), "when": time.strftime("%H:%M")}
            lines.append(line)
            if s == PRKIT_SUITE and not new:
                st["prkit_fp"] = kit_fp
    # the Magicite folders about to be installed or copied in
    folders = [os.path.join(PR, f) for f in MAGICITE_SRC.get(key, []) + setup_magicite_sources(batch)]
    folders = [f for f in dict.fromkeys(folders) if os.path.isdir(f)]
    if folders:
        import magicite_check
        c = magicite_check.check(folders)
        line = f"magicite check ({', '.join(os.path.relpath(f, PR) for f in folders)}): " + \
               ("ok" if not c.errors else f"{len(c.errors)} errors: " + "; ".join(c.errors[:4]))
        lines.append(line)
        if c.errors:
            blocking.append(line)
    save_preflight_state(st)
    secs = time.time() - t
    if not quiet:
        for l in lines:
            say(f"[pre-flight] {l}")
    return not blocking, lines if not blocking else blocking, secs


def preflight_blocked(batch, secs_saved):
    st = load_preflight_state()
    s = st.setdefault("stats", {"blocked": 0, "minutes": 0.0})
    s["blocked"] = s.get("blocked", 0) + 1
    s["minutes"] = round(s.get("minutes", 0.0) + secs_saved / 60, 1)
    save_preflight_state(st)
    return s


def magicite_conflicts():
    """asset files two installed Magicite folders both ship (the game reads one): checked before each launch"""
    try:
        folders = [os.path.join(MAGICITE_DIR, d) for d in sorted(os.listdir(MAGICITE_DIR))
                   if os.path.isdir(os.path.join(MAGICITE_DIR, d))]
    except OSError:
        return []
    if len(folders) < 2:
        return []
    import magicite_check
    c = magicite_check.Checker(None)
    c.check_across(folders)
    return c.errors


# --- the queue's turns: one mod at a time ------------------------------------------------------------------
# (the user, through the cross-mod coordinator: 26 batches had 19 mod changes, ~4.5 min each for WC) A mod's turn runs
# every batch of that mod queued, with no time limit (the user: "undo the 30 minute cap per mod"): its install once,
# its warm game for all of them; a batch of that mod queued during its turn joins it. Then the next mod in this order
# that has batches queued.
TURN_FILE = os.path.join(PR, "build", "batches", "turn.json")
MOD_ORDER = ["bnw", "wc", "bc", "ted", "none"]


def turn_load():
    try:
        with open(TURN_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def turn_save(t):
    tmp = TURN_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(t, f, indent=1)
    replace_retry(tmp, TURN_FILE)


def turn_add(key, seconds):
    """a batch of the turn's mod ended: its time counts toward the turn's cap"""
    t = turn_load()
    if t.get("mod") == key:
        t["spent"] = round(t.get("spent", 0) + seconds)
        turn_save(t)


# --- parts, estimates and the queue ---------------------------------------------------------------------

def parse_part(spec):
    """"A-B" / "A-" / "A" (1-based, inclusive) -> (A, B or None)"""
    m = re.fullmatch(r"(\d+)(?:-(\d*))?", spec.strip())
    if not m:
        raise ValueError(f"--part {spec!r}: A-B, A- or A")
    a = int(m[1])
    b = (int(m[2]) if m[2] else None) if m[2] is not None else a
    return a, b


def apply_part(batch, spec):
    """only requests A..B of the batch (counted across its runs, 1-based); runs left without requests dropped"""
    if not spec:
        return batch
    a, b = parse_part(spec)
    batch = json.loads(json.dumps(batch))
    n = 0
    for run in batch["runs"]:
        keep = []
        for req in run.get("requests", []):
            n += 1
            if n >= a and (b is None or n <= b):
                keep.append(req)
        run["requests"] = keep
    batch["runs"] = [r for r in batch["runs"] if r["requests"]]
    batch["part_note"] = f" (part {spec}: requests {a}-{b if b is not None else n} of {n})"
    return batch


def est_steps(steps):
    s = 0.0
    for st in steps:
        st = st.strip()
        w = st.split()[0] if st else ""
        if w == "boot":
            s += 35
        elif w in ("tofield", "totitle"):
            s += 15
        elif w == "sleep":
            try:
                s += float(st.split()[1])
            except (IndexError, ValueError):
                s += 5
        elif w == "until":
            m = UNTIL.match(st)
            s += min(int(m["t"] or 120), 20) if m else 10
        elif w in ("killall", "endfight", "warpfree", "loadfield", "freefield"):
            s += 8
        elif w in ("battle", "encount", "warp", "script", "title", "newgame", "shot"):
            s += 2
        else:
            s += 0.3
    return s


def est_run_fixed(run):
    k = run["kind"]
    extra = run.get("extra") or ""
    if k == "probe":
        if "sweep=0" in extra:
            m = re.search(r"selftestmax=(\d+)", extra)
            return 70 + (int(m[1]) if m else 30)
        return 300
    if k == "wctest":
        return 150
    if k == "live":
        return 120
    return 45   # a launch (a warm game: less)


def estimate(batch, installed="?"):
    total = 10.0   # the pre-flight build
    mod = batch.get("mod", "none")
    if mod in PLUGINS and (installed_mod() if installed == "?" else installed) != mod:
        total += {"bnw": 30, "wc": 60, "bc": 90}[mod]
    for run in batch["runs"]:
        total += est_run_fixed(run)
        if run["kind"] in WARM_KINDS:
            total += sum(est_steps(r.get("steps", [])) for r in run.get("requests", []))
    return total


def load_batch(name):
    """build/batches/<name>.json, made again from its .py first when that's newer (None if neither)"""
    d = os.path.join(PR, "build", "batches")
    js, py = os.path.join(d, name + ".json"), os.path.join(d, name + ".py")
    if os.path.exists(py) and (not os.path.exists(js) or os.path.getmtime(py) > os.path.getmtime(js)):
        run_cmd([PY, py], timeout=120)
    try:
        with open(js, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


MAX_SKIPS = 3          # a queue line passed over this often (within its mod's turn) goes next


def queue_entries(lines):
    out = []
    for idx, raw in enumerate(lines):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        body, _, mark = line.partition("#")
        sk = re.search(r"skips=(\d+)", mark)
        words = body.split()
        if not words:
            continue
        part = None
        if "--part" in words[1:]:
            k = words.index("--part")
            part = words[k + 1] if k + 1 < len(words) else None
        out.append({"idx": idx, "raw": raw, "line": " ".join(words), "name": words[0], "args": words[1:],
                    "part": part, "skips": int(sk[1]) if sk else 0})
    return out


def strip_part(words):
    out, skip = [], False
    for w in words:
        if skip:
            skip = False
        elif w == "--part":
            skip = True
        else:
            out.append(w)
    return out


def queue_pick(entries, installed=None, batches=None, turn=None, now=None):
    """-> (the entry taken, the line to run now, None (nothing put back: kept for --part lines a person writes),
    the entries passed over, the turn). The turn's mod while it has batches queued; else the next mod in MOD_ORDER
    with batches queued. Within the mod: a line passed over MAX_SKIPS times first, else the shortest (ties: queue
    order). A line may name a part of a batch itself ("bnw-2 --part 3-"): it runs as written."""
    now = time.time() if now is None else now
    for e in entries:
        b = batches.get(e["name"]) if batches is not None else load_batch(e["name"])
        if b is not None and e["part"]:
            try:
                b = apply_part(b, e["part"])
            except ValueError:
                pass
        e["batch"] = b
        e["est"] = estimate(b, installed) if b else 0
        e["key"] = mod_key(b, e["name"])
    waiting = [k for k in MOD_ORDER if any(e["key"] == k for e in entries)]
    turn = dict(turn or {})
    cur = turn.get("mod")
    if cur in waiting:
        key = cur
    else:
        rot = MOD_ORDER[MOD_ORDER.index(cur) + 1:] + MOD_ORDER[:MOD_ORDER.index(cur) + 1] if cur in MOD_ORDER else MOD_ORDER
        key = next(k for k in rot if k in waiting)
        turn = {"mod": key, "started": now, "spent": 0}
    cand = [e for e in entries if e["key"] == key]
    starved = [e for e in cand if e["skips"] >= MAX_SKIPS]
    pick = starved[0] if starved else min(cand, key=lambda e: (e["est"], e["idx"]))
    passed = [e for e in cand if e["idx"] < pick["idx"]]
    return pick, pick["line"], None, passed, turn


def queue_next(path):
    """Take the next line of the queue file (queue_pick) and print it; the file keeps the others (lines passed
    over get "#skips=N"), a long batch's rest in its place; build/batches/turn.json the mod whose turn it is.
    Prints nothing when it's empty."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return 0
    entries = queue_entries(lines)
    if not entries:
        return 0
    old = turn_load()
    pick, run_line, back, passed, turn = queue_pick(entries, installed_mod(), turn=old)
    if turn != old:
        turn_save(turn)
    # the file again (lines added meanwhile kept), then the change
    with open(path, encoding="utf-8") as f:
        now = f.read().splitlines()
    passed_raw = {e["raw"]: e for e in passed}
    out, done = [], False
    for raw in now:
        if not done and raw == pick["raw"]:
            done = True
            if back:
                out.append(back)
            continue
        if raw in passed_raw:
            e = passed_raw.pop(raw)
            out.append(f"{e['line']} #skips={e['skips'] + 1}")
            continue
        out.append(raw)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + ("\n" if out else ""))
    os.replace(tmp, path)
    say(run_line)
    return 0


BATCH_LOCK = os.path.join(LOGS, "test_batch.lock")


def take_batch_lock(max_wait=4 * 3600):
    """One batch (or --restore) at a time on this PC: two queue runners started bnw-11 twice at 18:06 (both died in
    pre-flight). A second one waits; a lock whose holder is gone (or whose pid is another process's) is taken over.
    -> None or why not"""
    t0, said = time.time(), False
    while time.time() - t0 < max_wait:
        try:
            fd = os.open(BATCH_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"pid {os.getpid()}\nstart {time.strftime('%Y-%m-%d %H:%M:%S')}\nargs {' '.join(sys.argv[1:])[:300]}\n".encode("utf-8"))
            os.close(fd)
            return None
        except FileExistsError:
            try:
                with open(BATCH_LOCK, encoding="utf-8", errors="replace") as f:
                    text = f.read()
                taken = os.path.getmtime(BATCH_LOCK)
            except OSError:
                continue
            m = re.search(r"^pid (\d+)", text, re.M)
            if not m or not holds(int(m[1]), taken):
                try:
                    os.remove(BATCH_LOCK)   # stale
                except OSError:
                    time.sleep(1)
                continue
            if not said:
                say(f"[batch] waiting: another batch runs ({' '.join(text.split())[:200]})")
                said = True
            time.sleep(5)
    return f"another batch held {BATCH_LOCK} for {max_wait} s"


def release_batch_lock():
    try:
        with open(BATCH_LOCK, encoding="utf-8", errors="replace") as f:
            mine = re.search(r"^pid (\d+)", f.read(), re.M)
        if mine and int(mine[1]) == os.getpid():
            os.remove(BATCH_LOCK)
    except OSError:
        pass


def order_runs(runs, opts):
    """the batch's own order: its author puts launches that may stall last on purpose (bnw-11: ai-3-triggers, then
    tower; bc-5: bc-events-6, then bc-player)"""
    return list(runs)


def main():
    # replies carry game text (Japanese names, symbols): a cp1252 console would end the run at the first one
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("batch", nargs="?")
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--no-install", action="store_true")
    ap.add_argument("--only", action="append", help="run only these runs (by name)")
    ap.add_argument("--part", help="only requests A-B of the batch (1-based, across its runs): queue4.sh's parts")
    ap.add_argument("--defer-restore", action="store_true", help="leave WC/BC installed (queue4.sh's end restores)")
    ap.add_argument("--no-warm", action="store_true", help="no warm game: every run its own launch, quit after")
    ap.add_argument("--no-preflight", action="store_true", help="skip the offline suites and the Magicite check")
    ap.add_argument("--preflight", metavar="BATCH", help="the pre-flight gate alone for a batch (no build, no game)")
    ap.add_argument("--build", choices=list(PLUGINS))
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--cool", action="store_true", help="stop the warm game")
    ap.add_argument("--restore", action="store_true", help="BC's test install restored, BNW active")
    ap.add_argument("--next", metavar="QUEUE", help="take the queue file's next line and print it")
    ap.add_argument("--estimate", metavar="BATCH", help="seconds the batch should take")
    a = ap.parse_args()
    os.makedirs(LOGS, exist_ok=True)
    if a.check:
        w = warm_load()
        why = blocked()
        if why and w and not why.startswith("Wow") and game_pids() == [w["pid"]]:
            say(f"warm: a {w.get('mod')} {w['kind']} game is up (pid {w['pid']}, launched "
                f"{time.strftime('%H:%M', time.localtime(w['started']))}, {w.get('runs')} runs): the next matching run "
                f"uses it, any other launch stops it first (--cool stops it now)")
        else:
            say(why or "free")
        return 0
    if a.cool:
        cool("asked (--cool)")
        say("[batch] no warm game")
        return 0
    if a.restore:
        why = take_batch_lock()
        if why:
            say(f"[batch] {why}")
            return 3
        try:
            ok, text = restore()
        finally:
            release_batch_lock()
        say("\n".join(l for l in text.splitlines() if l.strip())[-1500:])
        say(f"[batch] restore: {'ok' if ok else 'FAILED'}")
        return 0 if ok else 4
    if a.next:
        return queue_next(a.next)
    if a.preflight:
        # under the batch lock too: a lone --preflight beside a batch's ran the same suites on the same temp folders
        why = take_batch_lock()
        if why:
            say(f"[pre-flight] not running: {why}")
            return 3
        try:
            with open(a.preflight, encoding="utf-8") as f:
                ok, lines, secs = preflight(apply_part(json.load(f), a.part))
        finally:
            release_batch_lock()
        say(f"[pre-flight] {'ok' if ok else 'FAILED'} ({secs:.0f} s)")
        return 0 if ok else 5
    if a.estimate:
        with open(a.estimate, encoding="utf-8") as f:
            b = apply_part(json.load(f), a.part)
        say(f"{estimate(b):.0f}")
        return 0
    if a.build:
        ok, errs, s = build(a.build)
        say(f"build {a.build}: {'ok' if ok else 'FAILED'} ({s:.0f} s)")
        for e in errs:
            say("  " + e)
        return 0 if ok else 1
    why = take_batch_lock()
    if why:
        say(f"[batch] not running: {why}")
        return 3
    try:
        return run_batch(a)
    except BaseException:
        stop_ours("the batch crashed")
        raise
    finally:
        release_batch_lock()


def run_batch(a):
    with open(a.batch, encoding="utf-8") as f:
        batch = apply_part(json.load(f), a.part)
    batch, invalid = check_batch(batch)
    for run_name, rid, who, errs in invalid:
        say(f"[batch] request {rid} ({who}) in {run_name} not run: " + "; ".join(errs))
    mod = batch.get("mod", "none")
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    if invalid:
        batch["invalid"] = [{"run": r, "id": i, "from": f, "errors": e} for r, i, f, e in invalid]
    if not batch["runs"]:
        md_summary(batch, stamp, mod, None, None, [])
        say("[batch] nothing left to run (every request had a broken step or regex)")
        return 6
    build_info = install_ok = None
    install_note = ""
    t0 = time.time()
    if mod in PLUGINS and not a.no_build:
        build_info = build(mod)
        say(f"[batch] build {mod}: {'ok' if build_info[0] else 'FAILED'} ({build_info[2]:.0f} s)")
        for e in build_info[1]:
            say("  " + e)
        if not build_info[0]:
            md_summary(batch, stamp, mod, build_info, None, [])
            return 2
    preflight_info = None
    if not a.no_preflight:
        preflight_info = preflight(batch)
        say(f"[batch] pre-flight: {'ok' if preflight_info[0] else 'FAILED'} ({preflight_info[2]:.0f} s)")
        if not preflight_info[0]:
            saved = estimate(batch)
            stats = preflight_blocked(batch, saved)
            say(f"[batch] pre-flight FAILED: nothing installed or launched (~{saved / 60:.0f} min of launches saved; "
                f"{stats['blocked']} batches so far, ~{stats['minutes']:.0f} min)")
            for l in preflight_info[1]:
                say("  " + l)
            md_summary(batch, stamp, mod, build_info, None, [], preflight_info=preflight_info)
            with open(os.path.join(LOGS, f"{stamp}_{batch['name']}.json"), "w", encoding="utf-8") as f:
                json.dump({"batch": batch, "build": build_info, "preflight": preflight_info, "runs": [],
                           "seconds": int(time.time() - t0)}, f, indent=1)
            turn_add(mod_key(batch), time.time() - t0)
            return 5
    if mod == "none" and not a.no_install and (bc_installed() or installed_mod() == "wc"):
        # "installed as is" means the PC's usual state (a deferred WC/BC batch may have left another mod)
        ok, text = restore()
        say(f"[batch] the usual install back first (BNW): {'ok' if ok else 'FAILED'}")
        say("\n".join(l for l in text.splitlines() if l.strip())[-800:])
    if mod != "none" and not a.no_install:
        ti = time.time()
        install_ok, text = install(mod, built=build_info is not None)
        if text.startswith("[batch] blocked:"):
            say(f"[batch] not installing: {text[len('[batch] blocked: '):]}")
            return 3
        install_note = f" ({time.time() - ti:.0f} s{'; nothing changed' if 'nothing to install' in text else ''})"
        say(f"[batch] install {mod}: {'ok' if install_ok else 'FAILED'}{install_note}")
        say("\n".join(l for l in text.splitlines() if l.strip())[-1500:])
        if not install_ok:
            md_summary(batch, stamp, mod, build_info, False, [], install_note, preflight_info)
            turn_add(mod_key(batch), time.time() - t0)
            return 4
    runs = []
    todo = [r for r in batch["runs"] if not a.only or r["name"] in a.only]
    for run in order_runs(todo, a):
        say(f"[batch] run {run['name']} ({run['kind']}) ...")
        try:
            r = launch(run, stamp, a)
        except Exception as e:
            import traceback
            stop_ours(f"run {run['name']} crashed")
            r = {"run": run["name"], "skipped": f"runner error: {type(e).__name__}: {e} | " +
                 " | ".join(traceback.format_exc().strip().splitlines()[-4:])[:500]}
        runs.append(r)
        if "skipped" in r:
            say(f"[batch] {run['name']} skipped: {r['skipped']}")
        else:
            print_results([r])   # each launch's verdict as soon as it ends (the summary repeats them)
            with open(os.path.join(LOGS, f"{stamp}_{run['name']}.result.json"), "w", encoding="utf-8") as f:
                json.dump(r, f, indent=1)
    # another mod's batch: BNW back active (BC's test install restored, which brings the held BNW back), unless the
    # queue does it at its end (--defer-restore: the next batch may want the same mod)
    if mod in ("wc", "bc") and not batch.get("keep_installed") and not a.defer_restore:
        ok, text = restore()
        say(f"[batch] BNW back active: {'ok' if ok else 'FAILED'}")
    with open(os.path.join(LOGS, f"{stamp}_{batch['name']}.json"), "w", encoding="utf-8") as f:
        json.dump({"batch": batch, "build": build_info, "install": install_ok, "runs": runs,
                   "seconds": int(time.time() - t0)}, f, indent=1)
    md_summary(batch, stamp, mod, build_info, install_ok, runs, install_note, preflight_info)
    turn_add(mod_key(batch), time.time() - t0)
    print_results(runs)
    say(f"[batch] {batch['name']}: {int(time.time() - t0)} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
