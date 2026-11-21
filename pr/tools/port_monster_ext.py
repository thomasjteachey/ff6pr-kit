"""A mod's monsters and formations past the US tables (kit; T-Edition's 94 new monsters 384-511 and its
formations 576-767).

A profile whose mod grew the monster and formation tables registers them from its image build
(register(): profile_tedition.build): ff6snes.EXTENDED gets the grown tables (offset, record size,
count in the image) and the profile's data (names, a sprite reader, where the mod's events fight each
formation), idmap.MONSTER_EXT the PR monster id of each new monster (T-Edition: 1000 + e; the PR's own
rows end at 611). The shared porter then reads formations past 576 (port_encounters.formation), their
AP past 512 (formation_ap) and new monsters' ids (idmap.monster) wherever it builds parties: random
sets, the Veldt, boxes. port() (port.py's hook after the encounters) makes the rest:

- a PR monster row per new monster a formation uses: a copy of a template row (the vanilla monster
  drawn with the same art, matched by sprite content; for a recolor the vanilla monster of that shape;
  else a normal vanilla monster of the nearest sprite size, a placeholder), with the mod's stats, name,
  steals and drops (the profile's drop slots when it has more than two), undead flag, elements,
  immunities, initial statuses, a special attack of its own (ability SPECIAL_BASE + e, rebuilt from the
  SNES special byte as port_specials does, named), Sketch (a group of its own); no Rage (the SNES's
  rages stop at monster 255). AI: the template's PR script (a placeholder's when the template is a
  boss, whose script belongs to its own fight), until the plugin runs the mod's SNES scripts.
- the first party (port_encounters.first_party_id: 2000 + f, 30000 + f from 600) of every formation
  past 576 or holding new monsters that no random set needed, for the mod's event battles: the
  formation's monsters (EncounterPorter.party_row) on a look: the background the mod's event battle asks for
  (register's event_backgrounds), else that of the SNES map where its events fight it (register's event_maps,
  map properties byte 2): SNES background b is the PR's asset bg_ff6_<b + 1> (Looks); else vanilla's party for
  that formation number, else the commonest; the battle music its formation flags ask for (byte 3 bits 4-7, learned);
  a boss's party settings (script 0, normal attacks only, no escape) when a monster is a boss or the
  formation forbids escape, else a random battle's.
- monster_ext.json beside the port: per new monster its PR id, name, template, art (same / recolor /
  new: what the monster-art work needs), AI source, special; the parties made ({party: formation}).
"""
import collections
import json
import os

import ff6snes as S
import idmap as M
import port_encounters as E
import prdata as P

SPECIAL_BASE = 6000    # a new monster's special attack: ability 6000 + e (the PR's abilities end at 5917)
EXPORT = "monster_ext.json"
FIGHT, EE, EF, NONE = 1, 0xEE, 0xEF, 0xFF
BOSS_PARTY = {"appearance_production": "1", "script_name": "0", "not_escape": "2", "battle_flag_group_id": "7",
              **{f"battle_pattern{k}": "1" if k == 1 else "0" for k in range(1, 7)}}
RANDOM_PARTY = {"appearance_production": "1", "script_name": "8010", "not_escape": "0", "battle_flag_group_id": "11",
                **{f"battle_pattern{k}": "1" if k < 6 else "0" for k in range(1, 7)}}   # vanilla's commonest random party
SET_BASE = 5000   # monster sets made for a mod's new maps: 5001 up (the PR's end at 484)
EVENT_PARTY = {"appearance_production": "1", "script_name": "8010", "not_escape": "0", "battle_flag_group_id": "11",
               **{f"battle_pattern{k}": "1" if k == 1 else "0" for k in range(1, 7)}}


