# Testing and deploying

Owner: kit lead (QA for the runner parts). Moved verbatim from `pr/PORTING.md` on 2026-11-20 (roadmap item 5); `git log --follow` / the split commit trace any paragraph. Status rows stay in `pr/PORTING.md`.

## Testing (pr/tests/test_mod.py)

No playtesting by driving the user's screen (they asked not to). Offline suite:
`pr/.venv/Scripts/python -m unittest discover -s pr/tests -v` (21 tests): CSV
headers/rows, keys files, text lines, every id the mod writes resolves after
merging over vanilla, AI scripts vs the operand shapes/jump rules of the game's
own 430 scripts, chest map files differ from vanilla only in chest contents,
and BNW spot checks (Terra, growth, Ramuh, Sap, esper rules, stat caps).

### Decompiled game code (`pr/tools/ghidra/`, user OK'd the downloads 2026-11-05)

Il2CppDumper v6.7.46 (`tools/dl_il2cppdumper`) on GameAssembly.dll + global-metadata.dat
-> `tools/il2cpp_out/` (dump.cs with field offsets and RVAs, script.json, il2cpp.h).
Ghidra 12.2 (`tools/dl_ghidra`, JDK 25 already installed) headless, no window, no
auto-analysis: `pr/tools/ghidra/Il2CppDecompile.java` labels every method from
script.json and decompiles only the methods matching a pattern file
(`battle_rules.txt`, `commands.txt`) into `tools/decomp/<name>/<Class>.c`:

    tools\dl_ghidra\ghidra_12.2_PUBLIC\support\analyzeHeadless.bat tools\ghidra_proj FF6PR
      -process GameAssembly.dll -noanalysis -scriptPath pr\tools\ghidra
      -postScript Il2CppDecompile.java tools\il2cpp_out\script.json <patterns.txt> tools\decomp\<name>

(first time `-import <GameAssembly.dll>` instead of `-process`). Takes ~5 minutes.
No cross-references (no auto-analysis): `pr/tools/ghidra/callers.py <rva>...` finds a
method's direct callers by scanning the DLL's "il2cpp" code section for call/jmp rel32
(2026-11-06: the grip's ConfirmedAttack; 2026-11-07: the counter reset's InitFinishingState).
Pattern files since: twohand.txt, leap_mimic.txt, mimic2.txt, cover2.txt (-> tools/decomp/<same name>).
Overloads: until 2026-11-12 only the first method of a name was decompiled; each overload now
gets its own section, `Class$$Method#<rva>` (autobattle2-5.txt: the auto-battle replay, target
picking, the ATB queue and the executor's stack checks).
Field offsets in the C (param_1 + 0xd4...) match dump.cs; virtual calls are vtable
slots. The code is full of debug-log string building; grep past it.

### Test batches (`tools/test_batch.py`, 2026-11-20)

With several porting sessions at once, one "PC test runner" session owns the PC install and every
headless run; the others send it requests (format in the session notes: mod, what to run, pass/fail
regexes). `tools/test_batch.py <batch.json>` runs a batch: a pre-flight `dotnet build -c Release` of the
mod's plugin (a break is reported as file:line to whoever owns the file, nothing is installed), the
install (`deploy.sh --pc`, or BC's `bc_testinstall.py`), then each launch (probe, harness, WcTest,
Live, `kit.py run`), refused while `Wow.exe` or the game runs, the save folder checksummed before and
after; each request passes when all its "pass" regexes match the log or the harness replies and its
"fail" regex (default `Exception|\[Error`, minus Magicite's OnExportError signature warning) matches
nothing ("  ~" poll lines of the transcript don't count for fail). Harness requests in one launch run
in order; steps are harness commands plus `boot`, `tofield` (from the title, the demo, a battle or the
field to a free field), `killall` (BNW `endfight`, else `enemyhp 1`), `warpfree`, `loadfield`,
`sleep <s>`, `until <regex> [s] [check <cmd>|logfile] [repeat <cmd>]`; request options `keep_going`,
`skip_to`; run options `setup`/`undo` (commands around a launch, e.g. a test Magicite folder in and
out). The install is `deploy.sh` with `DEPLOY_NO_BUILD=1` then one checked `-p:Deploy=true` build (a
file saved after the pre-flight can't leave a failed build's old DLL installed). After a WC or BC batch
BNW is put back active. The runner waits for a closing game (~20 s) and holds while Wow.exe runs.
Logs: `build/test_logs/` (harness transcripts written live); summaries: `build/test_runs.md` (newest
first); batch files: `build/batches/*.py` generate the JSON; `build/batches/queue.sh` runs the lines of
`build/batches/queue.txt` in order (edit the file to reorder; never kill the shell mid-batch).
**Saves load headless at the title** (fixed 2026-11-20, `PrKit/ModSaves.cs` `LoadAtTitle`). Before:
the in-game load (`GotoLoadSaveData`) does nothing at the title, and the title's path (`LoadAsync`,
`RestoreSaveData`, `MapLoadProcessor.Start`, `SubSceneLoadingWait(false)`) read the save and stalled;
~74 s after the title its idle demo played the opening on map 609 (Terra/Biggs/Wedge), which looked like
a loaded field. Cause (decompiled in `tools/decomp/titleload`, `titleload2`): the title's Load window
does more than that path. (1) It fades out first, and `SubSceneLoadingWait(false)` switches to the
field's scene only once `FadeManager.IsStateFadeOut()`; with no fade it waited forever. (2) While it
waits, its `UpdateWait` runs `MapLoadProcessor.Update()` every frame (the map's load tasks; nothing
else does before the field exists). With the fade alone the scene switched in ~1 s, then the field
never got ready (`scene other; map 0`). (3) Its slot read runs `UserDataManager.Initialize()` first
and `OwnedCharacterClient.UpdateChracterName()` after. `LoadAtTitle` does all of it; the pump is a
postfix on the title's `Update` for that title only. Kit harness: `load [slot|party] [goto]`. At the
title this is the title's load; `party` picks the newest save with 3+ in the party, by time (the
TimeStamps mix formats, "03/15/2022 21:39:57" and "11/16/2026 5:13:15 PM"), and not one on a world map
(map ids 1, 2, 575) when another will do: twice (18:08, 18:45) a BNW probe self-test loaded the PC's slot
11 (map 1), started its field battle there, and a second game process appeared; cause still open, an A/B
with a town save (slot=6) vs a New Game is queued in bnw-13; `goto` is the in-game
load, for a field. The BNW probe's title step uses `LoadAtTitle` too (`slot=<n>|party`). Measured
(4 headless BNW runs): `load 6` sent 12 s after the title gave a free field on the save's map 399 in
3.5 s. `load party` sent 2 s after the title (slot 20: Edgar Lv 66, Terra Lv 46) gave a free field
on map 112 in ~23 s, because the title was still loading. The New Game `boot` took ~25 s of waiting
plus the opening, ~1-1.5 min, and its Lv 3 party dies in strong fights. The PC's save folder stayed
byte-identical. **Save sandbox:** the PC's own saves are 2022 vanilla ones (the user plays on the
Deck), so runs load copies of the Deck's saves from `build/save_sandbox/deck_20261120` (README
there; copied read-only over ssh). Point a run at it with `savesandbox=<abs dir>`: the BNW probe's
key (`probe_headless.ps1 -Extra "harness=1;savesandbox=..."`), or the kit's `prkit_test.request`
key, read by `ModSaves` for a mod that keeps its own saves. A sandbox equal to the game's own save
folder is ignored. WcTest's `load=1` uses `ModSaves.LoadAtTitle` too since 19:28 (it had the old
stalling path, so its loaded-save checks ran in the title demo's field until then: expect them to
run on the real save now). WcTest has no sandbox key (it reads the PC's shared saves). The kit harness's `state` says "title
window" on the title (its "scene" says field there, the demo's). A `press` is a 1-frame tap. **WcTest runs one check per launch** (`check=a,b` ends after a's plan).
**Self-tests only:** `-Extra "slot=party;sweep=0"` skips the 2373-direction formula sweep (and its 5
game-side Morph NullReferenceExceptions): the probe battle runs BnwRunner's chain (Plugin.cs: Veldt,
grip, limits, Leap, cover, toss) and every check registered with `FormulaProbe.AddSelfTest(name,
Func<string>)` (null until it can run, then its line; exceptions logged as FAILED with a stack head),
then quits (`selftestmax`, default 30 s since 2026-11-20, was 120: a check that answers does so within
~15 s; it names the checks still waiting). New in-battle checks go in that registry, not the chain.
probe_headless.ps1 no longer waits a fixed 10 s after "[probe] done". `slot=new`: a New Game at once
(asked again every 2.5 s while the title is up) and the probe battle on the opening's field, for a run
that needs no save.

