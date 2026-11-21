"""SNES FF6 event scripts -> Pixel Remaster event scripts (kit): learn how the two games' scenes
correspond, translate an SNES event command by command, compare a translation with the PR's own.

Built on tools/snes_events.py (the decoder) and tools/pr_script.py (the PR's script format).

Learning (`learn`, writes data/snes_event_maps.json): every SNES entry point's scene (what it can
reach through branches and calls) is paired with the PR scripts that show the same dialogue
(build/dialog/dialog_map.json: SNES dialogue -> PR story keys, through the Japanese); over all
pairs, each SNES event bit is tied to the PR story flag set (or tested) in the same scenes, each
SNES song to the PR BGM played there, each sound to the PR sound effect. Ties need agreement over
several scenes (a pair of one-off flags in one scene counts too, marked "single").

Translation (`Translator`): one PR script from an SNES entry point, in pr_script's format:
  * flow: the SNES code is a graph; each instruction becomes PR ops at a label L_<address> when
    something jumps there; conditionals (C0-CF: all/any of up to 8 bits) become Branch chains on
    the mapped flags; calls (B2/B3) become Call into a block whose returns (FE) are Return; a return
    in the event's own body is Exit; B6's choices become Msg + Select + Branch MessageSelection;
    repeats (B0/B1) are unrolled;
  * dialogue: a translator-provided key per SNES dialogue (vanilla: the PR's own key from
    dialog_map; a mod: new keys from its text, e.g. tools/ted_dialog.py);
  * flags: data/snes_event_maps.json's ties, else a flag of the mod's own (an allocation table
    the caller passes: `FlagAlloc`, kept in data/snes_event_alloc_<mod>.json so numbers stay put);
  * battles (4D/4C): the pack's first formation -> the PR party (idmap.party); the code after a
    battle goes on in a script of its own (the PR's Encount names the script to run after it);
  * gifts: items (idmap.item_content), gil, espers (idmap.esper_content);
  * party: 3F join/leave -> the PR's SysCalls (メンバー加入/離脱：<name>), 98 name menu, 99 party menu;
  * maps (6A/6B): snes_maps.to_pr (SNES map + tile -> PR map + tile) -> ChangeMap with a PR
    arrival point, or SysCall stubs when the place has no PR map yet (ted_maps.json, later);
  * objects (00-34 queues, 41/42 show/hide): puppets (SetPuppet/ExecPuppet) whose actions are
    Move/LookAt/SetPos/Wait/Show/Hide; a queue without the wait bit is an asynchronous Call
    (Call [t, 1]) and the next obj_wait a FinishPuppet;
  * waits, fades, shakes, flashes, songs, sounds.
Anything not translatable becomes `SysCall "SNES:<name> <hex>"` (the bytes in its comment) and is
counted per command class in `report`. Nothing here runs the game.

  .venv/Scripts/python tools/event_translate.py learn                 (writes data/snes_event_maps.json)
  .venv/Scripts/python tools/event_translate.py pairs [n]             (paired scenes, best first)
  .venv/Scripts/python tools/event_translate.py translate CC/B148 [us] (prints the PR script;
                         a mod's ROM: translate <address> ted --module ted_events)
  .venv/Scripts/python tools/event_translate.py compare CC/B148        (signature vs the PR's scene)
"""
import collections
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import kitpath  # noqa: E402,F401  (a mod repository's: the kit on the path; the kit has none)
except ImportError:
    pass
import prdata as P  # noqa: E402
import pr_script as S  # noqa: E402
import snes_events as E  # noqa: E402

DATA = os.path.join(P.ROOT, "data")
MAPS_FILE = os.path.join(DATA, "snes_event_maps.json")
OVERRIDES_FILE = os.path.join(DATA, "snes_event_overrides.json")
DIALOG_MAP = os.path.join(P.ROOT, "build", "dialog", "dialog_map.json")
EQ = "＝"
JOIN = "メンバー加入："        # メンバー加入：
LEAVE = "メンバー離脱："       # メンバー離脱：
NAMING = "名前入力："                  # 名前入力：
RESERVE = "控えに移動："                # 控えに移動：
PARTY_MENU = "パーティ編成：{}パーティ"   # パーティ編成：Nパーティ
# the PR's names in its SysCalls, by SNES character id (Terra ... Umaro, then the guests)
PR_NAMES = ["ティナ", "ロック", "カイエン", "シャドウ",
            "エドガー", "マッシュ", "セリス", "ストラゴス",
            "リルム", "セッツァー", "モグ", "ガウ",
            "ゴゴ", "ウーマロ", "ビックス", "ウェッジ",
            "バナン", "レオ"]
FLAG_CATS = ("ScenarioFlag1", "ScenarioFlag2", "ScenarioFlag3", "ScenarioFlag4",
             "TreasureFlag1", "TreasureFlag2", "TreasureFlag3", "TreasureFlag4")
PARTY_SLOT = -1001          # PR entity of party slot 1 (-1001..-1004)
# SNES character -> the PR's id in party ops (OrganizePartySlot): the 14 playable ones SNES + 1, the guests Banon (0E)
# and Leo (0F) 31 and 32 (vanilla's paired scenes: CC/9F6D 3C 00 0E 0F FF = [1, 1, 31, 32, -2, 0])
PARTY_IDS = {**{c: c + 1 for c in range(14)}, 0x0E: 31, 0x0F: 32}
# SNES event bits that aren't story flags: the case word (1A0-1AF: party checks, word compares,
# loaded by DE-E4/EB), bits the field code keeps (1B0-1CF: character availability, menus), and the
# scratch bits 1F0-1FF, cleared on every map load (C0/BFB2): those are the PR's map-local variables
SCRATCH = range(0x1F0, 0x200)
ENGINE_BITS = range(0x1A0, 0x1D0)
# engine bits whose value is known when the party walks into a map, so Translator.cond decides tests of them:
#   1B6 clear: set by the field code when an event loads the map (vanilla's 54 entrance events skip their NPCs' walking
#       on it; no event sets or clears it);
#   1CC clear: an event's song carries over the map load (set and cleared by the scene that plays it)
STATIC_ENGINE_BITS = {0x1B6: False, 0x1CC: False}
GIL_SHORT = 0x1BE                 # set by 85 (take gil) when the party has too little: the PR's RemoveGil
                                  # leaves 1 (paid) or 0 in MapLocalVariable 0, and its scripts branch on that
CHAR_BITS = range(0x2E0, 0x300)   # 2E0 + c: c recruited (shops, items), 2F0 + c: c available (party menus)
TINTS = {0: (0, 0, 0), 1: (255, 0, 0), 2: (0, 255, 0), 3: (255, 255, 0), 4: (0, 0, 255), 5: (255, 0, 255),
         6: (0, 255, 255), 7: (255, 255, 255)}
FRAME = 1 / 60
WORLD = {0: "Map_10010", 1: "Map_10020"}   # the World of Balance / Ruin
# the PR's instructions whose iValues hold jump targets (mnemonic indices), by operand position:
# every vanilla use of these lands on a labelled Nop (checked over all 2846 vanilla scripts)
JUMP_OPERANDS = {"Jump": (0,), "Call": (0,), "Branch": (2,), "SetPuppet": (2,), "BranchByCharacter": (3,),
                 "BranchByPlayerDirection": (0, 1, 2, 3), "BranchByLeader": (1,), "BranchByOriginalAudioType": (0,),
                 "BranchByNumOfMember": (2,), "BranchByEntityActive": (2,)}
NL = chr(10)


# --- the PR's scripts ------------------------------------------------------------------------------
def _json(path):
    return read_json(path)


def pr_summary(sc):
    """What a PR script does, in order: msgs, flag sets/resets/tests, music, sounds, battles, map
    changes, gifts, joins/leaves."""
    out = collections.defaultdict(list)
    for m in sc.get("Mnemonics", []):
        o = m.get("operands") or {}
        iv, sv = o.get("iValues") or [], o.get("sValues") or []
        op = m["mnemonic"]
        if op == "Msg" and sv and sv[0]:
            out["msgs"].append(sv[0])
        elif op == "Select":
            out["msgs"].extend(s for s in sv if s)
        elif op in ("SetFlag", "ResetFlag") and sv and sv[0] in FLAG_CATS:
            out["sets" if op == "SetFlag" else "resets"].append((sv[0], iv[0]))
        elif op == "Branch" and sv and sv[0] in FLAG_CATS:
            out["tests"].append((sv[0], iv[0]))
        elif op == "PlayBGM":
            out["bgm"].append(iv[0])
        elif op == "PlaySE":
            out["se"].append(iv[0])
        elif op in ("Encount", "EncountBoss"):
            out["battles"].append(iv[0])
        elif op == "ChangeMap":
            out["maps"].append(iv[0])
            out["arrivals"].append((iv[0], iv[1]))
        elif op == "GetItem":
            out["items"].append(iv[0])
        elif op == "SysCall" and sv and sv[0].startswith((JOIN, LEAVE)):
            out["party"].append(sv[0])
    return dict(out)


_pr_index = None


