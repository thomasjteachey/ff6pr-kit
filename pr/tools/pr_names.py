"""A mod's names in the Pixel Remaster's own words (the shared porter; the user, 2026-11-20: "i don't
like R-Ice": no SNES abbreviations where the PR has a full name).

SNES names are cut to fit (12 characters for items with their icon, 10 for monsters, 8 for espers, 7
for commands), and the PR renamed much of FF6 (Saucer for Titanium, Fang for Dispatch). A name a mod
changed is often only an SNES name of the same thing with a mark (Beyond Chaos's questionable items:
"BehemothSui?" = Behemoth Suit + "?"), or the SNES name of another entry of the same table (a mod
moving names around). Those get the PR's name; a name of the mod's own (an invented monster or a
custom item) stays as the mod wrote it.
"""
MARKS = "?!"         # marks a mod adds after a name (Beyond Chaos: "?" an item that isn't what it was, "!" one with a junction effect)


def _norm(s):
    return "".join(c for c in (s or "").lower() if c.isalnum())


def in_pr_words(mod, van, pr, pairs=()):
    """mod: the mod's SNES name; van: the vanilla SNES name of the same entry; pr: the PR's name for that
    entry; pairs: (vanilla SNES name, PR name) of the table's other entries. Returns the name to show."""
    mod = (mod or "").strip()
    base = mod.rstrip(MARKS)
    mark = mod[len(base):]
    nb = _norm(base)
    if not nb:
        return mod
    # the entry's own SNES name, maybe cut short to make room for the mark
    if van and (_norm(van) == nb or (len(nb) >= 4 and _norm(van).startswith(nb))):
        return (pr or van) + mark
    # another entry's SNES name (one only)
    hits = [p for v, p in pairs if v and p and (_norm(v) == nb)]
    if not hits and len(nb) >= 5:
        hits = [p for v, p in pairs if v and p and _norm(v).startswith(nb)]
    if len(set(hits)) == 1:
        return hits[0] + mark
    return mod
