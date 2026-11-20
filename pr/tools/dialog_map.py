"""SNES FF6 dialogue numbers -> Pixel Remaster story line keys, through the Japanese.

The SNES game's 3084 dialogues (CC/E602 pointers) have the same numbers in the US and the Japanese
ROM, and a mod built on the US ROM (Brave New World, Worlds Collide) keeps them. The PR's English is
a new translation, so English-to-English matching is weak (tools/dialog_align*.py: 56% of lines,
some off by one); its Japanese follows the Super Famicom's Japanese nearly character for character.
So: the Japanese ROM's dialogues are decoded with a character table learned from the PR's own
story_mes_ja (no font, no download), and every PR story line is matched to the dialogue (and the
speaker turns of it) whose Japanese it shares.

JP ROM dialogue codes: 00 end, 01 newline, 13 new page, 02-0F character names, 10/12 waits,
11/14/16 + one byte, 15 choice, 17-1B placeholders, 1C-1F + one byte = kanji, D0 starts a speaker's
turn (the line's speaker marker), FF space, 20-FE single glyphs (some stand for two characters).

    .venv/Scripts/python tools/dialog_map.py            (writes build/dialog/, prints coverage)

Outputs (build/dialog/): jp_table.json (code -> text), dialog_map.json ({PR key: [dialogue, first
turn, last turn, score, how]}), jp_turns.json (each dialogue's decoded turns, for review).
Nothing of the game's text is written outside build/.
"""
import collections
import difflib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kitpath  # noqa: E402,F401
import prdata as P  # noqa: E402

JP_ROM_NAME = "Final Fantasy VI (Japan).sfc"
OUT = os.path.join(P.ROOT, "build", "dialog")
COUNT = 3084
TAG = re.compile(r"<[^>]*>|\\n|\([A-Z_]+\)|[\s　]")
KATA = {chr(c): chr(c - 0x60) for c in range(0x30A1, 0x30F7)}


def skeleton(s):
    """Kana only, katakana as hiragana (the PR writes kanji or katakana where the SFC wrote kana:
    許して/ゆるして, ウソ/うそ); punctuation and digits kept, kanji dropped."""
    out = []
    for ch in s:
        ch = KATA.get(ch, ch)
        if "一" <= ch <= "鿿" or ch == "□":
            continue
        out.append(ch)
    return "".join(out)


def jp_rom_path():
    for p in (os.environ.get("FF6_JP_ROM"), os.path.join(P.ROOT, "rom", JP_ROM_NAME),
              os.path.join(P.ROOT, "..", "rom", "vanilla", JP_ROM_NAME)):
        if p and os.path.exists(p):
            return p
    raise SystemExit(f"no Japanese ROM ({JP_ROM_NAME}): set FF6_JP_ROM")


def jp_dialogs(d):
    """Each dialogue as turns, each turn a list of glyph codes ("8b", "1c76"...); a turn starts at
    a speaker marker (D0) or a new page (13)."""
    w = lambda a: d[a] | d[a + 1] << 8
    split, out = w(0x0CE600), []
    for i in range(COUNT):
        k = (0x0D0000 if i < split else 0x0E0000) + w(0x0CE602 + 2 * i)
        turns, cur, n = [], [], 0
        while n < 3000:
            c = d[k]; k += 1; n += 1
            if c == 0x00:
                break
            if c in (0x13, 0xD0):
                if cur:
                    turns.append(cur)
                cur = []
            elif c in (0x01, 0x10, 0x12, 0x15, 0xFF):
                pass
            elif c in (0x11, 0x14, 0x16):
                k += 1; n += 1
            elif 0x02 <= c <= 0x0F or 0x17 <= c <= 0x1B:
                pass
            elif 0x1C <= c <= 0x1F:
                cur.append(f"{c:02x}{d[k]:02x}"); k += 1; n += 1
            else:
                cur.append(f"{c:02x}")
        if cur:
            turns.append(cur)
        out.append(turns)
    return out


def pr_lines(lang):
    out = {}
    path = f"{P.MESSAGE}/story_mes_{lang}.txt"
    for line in open(path, encoding="utf-8").read().splitlines():
        if "\t" in line:
            k, v = line.split("\t", 1)
            if v.strip():
                out[k] = v
    return out


def clean_ja(s):
    return TAG.sub("", s)