def pr_index():
    """{script name: summary} over every vanilla script (names lower-case; first file of a name)."""
    global _pr_index
    if _pr_index is None:
        import vcache

        def build():
            out = {}
            for rel in S._script_files():
                f = os.path.join(P.VANILLA, rel)
                try:
                    sc = _json(f)
                except (ValueError, UnicodeDecodeError):
                    continue
                name = os.path.splitext(os.path.basename(f))[0].lower()
                out.setdefault(name, pr_summary(sc))
            return out
        _pr_index = vcache.cached("event_translate_pr_index_v2", build)
        for summ in _pr_index.values():         # JSON made the (category, index) pairs lists
            for k in ("sets", "resets", "tests", "arrivals"):
                if k in summ:
                    summ[k] = [tuple(x) for x in summ[k]]
    return _pr_index


def key_scripts():
    """{PR story key: [script names that show it]}."""
    out = collections.defaultdict(list)
    for name, summ in pr_index().items():
        for k in summ.get("msgs", []):
            if name not in out[k]:
                out[k].append(name)
    return out


def dialog_keys():
    """{SNES dialogue: [PR story keys]} (dialog_map's pairs, in key order)."""
    m = _json(DIALOG_MAP)
    out = collections.defaultdict(list)
    for k, v in sorted(m.items()):
        out[v[0]].append(k)
    return out


def group(name):
    """A PR script's scene group: sc_e_0089_1 -> sc_e_0089 (the scene's scripts share it)."""
    parts = name.split("_")
    if len(parts) >= 3 and parts[0] == "sc" and parts[1] == "e":
        return "_".join(parts[:3])
    return name


# --- SNES scenes -----------------------------------------------------------------------------------
def scene(prog, entry, mode="field", follow_calls=True):
    """The instructions an entry point can reach (branches, choices, calls), in address order."""
    seen, todo, out = set(), [(entry, mode)], []
    while todo:
        off, md = todo.pop()
        while (off, md) not in seen:
            seen.add((off, md))
            ins = prog.code.get((off, md))
            if ins is None:
                break
            out.append(ins)
            for kind, t in ins.targets:
                if kind == "call" and not follow_calls:
                    continue
                if kind != "timer":
                    todo.append((t, md))
            if ins.flow in ("end", "choice") or off in prog.dead or off in prog.map_ends:
                break
            off += ins.size
            md = ins.next_mode if ins.next_mode in ("field", "vehicle") else md
    return sorted(out, key=lambda i: i.off)


def snes_summary(instrs, rom=None):
    out = collections.defaultdict(list)
    for ins in instrs:
        a = ins.args
        if "dlg" in a:
            out["dialogs"].append(E.dialog_key(ins))
        if ins.name in ("bit_set", "bit_clear", "v_bit_set", "v_bit_clear"):
            b = a["bit"][0]
            if b not in SCRATCH and b not in ENGINE_BITS and b not in CHAR_BITS:
                out["sets" if a["bit"][1] else "resets"].append(b)
        if "bits" in a:
            out["tests"].extend(b for b, _ in a["bits"] if b not in SCRATCH and b not in ENGINE_BITS and b not in CHAR_BITS)
        if ins.name in ("song", "song_volume", "song_fade_in"):
            out["songs"].append(a["song"])
        if ins.name == "sound":
            out["sounds"].append(a["sound"])
        if ins.name in ("battle", "battle_nogameover", "v_battle"):
            out["battles"].append(a["pack"])
        if ins.name in ("map", "map_fade", "v_map", "v_map2"):
            out["maps"].append(a["map"])
            out["arrivals"].append((a["map"], a["x"], a["y"]))
        if ins.name == "item_add":
            out["items"].append(a["item"])
        if ins.name == "esper_add":
            out["espers"].append(a["esper"])
        if ins.name == "gil_add":
            out["gil"].append(a["gil"])
        if ins.name == "party_char":
            out["party"].append((a["char"], a["party"]))
    return dict(out)


def pairs(prog=None, min_shared=1):
    """[(entry address, kind, map, PR scene group, shared dialogues, SNES dialogues, PR scripts)]:
    each SNES entry point's scene paired with the PR scene group showing most of its dialogue."""
    prog = prog or E.Program(E.load("us")).walk_all()
    dk, ks = dialog_keys(), key_scripts()
    out, done = [], set()
    for off, kind, m, det in prog.entries:
        if off in done or (off, "field") not in prog.code:
            continue
        done.add(off)
        ins = scene(prog, off)
        dl = [d for d in snes_summary(ins).get("dialogs", []) if isinstance(d, int)]
        if not dl:
            continue
        votes = collections.Counter()
        scripts = collections.defaultdict(set)
        for d in set(dl):
            gs = set()
            for k in dk.get(d, []):
                for sname in ks.get(k, []):
                    gs.add(group(sname))
                    scripts[group(sname)].add(sname)
            for g in gs:
                votes[g] += 1
        if not votes:
            continue
        g, n = min(votes.items(), key=lambda kv: (-kv[1], kv[0]))   # deterministic on ties
        if n >= min_shared:
            out.append((off, kind, m, g, n, len(set(dl)), sorted(scripts[g])))
    out.sort(key=lambda r: (-r[4], r[0]))
    return out


def group_summary(g, scripts=None):
    """The union of a PR scene group's scripts' summaries (sc_e_0089, sc_e_0089_1...)."""
    idx = pr_index()
    names = scripts or [n for n in idx if group(n) == g]
    out = collections.defaultdict(list)
    for n in names:
        for k, v in idx.get(n, {}).items():
            out[k].extend(v)
    return dict(out)


# --- learning --------------------------------------------------------------------------------------
def _associate(pairs_, a_key, b_key, min_support=2):
    """Tie each SNES value to the PR value seen with it in the most paired scenes. -> {a: [b,
    together, a's scenes, b's scenes, how]}."""
    co = collections.defaultdict(collections.Counter)
    na, nb = collections.Counter(), collections.Counter()
    for sn, pr in pairs_:
        A, B = sorted(set(sn.get(a_key, [])), key=repr), sorted(set(pr.get(b_key, [])), key=repr)
        for a in A:
            na[a] += 1
            for b in B:
                co[a][b] += 1
        for b in B:
            nb[b] += 1
    out = {}
    for a, c in co.items():
        ranked = sorted(c.items(), key=lambda kv: (-kv[1] / (na[a] + nb[kv[0]] - kv[1]), -kv[1], repr(kv[0])))
        b, n = ranked[0]
        jacc = n / (na[a] + nb[b] - n)
        if n >= min_support and jacc >= 0.34:
            out[a] = [b, n, na[a], nb[b], "votes"]
        elif n == na[a] == nb[b] == 1 and len(c) == 1:
            out[a] = [b, n, na[a], nb[b], "single"]
    return out


def _associate_seq(pairs_, a_key, b_key):
    """Songs and sounds: several SNES values may share one PR value, and a PR sound may be in many
    scenes. A scene whose SNES and PR lists have the same length votes position by position (2),
    else every PR value of the scene gets a share. Tie = the value with most of a's votes (>= half)."""
    votes = collections.defaultdict(collections.Counter)
    total = collections.Counter()
    for sn, pr in pairs_:
        A, B = sn.get(a_key, []), pr.get(b_key, [])
        if not A or not B:
            continue
        if len(A) == len(B):
            for a, b in zip(A, B):
                votes[a][b] += 2
                total[a] += 2
        else:
            for a in sorted(set(A)):
                for b in sorted(set(B)):
                    votes[a][b] += 1 / len(set(B))
                total[a] += 1
    out = {}
    for a, c in votes.items():
        b, v = min(c.items(), key=lambda kv: (-kv[1], kv[0]))
        if v >= 0.5 * total[a] and v >= 1:
            out[a] = [b, round(v, 2), total[a], "votes" if total[a] >= 2 else "single"]
    return out