def register(data, tables, monster_base=None, **extra):
    """A profile's image with grown tables: tables {name: (offset, record size, count)} (ff6snes.EXTENDED's
    names), extra data (monster_names, special_names: lists by monster; sprites: a reader whose
    sprite(e) is a snes_sprites.Sprite; event_maps: {formation: [SNES maps]}), and new monsters' PR ids
    monster_base + e (idmap.MONSTER_EXT)."""
    entry = dict(tables, _image=data)   # the image itself: kept alive while registered (ff6snes.extended checks it)
    entry.update(extra)
    S.EXTENDED[id(data)] = entry
    mon = tables.get("monsters")
    if monster_base is not None and mon:
        M.MONSTER_EXT.update({e: monster_base + e for e in range(384, mon[2])})


def record(rom, name, i):
    at, size, count = S.extended(rom, name)
    return rom.data[at + size * i:at + size * (i + 1)] if i < count else b""


def formation_count(rom):
    ext = S.extended(rom, "formations")
    decoded = S.extended(rom, "formation_monsters") or {}
    return max([ext[2] if ext else 576] + [f + 1 for f in decoded])


def members(rom, f):
    """Every monster of formation f, shown at the start or brought in later (hidden slots: E.formation lists
    only the shown ones)."""
    decoded = S.extended(rom, "formation_monsters")
    if decoded and f in decoded:
        return [e for e, _, _, _ in decoded[f]]
    r = E.formation_raw(rom, f)
    if not r:
        return []
    ids = [r[2 + s] | ((r[14] >> s & 1) << 8) for s in range(6)]
    return [e for s, e in enumerate(ids) if r[1] >> s & 1 or e not in (0x1FF, 0xFF)]


def new_monsters(rom):
    """The monsters past 384 the mod's formations use (shown or brought in)."""
    return sorted({e for f in range(formation_count(rom)) for e in members(rom, f) if e >= 384})


def ext_formations(rom):
    """Formations past 576, or under it holding monsters past 384, that have monsters."""
    out = []
    for f in range(formation_count(rom)):
        mons = [e for e, _, _ in E.formation(rom, f)]
        if mons and (f >= 576 or any(e >= 384 for e in mons)):
            out.append(f)
    return out


def random_monsters(rom):
    """Monsters a random battle can show (the packs of the places with random battles)."""
    out = set()
    for p in set(E.locations(rom).values()):
        for f in E.pack(rom, p):
            out.update(e for e, _, _ in E.formation(rom, f))
    return out


# --- art: which vanilla monster each new one looks like --------------------------------------------

def match_art(rom, news):
    """{e: (kind, vanilla monster, (w, h))}: kind "same" (vanilla's art), "recolor" (a vanilla shape in
    other colors) or "new" (the vanilla monster of the nearest size stands in: a placeholder)."""
    import port_sprites as PS
    import snes_sprites as SS
    van = S.Rom(P.VANILLA_ROM)
    V = [PS.Crop(SS.Sprites(van).sprite(i)) for i in range(384)]
    reader = S.extended(rom, "sprites")
    vmo = P.Table("monster")
    normal = random_monsters(van)
    by_size = collections.defaultdict(list)
    for j, c in enumerate(V):
        if not c.empty:
            by_size[(c.w, c.h)].append(j)
    placeholders = [j for j in sorted(normal) if not V[j].empty and vmo.rows.get(j + 1, {}).get("boss") == "0"]
    out = {}
    for e in news:
        if reader is None:      # no reader: the graphics entry alone (same tiles and stencil = same art)
            g = record(rom, "monster_graphics", e) if S.extended(rom, "monster_graphics") else b""
            j = next((j for j in range(384) if g and van.data[0x127000 + 5 * j:0x127000 + 5 * j + 5] == g), None)
            out[e] = ("same", j, None) if j is not None else ("new", placeholders[0], None)
            continue
        sp = reader.sprite(e)
        if sp is None:          # the reader has none (T-Edition EX's bosses): a big stand-in
            out[e] = ("new", min(placeholders, key=lambda j: (abs(V[j].w - 96) + abs(V[j].h - 96), j)), None)
            continue
        b = PS.Crop(sp)
        size = (b.w, b.h)
        scored = []
        for j in by_size.get(size, ()) if not b.empty else ():
            if sum(x != y for x, y in zip(V[j].mask, b.mask)) > 0.2 * len(b.mask):
                continue
            scored.append((PS.shape_diff(V[j], b), j))
        scored.sort()
        if scored and scored[0][0] <= 0.2:
            c, j = min((PS.color_diff(V[j], b), j) for s, j in scored if s <= 0.2)
            out[e] = ("same" if c <= 4 else "recolor", j, size)
            continue
        j = min(placeholders, key=lambda j: (abs(V[j].w - b.w) + abs(V[j].h - b.h), j))
        out[e] = ("new", j, size)
    return out