**Runner speed (2026-11-20; the user: "it shouldn't be lasting this long").** Measured before: 250 s per
request (today's 15 completed batches, 8,508 s for 34 requests: build, install, launches, steps); a
launch ~30 s to the title, then a fixed 25 s, New Game, the warp: ~90 s before a request's first step.
- **Warm game.** A harness or kit launch stays up after its run: the runner sends `idle 10` (the kit
  harness then quits the game by itself after 10 minutes with no client and no command, or at once
  when Wow.exe starts) and writes `build/test_logs/warm_game.json`. The next harness/kit run with the
  same kind, `graphics` (a graphics game serves both), `extra`/`set`, installed mod and installed files
  (plugins + Magicite folders, sizes and times) and enough time left in the launch (`-Minutes` 120 for
  a warm launch) reuses it: `title` (the field's own sub-scene state GotoTitle behind a fade-out; `MainGame.GotoTitle()`
  alone did nothing) and its steps from the
  title, no launch; a run whose first step is `tofield` goes on from where the game is. Anything else
  (a probe, WcTest, an install that changes files, a run with `setup`/`undo`) stops it first (`quit`,
  then the process; its launcher removes steam_appid.txt and the lock). `test_batch.py --cool` stops it
  by hand; `--check` says when one is up. The launcher starts detached (its own hidden console, out of
  the queue shell's job where Windows allows) so it outlives the batch. A game that dies mid-run, or
  can't get back to the title, is relaunched for the requests left (twice at most); each request is
  judged on its own launch's log. Kit harness: any number of clients at once (one thread each), so a
  second connection is never refused; `newgame` asks the title again every 1.5 s until it takes it
  (its intro ignores it; the title state, `title window (Select)`, is in `state`); `title`; `idle`.
- **Boot without fixed sleeps.** `boot` = until the title window, `newgamego` (New Game 12 s after
  the title appears, not 25: asked in its first seconds the title holds it, its state at NewGame, until
  its attract demo ~74 s later, live "2 tries, 75.1 s"; the idle title's state is None throughout; a
  demo that starts first is ended with a press), skipmsg, `newfield` (the new game's own field: a game
  back at the title still says the last game's map until the new one loads, so a field on another
  map, or any after 20 s), `warpfree` (speed 4 meanwhile; the first landing is watched 5 s for the
  opening carrying the party off, then it warps once more), `freefield` (1.5 s of free field). Polls
  every 0.25 s; transcripts log a reply only when it changed (the frame counter aside). `until ...
  every <s>` paces the checks and repeats. A run's `"boot": "save"`: `boot` loads the newest save with
  3+ in its party at the title instead (`load party`, runner-saveload's `LoadAtTitle`; with the run's
  `extra` `savesandbox=<dir>` the Deck saves' copies). Measured live (PC, 2026-11-20): launch to a free
  field ~48 s (was ~90); on a kept game, `title` 1.4-3.5 s, title to free field ~26 s, a request of
  boot + battle + its end 36-42 s (69-71 s with a launch).
- **Stuck games and flaky battles.** `tofield` in a battle tries once (killall, 90 s of presses): a
  battle that doesn't end (a boss its script holds at 0 HP, bnw-2) gives the game up and the requests
  left get a new launch, instead of 3 minutes per request; a request given up so before any of its own
  steps ran runs again on that launch (bnw-11's scenes-1 failed for its reused game's battle). A game
  whose run ended in a battle or with a script running isn't kept warm. A broken request (an `until`
  step, a pass or fail regex that doesn't compile) is set aside when the batch loads ("not run: ..."
  in test_runs.md; the rest runs); a step or request that throws fails only itself; a run that crashes
  stops this batch's own games and launchers (never another game) and the batch goes on with its next
  run (bnw-11, 18:31: one cut regex ended the batch and left its game up). `battle`/`encount` answered with a
  NullReferenceException (the field a moment after a warp: `FieldController.ScreenShotMainView`) is
  asked again after 2 s and a free field.
- **Fast sleeps.** Request option `fast_sleep`: a `sleep N` (N >= 4) ends 1.5 s after the BepInEx log
  shows a line for one of the request's pass regexes it hadn't matched yet, else after N.
- **`needs: title`** on a request: its steps run at the title (no New Game or load; `boot`/`tofield`
  dropped). `field` is the default (the steps' own `boot`). `boot` starts from anywhere (`totitle`
  first), so a request may begin with it after another one in the same launch.
- **Test-run speed-ups in the game (2026-11-20, the user: "can we speed up the one test game (like for
  example skipping the logos at the beginning, etc)"; measured live on the PC with a Debug BNW DLL):**
  - *Logos:* the kit harness skips the opening logos in a test run only (`Harness.SkipLogosInTestRun`:
    `Application.isBatchMode`, called from `Harness.Start` and the BNW probe's start; a player's game
    never; the user had the player-facing skip removed on 2026-11-12). `SceneSplash.OnSplashAnimationFinished`
    is called once `loadFinished` and `messageIsReady` are set, the logos' own later call dropped. Headless
    the data load and the logos overlap: 703 -> 496 splash frames, launch to title 38 -> 35 s (one A/B).
  - *`fast on|off`* (kit harness): Active battles, the battle speed with the largest factor
    (`BattleUtility.GetBattleSpeedByConfigValue`: 0.5/0.75/1/1.5/2 for 0-4, the default 2), the shortest
    battle-message time (`Message.battleMessageSpeedTable`: 0.5-1.5 s, index 0), no frame cap
    (`targetFrameRate` 60 -> -1: a battle ran at ~68 frames a second instead of ~21); `off` puts them back,
    and nothing is saved. Opt-in, a run's `"fast": true` (else the runner sends `fast off`): on BNW's boss
    446 it didn't change the boss's turns in 30 s (4 -> 4; acts 7 -> 8), and the fight went differently
    (the party fell). Never with a request marked `"timing": true`.
  - *A request's `speed: N`* (1-10, Unity's time scale through the request; the boot's warp keeps it):
    harness/kit runs only, never with `"timing": true`, and **not on a request with a battle**: at 3x
    BNW's boss 446 ended at once with no act and nothing defeated (at 1x: 4 boss acts in 30 s). Field and
    scene tests may try it; nothing has confirmed it there yet. (Found 2026-11-21, the kit lead: that battle
    started without its own script, which the game judges a win at once; the speed only made it likelier. The
    harness's `battle` now replies "battle N started (script sc_b_...)" or "error: battle N started without its
    battle script ..." after 5 s, so it can't pass as a win; BC's battle 25 after a single warp did the same.)
- **No commands in a battle's opening** (kit harness, 2026-11-21). Commands run while a battle opens (shot,
  damage/steal simulations, enemy HP) let the field's map script take the script slot from the battle's own
  (T-Edition's battle 72, BNW's dream fight: stuck at the Preemptive! message). The harness now holds every
  command but ping/help/state/log/aistat/quit until the battle's Play phase (60 s at most), presses too (BNW's door
  runs pressed action as the battle opened and stalled); wait isn't held. Presses before the battle is up (waiting for
  an event battle to start) still reach the field: don't loop presses while waiting for a battle to begin.