def learn(write=True):
    """Learns SNES -> PR ties over every paired scene; writes data/snes_event_maps.json."""
    prog = E.Program(E.load("us")).walk_all()
    ps = pairs(prog)
    data = []
    for off, kind, m, g, n, nd, scripts in ps:
        if n < 1:
            continue
        sn = snes_summary(scene(prog, off))
        pr = group_summary(g)
        data.append((sn, pr))
    # flags: sets with sets, resets with resets, tests with tests; a tie from sets wins
    flag = {}
    for a_key, b_key, how in (("sets", "sets", "set"), ("resets", "resets", "reset"), ("tests", "tests", "test")):
        for bit, v in _associate(data, a_key, b_key).items():
            if bit not in flag:
                flag[bit] = [v[0][0], v[0][1], v[1], v[2], v[3], f"{how}-{v[4]}"]
    # second pass: in a pair whose still-untied SNES sets and PR sets are as many, tie them in order
    # (both games set a scene's flags in the scene's order); a tie needs every such pair to agree
    tied_pr = {(v[0], v[1]) for v in flag.values()}
    votes = collections.defaultdict(collections.Counter)
    for sn, pr in data:
        a = [b for b in dict.fromkeys(sn.get("sets", [])) if b not in flag]
        b = [f for f in dict.fromkeys(pr.get("sets", [])) if f not in tied_pr]
        if a and len(a) == len(b):
            for x, y in zip(a, b):
                votes[x][y] += 1
    for bit, c in sorted(votes.items()):
        f, n = min(c.items(), key=lambda kv: (-kv[1], kv[0]))
        if n == sum(c.values()) and f not in tied_pr:
            flag[bit] = [f[0], f[1], n, n, n, "set-order"]
            tied_pr.add(f)
    bgm = _associate_seq(data, "songs", "bgm")
    se = _associate_seq(data, "sounds", "se")
    # map loads: each SNES arrival (map, x, y) -> the PR ChangeMap (map, point) in the same place of
    # the paired scene; a SNES map -> the PR map most of its arrivals went to
    arr = {k: v for k, v in _associate_seq(data, "arrivals", "arrivals").items() if v[3] == "votes"}  # 2+ scenes
    by_map = collections.defaultdict(collections.Counter)
    for (m, x, y), v in arr.items():
        by_map[m][v[0][0]] += 1
    map_ties = {m: [min(c.items(), key=lambda kv: (-kv[1], kv[0]))[0], sum(c.values())] for m, c in by_map.items()}
    out = {"_doc": "SNES -> PR ties learned by tools/event_translate.py learn from paired vanilla scenes "
                   "(SNES event bit -> [PR flag category, index, scenes together, SNES scenes, PR scenes, how]; "
                   "song -> [PR bgm id, ...]; sound -> [PR se id, ...]; arrival 'map,x,y' -> [[PR map id, point], "
                   "votes, scenes, how]; SNES map -> [PR map id, arrivals])",
           "pairs": len(data),
           "flags": {f"{b:03X}": v for b, v in sorted(flag.items())},
           "bgm": {str(k): v for k, v in sorted(bgm.items())},
           "se": {str(k): v for k, v in sorted(se.items())},
           "arrivals": {"%d,%d,%d" % k: [list(v[0])] + v[1:] for k, v in sorted(arr.items())},
           "maps": {str(k): v for k, v in sorted(map_ties.items())}}
    if write:
        write_json(MAPS_FILE, out, ensure_ascii=False, indent=0)
    return out


_maps = None


def read_json(path, tries=10):
    """json.load of a file another tool or port may be replacing (write_json): Windows refuses the open
    for the instant of a replace (PermissionError), so that is retried 10 times, 50 ms apart."""
    import time
    for attempt in range(tries):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(0.05)


def write_json(path, obj, **dump_args):
    """json.dump to a temporary file next to `path`, then os.replace() it over `path`: a tool or port
    reading the file meanwhile sees the old whole file or the new one, never a half-written one.
    (Windows refuses the replace while another process has the file open: retried for ~2 s.)"""
    import time
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, **dump_args)
    for attempt in range(40):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 39:
                os.remove(tmp)
                raise
            time.sleep(0.05)


def song_bgm(song):
    """An SNES song id -> the PR's bgm id: the kit's song table (snes_songs.FF6_SONG_PR_BGM, checked
    by hand), else a tie learned from paired scenes; None: no PR track (jingles, a mod's new songs)."""
    import snes_songs
    b = snes_songs.FF6_SONG_PR_BGM.get(song)
    return b if b is not None else maps()["bgm"].get(song)


def maps():
    global _maps
    if _maps is None:
        if os.path.exists(MAPS_FILE):
            d = _json(MAPS_FILE)
        else:
            d = {"flags": {}, "bgm": {}, "se": {}}
        _maps = {"flags": {int(k, 16): (v[0], v[1]) for k, v in d["flags"].items()},
                 "bgm": {int(k): v[0] for k, v in d["bgm"].items()},
                 "se": {int(k): v[0] for k, v in d["se"].items()},
                 "arrivals": {tuple(int(x) for x in k.split(",")): tuple(v[0]) for k, v in d.get("arrivals", {}).items()},
                 "maps": {int(k): v[0] for k, v in d.get("maps", {}).items()}}
        if os.path.exists(OVERRIDES_FILE):          # ties confirmed by hand win
            o = _json(OVERRIDES_FILE)
            for k, v in o.get("flags", {}).items():
                _maps["flags"][int(k, 16)] = (v[0], v[1])
    return _maps


# --- flags of a mod's own --------------------------------------------------------------------------
class FlagAlloc:
    """PR flags for SNES bits vanilla's PR has no tie for (a mod's new story bits, NPC bits on its
    own maps): handed out in order from a free range and kept in a JSON file, so a bit keeps its
    flag from one build to the next. Default range: ScenarioFlag4 0-131, which no vanilla script
    touches (Worlds Collide uses the same range for its own flags: the two mods never run together)."""

    def __init__(self, path, category="ScenarioFlag4", first=0, last=131):
        assert category.startswith("ScenarioFlag"), "treasure flags are the chests' (T-Edition's new ones: 300-369)"
        self.path, self.category, self.first, self.last = path, category, first, last
        self.table = self._disk()

    def _disk(self):
        if self.path and os.path.exists(self.path):
            return {int(k, 16): tuple(v) for k, v in read_json(self.path).items()}
        return {}

    def get(self, bit):
        if bit not in self.table:
            # another session may share the file (T-Edition's events and EX's): take its entries first
            for k, v in self._disk().items():
                self.table.setdefault(k, v)
        if bit not in self.table:
            used = {v[1] for v in self.table.values() if v[0] == self.category}
            free = next(i for i in range(self.first, self.last + 1) if i not in used)
            self.table[bit] = (self.category, free)
        return self.table[bit]

    def reserve(self, bits):
        """Hands out flags for `bits` now, in this order (bits other tools read by flag: a mod's
        achievement or boss bits), and saves."""
        for b in bits:
            self.get(b)
        self.save()
        return {b: self.table[b] for b in bits}

    def save(self):
        """Writes the table merged with what's on disk now (entries another session added are kept;
        the same bit on two flags, or two bits on one flag, is an error)."""
        if not self.path:
            return
        disk = self._disk()
        for k, v in disk.items():
            if k in self.table and self.table[k] != v:
                raise ValueError(f"{self.path}: bit {k:03X} is {v} on disk but {self.table[k]} here")
            self.table.setdefault(k, v)
        owners = {}
        for k, v in self.table.items():
            if v in owners:
                raise ValueError(f"{self.path}: {v} given to bits {owners[v]:03X} and {k:03X}")
            owners[v] = k
        write_json(self.path, {f"{k:03X}": list(v) for k, v in sorted(self.table.items())}, indent=0)


# --- translation -----------------------------------------------------------------------------------
def op(mnemonic, i=(), s=(), r=(), label="", kind=1, comment=""):
    o = S.op(mnemonic, i=i, s=s, r=r, label=label, kind=kind)
    o["comment"] = comment
    return o


def lab(name, kind=1):
    return S.label(name, kind=kind)


def stub(ins, why=""):
    return op("SysCall", s=[f"SNES:{ins.name}"], comment=f"{E.fmt(ins.off)} {ins.raw.hex(' ').upper()} {why}".strip())