# --- looks for event parties -----------------------------------------------------------------------

class Looks:
    """Battle backgrounds and music for a mod's event parties. Background: SNES battle background b (map
    properties byte 2 & 0x7F, the event battle command 4D's second byte) is the PR's asset bg_ff6_<b + 1>
    (battle_background_asset.csv; checked on vanilla: the event battles' parties agree 10 of 11 times, the maps'
    random sets 21 of 26, the rest being sets the PR shares between maps). Music: formation flags byte 3 bits
    4-7 -> the PR music of vanilla's party for formations with those bits (learned)."""

    def __init__(self):
        van = S.Rom(P.VANILLA_ROM)
        vmp = P.Table("monster_party")
        names = {r["asset_name"]: r["id"] for r in P.Table("battle_background_asset")}
        self.bg = {b: names[f"bg_ff6_{b + 1:02d}"] for b in range(0x7F) if f"bg_ff6_{b + 1:02d}" in names}
        music = collections.defaultdict(collections.Counter)
        allbg = collections.Counter()
        for f in range(576):
            row = vmp.rows.get(M.party(f))
            if row and E.formation(van, f):
                music[van.data[0x0F5900 + 4 * f + 3] >> 4][row["battle_bgm_asset_id"]] += 1
                allbg[row["battle_background_asset_id"]] += 1
        self.music = {k: c.most_common(1)[0][0] for k, c in music.items()}
        self.default_bg = allbg.most_common(1)[0][0]
        self.default_music = music[0].most_common(1)[0][0]

    def map_background(self, rom, snes_map):
        ext = S.extended(rom, "map_properties")
        if snes_map < 416:
            b = rom.data[0x2D8F00 + 33 * snes_map + 2]
        elif ext and snes_map < ext[2]:
            b = rom.data[ext[0] + 33 * snes_map + 2]
        else:
            return None
        return self.bg.get(b & 0x7F)


# --- the port --------------------------------------------------------------------------------------