- **Fail fast** (2026-11-21). bc-events-all spent 56 of 62 min in 37 timeouts after one wrong step. Its own
  `newgame`, then `tofield` 0 s later, saw "scene other; map 0" and sent the loading game to the title, and it
  never recovered. Now:
  - `tofield`/`totitle` on a running game between scenes wait for it to land. Mid-New-Game, `tofield` goes on
    with the boot's steps after `newgamego`.
  - The harness connection gives up a running game (MainGame loaded) that stays in "scene other" on one map for
    30 s (90 s on map 0); normally that lasts at most 6 s.
  - A failed step of the way to a free field (boot, tofield) gives the game up at once. Either way the runner
    relaunches for the requests left; on the laptop/Deck they're "not run".
  - Each run has a time budget, its `"minutes"` + 1 min, checked before every step and request.
- **A second test machine: the user's laptop** (2026-11-20, the user: "also i have this laptop you can test on";
  memory test-machines.md). `tools/remote_batch.py <batch.json> [--only RUN]` runs a BNW batch's harness runs
  there, beside the PC's queue: this PC's build into a test copy (`C:\ff6pr-test`, never the user's install),
  a headless launch through a one-shot scheduled task in the user's session (Steam runs there; SSH is session 0),
  the harness through an SSH tunnel (PC port 47812), test_batch's own step code, results as `<batch>@laptop`.
  Steam (offline on the laptop) let it run beside a PC test game. First batch 20:04: boot + battle, PASS, 66 s
  with a cold launch. Not yet: graphics runs (screenshot paths), setup/undo, other mods, a warm game there.
  - The machine's BepInEx log is mirrored every 2 s as base64 text, so byte counts stay exact. The transcript
    ends with `[log mirror] N bytes` (or `SHORT`, or the pull errors). Until 01:03 on 11-21 every `@laptop`
    `.log` was empty: under `powershell -Command -` a multi-line block only runs once a blank line follows it,
    so every piped script now ends with one.
  - Every 10 s during a run, and the moment the user starts a game there, the test game is stopped and the run
    reads "stopped: the user started playing (not a test result)".
- **A third: the Steam Deck** (`--machine deck`, 2026-11-21; memory test-machines.md). `remote_batch.py <batch>
  --machine deck --setup` sets it up once:
  - `~/ff6pr-test/game` is a copy of the user's install, which is only read from. Other mods' plugin and
    Magicite folders are shelved *in the copy*, and its BepInEx console logging is off: a detached game dies on
    its first console write.
  - The game gets its own Proton prefix, `~/ff6pr-test/compatdata`. The user's saves live in the user's prefix,
    which is never used.
  - Proton is the one that made the user's FF6 prefix (11.0, on the SD card), and the test prefix's Wine
    graphics driver is `null`.

  What the launch needed (each was found the hard way):
  - `systemd-run --user --scope` from the ssh shell: SteamOS's logind kills a session's processes when ssh
    closes.
  - Proton's `runinprefix`, not `run`: under Proton's `steam.exe` launcher the game hung before Unity's init.
  - The null driver: `-batchmode` still makes a window, and it must never go to the Deck's own screen.
  - Waiting until the game listens *on the machine* (`ss`/`Get-NetTCPConnection`) before connecting: an SSH
    tunnel accepts on the PC at once.

  No launch while any Steam game runs on the Deck (a `reaper SteamLaunch` process), with under 2 GB free, or on
  battery under 40%.
- **Remote T-Edition and kit runs** (2026-11-21): `remote_batch.py` takes `"kind": "kit"` runs, with a request file
  `prkit_test.request` (`harness=1`, `minutes`, the run's `set`). A `savesandbox` folder is copied into the test copy.
  It also takes batches with `"mod": "none"` whose runs install their mod in `setup` (ted-7). Setup and undo:
  - build steps still run on this PC;
  - `ted_testinstall.py install` installs into the test copy, using ted_testinstall's own file lists, after
    clearing every game-data mod there (a test copy: no hold, no restore; restores are skipped);
  - `ted_cfg.py set/restore` and `rm -rf`/`cp -r` into the PC game's folder do the same on the test copy;
  - anything else that touches the PC's game, or `bc_testinstall` (BC's generator needs this PC's project
    folder), skips the run.

  Graphics runs go to the laptop only (`-batchmode -screen-width 1920 -screen-height 1080`, no window); the Deck
  has no graphics device for tests. Each `shot <PC path>` is saved in the machine's own shots folder, which has
  no spaces because the harness splits a command at them (`C:\ff6pr-test\shots`, `~/ff6pr-test/shots`). After
  the run the shots are copied back with scp to the PC paths the steps named.
  - **No window on the laptop's screen** (the user, 2026-11-21). During a laptop graphics run, every 20 s a
    one-shot scheduled task in the user's session starts `tools/remote_wincheck/wincheck.vbs` (wscript, so no
    console flashes). It runs wincheck.ps1, which reports the test game's visible windows and whether it owns
    the foreground window. Any window or focus stops the game at once, and laptop graphics runs stay off until
    `build/test_logs/remote_graphics_blocked.txt` is deleted. Two checks that can't run also stop it
    (unverified).
  - **Beyond Chaos** (`"mod": "bc"`, or `bc_testinstall install` in setup) installs from the full bundle
    (`build/BeyondChaos`, tools/bc_bundle.py): DLL + bc_flags.json, the bundle's `plugin/` (its own Python
    generator, baselines) and its Magicite folder. There's no dev config, so nothing of this PC's is used.
    Bundle tool scripts older than pr/tools' go into the test copy only (later in the tar); the bundle itself
    is untouched.
  - A setup/undo step with a tool that acts on the PC's game (`*testinstall`/`*playertest` other than the two
    above, deploy.sh, deck_push.sh, modswitch, `kit.py run/deploy/install/setup`, the runners) makes the run
    skipped: none of it runs on this PC. Steam's log still records each test game as a running FF6 (`Game process added`).
  Harness port 47813 on the PC.