def learn_table(jp, prj, anchors, rounds=4):
    """Code -> text from dialogues the English aligner placed (anchors: {dialogue: [PR keys]})."""
    pairs = []
    for i, keys in anchors.items():
        codes = [c for t in jp[i] for c in t]
        pairs.append((codes, "".join(clean_ja(prj.get(k, "")) for k in keys)))
    votes = collections.defaultdict(collections.Counter)
    for c, t in pairs:
        if c and len(c) == len(t):
            for a, b in zip(c, t):
                votes[a][b] += 1
    table = {a: v.most_common(1)[0][0] for a, v in votes.items() if v.most_common(1)[0][1] >= 2}
    for _ in range(rounds):
        v1 = collections.defaultdict(collections.Counter)
        for c, t in pairs:
            dec, owner = [], []
            for n, x in enumerate(c):
                s = table.get(x, "\0")
                dec += list(s)
                owner += [n] * len(s)
            sm = difflib.SequenceMatcher(None, dec, t, autojunk=False)
            for op, a1, a2, b1, b2 in sm.get_opcodes():
                if op == "equal":
                    for p, q in zip(range(a1, a2), range(b1, b2)):
                        if p == a1 or owner[p] != owner[p - 1]:
                            n = owner[p]
                            v1[c[n]][t[q:q + len(table.get(c[n], ""))] if len(table.get(c[n], "")) > 1 else t[q]] += 1
                elif op == "replace":
                    codes_here = sorted(set(owner[a1:a2]))
                    if len(codes_here) == b2 - b1:
                        for n, q in zip(codes_here, range(b1, b2)):
                            v1[c[n]][t[q]] += 1
                    elif len(codes_here) == 1 and b2 - b1 == 2:
                        v1[c[codes_here[0]]][t[b1:b2]] += 1
                    elif 2 * len(codes_here) == b2 - b1:
                        for j, n in enumerate(codes_here):
                            v1[c[n]][t[b1 + 2 * j:b1 + 2 * j + 2]] += 1
        new = {}
        for a, v in v1.items():
            ch, n = v.most_common(1)[0]
            if n >= 2 and n >= 0.55 * sum(v.values()):
                new[a] = ch
        table = new
    return table


def decode(turn, table):
    return "".join(table.get(x, "□") for x in turn)


def grams(s):
    return {s[i:i + 2] for i in range(len(s) - 1) if "□" not in s[i:i + 2]}


def scene(k):
    return k.rsplit("_", 1)[0] if k[0] == "E" else k.rsplit("_", 2)[0]