def port(van, mod, tables, encounters, messages, out_dir, log, profile=None):
    """Rows for the mod's new monsters and parties for its grown formations; {} for a mod without
    grown tables (every mod but those whose profile registers them)."""
    P.ADDED_ROWS.pop("monster", None)   # an earlier port's in this process (its new rows are its own)
    if not S.extended(mod, "monsters") or not S.extended(mod, "formations"):
        return {}
    import port as PT
    import port_resist as R
    import port_specials as SP
    import groups as G
    changed = collections.defaultdict(set)
    mo = tables["monster"]
    vmo = P.Table("monster")
    news = new_monsters(mod)
    art = match_art(mod, news)
    rand = random_monsters(mod)
    names = S.extended(mod, "monster_names") or []
    snames = S.extended(mod, "special_names") or []
    drop_slots = getattr(profile, "monster_drop_slots", None)
    own_drops = S.extended(mod, "drop_slots") or {}
    ag = G.GroupTable("attribute_group", "attribute_id", ["type_id"], tables.setdefault("attribute_group", P.Table("attribute_group")))
    cg = G.GroupTable("condition_group", "condition_id", ["type_id"], tables.setdefault("condition_group", P.Table("condition_group")))
    flag_groups = tables.setdefault("monster_flag_group", P.Table("monster_flag_group"))
    ab = tables.setdefault("ability", P.Table("ability"))
    content = tables.setdefault("content", P.Table("content"))
    arg = tables.setdefault("ability_random_group", P.Table("ability_random_group"))
    fgroups = SP.FunctionGroups(tables)
    specials = SP.pr_specials()
    content4 = {int(r["type_value"]): r for r in content if r["type_id"] == "4"}
    placeholders_ai = {}
    export = {"monsters": {}, "parties": {}}
    stats = collections.Counter()
    for e in news:
        kind, tmpl, size = art[e]
        pid = M.monster(e)
        raw = record(mod, "monsters", e)
        items = record(mod, "monster_items", e) if S.extended(mod, "monster_items") else b"\xff" * 4
        en = S.Enemy(e, names[e] if e < len(names) else "", raw, items)
        row = dict(vmo[tmpl + 1], id=str(pid))
        ai_from = tmpl
        if vmo[tmpl + 1]["boss"] == "1":       # a boss's script belongs to its own fight: a placeholder's
            ai_from = min((j for j in random_monsters(S.Rom(P.VANILLA_ROM)) if vmo.rows.get(j + 1, {}).get("boss") == "0"),
                          key=lambda j: (abs(int(vmo[j + 1]["lv"]) - en.level), j))
            row["script_id"] = vmo[ai_from + 1]["script_id"]
            placeholders_ai[e] = ai_from
        key = f"MSG_PORT_MONSTER_NAME_{pid}"
        row["mes_id_name"] = key
        messages[key] = en.name or messages.get(vmo[tmpl + 1]["mes_id_name"], "") or "?"
        for col, val in (("hp", en.hp), ("mp", en.mp), ("exp", en.exp), ("gill", en.gold), ("lv", en.level),
                         ("agility", en.speed), ("attack", en.vigor), ("ability_attack", en.magic),
                         ("defense", en.defense), ("ability_defense", en.mdef), ("evasion_rate", en.evade),
                         ("magic_evasion_rate", en.mblock), ("accuracy_rate", en.accuracy)):
            row[col] = str(val)
        if kind == "new":
            row["boss"] = "0" if e in rand else "1"     # a placeholder: a boss when only events fight it
        mo.rows[pid] = row
        ch = set()
        # undead (byte 18 bit 7): species bit 0 + the Undead flag (port_enemies' rule)
        undead = bool(raw[18] & 0x80)
        sp = int(row["species"])
        PT.setv(row, "species", sp | 1 if undead else sp & ~1, ch)
        gid = PT.flag_group_with(flag_groups, int(row["monster_flag_group_id"]), PT.UNDEAD_FLAG, undead, changed["monster_flag_group"])
        PT.setv(row, "monster_flag_group_id", gid, ch)
        # steals, drops
        (rate, d1, d2), (s1, s2) = PT.drop_fields(items)
        row["steal_content_id1"], row["steal_content_id2"] = str(s1), str(s2)
        if e in own_drops or drop_slots:   # the registry's (records the profile handed over), else the profile's
            PT.set_drop_slots(row, own_drops[e] if e in own_drops else drop_slots(e), ch)
        else:
            for k in range(1, 9):
                row[f"drop_content_id{k}"], row[f"drop_content_id{k}_value"] = "0", "0"
            row["drop_rate"] = str(rate)
            row["drop_content_id1"], row["drop_content_id1_value"] = str(d1), "1" if d1 else "0"
            row["drop_content_id2"], row["drop_content_id2_value"] = str(d2), "1" if d2 else "0"
        # elements, immunities, initial statuses (port_resist's tables)
        row["resistance_attribute"] = str(ag.find_or_create(R.elem_set([(raw[23], R.ABSORB), (raw[24], R.NULL), (raw[25], R.WEAK)])))
        row["resistance_condition"] = str(cg.find_or_create(R.cond_set(raw[20] | raw[21] << 8 | raw[22] << 16, R.ENEMY_IMMUNE, 24)))
        row["initial_condition"] = str(cg.find_or_create(R.cond_set(raw[27] | raw[28] << 8 | raw[29] << 16, R.ENEMY_INITIAL, 24)))
        # its special attack: an ability of its own, from the SNES byte (port_specials.build), named
        special = None
        src = specials.get(tmpl)
        if src is not None and src in ab.rows:
            aid = SPECIAL_BASE + e
            if aid in P.Table("ability").rows:
                raise ValueError(f"special {aid} would overwrite one of the game's abilities")
            arow = dict(ab[src], id=str(aid))
            built = SP.build(raw[31])
            if built:
                funcs, system, unblockable, mult = built
                arow["battle_function_group_id"] = str(fgroups.get(funcs))
                arow["system_id"] = system
                if unblockable:
                    arow["content_flag_group_id"] = SP.UNBLOCKABLE_FLAG
            ab.rows[aid] = arow
            changed["ability"].add(aid)
            crow = content4.get(src)
            if crow is not None:
                cid = max(content.rows) + 1
                skey = f"MSG_PORT_MONSTER_ATK_{aid}"
                text = snames[e] if e < len(snames) and snames[e] else messages.get(crow["mes_id_name"]) or P.messages().get(crow["mes_id_name"], "")
                content.rows[cid] = dict(crow, id=str(cid), type_value=str(aid), mes_id_name=skey)
                messages[skey] = text or "?"
                changed["content"].add(cid)
            special = {"ability": aid, "byte": raw[31], "multiplier": SP.multiplier(raw[31]),
                       "name": snames[e] if e < len(snames) else "", "rebuilt": bool(built)}
            stats["specials"] += 1
        # Sketch: a group of its own (port_skills' reading: EE Fight, EF the special)
        sk = record(mod, "sketches", e) if S.extended(mod, "sketches") else b""
        pr = []
        for x in sk:
            pr.append(FIGHT if x == EE else (special["ability"] if special else None) if x == EF else
                      None if x == NONE else M.spell(x))
        if sk and all(a is not None for a in pr):
            g = max(int(r["group_id"]) for r in arg) + 1
            for a in pr:
                rid = max(arg.rows) + 1
                arg.rows[rid] = {"id": str(rid), "group_id": str(g), "ability_id": str(a),
                                 "invocation_rate": str(100 // len(pr)), "condition_group_id": "0"}
                changed["ability_random_group"].add(rid)
            row["release_ability_random_group_id"] = str(g)
            stats["sketches"] += 1
        row["rage_ability_random_group_id"] = "0"
        P.ADDED_ROWS.setdefault("monster", {})[pid] = dict(row)
        changed["monster"].add(pid)
        stats[f"art {kind}"] += 1
        export["monsters"][e] = {"pr_id": pid, "name": en.name, "template": tmpl, "template_name": messages.get(
            vmo[tmpl + 1]["mes_id_name"]) or P.messages().get(vmo[tmpl + 1]["mes_id_name"], ""), "art": kind,
            "sprite_size": size, "ai": "template" if e not in placeholders_ai else f"placeholder {ai_from}",
            "boss": row["boss"], "special": special}
    changed["attribute_group"] |= ag.new_rows
    changed["condition_group"] |= cg.new_rows
    changed["function_group"] |= fgroups.changed

    # parties for the formations no random set needed: the mod's event battles fight them
    mp = tables["monster_party"]
    vmp = P.Table("monster_party")
    looks = Looks()
    event_maps = S.extended(mod, "event_maps") or {}
    event_bgs = S.extended(mod, "event_backgrounds") or {}   # {formation: the event battle's SNES background}
    flags = S.extended(mod, "formation_flags")
    made = []
    for f in ext_formations(mod):
        ids = E.party_ids(f, mp.rows)
        if ids:
            export["parties"][ids[0]] = f
            continue
        bg = looks.bg.get(event_bgs[f] & 0x3F) if f in event_bgs and event_bgs[f] & 0x3F != 0x3F else None   # (0x3F: the map's)
        bg = bg or next((b for m in event_maps.get(f, []) for b in [looks.map_background(mod, m)] if b), None)
        vrow = vmp.rows.get(M.party(f)) if f < 576 else None
        fl = mod.data[flags[0] + 4 * f:flags[0] + 4 * f + 4] if flags else mod.data[0x0F5900 + 4 * f:0x0F5900 + 4 * f + 4]
        mons = [e for e, _, _ in E.formation(mod, f)]
        boss = any(mo.rows.get(M.monster(e), {}).get("boss") == "1" for e in mons) or fl[3] & 1
        tmpl = dict(vmp[1], **(BOSS_PARTY if boss else EVENT_PARTY))
        tmpl["battle_background_asset_id"] = bg or (vrow["battle_background_asset_id"] if vrow else looks.default_bg)
        tmpl["battle_bgm_asset_id"] = looks.music.get(fl[3] >> 4, looks.default_music)
        pid = E.first_party_id(f)
        if pid in vmp.rows:
            raise ValueError(f"party {pid} would overwrite one of the game's")
        row = encounters.party_row(f, tmpl, pid)
        if any(mod.data[0x0F0000 + 32 * e + 19] & 0x08 for e in mons if e < 384) or \
                any(record(mod, "monsters", e)[19] & 0x08 for e in mons if e >= 384):
            row["not_escape"] = "2"
        mp.rows[pid] = row
        changed["monster_party"].add(pid)
        export["parties"][pid] = f
        made.append(f)
        stats["event parties"] += 1
        stats["event parties on the event's background (its battle's or its map's)" if bg else "event parties on a fallback background"] += 1
    map_packs = S.extended(mod, "map_packs") or {}
    if map_packs:
        export["map_sets"] = sets = map_sets(mod, tables, encounters, map_packs, looks, changed, log)
        name = S.extended(mod, "map_sets_file")
        if name:
            os.makedirs(out_dir, exist_ok=True)
            with open(os.path.join(out_dir, name), "w", encoding="utf-8") as fh:
                json.dump({"packs": sets["packs"], "maps": sets["maps"]}, fh, indent=1)
    log(f"monster ext: {len(news)} new monsters (PR ids {M.monster(news[0])}-{M.monster(news[-1])}), "
        f"{dict(stats)}; AI from a placeholder (boss templates): {sorted(placeholders_ai)}; "
        f"{len(made)} parties made for formations past 576 / with new monsters")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, EXPORT), "w", encoding="utf-8") as fh:
        json.dump(export, fh, indent=1)
    _STATE.clear()
    _STATE.update(van=van, mod=mod, tables=tables, export=export, out_dir=out_dir, ai_from=placeholders_ai)
    return {k: v for k, v in changed.items() if v}