class Translator:
    """One SNES entry point -> one PR script (plus after-battle scripts). Hooks a mod overrides:
    dialog(key) -> (msg key, choice keys), entity(obj) -> PR entity, place(map, x, y)."""

    def __init__(self, rom, name, snes_map=None, alloc=None, dialog=None, prog=None, pr_map=None):
        self.rom, self.name, self.snes_map = rom, name, snes_map
        self.prog = prog or E.Program(rom)
        self.alloc = alloc or FlagAlloc(None)
        self.dialog_hook = dialog
        self.pr_map = pr_map
        self.report = collections.Counter()      # (class, how) -> count
        self.stubs = collections.Counter()       # class -> count of SNES commands left as SysCall stubs
        self.done = collections.Counter()        # class -> count translated
        self.blocks = []                         # [(label, ops)] (segments after Main)
        self.subs = {}                           # SNES call target -> label
        self.puppet_n = 0
        self.after = []                          # [(name, script)] after-battle scripts
        self.pending_wait = False                # an async puppet call not yet finished
        self.joined = set()                      # characters joined in this scene
        self.stub_at = {}                        # SNES address -> (class, command) left as a stub
        self.fallbacks = {}                      # SNES routine -> a PR script to graft in its place
        self.needs_formations = set()            # formations whose battles wait for a PR party
        self.grafted = {}                        # PR script name -> its Main label here
        self.extra_locals, self.extra_anims = [], []
        self._dk = None

    # --- hooks ----------------------------------------------------------------------------------
    def dialog(self, key):
        """SNES dialogue -> (PR message key, [choice keys]); vanilla: the PR's own keys."""
        if self.dialog_hook:
            return self.dialog_hook(key)
        if self._dk is None:
            self._dk = dialog_keys()
        keys = self._dk.get(key, []) if isinstance(key, int) else []
        msg = [k for k in keys if "_c_" not in k]
        cho = [k for k in keys if "_c_" in k]
        return (msg[0] if msg else None), cho

    own_bits = frozenset()   # a mod's bits whose meaning isn't vanilla's: never the learned tie

    def flag(self, bit):
        m = maps()["flags"].get(bit)
        if m and bit not in self.own_bits:
            return m
        return self.alloc.get(bit)

    def entity(self, obj):
        """SNES object -> PR entity: characters 00-0F -> -(id + 1), party slots 31-34 -> -1001..
        -1004, the camera -> None, map NPCs (10 + n) -> the PR entity at the NPC's spot (pr_map)."""
        if obj < 0x10:
            return -(obj + 1)
        if 0x31 <= obj <= 0x34:
            return PARTY_SLOT - (obj - 0x31)
        if obj == 0x30:
            return None
        return self.npc_entity(obj - 0x10)

    layers = None        # the PR entity layer the scene runs with (its NPCs' ids are looked up there first)

    def npc_entity(self, n):
        """SNES NPC n of this map -> the PR entity standing on its spot (within 2 tiles: the PR moved
        a few) in the PR map's entity layers, the scene's layer (`layers`) first, then the others its
        package lists, then entity_default. The PR keeps a room's NPCs per story state (ev_e_* layers,
        chosen by the map script): the same NPC can carry another entity id in each."""
        if self.snes_map is None:
            return None
        det = snes_npcs(self.rom).get((self.snes_map, n))
        if det is None:
            return None
        if self.pr_map is not None:
            room, spot = self.pr_map, self.local(det["x"], det["y"])
        else:                                   # no room given: the one drawn at the NPC's tile
            import snes_maps
            r = snes_maps.to_pr(self.snes_map, det["x"], det["y"])
            if not r:
                return None
            room, spot = r[0], (r[1], r[2])
        best = None
        looks = sprite_assets(self.rom).get(det["sprite"], ())
        for k, (layer, objs) in enumerate(pr_entities(room, self.layers)):
            for name, x, y, eid, asset in objs:
                if not eid or name in NOT_NPCS:
                    continue
                d = abs(x - spot[0]) + abs(y - spot[1])
                # on its spot (the PR moved a few by a tile or two), else the nearest entity in the
                # room that looks like it (the PR asset its SNES sprite became), up to 8 tiles off
                rank = (0, d, k) if d <= 2 else (1, d, k) if asset in looks and d <= 8 else None
                if rank and (best is None or rank < best[0]):
                    best = (rank, eid)
        return best[1] if best else None

    def place(self, m, x, y):
        """SNES map, tile -> (PR map id, PR map name, x, y, point or None) or None: the PR arrival a
        paired vanilla scene used for this very SNES arrival (learned: its point), else the PR room
        snes_maps draws at that tile (the nearest arrival point is picked by the caller), else the PR
        map most of this SNES map's learned arrivals went to (at the SNES tile), else the world maps
        (0 = Map_10010, 1 = Map_10020: SNES and PR world tiles agree)."""
        import snes_maps
        ids, names = map_ids()
        learned = maps()["arrivals"].get((m, x, y))
        if learned and learned[0] in names:
            return learned[0], names[learned[0]], x, y, learned[1]
        r = snes_maps.to_pr(m, x, y)
        if r and r[0] in ids:
            return ids[r[0]], r[0], r[1], r[2], None
        mt = maps()["maps"].get(m)
        if mt in names:
            return mt, names[mt], x, y, None
        if m in WORLD:
            return ids[WORLD[m]], WORLD[m], x, y, None
        return None

    # --- assembly --------------------------------------------------------------------------------
    def translate(self, entry, mode="field", preamble=()):
        """The script; `preamble`: ops to run first (a test entry: flags set, an entity layer)."""
        main = [lab("Main")] + list(preamble)
        main += self.body(entry, mode, sub=False)
        script = self.assemble(self.name, main + [op("Exit")], self.blocks)
        return script

    def assemble(self, name, main, blocks):
        sc = {"SystemFlag": {"SkipInitialize": 0, "KeepPlayerPuppet": 0, "KeepBadStatusVisual": 0, "RidingVehicle": 0},
              "Segments": [], "ScriptLocal": ["なし"], "ScriptLocalValue": [0], "Mnemonics": [],
              "Animations": [], "Name": name, "Title": {"main": "SNES event (event_translate.py)", "sub": ""}}
        if self.extra_locals:                  # a grafted script's local variables (by position)
            names, values = zip(*self.extra_locals)
            sc["ScriptLocal"], sc["ScriptLocalValue"] = list(names), list(values)
        sc["Animations"] = list(self.extra_anims)
        ops = []
        segs = [("Main", main)] + blocks
        for label, block in segs:
            sc["Segments"].append({"Label": label, "EntryPoint": len(ops), "Count": len(block)})
            ops.extend(block)
        names = {}
        for n, o in enumerate(ops):
            if o["mnemonic"] == "Nop" and o["label"]:
                names.setdefault(o["label"], n)
        missing = sorted({v[1:] for o in ops for v in o["operands"]["iValues"] if isinstance(v, str)} - set(names))
        for m in missing:                  # a target no run starts at (shouldn't happen): end there, noted
            self.stubs["flow"] += 1
            self.report[("flow", "stub:missing_target")] += 1
            names[m] = len(ops)
            ops.extend([lab(m), op("SysCall", s=["SNES:missing_target"], comment=m), op("Exit")])
            sc["Segments"].append({"Label": m, "EntryPoint": names[m], "Count": 3})
        for o in ops:
            iv = o["operands"]["iValues"]
            for k, v in enumerate(iv):
                if isinstance(v, str):
                    iv[k] = names[v[1:]]
        sc["Mnemonics"] = ops
        return sc

    def body(self, entry, mode, sub):
        """PR ops for the code reachable from `entry` in one context (an event's body, or a called
        block when `sub`): straight-line runs, each jump target labelled L_<address>."""
        prog = self.prog
        if (entry, mode) not in prog.code:
            prog.walk([(entry, "tile", self.snes_map, None)] if mode == "field" else
                      [(entry, "tile", 0, None)])
        runs, todo, emitted = {}, [(entry, mode)], set()
        targets = self._targets(entry, mode)
        while todo:
            off, md = todo.pop(0)
            if (off, md) in emitted:
                continue
            out = runs[(off, md)] = [lab(f"L_{off:06X}")]
            last = None
            while True:
                if (off, md) in emitted:
                    out.append(op("Jump", i=[f"@L_{off:06X}"]))
                    break
                ins = prog.code.get((off, md))
                if ins is None:
                    out.append(op("SysCall", s=["SNES:not_code"], comment=E.fmt(off)))
                    out.append(op("Exit"))
                    break
                emitted.add((off, md))
                if ((off, md) in targets or off in prog.callers) and out[-1].get("label") != f"L_{off:06X}":
                    out.append(lab(f"L_{off:06X}"))
                self.skip_to = None
                ops, cont = self.instr(ins, sub, last)
                out.extend(ops)
                if self.skip_to is not None:
                    off = self.skip_to
                    continue
                if "dlg" in ins.args:
                    last = ins
                elif ins.cls != "wait" and ins.name != "dialog_close":
                    last = last if ins.name == "obj" else None
                for kind, t in ins.targets:
                    if kind in ("cond", "choice", "switch", "random"):
                        todo.append((t, md))
                if not cont or ins.flow in ("end", "choice") or off in prog.dead or off in prog.map_ends:
                    if off in prog.dead or (off in prog.map_ends and ins.flow != "end"):
                        out.append(op("Exit" if not sub else "Return"))
                    break
                off += ins.size
                nm = ins.next_mode
                md = nm if nm in ("field", "vehicle") else md
        # every run ends in Exit/Return/Jump/a battle, so runs can go in the SNES's address order
        # (the entry's first: Main falls into it), which is how the scene reads
        first = runs.pop((entry, mode))
        return first + [o for k in sorted(runs) for o in runs[k]]

    def _targets(self, entry, mode):
        return {(t, mode) for ins in scene(self.prog, entry, mode, follow_calls=False) for _, t in ins.targets}

    def child(self, name, snes_map, pr_map):
        """A translator for a continuation script (after a battle, on arrival after a warp): the
        same class and hooks (a mod's text, entity layers), its own blocks."""
        t = type(self)(self.rom, name, snes_map, self.alloc, self.dialog_hook, self.prog, pr_map)
        for k, v in vars(self).items():
            if k not in vars(t):           # a subclass's hooks set on the instance (texts, layers...)
                setattr(t, k, v)
        t.joined = self.joined
        return t

    def graft(self, pr_sc, callable_=False):
        """A PR script's code as blocks of this one (labels prefixed G<k>_, jump indices made
        labels again); -> its Main label. `callable_`: its main-level Exits (type 1; a puppet's
        Exit, type 2, ends the puppet) become Return, so Call runs it and comes back. Its local
        variables and animations come along (a script that declares locals of its own can't be
        grafted next to another such)."""
        name = pr_sc["Name"]
        key = (name, callable_)
        if key in self.grafted:
            return self.grafted[key]
        pre = f"G{len(self.grafted)}{'c' if callable_ else ''}_"
        ms = copy.deepcopy(pr_sc["Mnemonics"])
        if callable_:
            for m in ms:
                if m["mnemonic"] == "Exit" and m.get("type", 1) == 1:
                    m["mnemonic"] = "Return"
        for n, m in enumerate(ms):                       # every target becomes a labelled Nop
            for k in JUMP_OPERANDS.get(m["mnemonic"], ()):
                t = m["operands"]["iValues"][k]
                if isinstance(t, int) and 0 <= t < len(ms) and not (ms[t]["mnemonic"] == "Nop" and ms[t]["label"]):
                    raise ValueError(f"{name}[{n}] {m['mnemonic']} -> {t}: not a label")
        for m in ms:
            for k in JUMP_OPERANDS.get(m["mnemonic"], ()):
                iv = m["operands"]["iValues"]
                if isinstance(iv[k], int) and (k > 0 or iv[k] > 0 or m["mnemonic"] in ("Jump", "Call")):
                    iv[k] = "@" + pre + ms[iv[k]]["label"]
            if m["mnemonic"] == "JumpIfSpecificLanguage":
                raise ValueError(f"{name}: JumpIfSpecificLanguage (its operands aren't known)")
        for m in ms:
            if m["label"]:
                m["label"] = pre + m["label"]
        segs = pr_sc["Segments"]
        for sg in segs:
            block = ms[sg["EntryPoint"]:sg["EntryPoint"] + sg["Count"]]
            self.blocks.append((pre + sg["Label"], block))
        locals_ = list(zip(pr_sc.get("ScriptLocal") or [], pr_sc.get("ScriptLocalValue") or []))
        if [x for x in locals_ if x[0] != "なし"]:
            if self.extra_locals and self.extra_locals != locals_:
                raise ValueError(f"{name}: its local variables clash with another grafted script's")
            self.extra_locals = locals_
        self.extra_anims += [a for a in pr_sc.get("Animations") or [] if a not in self.extra_anims]
        self.grafted[key] = pre + segs[0]["Label"]
        return self.grafted[key]

    def sub_label(self, t, mode="field"):
        if t not in self.subs:
            label = f"S_{t:06X}"
            self.subs[t] = label
            block = self.body(t, mode, sub=True)
            # the block keeps its entry's L_ label after the S_ one: code that jumps (not calls) to the routine's
            # start, such as a menu looping back to itself, lands there too (it was a missing target, ending the script)
            self.blocks.append((label, [lab(label)] + block + [op("Return")]))
        return f"@{self.subs[t]}"

    # --- one instruction -------------------------------------------------------------------------
    def instr(self, ins, sub, last):
        """-> (ops, continues): ops for one SNES instruction."""
        a, n = ins.args, ins.name
        cls = ins.cls

        def ok(ops, how="ok"):
            self.done[cls] += 1
            self.report[(cls, how)] += 1
            return ops, True

        if ins.mode == "vehicle":
            return self.vehicle(ins, sub)
        if n == "obj":
            return ok(self.puppet(ins))
        if n in ("obj_show", "obj_hide", "obj_create", "obj_delete"):
            e = self.entity(a["obj"])
            if e is None:
                return self.left(ins, "no PR entity")
            verb = "Show" if n in ("obj_show", "obj_create") else "Hide"
            return ok(self.puppet_ops([e], [[op(verb, kind=2)]]))
        if n == "obj_wait":
            self.pending_wait = False
            return ok([op("FinishPuppet")])
        if n in ("dialog", "dialog_nowait", "dialog2"):
            return ok(self.message(ins))
        if n == "choice":
            return ok(self.choice(ins, last), "choice")
        if n in ("dialog_close", "dialog_keywait"):
            return ok([op("MsgClose")] if n == "dialog_close" else [])
        if n in ("bit_set", "bit_clear") and a["bit"][0] in SCRATCH:
            idx = a["bit"][0] - SCRATCH.start
            cat = "MapLocalVariable" if idx < 8 else "AreaLocalVariable"
            return ok([op("Calc", i=[idx & 7, 1 if a["bit"][1] else 0], s=[cat, "←", "imm"],
                          comment=f"SNES scratch bit {a['bit'][0]:03X}")], "scratch")
        if n in ("bit_set", "bit_clear") and a["bit"][0] in CHAR_BITS:
            return ok(self.char_bit(*a["bit"]), "character")
        if n in ("bit_set", "bit_clear") and a["bit"][0] in ENGINE_BITS and a["bit"][0] not in self.story_engine_bits:
            return self.left(ins, "engine bit")
        if n in ("bit_set", "bit_clear"):
            cat, idx = self.flag(a["bit"][0])
            return ok([op("SetFlag" if a["bit"][1] else "ResetFlag", i=[idx], s=[cat],
                          comment=f"SNES bit {a['bit'][0]:03X}")])
        if 0xC0 <= ins.op <= 0xCF:
            return ok(self.cond(ins))
        if n == "call" and a["event"] in self.fallbacks:
            # a mod's event that ends in vanilla's routine: the PR's own script for it, grafted in
            # (its Exit ends the event, so this is a jump; the SNES's return after the call is moot)
            nxt = self.prog.code.get((ins.off + ins.size, "field"))
            if sub or nxt is None or nxt.flow != "end":
                # mid-script: a callable copy (its Exits Return) so the SNES code after the call goes on
                label = self.graft(self.fallbacks[a["event"]], callable_=True)
                return ok([op("Call", i=[f"@{label}"], comment=f"SNES call {E.fmt(a['event'])}: the PR's own script")],
                          "fallback call")
            label = self.graft(self.fallbacks[a["event"]])
            return ok([op("Jump", i=[f"@{label}"], comment=f"SNES call {E.fmt(a['event'])}: the PR's own script")],
                      "fallback")
        if n == "call" and self.game_over_check(a["event"]):
            # after a battle: "lost -> the game-over scene" (US CA/5EA9, T-Edition CA/5E9F); the PR's
            # Encount ends in its own game over, and its after-battle script only runs on a win
            return ok([], "game over check")
        if n == "call":
            return ok([op("Call", i=[self.sub_label(a["event"])], comment=f"SNES call {E.fmt(a['event'])}")])
        if n == "call_times":
            t = self.sub_label(a["event"])
            return ok([op("Call", i=[t]) for _ in range(a["count"])])
        if n in ("return", "end"):
            return ok([op("Return" if sub else "Exit")])
        if n == "repeat":
            return self.repeat(ins, sub)
        if n == "repeat_end":
            return ok([], "repeat end")
        if cls == "wait":
            secs = {"wait_15": 15, "wait_30": 30, "wait_45": 45, "wait_60": 60, "wait_120": 120}.get(n)
            if secs is None:
                secs = a.get("frames", 0) if n == "wait_frames" else a.get("quarters", 0) * 15
            return ok([op("Wait", r=[round(secs * FRAME, 3)])])
        if n in ("fade_in", "fade_out", "fade_in_speed", "fade_out_speed"):
            speed = a.get("speed", 4)
            secs = round(min(2.0, max(0.2, 256 / max(speed, 1) / 60)), 2) if "speed" in a else 0.7
            return ok([op("FadeIn" if "in" in n else "FadeOut", i=[0, 0, 0, 255], r=[secs])])
        if n == "fade_wait":
            return ok([])
        if n == "shake":
            return ok([op("Shake", i=[1 if a["mode"] & 0x03 else 0, 1])])
        if n == "flash":
            return ok([op("Flash", i=[255, 255, 255, 255], r=[0.2])])
        if n in ("song", "song_volume", "song_fade_in") or n in self.song_commands:
            song = a["song"] & 0x7F if n == "song" else a["song"]    # F0: bit 7 picks a play mode
            b = self.song_bgm(song, n)
            if b is None:
                return self.left(ins, "song not tied")
            return ok([op("PlayBGM", i=[b, 1], comment=f"SNES song {song}")])
        if n == "song_wait":                   # FA: wait for a jingle to end (PR scripts don't)
            return ok([], "song wait")
        if n == "song_resume":                 # F3: back to the song a jingle interrupted
            return ok([op("ReplayBgm")])
        if n == "song_fade_out":
            return ok([op("StopBGM", r=[0.7])])
        if n == "sound":
            se = maps()["se"].get(a["sound"])
            if se is None:
                return self.left(ins, "sound not tied")
            return ok([op("PlaySE", i=[se, 1], comment=f"SNES sound {a['sound']:02X}")])
        if n in ("battle", "battle_nogameover"):
            return self.battle(ins, sub)
        if n in ("item_add", "item_remove"):
            import idmap
            try:
                cid = idmap.item_content(a["item"])
            except KeyError:                       # a mod's new item: its row is the porter's to make
                cid = 0
            if not cid:
                return self.left(ins, "no PR item")
            return ok([op("GetItem" if n == "item_add" else "RemoveItem", i=[cid, 1])])
        if n == "esper_add":
            import idmap
            if a["esper"] >= 0x36 and idmap.esper_content(a["esper"] - 0x36):
                return ok([op("GetItem", i=[idmap.esper_content(a["esper"] - 0x36), 1])])
            return self.left(ins, "esper")
        if n == "gil_remove":
            return ok([op("RemoveGil", i=[a["gil"]])])
        if n == "party_char":
            # 3F puts a character in party n (1-3) or out of the parties (0): the PR's join SysCall
            # (from the recruit bits) already puts a new member in; out of the parties = reserve
            c = a["char"]
            if a["party"]:
                return ok([], "party slot")
            if c >= 14:
                return ok([], "guest out")
            return ok([op("SysCall", s=[RESERVE + PR_NAMES[c]], comment=f"SNES 3F {c:02X} 00")])
        if n in ("tint_bg", "tint_sprites", "tint_bg_range", "tint_sprite_range", "color_add", "color_sub",
                 "color_range"):
            v = a.get("tint", a.get("v", a.get("color", 0)))
            r, g, b = TINTS[v >> 5 & 7]
            alpha = min(255, 40 + (v & 0x1F) * 7)
            return ok([op("ColorFade", i=[r, g, b, alpha], r=[0.35], comment=f"SNES {n} {v:02X}")], "approx")
        if n == "colors_reset":
            return ok([op("ColorFade", r=[0.35])], "approx")
        if n == "name_menu" and a["char"] < len(PR_NAMES):
            return ok([op("SysCall", s=[NAMING + PR_NAMES[a["char"]]])])
        if n == "party_set" and all(a[k] in PARTY_IDS or a[k] == 0xFF for k in ("c1", "c2", "c3", "c4")):
            # 3C c1-c4: the party is these characters (FF none) -> the PR's OrganizePartySlot [party 1, four members
            # (PARTY_IDS, -2 none), 0], its form in vanilla's paired scenes (CA/9FBF 3C 01 09 FF FF = [1, 2, 10, -2, -2, 0])
            ids = [PARTY_IDS[a[k]] if a[k] != 0xFF else -2 for k in ("c1", "c2", "c3", "c4")]
            return ok([op("OrganizePartySlot", i=[1] + ids + [0],
                          comment="SNES 3C %s" % " ".join("%02X" % a[k] for k in ("c1", "c2", "c3", "c4")))])
        if n == "party_menu" and 1 <= a["parties"] & 0x7F <= 3:
            # bit 7 of the count is a mode bit (vanilla's own 99 81/82/83: the WoR party change CA/CB95, the final
            # dungeon's split): the PR's party menu for that many parties either way
            return ok([op("SysCall", s=[PARTY_MENU.format("１２３"[(a["parties"] & 0x7F) - 1])],
                          comment="SNES 99 %02X" % a["parties"] if a["parties"] > 0x80 else "")])
        if n == "shop":
            ops = self.shop_ops(a["shop"])
            if ops is None:
                return self.left(ins, f"shop {a['shop']}")
            return ok(ops)
        if n in ("hp_restore", "mp_restore"):
            return ok([op("RecoveryHP" if n == "hp_restore" else "RecoveryMP", i=[9999, 1, 1] if n == "hp_restore" else [9999, 1, 1, 1])])
        if n in ("map", "map_fade"):
            return self.warp(ins, sub)
        if n in ("screen_hold", "screen_free", "player_control", "objs_refresh", "party_formation", "obj_pass_on",
                 "obj_pass_off", "party_leader", "tiles_refresh", "colors_reset", "nop", "case_party",
                 "obj_touch_on", "obj_touch_off"):
            return ok([], "no-op")
        return self.left(ins)

    def left(self, ins, why=""):
        """An SNES command the translator doesn't do yet: a SysCall stub, counted."""
        self.stubs[ins.cls] += 1
        self.report[(ins.cls, "stub:" + ins.name)] += 1
        self.stub_at[ins.off] = (ins.cls, ins.name)
        return [stub(ins, why)], True

    # --- pieces ----------------------------------------------------------------------------------
    def char_bit(self, bit, value):
        """2E0 + c set: c recruited -> the PR's join; 2F0 + c set: c available again (a join unless
        recruited in the same scene); either cleared: c leaves."""
        c = bit & 0xF
        if c >= len(PR_NAMES):
            return []
        if value:
            if c in self.joined:
                return []
            self.joined.add(c)
            return [op("SysCall", s=[JOIN + PR_NAMES[c]], comment=f"SNES bit {bit:03X}")]
        return [op("SysCall", s=[LEAVE + PR_NAMES[c]], comment=f"SNES bit {bit:03X} cleared")]

    def puppet_ops(self, entities, bodies, wait=True):
        """A puppet block (SetPuppet per entity, ExecPuppet, Return) as a segment; -> the Call."""
        self.puppet_n += 1
        name = f"Puppet_{self.puppet_n:04d}"
        block = [lab(name, kind=2)]
        block += [op("SetPuppet", i=[k, e, f"@{name}_{k}"], kind=2) for k, e in enumerate(entities)]
        block += [op("ExecPuppet", kind=2), op("Return", kind=2)]
        for k, b in enumerate(bodies):
            block += [lab(f"{name}_{k}", kind=2)] + b + [op("Exit", kind=2)]
        self.blocks.append((name, block))
        return [op("Call", i=[f"@{name}"] + ([] if wait else [1]))]

    def puppet(self, ins):
        a = ins.args
        e = self.entity(a["obj"])
        if e is None:
            self.report[("object", "camera")] += 1
            return []
        body = []
        x = y = None
        for name, args in a["actions"]:
            if name == "move":
                d, steps = args
                body.append(op("Move", i=[E.DIRS.index(d), steps, -1], kind=2))
            elif name == "diag":
                pass
            elif name.startswith("face_"):
                body.append(op("LookAt", i=[E.DIRS.index(name[5:])], kind=2))
            elif name == "wait":
                body.append(op("Wait", r=[round(args[0] * 4 * FRAME, 3)], kind=2))
            elif name == "show":
                body.append(op("Show", kind=2))
            elif name == "hide":
                body.append(op("Hide", kind=2))
            elif name == "pos":
                x, y = args
                p = self.local(x, y)
                if p:
                    body.append(op("SetPos", i=list(p), kind=2))
        if not body:
            return []
        wait = a["wait"]
        if not wait:
            self.pending_wait = True
        return self.puppet_ops([e], [body], wait=wait)

    def local(self, x, y):
        """An SNES tile on this event's map -> the PR map's tile (the map's offset)."""
        if self.snes_map is None:
            return x, y
        import snes_maps
        r = snes_maps.to_pr(self.snes_map, x, y, pr=self.pr_map)
        return (r[1], r[2]) if r else (x, y)

    def message(self, ins):
        key, choices = self.dialog(E.dialog_key(ins))
        if key is None:
            self.stubs["dialog"] += 1
            self.report[("dialog", "no key")] += 1
            return [stub(ins, "no PR key")]
        keys = key if isinstance(key, list) else [key]       # a mod's dialogue may be several turns
        out = [op("Msg", s=[k], comment=f"SNES dialogue {ins.args['dlg'] & 0x1FFF}") for k in keys]
        if choices:
            out.append(op("Select", s=choices))
        return out

    def choice(self, ins, last):
        """B6: the choice made in the last dialogue (its Select) -> Branch on MessageSelection."""
        out = []
        ts = [t for _, t in ins.targets]
        for k, t in enumerate(ts[:-1]):
            out.append(op("Branch", i=[0, k, f"@L_{t:06X}"], s=["MessageSelection", EQ, "imm"]))
        out.append(op("Jump", i=[f"@L_{ts[-1]:06X}"]))
        return out

    def cond(self, ins):
        """C0-C7 (all of n bits) / C8-CF (any): Branch chains on the mapped flags. A bit of the
        case word (1A0-1AF: party checks after DE-E4, word compares) is left as a stub test."""
        a = ins.args
        t = f"@L_{a['event']:06X}"
        bits = a["bits"]
        static = [(b, w) for b, w in bits if b in STATIC_ENGINE_BITS]
        if static:
            # engine bits with a known value when the party walks in (STATIC_ENGINE_BITS): the condition is decided,
            # or loses those terms
            self.report[("flow", "engine bit (as on a walk-in)")] += 1
            met = [STATIC_ENGINE_BITS[b] == w for b, w in static]
            rest = [(b, w) for b, w in bits if b not in STATIC_ENGINE_BITS]
            jump = [op("Jump", i=[t], comment="SNES bits %s as on a walk-in" % " ".join("%03X" % b for b, _ in static))]
            if ins.op >= 0xC8:                     # any
                if any(met):
                    return jump
                if not rest:
                    return []
            else:                                  # all
                if not all(met):
                    return []
                if not rest:
                    return jump
            ins2 = copy.copy(ins)
            ins2.args = dict(a, bits=rest)
            return self.cond(ins2)
        out = []
        tests = []
        for b, want in bits:
            if b == GIL_SHORT:
                tests.append(("MapLocalVariable", 0, 0 if want else 1))
                continue
            if b in ENGINE_BITS and b not in self.story_engine_bits:
                self.stubs["flow"] += 1
                self.report[("flow", "stub:case_bit" if b < 0x1B0 else "stub:engine_bit")] += 1
                tests.append(None)
                continue
            if b in SCRATCH:
                k = b - SCRATCH.start
                tests.append(("MapLocalVariable" if k < 8 else "AreaLocalVariable", k & 7, 1 if want else 0))
                continue
            cat, idx = self.flag(b)
            tests.append((cat, idx, 1 if want else 0))
        if any(x is None for x in tests):
            # a test of the engine's bits (the case word after DE-E4 or a word compare; the field
            # code's own bits): dropped from the condition (an "all" takes it as met, an "any" as
            # not met), noted
            out.append(op("SysCall", s=["SNES:case_test"], comment=f"{E.fmt(ins.off)} {ins.raw.hex(' ').upper()}"))
            tests = [x for x in tests if x is not None]
            if not tests:
                return out
        any_of = ins.op >= 0xC8
        if any_of or len(tests) == 1:
            for cat, idx, v in tests:
                out.append(op("Branch", i=[idx, v, t], s=[cat, EQ, "imm"]))
            return out
        # all of n: any test failing skips the jump
        skip = f"skip_{ins.off:06X}"
        for cat, idx, v in tests:
            out.append(op("Branch", i=[idx, 1 - v, f"@{skip}"], s=[cat, EQ, "imm"]))
        out.append(op("Jump", i=[t]))
        out.append(lab(skip))
        return out

    def repeat(self, ins, sub):
        """B0 n ... B1: the loop body (straight-line, up to the B1) unrolled n times (up to 32)."""
        body, off = [], ins.off + ins.size
        for _ in range(64):
            i = self.prog.code.get((off, "field"))
            if i is None or i.name == "repeat_end" or i.flow != "next":
                break
            body.append(i)
            off += i.size
        if i is None or i.name != "repeat_end" or not body:
            return self.left(ins, "repeat")
        ops = []
        for _ in range(min(ins.args["count"], 32)):
            for b in body:
                o, _ = self.instr(b, sub, None)
                ops.extend(copy.deepcopy(o))
        self.done["flow"] += 1
        self.report[("flow", "repeat")] += 1
        self.skip_to = off            # the body was emitted: go on after B1
        return ops, True

    def battle(self, ins, sub):
        """4D/4C: the pack's first formation's PR party; the code after it goes in a script of its
        own (Encount names it)."""
        f, party = self.battle_party(ins.args["pack"])
        if f is None:
            return self.left(ins, "pack")
        if party is None:                      # a formation the PR has no party for yet
            self.needs_formations.add(f)
            return self.left(ins, f"formation {f} has no PR party yet")
        self.done["battle"] += 1
        self.report[("battle", "ok")] += 1
        after = f"{self.name}_b{len(self.after) + 1}"
        cont = ins.off + ins.size
        t = self.child(after, self.snes_map, self.pr_map)
        script = t.translate(cont)
        self.after.append((after, script, self.pr_map))
        self.after.extend(t.after)
        for k in ("report", "stubs", "done", "stub_at", "needs_formations"):
            getattr(self, k).update(getattr(t, k))
        return [op("Encount", i=[party], s=[after], comment=f"SNES pack {ins.args['pack']} formation {f}"),
                op("Exit")], False

    def game_over_check(self, t):
        """True when the routine at `t` is the battle loss check: `if_battle_bit_clear 40 -> R;
        call <game-over scene>; R: return` (found by shape, so a mod that moved it is found too)."""
        code = self.prog.code
        a = code.get((t, "field"))
        if a is None or a.name != "if_battle_bit_clear" or a.args.get("bit") != 0x40:
            return False
        b = code.get((t + a.size, "field"))
        r = code.get((a.targets[0][1], "field")) if a.targets else None
        return (b is not None and b.name == "call" and r is not None and r.name == "return"
                and a.targets[0][1] == t + a.size + b.size)

    # a mod's own song commands (T-Edition: 76, 9E, 9F on its second sound driver): played like F0/EF/F1
    song_commands = frozenset()
    # bits in the engine's range (1B0-1CF) a mod uses as story flags (vanilla's events never touch them; T-Edition's
    # costume unlocks and dream chapters): set, cleared and tested as flags (self.flag) instead of left as engine bits
    story_engine_bits = frozenset()

    def song_bgm(self, song, command):
        """An SNES song number (as `command` plays it) -> the PR's bgm id or None. A mod whose song
        numbers aren't vanilla's (more songs, a second driver) overrides this."""
        return song_bgm(song)

    def battle_party(self, pack):
        """An event battle's pack -> (its formation, the PR party to fight or None). A mod whose packs
        map straight to parties of its own overrides this (T-Edition EX: packs 0-12 -> 30768+)."""
        f = self.pack_formation(pack)
        return f, (None if f is None else self.party_for(f))

    def shop_ops(self, shop):
        """9B <shop> -> PR ops that open it, or None (a stub). The PR opens its shops by name
        (SysCall "ショップを開く:<place>"), a mod's through its plugin: a mod overrides this."""
        return None

    def party_for(self, formation):
        """The PR monster party of an SNES formation, or None when the PR has none (a mod's new
        formation the porter hasn't made yet): idmap.party (vanilla's, or the porter's numbering)."""
        import idmap
        return idmap.party(formation)

    def pack_formation(self, pack):
        import port_chests as C
        d = self.rom.data
        a = C.PACK2 + 4 * pack
        return (d[a] | d[a + 1] << 8) & 0x7FFF

    def warp(self, ins, sub):
        a = ins.args
        if a["map"] == E.PARENT_MAP:
            return self.left(ins, "parent map")
        p = self.place(a["map"], a["x"], a["y"])
        if p is None or p[0] is None:
            return self.left(ins, "no PR map")
        pr_id, pr_name, x, y, point = p
        if point is not None:
            px, py = x, y
            self.report[("map", "learned arrival")] += 1
        else:
            pts = pr_points(pr_name)
            if not pts:
                return self.left(ins, f"no arrival point on {pr_name}")
            point, px, py = min(pts, key=lambda q: (abs(q[1] - x) + abs(q[2] - y), q[0]))
            self.report[("map", "ok" if (px, py) == (x, y) else "nearest point")] += 1
        self.done["map"] += 1
        if a["map"] in E.WORLD_MAPS:
            # the world map: what follows is a vehicle script (the airship flying off...) or nothing
            if (ins.off + ins.size, "vehicle") in self.prog.code:
                self.stubs["vehicle"] += 1
                self.report[("vehicle", "stub:vehicle_script")] += 1
            return [op("ChangeMap", i=[pr_id, point], comment=f"SNES world map {a['map']} ({a['x']},{a['y']})"),
                    op("Exit")], False
        # the SNES event goes on on the new map: the PR's ChangeMap names the script it runs there
        cont = ins.off + ins.size
        nxt = self.prog.code.get((cont, "field"))
        after = ""
        if nxt is not None and nxt.flow != "end" and ins.off not in self.prog.map_ends:
            after = f"{self.name}_m{len(self.after) + 1}"
            t = self.child(after, a["map"], pr_name)
            script = t.translate(cont)
            self.after.append((after, script, pr_name))
            self.after.extend(t.after)
            for k in ("report", "stubs", "done", "stub_at", "needs_formations"):
                getattr(self, k).update(getattr(t, k))
        iv = [pr_id, point] + ([0, 0, 1 if ins.op == 0x6B else 0, 0] if after else [])
        return [op("ChangeMap", i=iv, s=[after] if after else [],
                   comment=f"SNES map {a['map']} ({a['x']},{a['y']}) -> {pr_name} ({x},{y}), point {point} at ({px},{py})"),
                op("Exit")], False

    def vehicle(self, ins, sub):
        if ins.name == "v_end":
            return [op("Return" if sub else "Exit")], False
        return self.left(ins, "vehicle")