def build(verbose=True):
    import dialog_align as D
    import ff6snes as S
    jp = jp_dialogs(open(jp_rom_path(), "rb").read())
    prj = pr_lines("ja")
    mapping, segs, pr_en, sim = D.align(S.Rom(P.VANILLA_ROM))
    en = {k: i for (i, j), k in mapping.items()}
    anchors = collections.defaultdict(list)
    for (i, j), k in sorted(mapping.items()):
        anchors[i].append(k)
    table = learn_table(jp, prj, anchors)
    dec = [[decode(t, table) for t in d] for d in jp]
    dec[0] = []   # dialogue 0 is a copy of 1 (both pointers 0): it would make 1's lines ambiguous
    dg = [grams("".join(d)) for d in dec]
    inv = collections.defaultdict(set)
    for i, g in enumerate(dg):
        for x in g:
            inv[x].add(i)
    lines = {k: clean_ja(v) for k, v in prj.items()}
    story = [k for k in lines if len(grams(lines[k])) >= 3 and not k.startswith("SPEAKER")]
    # 1. unique dialogue by Japanese bigram containment
    match = {}
    for k in story:
        g = grams(lines[k])
        sc = collections.Counter()
        for x in g:
            for i in inv.get(x, ()):
                sc[i] += 1
        top = sc.most_common(2)
        if not top:
            continue
        best, n = top[0]
        second = top[1][1] if len(top) > 1 else 0
        if n / len(g) >= 0.7 and n - second >= max(2, 0.2 * n):
            match[k] = (best, n / len(g), "jp")
    # 2. in-scene order fills; then the English aligner where Japanese found nothing
    groups = collections.defaultdict(list)
    for k in story:
        groups[scene(k)].append(k)
    for ks in groups.values():
        ks.sort(key=D.keyorder)
        placed = [(n, match[k][0]) for n, k in enumerate(ks) if k in match]
        for n, k in enumerate(ks):
            if k in match:
                continue
            lo = max((d for m, d in placed if m < n), default=None)
            hi = min((d for m, d in placed if m > n), default=None)
            if lo is None and hi is None:
                continue
            lo = lo if lo is not None else max(0, hi - 3)
            hi = hi if hi is not None else min(COUNT - 1, lo + 3)
            if hi < lo:
                continue
            g = grams(lines[k])
            best = max(range(lo, hi + 1), key=lambda i: len(g & dg[i]))
            cov = len(g & dg[best]) / len(g)
            if cov >= 0.35:
                match[k] = (best, cov, "order")
            elif k in en and lo <= en[k] <= hi:
                match[k] = (en[k], cov, "en")
    # 3. windows: a line still unplaced is searched only among the dialogues its event (or the
    # events around it) already spans, turn by turn, so a short or repeated line is unambiguous
    def event(k):
        return k.split("_")[0]
    ev = collections.defaultdict(list)
    for k, v in match.items():
        ev[event(k)].append(v[0])
    evs = sorted(ev, key=lambda e: (e[0], int(re.sub(r"\D", "", e) or 0)))
    span = {e: (min(ev[e]), max(ev[e])) for e in evs}
    def window(k):
        e = event(k)
        if e in span:
            lo, hi = span[e]
            return max(0, lo - 4), min(COUNT - 1, hi + 4)
        kind = [x for x in evs if x[0] == e[0]]
        num = int(re.sub(r"\D", "", e) or 0)
        before = [x for x in kind if int(re.sub(r"\D", "", x) or 0) < num]
        after = [x for x in kind if int(re.sub(r"\D", "", x) or 0) > num]
        if not before or not after:
            return None
        lo, hi = span[before[-1]][1], span[after[0]][0]
        return (lo, hi) if 0 <= hi - lo <= 60 else None
    for k in story:
        if k in match:
            continue
        w = window(k)
        if not w:
            continue
        g, gs = grams(lines[k]), grams(skeleton(lines[k]))

        def turn_score(t):
            a = len(g & grams(t)) / len(g)
            b = len(gs & grams(skeleton(t))) / len(gs) if len(gs) >= 3 else 0.0
            return max(a, b)
        scored = sorted(((turn_score(t), i) for i in range(w[0], w[1] + 1) for t in dec[i]), reverse=True)
        if not scored:
            continue
        top, i = scored[0]
        second = next((s for s, j in scored[1:] if j != i), 0.0)
        if top >= 0.6 and top - second >= 0.15:
            match[k] = (i, top, "window")
    # 3b. the rest anywhere, by kana skeleton: one clear best turn
    skel = [(i, grams(skeleton(t))) for i, d in enumerate(dec) for t in d]
    sinv = collections.defaultdict(set)
    for n, (i, sg) in enumerate(skel):
        for x in sg:
            sinv[x].add(n)
    for k in story:
        if k in match:
            continue
        gs = grams(skeleton(lines[k]))
        if len(gs) < 4:
            continue
        sc = collections.Counter()
        for x in gs:
            for n in sinv.get(x, ()):
                sc[n] += 1
        top = sc.most_common(5)
        if not top:
            continue
        n0, c0 = top[0]
        other = max((c for n, c in top[1:] if skel[n][0] != skel[n0][0]), default=0)
        if c0 / len(gs) >= 0.7 and c0 - other >= max(2, 0.25 * c0):
            match[k] = (skel[n0][0], c0 / len(gs), "skeleton")
    for k in story:
        if k not in match and k in en:
            match[k] = (en[k], 0.0, "en-only")
    # 4. turns: each placed line -> the run of its dialogue's turns it covers best
    out = {}
    for k, (d, cov, how) in match.items():
        g = grams(lines[k])
        turns = dec[d]
        best = (0.0, 0, len(turns) - 1)
        for a in range(len(turns)):
            acc = set()
            for b in range(a, len(turns)):
                acc |= grams(turns[b])
                if not g:
                    break
                inter = len(g & acc)
                score = inter / len(g) - 0.15 * max(0, len(acc) - inter) / max(1, len(acc))
                if score > best[0]:
                    best = (score, a, b)
        out[k] = [d, best[1], best[2], round(cov, 2), how]
    os.makedirs(OUT, exist_ok=True)
    json.dump(table, open(os.path.join(OUT, "jp_table.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    json.dump(out, open(os.path.join(OUT, "dialog_map.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    json.dump(dec, open(os.path.join(OUT, "jp_turns.json"), "w", encoding="utf-8"), ensure_ascii=False)
    if verbose:
        used = collections.Counter(x for d in jp for t in d for x in t)
        cov_uses = sum(n for x, n in used.items() if x in table) / sum(used.values())
        two = sum(1 for v in table.values() if len(v) > 1)
        hows = collections.Counter(v[4] for v in out.values())
        print(f"table: {len(table)} codes ({two} of two characters), {cov_uses:.1%} of glyph uses")
        print(f"PR story lines: {len(story)}; placed {len(out)} ({len(out) / len(story):.0%}): {dict(hows)}")
        both = [k for k in en if k in out and out[k][4] != "en-only"]
        agree = sum(1 for k in both if out[k][0] == en[k])
        print(f"vs the English aligner: {agree} of {len(both)} the same dialogue ({agree / max(1, len(both)):.0%})")
    return out, dec, lines, story


if __name__ == "__main__":
    build()