_STATE = {}   # the last port's (for snes_ai_extend, which runs after port_ai)


def map_sets(mod, tables, encounters, map_packs, looks, changed, log):
    """PR monster sets for a mod's new maps (map_packs {SNES map: (pack, battle background)}): each map gets a set
    holding its pack's four formations on the map's own background (SNES background b = bg_ff6_<b + 1>, Looks):
    the set the encounter porter refilled with that pack where its look is the same, else a new one (SET_BASE + n,
    parties by EncounterPorter.party_for on a random battle's settings and music, the mod's party odds as weights).
    -> {"packs": {pack: the set most of its maps use}, "maps": {SNES map: set}, "made": [new set ids]}."""
    import port_encounter_rates as R
    ms, mp = tables["monster_set"], tables["monster_party"]
    pf = dict((p, f) for p, f in M.party_formation().items())
    for f in range(formation_count(mod)):
        for p in E.party_ids(f, mp.rows):
            pf[p] = f
    have = {}
    for sid, r in sorted(ms.rows.items()):
        ps = [int(r[f"monster_set{k}"] or 0) for k in range(1, 5)]
        if all(p in pf for p in ps):
            have.setdefault((tuple(sorted(pf[p] for p in ps)), mp.rows[ps[0]]["battle_background_asset_id"]), sid)
    odds = R.party_odds(mod)["map"]
    template = dict(P.Table("monster_party")[1], **RANDOM_PARTY,
                    battle_bgm_asset_id=looks.music.get(0, looks.default_music))
    maps, by_pack, made, empty = {}, collections.defaultdict(collections.Counter), [], []
    for m, (p, b) in sorted(map_packs.items()):
        forms = E.pack(mod, p)
        if any(not E.formation(mod, f) for f in forms):
            empty.append(m)          # an empty formation: no random battles there (as the encounter porter)
            continue
        bg = looks.bg.get(b & 0x7F) or looks.default_bg
        key = (tuple(sorted(forms)), bg)
        sid = have.get(key)
        if sid is None:
            sid = SET_BASE + 1 + len(made)
            if sid in P.Table("monster_set").rows:
                raise ValueError(f"monster set {sid} would overwrite one of the game's")
            row = {c: "0" for c in ms.columns}
            row["id"] = str(sid)
            look = dict(template, battle_background_asset_id=bg)
            for k, f in enumerate(forms, 1):
                pid = encounters.party_for(f, look)
                changed["monster_party"].add(pid)
                row[f"monster_set{k}"], row[f"monster_set{k}_rate"] = str(pid), str(odds[k - 1])
            ms.rows[sid] = row
            changed["monster_set"].add(sid)
            have[key] = sid
            made.append(sid)
        maps[m] = sid
        by_pack[p][sid] += 1
    packs = {p: c.most_common(1)[0][0] for p, c in sorted(by_pack.items())}
    log(f"  map sets: {len(maps)} new maps with random battles on {len(packs)} packs; {len(made)} sets made "
        f"({SET_BASE + 1}-{SET_BASE + len(made)}), {len(maps) - sum(1 for s in maps.values() if s in made)} maps on a set "
        f"the encounter porter refilled; no battles (empty formation): {empty}")
    return {"packs": packs, "maps": maps, "made": made}