- Runner options since 20:1x: `"graphics": false` on a run gets a game without a graphics device (a graphics
  warm game is stopped first), `"fresh": true` a new launch; a relative program in `setup`/`undo`
  (`.venv/Scripts/python`) is found under pr/; builds wait while `build/batches/quiet.flag` exists and skip the
  package restore once restored (`--no-restore`); build errors name the file's owner (pr/OWNERS).
- **Installs.** BNW active with the built DLL, `bnw_data.json`/`bnw_dialog.json` and the Magicite
  folder the same as the installed ones: nothing deployed (the warm game stays up). Otherwise `deploy.sh`
  (`DEPLOY_NO_BUILD=1`), then the batch's own pre-flight build is copied in as the csproj's Deploy target
  would (the DLL; BNW's two data files; WC's `wc_flags.json`) and its md5 checked: no second
  `-p:Deploy=true` build (11-20 s), and the install is exactly the build the batch checked. WC's bundle and the
  mod switch skip unchanged work inside `deploy.sh`/`wc_bundle.py` (runner-wc-cache's work).
- **Pre-flight** (after the build, before any install or launch): the mod's offline suites (BNW:
  Rules.Tests, `test_mod`; WC: Wc.Tests, WcAi.Tests; BC: Bc.Tests, `test_bc`; T-Edition: Ted.Tests,
  `test_mod` with PR_MOD=TEdition, `test_snes_events`; PrKit.Tests when the kit's sources changed),
  three at a time, run only when what they read changed, blocking only on a failure not in their
  baseline (`build/test_logs/preflight_state.json`: today's failures, e.g. 214 failing cases of BNW's
  `test_mod`, shrunk as they get fixed); a request's `offline: [commands]` replaces them (each must
  pass). Then `tools/magicite_check.py` (game-free; `tests/test_magicite_check.py`) on the mod's
  Magicite folder and any folder a run's `setup` copies in: JSON parses, master tables' ids and texts'
  keys unique, every asset a map package lists exists (the folder's or the game's), every script beside
  a package is listed by it (T-Edition's "didn't start (not in this map's list?)"). Before each launch
  the installed Magicite folders are checked for files two of them ship (BNW's `map_20071` package hid
  T-Edition's). A failure: nothing installed or launched, "failed (pre-flight)" in test_runs.md, exit 5,
  counted in the state file (`--preflight BATCH` runs the gate alone).
- **The queue** (`build/batches/queue4.sh`, `test_batch.py --next`): one mod's turn at a time (BNW, WC,
  BC, T-Edition; mods with nothing queued skipped; `build/batches/turn.json`): every batch of that mod
  queued, with no time limit (the user: "undo the 30 minute cap per mod"; a batch of the mod queued during
  its turn joins it), its install once and its warm game for all of them; within a turn the shortest
  batch first (a line passed over 3 times gets `#skips=3` and goes next); `--part A-B` (written in a
  line) runs requests A..B of a batch. Batches run with `--defer-restore` (WC/BC stay installed for their
  next batch); the empty queue runs `--restore` (BC's test install restored, BNW active). Before each
  batch queue4.sh waits for `optimizer.lock` to go and for 10 s without a game (queue3.sh's wait), unless
  the runner's own warm game is the one up. A batch's runs go in its own order (its author puts launches
  that may stall last). One batch at a time: `build/test_logs/test_batch.lock` (pid; a second
  `test_batch.py` waits; a holder that's gone, or whose pid is another process's now, is taken over).
- **Before an install**: while `mods/<Mod>.porting` is held (tools/port.py's lock: its owner's pid alive
  and started before the lock was taken, port.py's own rule; port.py renames `mods/<Mod>.new` over the
  folder at the end) or, for BNW, `build/bnw_port.lock`, the install waits (30 min at most); BNW's folder
  must also have `bnw_data.json` and `port_report.txt` and be still for 3 s. Then no FINAL FANTASY VI.exe, no UnityCrashHandler64.exe and no
  `BepInEx/probe_run.lock` for 10 s straight (wc-4's mod switch, 17:04: a closing game's files still
  held). Each summary line names the install: `DLL <md5>, data <hash of the installed Magicite folder>`.

### Formula probe (in-game, automated; plugin `FormulaProbe.cs`, `tools/probe_check.py`)

2026-11-05: `probe_headless.ps1` only watches and stops the process it started (it used to
stop every "FINAL FANTASY VI" process once one had a window, which would include a game you
started yourself); if someone starts the game during a run, the run stops its own game and
leaves theirs alone, and the Magicite setting a WC test changed is put back as soon as
BepInEx has read it ("Chainloader startup complete").
`-Mods Magicite` runs with another Magicite folder for that run only (put back the same way:
check the BNW port while the game is set to Worlds Collide); `-Until "<regex>"` stops as soon
as the log has a matching line (a startup check takes ~17 s instead of the whole probe).

2026-11-07: **saves.** A run loads the player's latest save, and the shop/box checks' warps
autosaved: the PC's slot 21 (the autosave, then a save from a new game's opening) was written
by those runs before anyone noticed (the user's other slots, from 2022, untouched). Every probe
request now blocks the game's saves for its run (`FormulaProbe.PatchNoSaves`: every
`SaveSlotManager.Save` overload, a script's `AutoSave`, the bestiary's
`PictureBookSaveManager.Save` (a won battle records its monsters) and `SystemConfigManager
.Save`); a harness run through a new game, its first battle and the victory screen left the
save folder byte-identical, timestamps included.

2026-11-07: **the game harness** (`BnwPlugin/GameHarness.cs`, client `tools/game_harness.py`;
the user: "make a test harness by which you can communicate with the game efficiently and play
the first battle yourself"). `probe_headless.ps1 -Extra "harness=1" -Minutes 40 -Until
"\[probe\] done"` (in the background) starts the game headless with the plugin listening on
127.0.0.1:47811: one command per line (`state`, `party`, `newgame`, `load`, `skipmsg on|off`,
`press <key> [hold frames]`, `wait <frames>`, `quit`), presses answering the game's own input
checks (`InputListener.GetKey/GetKeyDown/GetKeyUp`, `AnyKey*`). `state` gives the scene, map,
the Unity scenes, the battle's phase (`BattleController` state machine) and units, and the
running script; `party` every owned character's abilities (known / below 100%) and the party
magic list. The client's `--until REGEX` repeats a command (with `--repeat` a press between
checks) until a reply matches. The first battle from the title: `skipmsg on`, `newgame` (sent
until the title takes it: an idle title starts its attract demo), wait for `scene other` (the
opening ends on a controls help popup: `press start` closes it), `press up 90` until `scene
battle` (Narshe's guards), `press action` until `battle phase WinResult`, then until `scene
field`: about 6 minutes, nearly all of it the opening's scenes.

Later the same day (the Whelk, the event fights): `warp <map> [point]` (as the ChangeMap
instruction goes), `script <name>` (an event script of the current map run as the field runs
one, its Encount a real battle; refused while another script runs: an arrival script, or the
opening's, which may also carry the party back after a warp, so check `state` and warp again),
`slots`, `log` (the battle log since the last call: every action as it's built, actor, ability
ids, command, targets with HP, counters marked, and everyone's HP after each act ends; also in
the BepInEx log as `[harness]`). `encount <party>` sets a battle up but its loop never runs:
not for play. The Whelk from a new game: `newgame` while the title shows (`press action` until
`scene title` first if its demo started), `press start` only while `scene other` (the opening's
popups: extra presses skip cutscene pieces), then `warp 323 1`, wait until no script runs,
`script sc_e_0011`. Aiming: `press action` opens the command, a second picks the first entry,
`press right` there moves along the list, not between targets (aiming at a chosen monster isn't
worked out yet). `load <slot>` from the title follows the title's Load window
(SaveSlotManager.LoadAsync, then LoadData.RestoreSaveData, MapLoadProcessor.Start, the title's
SubSceneLoadingWait: decompiled in tools/decomp/load) but stalls before the field appears
(`scene other`); GotoLoadSaveData is the in-game load and does nothing at the title, so the
earlier runs that "loaded" a save were in the title demo (fixed 2026-11-20: the missing fade-out and
map-load pump, see "Test batches"). One `probe_headless.ps1` run at a
time: a run finishing removes steam_appid.txt, and a game started meanwhile is relaunched by
Steam outside the run, without its request (no save block). The script now waits for a run
still finishing (BepInEx\probe_run.lock), and stops any game started since it began when its
own exits at once.

2026-11-07: `-Extra "shopcheck=<map id>:<point>:<script>"` checks a script the port added
instead of probing: after the loaded save's field settles (messages pass at once; an event
scene's own map change is waited out, the warp retried up to 3 times), it warps to the map,
finds the script the way the field does, logs the mod's NPCs there (script ids from 9901) and
runs it; the shop screen must open. `boxcheck=` (same fields) runs a box's script and logs the
battle's monsters. A script reservation the save's event scene left (the opening's
`sc_e_0001_1`) is cancelled first: a box's battle reserves its own, and a second one throws
"Reserved script is already booked". About 2 minutes a run.

2026-11-05 (later): the probe now forces every unit to the front row while it measures
(postfixes on `CalcControllerProvider.GetCorpsId`, which the damage calc reads, and
`BattleUtility.GetCorpsId`): a back-row character in the latest save had halved every Fight
case both ways (41 "failures"). Back to vanilla 5 / BNW 5 failures (the Meltdown quirk).

The user won't play test battles for every damage formula, so the plugin tests them itself:

1. `powershell -NoProfile -ExecutionPolicy Bypass -File pr\tools\probe_headless.ps1`
   (about 4 minutes): writes `BepInEx/bnw_probe.request`, adds `steam_appid.txt` (else
   Steamworks relaunches the game through Steam, in a window), starts the game with
   `-batchmode -nographics` (no window; the plugin mutes SEAD and Unity audio), kills it if
   any window appears or after 15 min, removes what it added and runs the checker.
   **Never launch the game with a visible window on the user's PC** (2026-11-05: the user
   objected to a self-closing windowed run) and only run this with the user's OK. The
   request alone (`party`, `weapon`, `samples`, `quit` lines) also runs on the user's own
   next launch; it is deleted at start (one run only). Runs 2-5 (2026-11-05): 1.5-3 M
   calls each, 0 errors, every stat getter patched, no window.
2. The plugin loads the latest save from the title screen (`SaveSlotManager
   .GetLatestSaveSlotData` + `GotoLoadSaveData`), starts formation 7 (one Leaf Bunny) from
   the field like the boss test, and in battle runs every ability whose function group has
   a damage/heal function type (1, 2, 3, 13, 23, 32-34, 36, 41, 48, 50, 55, 56, 65, 68, 70,
   74, 76, 77; 839 abilities) through the game's own objects:
   `ParameterActFunctionManagment.GetFunctionBaseCalc(type, v1, v2, v3, SingleEnemy)` +
   `FunctionBase.MainCalc(attacker, target, ability, null)` + `GetCalcResult()`, after
   `CalcControllerProvider.SetCalcInfo` (weapon, rows, command). Both directions
   (character -> monster, monster -> character), 79 stat cases (base, one stat at a time,
   Level x Vigor/BP/Magic grids, rows), 8 samples each.
3. Stats are set by first-priority postfixes on the Confirmed* getters of
   PlayerCharacterParameter and EnemyCharacterParameter that answer only during a probe
   call (`FormulaProbe.Active`; the EL/esper/relic hooks stand aside then, elements are
   neutral). The values the getters actually returned are written next to each result,
   so a getter that couldn't be patched shows up. BNW's damage hooks stay on: the
   numbers are what a player gets. Each case runs twice: with BNW's battle rules off
   (`raw_*`: the game's own values, the vanilla baseline for every port) and on (final).
   The game caches a character's Battle Power for its Fight formula (fitted ~107 when the
   probe sets 100) and takes rows from the units, not CalcInfo, so neither is varied.
   Units are healed between frames; the run is spread over frames (150 ms each), then
   `BepInEx/bnw_probe.csv` is written and the game quits.
4. `tools/probe_check.py` checks two rule sets and writes `pr/probe_report.md`:
   **vanilla** (SNES FF6's formulas vs the raw pass: where the PR itself differs from the
   SNES; the baseline for Worlds Collide, Beyond Chaos...) and **bnw** (c2.asm formulas vs
   the final pass), each pass / fail (game vs expected per case) / no hits; defense met
   (measured from the Def/MDef 0 vs 255 cases) against each ROM's spell flags; and the
   unchecked function types with which stats move them. Exit 1 on failures. Run 5: vanilla
   534 pass, 4 fail (Meltdown 1350/1524 hit ~8x the formula in the PR).

## Deploying (pr/tools/deploy.sh) — PC and Steam Deck

`pr/tools/deploy.sh` builds + installs the plugin on the PC (`dotnet build
-p:Deploy=true`), mirrors `mods/BraveNewWorld` into the PC's Magicite folder, then
pushes the plugin, `BepInEx/config` and the Magicite folder to the Steam Deck over
`ssh deck` (tar). The first push (or `--full`) also sends BepInEx itself (core,
interop, cache, Magicite plugin), the `dotnet` runtime and the loader
(`winhttp.dll`, `doorstop_config.ini`). `--pc` / `--deck` do one side, `--deck-log`
prints the Deck's BepInEx log. Both games must be closed. Deck: same game build as
the PC (GameAssembly.dll md5 872278b3...), install at
`/home/deck/.local/share/Steam/steamapps/common/FINAL FANTASY VI PR`, app 1173820;
BepInEx under Proton needs Wine to prefer the game's winhttp.dll: deploy.sh runs
`tools/deck_winhttp_override.py` on the Deck, which adds `"winhttp"="native,builtin"`
to the existing `[Software\Wine\DllOverrides]` section of FF6's prefix
(`compatdata/1173820/pfx/user.reg`, backup `user.reg.bak-before-bnw`). Same effect as
the launch option `WINEDLLOVERRIDES="winhttp=n,b" %command%`, without touching Steam's
localconfig.vdf (Steam rewrites it while running). Gotcha: backslashes in inline
`ssh deck '...'` commands get halved on the way from Git Bash, so remote edits go
through script files piped to `python3 -`.

**One mod per install (2026-11-07, the user: "WC/BNW need to be separate mods entirely").**
Brave New World and Worlds Collide are separate mods; neither plugin knows the other
(plugin/Shared holds only `MagiciteDir`: where Magicite's import folder is, so each plugin
checks its own data is installed). `deploy.sh --bnw` / `--wc` (default: the one installed
now) installs that mod (`BepInEx/plugins/<Mod>` + `StreamingAssets/Magicite/<Mod>`, Magicite's
import directory the standard `%StreamingAssets%/Magicite`) and moves the other mod's plugin
folder to `BepInEx/mod-shelf/<Mod>` (BepInEx loads nothing there): Worlds Collide's `seeds/`
stay with it and come back with `--wc`. The old shared layout (`MagiciteWC`,
`MagiciteVanilla`, the in-game Mods screen and its mode switch) is folded in on a machine's
first run. For WC, deploy.sh re-exports `wc_flags.json`, builds `plugin/WcPlugin`, runs
`tools/wc_bundle.py` and mirrors its `generator/` and `baseline/` into the plugin folder and
its Magicite folder into `Magicite/WorldsCollide`; the seed sync between PC and Deck runs only
with WC installed. Players get one zip per mod: `tools/package_mod.py bnw|wc` ->
`build/dist/<Mod>-PR.zip` (the plugin + its Magicite folder + a README; never a ROM, never the
game's own files: WC's are made on the player's machine, "WC without the game's files").
The headless runs check the mod they need is installed (the probe and the harness: BNW;
`-WcTest` / `-Live`: WC) instead of switching Magicite's folder per run.

**Four mods, one active; tiles; per-mod Deck push (2026-11-20).** Worlds Collide, Brave New
World, Beyond Chaos and T-Edition all stay installed on the PC and the Deck, exactly one active:
the others' plugin and Magicite folders wait in `BepInEx/mod-shelf/<Mod>` and
`mod-shelf/magicite/<Mod>` (T-Edition is Magicite-only until `plugin/TedPlugin` exists). deploy.sh
`--bnw|--wc` also shelves BC and T-Edition if a tile left one active. `tools/modswitch`:
`ff6-mod-switch.sh wc|bnw|bc|ted|status [--launch] [--dry-run]` (Deck, `~/.local/share/ff6pr-mods`)
and `Switch-Ff6Mod.ps1 -Mod wc|bnw|bc|ted|status [-Launch] [-DryRun]` (PC, `%LOCALAPPDATA%\ff6pr-mods`;
also refuses during a BC test install, `BepInEx\bc_testinstall.json`) move folders only, nothing
deleted, refused while the game runs; a mod that isn't installed is reported and nothing moves or
launches. `modswitch/install.sh [--pc|--deck]` makes four Deck library tiles and PC Desktop/Start
menu shortcuts: "FINAL FANTASY VI - Worlds Collide", "... - Brave New World", "... - Beyond Chaos",
"... - T-Edition" (art: `make_art.py`, FF6's art with the mod's name). `tools/deck_push.sh
bnw|wc|bc|ted` copies one mod as it is installed in the PC game (active, shelved, or held by a BC
test; what the test runner last built and checked) to the Deck, into the state it has there (its
active copy if active, else its shelf copy; a new mod goes on the shelf): plugin folder, Magicite
folder, `BepInEx/<Mod>` data except seeds, its cfg where the Deck has none (never BC's: it holds
this PC's ProjectDir), seeds the Deck lacks (one way, not `*-test`, state.json untouched). No build,
the PC only read, the Deck's active mod unchanged, refused while FF6 runs on the Deck; files are
staged on the Deck (`BepInEx/deck_push-staging/<Mod>`) and swapped in only if the PC copy didn't
change meanwhile. Last line `deck_push: <mod> done (<n> files, plugin md5 <first 8>)` or
`deck_push: <mod> FAILED: <why>` (exit 1). BC pushes only once its player bundle exists
(`BepInEx/BeyondChaos/generator/bundle.json`) and T-Edition once its player build does
(`BepInEx/TEdition/build.json`, the file it writes last); until then both say "... has no
installable build yet". The PC's switcher applies the same rule (2026-11-20, coordinator): its
BC and T-Edition shortcuts change nothing until those files exist, since the PC's copies before
that are the test runner's test installs, which must never stay active.

**Installs skip work already done (2026-11-20).** Every PC install used to redo everything: a WC
install took 3.5+ min even with nothing changed (`wc_bundle.py` rebuilt the 72 MB generator bundle,
130-520 s depending on load, then robocopy walked the unchanged trees: generator 6.2 s, baseline
2.0 s, Magicite 2.4 s), and switching back to BNW mirrored its Magicite folder again (2.3 s of
robocopy plus a `dotnet build-server shutdown`). Now the PC side of deploy.sh (`--pc`, and the PC
half of a plain run; `--deck` / `--full` are unchanged) does only what's needed:
- `tools/wc_bundle.py` builds only when something it's made from changed. A build runs under an
  audit hook and `sys.monitoring` and records in `build/WorldsCollide/bundle_inputs.json` every
  file it read or copied (size, time), every folder it listed (time, listing), every function that
  ran (in its own Python and in the bundle's Python making the vanilla cache) and a listing of what
  it made. The next run checks that in ~1 s. Nothing changed: "bundle: up to date". A file it only
  copies (WC's own files, most of the ~65 tool scripts the generator ships), or a module it ran whose
  change is only in functions or methods that didn't run (port_ai, port_procs, the snes_* and other
  porter modules other sessions edit all day: the build imports most of them for a constant): that
  file is copied again with its bytecode, and scripts the generator now imports are copied in ("up
  to date after copying N changed files again", 1-2 s). Anything else (pr/vanilla, the ROM, the
  presets, code that ran, module-level code, class bodies, a function's arguments): a full build.
  A change in a module only the vanilla cache ran makes the cache again (~20 s) and keeps the old
  one if it comes out the same. `--status` says which it would do, `--force` builds. An input saved
  while a build runs marks the record stale (the next run builds again). `--check` no longer
  deletes the bundle's precompiled bytecode (it removed every `__pycache__`, not just its own).
- `wc_bundle.py --install DATA_DIR MAGICITE_DIR` (deploy.sh): generator/ and baseline/ ->
  `BepInEx/WorldsCollide`, the Magicite folder -> `Magicite/WorldsCollide`, each compared with
  what the build made (an os.scandir listing: names, sizes, times; the copies keep the times) and
  only the differing files copied or deleted (robocopy /MIR if that fails). A seed a test applied
  in `Magicite/WorldsCollide` is still put back to the baseline (those files differ).
- `tools/quick_mirror.py SRC DST` (kit tool): the same for BNW's Magicite folder.
- deploy.sh: `wc_flags.json` is rewritten only when the export differs; `dotnet build-server
  shutdown` runs only when deploy.sh built something (not with `DEPLOY_NO_BUILD=1`); a switch's
  folder moves retry for ~10 s and, if one still can't move, the switch puts back what it moved
  and stops ("can't move ... switch undone, nothing changed", exit 1) instead of leaving half a
  switch (wc-4's install at 17:04: "mv: cannot move .../Magicite/BraveNewWorld: Permission
  denied" half a minute after another run's game closed, with BNW's plugin already shelved; the
  same code runs on the Deck); a PC install waits (up to 15 min, then refuses) while a port holds
  `mods/<Mod>.porting` (tools/port.py) or, for BNW, `build/bnw_port.lock`.
Measured on this PC's game, `DEPLOY_NO_BUILD=1 deploy.sh --<mod> --pc` as the test runner runs it
(18:05): BNW reinstalled with nothing changed 2.7 s before, 0.9 s now; WC installed over BNW 10.1 s
(the game's WC copy was an older bundle with a seed applied: 2,870 files copied; 4 changed tool
scripts copied into the bundle first); WC again 3.8 s (1 tool script changed meanwhile); WC -> BNW
1.0-1.2 s; BNW -> WC with nothing changed 3.1 s. A full bundle build, when one is needed, is
still 130-520 s (`--status` tells beforehand). The test runner's side (runner-core, from the
batch after bnw-11): after deploy.sh it copies the batch's own pre-flight build in (DLL + BNW's
data files / WC's wc_flags.json, md5 checked) instead of a second `-p:Deploy=true` build (11-20 s),
and waits 3 s instead of 20 for `mods/BraveNewWorld` to settle.