_npc_cache = {}


def snes_npcs(rom):
    """{(SNES map, NPC index): its record's details (x, y, sprite, bit)} (entry_points' NPCs, per ROM)."""
    if id(rom) not in _npc_cache:
        _npc_cache[id(rom)] = {(e[2], e[3]["npc"]): e[3] for e in E.entry_points(rom) if e[1] in ("npc", "npc_object")}
    return _npc_cache[id(rom)]


_looks = {}


def sprite_assets(rom):
    """{SNES NPC sprite: (PR asset ids it became, most often first)}: learned from the NPCs found on
    their own spot in their PR room (a tile or two off at most), over every map of the ROM."""
    if id(rom) not in _looks:
        import snes_maps
        votes = collections.defaultdict(collections.Counter)
        for (m, n), det in snes_npcs(rom).items():
            r = snes_maps.to_pr(m, det["x"], det["y"])
            if not r:
                continue
            for layer, objs in pr_entities(r[0]):
                for name, x, y, eid, asset in objs:
                    if eid and asset and name not in NOT_NPCS and abs(x - r[1]) + abs(y - r[2]) <= 1:
                        votes[det["sprite"]][asset] += 1
        _looks[id(rom)] = {sp: tuple(a for a, c in v.most_common() if c >= max(2, v.most_common(1)[0][1] // 4))
                           for sp, v in votes.items()}
    return _looks[id(rom)]


NOT_NPCS = {"PointIn", "GotoMap", "OpenTrigger", "TileAnimRegion", "MoveArea", "MapRange", "EffectEntity_fire"}
_layers = {}


def pr_entities(pr_map, prefer=None):
    """[(layer, [(object name, x, y, entity id)])] of a PR map: the preferred entity layer first,
    then the others its package lists, then entity_default."""
    key = (pr_map, prefer)
    if key in _layers:
        return _layers[key]
    import snes_maps
    if not hasattr(pr_entities, "paths"):
        pr_entities.paths = snes_maps.pr_tilemaps()
    path = pr_entities.paths.get(pr_map)
    out = []
    if path:
        room = os.path.dirname(path)
        with open(os.path.join(os.path.dirname(room), "package.json"), encoding="utf-8") as f:
            pk = json.load(f)
        entry = next((m for m in pk["map"] if m["name"] == pr_map), {})
        names = [x["name"] for x in entry.get("entity", [])]
        if prefer in names:
            names.remove(prefer)
            names.insert(0, prefer)
        for nm in names + ["entity_default"]:
            f = os.path.join(room, nm + ".json")
            if not os.path.exists(f):
                continue
            objs = []
            with open(f, encoding="utf-8") as fh:
                doc = json.load(fh)
            for lay in doc.get("layers", []):
                for o in lay.get("objects") or []:
                    props = {q["name"]: q["value"] for q in o.get("properties", [])}
                    objs.append((o.get("name", ""), int(o["x"] // 16), int(o["y"] // 16) - (1 if "gid" in o else 0),
                                 props.get("entity_id"), props.get("asset_id")))
            out.append((nm, objs))
    _layers[key] = out
    return out


_ids = None


def map_ids():
    """({PR map name: id}, {id: name}) from map.csv."""
    global _ids
    if _ids is None:
        a = {row["map_name"]: int(row["id"]) for row in P.Table("map")}
        _ids = (a, {v: k for k, v in a.items()})
    return _ids


_points = {}


def pr_points(pr_name):
    """A PR map's arrival points (PointIn objects): [(point id, tile x, tile y)]."""
    if pr_name not in _points:
        import snes_maps
        if not hasattr(pr_points, "paths"):
            pr_points.paths = snes_maps.pr_tilemaps()
        out = []
        path = pr_points.paths.get(pr_name)
        if path:
            ent = os.path.join(os.path.dirname(path), "entity_default.json")
            if os.path.exists(ent):
                d = _json(ent)
                for lay in d.get("layers", []):
                    for o in lay.get("objects") or []:
                        props = {q["name"]: q["value"] for q in o.get("properties", [])}
                        # arrival points: PointIn objects, or (the world maps, named by place) any
                        # object of type 0 with a point id
                        if o.get("name") == "PointIn" or (props.get("object_type") == 0 and props.get("object_id")
                                                          and "action_id" not in props):
                            out.append((props.get("object_id"), int(o["x"] // 16),
                                        int(o["y"] // 16) - (1 if "gid" in o else 0)))
        _points[pr_name] = out
    return _points[pr_name]


def check(sc):
    """Problems with a PR script's structure (none for a good one): a jump, call, branch or puppet
    whose target isn't a labelled Nop, segments that don't add up or don't start at their label,
    operand arrays not 8 long (the game's own Nops carry empty ones)."""
    ms, errs = sc["Mnemonics"], []
    if sum(s["Count"] for s in sc["Segments"]) != len(ms):
        errs.append("segments")
    for s in sc["Segments"]:
        m = ms[s["EntryPoint"]]
        if m["mnemonic"] != "Nop" or m["label"] != s["Label"]:
            errs.append("segment " + s["Label"])
    for n, m in enumerate(ms):
        o = m["operands"]
        if any(len(o[k]) != 8 for k in ("iValues", "sValues", "rValues")) and not (
                m["mnemonic"] == "Nop" and not any(o.values())):
            errs.append(f"{n} operands")
        for k in JUMP_OPERANDS.get(m["mnemonic"], ()):
            t = o["iValues"][k]
            if not isinstance(t, int) or not 0 <= t < len(ms) or ms[t]["mnemonic"] != "Nop" or not ms[t]["label"]:
                errs.append(f"{n} {m['mnemonic']} -> {t}")
    return errs


def translate(rom, entry, name, **kw):
    t = Translator(rom, name, **kw)
    sc = t.translate(entry)
    return sc, t


# --- comparison with the PR's own scenes -----------------------------------------------------------
def signature(sc):
    """What a PR script does that a scene comparison checks: flags set (in order), battles, map
    changes, gifts, dialogue order."""
    s = pr_summary(sc)
    return {"msgs": s.get("msgs", []), "sets": s.get("sets", []), "battles": s.get("battles", []),
            "maps": s.get("maps", []), "items": s.get("items", []), "party": s.get("party", [])}


def compare(translated, pr_names):
    """Translated script(s) vs the PR's scripts of the same scene: per aspect, (ours, theirs,
    agreement 0-1). Dialogue: the share of the PR's lines we show, in the PR's order."""
    ours = collections.defaultdict(list)
    for sc in translated:
        for k, v in signature(sc).items():
            ours[k].extend(v)
    theirs = collections.defaultdict(list)
    for n in pr_names:
        for k, v in pr_index().get(n.lower(), {}).items():
            theirs[k].extend(v)
    out = {}
    for k in ("msgs", "sets", "battles", "maps", "items", "party"):
        a, b = ours.get(k, []), theirs.get(k, [])
        if not a and not b:
            continue
        sa, sb = set(map(str, a)), set(map(str, b))
        out[k] = {"ours": a, "theirs": b, "share": round(len(sa & sb) / max(1, len(sb)), 2),
                  "extra": sorted(sa - sb)}
    if "msgs" in out:
        a = [m for m in ours["msgs"] if m in set(theirs["msgs"])]
        b = [m for m in theirs["msgs"] if m in set(a)]
        out["msgs"]["in_order"] = a == b
    return out


# vanilla scenes the PR also has, short to long (tests/test_snes_events.py): (SNES entry, its map)
VALIDATION = ["CC/33F4", "CA/7913", "CC/0B70", "CC/0B1E", "CA/8CBB", "CC/91C0", "CB/AADD", "CB/B7F8",
              "CB/E767", "CA/9749", "CA/BF4B", "CB/75BF"]


def validate(entries=VALIDATION, prog=None):
    """Translates each validation scene and compares it with the PR's own: -> [(entry, PR group,
    comparison, stubs by class, translated by class, instructions)]."""
    prog = prog or E.Program(E.load("us")).walk_all()
    by_off = {}
    for row in pairs(prog):
        by_off.setdefault(row[0], row)
    out = []
    for a in entries:
        off = E.parse_addr(a)
        row = by_off[off]
        sc, t = translate(prog.rom, off, f"sc_snes_{off:06x}", snes_map=row[2], prog=prog)
        res = compare([sc] + [x[1] for x in t.after], row[6])
        out.append((a, row[3], res, dict(t.stubs), dict(t.done), len(scene(prog, off))))
    return out


def _main(argv):
    argv = E.cli_modules(argv)          # --module ted_events: a mod's ROMs for `translate`
    cmd = argv[0] if argv else "learn"
    if cmd == "learn":
        out = learn()
        print(f"pairs {out['pairs']}, flags {len(out['flags'])}, bgm {len(out['bgm'])}, se {len(out['se'])} -> {MAPS_FILE}")
    elif cmd == "pairs":
        n = int(argv[1]) if len(argv) > 1 else 40
        for row in pairs()[:n]:
            print(E.fmt(row[0]), row[1], row[2], row[3], f"{row[4]}/{row[5]}", ",".join(row[6]))
    elif cmd == "translate":
        rom = E.load(argv[2] if len(argv) > 2 else "us")
        off = E.parse_addr(argv[1])
        prog = E.Program(rom).walk_all()
        m = next((e[2] for e in prog.entries if e[0] == off), None)
        sc, t = translate(rom, off, f"sc_snes_{off:06x}", snes_map=m, prog=prog)
        print(S.dumps(sc))
        for name, s, where in t.after:
            print(f"--- {name} (runs on {where or 'this map'})")
            print(S.dumps(s))
        print("translated:", dict(t.done), "stubs:", dict(t.stubs))
    elif cmd == "compare":
        rom = E.load("us")
        off = E.parse_addr(argv[1])
        prog = E.Program(rom).walk_all()
        row = next(r for r in pairs(prog) if r[0] == off)
        sc, t = translate(rom, off, f"sc_snes_{off:06x}", snes_map=row[2], prog=prog)
        res = compare([sc] + [x[1] for x in t.after], row[6])
        print(json.dumps(res, ensure_ascii=False, indent=1))
    elif cmd == "validate":
        tot_s, tot_d = collections.Counter(), collections.Counter()
        for a, g, res, stubs, done, n in validate():
            tot_s.update(stubs)
            tot_d.update(done)
            line = f"{a} {g} ({n} SNES instructions)"
            for k, v in res.items():
                extra = f" in order: {v['in_order']}" if "in_order" in v else ""
                line += NL + f"    {k}: share {v['share']} ours {len(v['ours'])} theirs {len(v['theirs'])}{extra}"
                if k != "msgs":
                    line += f" {v['ours']} vs {v['theirs']}"
            print(line + NL + f"    stubs {stubs}")
        print("translated by class:", dict(tot_d))
        print("stubs by class:", dict(tot_s))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    _main(sys.argv[1:])