class _FormationBytes:
    """rom.data for port_ai.party_slots, which reads formation f at E.FORMATIONS + 15 f: past 576 from the
    grown table (port_encounters.formation_raw); anything else as the image has it."""

    def __init__(self, rom):
        self.rom = rom

    def __getitem__(self, s):
        if isinstance(s, slice) and s.start is not None and s.start >= E.FORMATIONS and (s.start - E.FORMATIONS) % 15 == 0                 and s.stop == s.start + 15:
            return E.formation_raw(self.rom, (s.start - E.FORMATIONS) // 15)
        return self.rom.data[s]


def snes_ai_extend(sa, limit=512, formations_to=768):
    """The new monsters (384 to limit) and the grown formations' parties (576 to formations_to) in a mod's
    SNES AI data (port_ai's snes_ai dict, the kit's SnesAiHost; call it after port_ai, before the dict is
    written: profile_tedition's extra_data). Each new monster whose script the plugin can run: scripts[e]
    (the mod's script: snes_ai.script reads it through the profile's hook), battle/special (the template's
    Battle, its own special ability SPECIAL_BASE + e), weak, copies {PR id: e} (the host maps a PR monster to
    its SNES id through them), e in plugin, and its PR row on a shim the plugin answers (the template's shim
    when the plugin runs the template, else one with the same Battle: a shim only carries markers and a
    confused monster's Battle). Lines its scripts show join message_keys / messages as port_ai's do.
    formations {party: f} and party_slots / party_members for the parties of formations 576+. Monsters
    past `limit` (T-Edition EX's 512+) and formations past `formations_to` are another workstream's.
    Returns sa (changed in place)."""
    if not sa or not _STATE:
        return sa
    import battle_text
    import port_ai as PA
    import snes_ai as A
    van, mod, tables, export = _STATE["van"], _STATE["mod"], _STATE["tables"], _STATE["export"]
    mo, mp = tables["monster"], tables["monster_party"]
    plugin = set(sa.get("plugin", []))
    shims = {e: mo[e + 1]["script_id"] for e in plugin if e + 1 in mo.rows}
    copies = sa.setdefault("copies", {})
    on, kept = [], {}
    for e in sorted(export["monsters"]):
        info = export["monsters"][e]
        if e >= limit:
            continue
        main, counter = A.script(mod, e)
        why = PA.snes_ai_unsupported(main, counter)
        tmpl = info["template"]
        battle = sa["battle"].get(tmpl, 1)
        same = [j for j in sorted(shims) if sa["battle"].get(j) == battle]
        shim = tmpl if tmpl in shims else (same[0] if same else (min(shims) if shims else None))
        if why or shim is None:
            kept[e] = why or "no shim"
            continue
        raw = PA._ai_bytes(main) + PA._ai_bytes(counter)
        sa["scripts"][e] = raw.hex()
        sa["battle"][e] = battle
        sa["special"][e] = (info.get("special") or {}).get("ability") or sa["special"].get(tmpl, battle)
        w = record(mod, "monsters", e)[0x19]
        if w:
            sa.setdefault("weak", {})[e] = w
        i = 0
        while i < len(raw):
            if raw[i] == 0xF3 and i + 1 < len(raw):
                k = raw[i + 1]
                if k not in sa["message_keys"] and k not in sa["messages"] and k not in sa["unmapped_messages"]:
                    if k in battle_text.PR_KEYS:
                        sa["message_keys"][k] = battle_text.PR_KEYS[k]
                    elif k in battle_text.OWN_TEXT:
                        sa["messages"][k] = battle_text.OWN_TEXT[k]
                    else:
                        sa["unmapped_messages"].append(k)
            i += A.SIZES.get(raw[i], 1)
        pid = info["pr_id"]
        mo[pid]["script_id"] = shims[shim]
        copies[pid] = e
        plugin.add(e)
        info["ai"] = f"snes (shim of {shim})"
        on.append(e)
    for e, why in kept.items():
        export["monsters"][e]["ai"] += f"; plugin can't run its script: {why}"
    sa["plugin"] = sorted(plugin)
    forms = {}
    for f in range(576, min(formations_to, formation_count(mod))):
        for p in E.party_ids(f, mp.rows):
            forms[p] = f
    sa["formations"].update(forms)
    # slots: port_ai.party_slots takes a member's SNES id as its PR id - 1, so the parties holding new monsters
    # (576+, and those under 576 that hold them: port_ai's own pass got their slots wrong) go through rows
    # whose 1000 + e ids read as e + 1
    inv = {v: k for k, v in M.MONSTER_EXT.items()}
    redo = {}   # (0x1FF in a formation's slot: empty)
    for p, f in sa["formations"].items():
        if f >= formations_to or p not in mp.rows:
            continue
        raw = E.formation_raw(mod, f)
        if p in forms or (raw and any((raw[2 + s] | (raw[14] >> s & 1) << 8) in range(384, 511) for s in range(6))):
            redo[p] = f
    rows = {}
    for p in redo:
        r = dict(mp.rows[p])
        for k in range(1, 10):
            v = int(r.get(f"monster{k}") or 0)
            if v in inv:
                r[f"monster{k}"] = str(inv[v] + 1)
        rows[p] = r
    members = {}
    view = type("_Rom", (), {"data": _FormationBytes(mod)})()
    slots = PA.party_slots(view, type("_Rows", (), {"rows": rows})(), redo, members)
    for p in redo:
        sa.setdefault("party_slots", {}).pop(p, None)
        sa.setdefault("party_members", {}).pop(p, None)
    sa["party_slots"].update(slots)
    sa["party_members"].update(members)
    export["snes_ai"] = {"on_plugin": on, "kept": {e: why for e, why in kept.items()}, "parties": len(forms),
                         "slots_redone": len(redo)}
    folder = _STATE["out_dir"]
    if not os.path.isdir(folder) and folder.endswith(".new"):   # called after port.py swapped its output in
        folder = folder[:-4]
    if os.path.isdir(folder):
        with open(os.path.join(folder, EXPORT), "w", encoding="utf-8") as fh:
            json.dump(export, fh, indent=1)
    print(f"monster ext SNES AI: {len(on)} new monsters on their own scripts, {len(kept)} kept on PR scripts "
          f"({kept}); {len(forms)} parties of formations 576+ in formations, {len(slots)} of {len(redo)} parties' slots "
          f"with new monsters (re)made")
    return sa
