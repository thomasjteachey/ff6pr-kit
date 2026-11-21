"""Per-mod settings for the shared SNES -> Pixel Remaster porter (tools/port.py).

Everything in the porter works by diffing a modded FF6 ROM (US v1.0 layout)
against vanilla. A profile only says where the ROM is, where the Magicite mod
goes, and how to read the mod's own text and extras.
"""
import os

import prdata as P

PROJECT = os.path.normpath(os.path.join(P.ROOT, ".."))


class Profile:
    name = "generic"
    mod_name = "Generic"
    rom = None
    rage_odds = (50, 50)  # vanilla: each Rage attack half the time
    rename_all = False    # True: use the mod's names everywhere; False: only names/text the mod changed
    spell_bank_only = False  # True: espers teach nothing in battle (learn rate 0); spells come from
                             # the plugin's SP bank instead (BNW c2.asm "Remove learning spells")
    esper_learning = "snes"  # "snes": an esper's 5 (rate, spell) pairs, the PR's learn rate = the SNES
                             # rate (Ramuh Bolt x10 = 10); "bnw": BNW's 3 (SP cost, spell) pairs
    monster_names = False  # True: the mod's monster names onto the PR's (tools/port_names.py; with
                           # rename_all every monster's, else only those the mod renamed)
    character_names = False  # True: the mod's names for the 14 characters onto MSG_CHAR_NAME_01..14, for those
                             # it renamed (tools/port_names.port_character_names; Beyond Chaos's c, makeover)
    stat_cap = None  # e.g. 255: raise the PR's 128 caps on Vigor/Stamina/Speed/Magic/magic power
                     # (game_constant_int.csv). Caps are raised anyway where a monster needs it.

    @property
    def out(self):
        return os.path.join(P.ROOT, "mods", self.mod_name)

    def descriptions(self):
        """{"items": [...], "spells": [...], ...} in the mod's ROM, or None to keep the PR's text."""
        import bnw_text
        try:
            secs = bnw_text.sections(self.rom, only=("items", "spells", "lores"))
        except Exception:
            return None
        return secs

    def vanilla_descriptions(self):
        import bnw_text
        return bnw_text.sections(P.VANILLA_ROM,
                                 only=("items", "spells", "lores"))

    def esper_descriptions(self):
        return None

    def extra_data(self, rom):
        """Mod-specific data exported for a plugin (bnw_data.json etc.), or None."""
        return None

    def extra_messages(self, rom):
        """Extra text keys the mod's plugin uses ({key: text}), or None."""
        return None


class BeyondChaos(Profile):
    name = "beyond-chaos"
    mod_name = "BeyondChaos"

    @property
    def rom(self):
        import glob
        seeds = sorted(glob.glob(os.path.join(PROJECT, "build", "beyond-chaos", "*.sfc")))
        return seeds[-1] if seeds else None


class WorldsCollide(Profile):
    name = "worlds-collide"
    mod_name = "WorldsCollide"

    @property
    def rom(self):
        import glob
        seeds = sorted(glob.glob(os.path.join(PROJECT, "build", "worlds-collide", "*.sfc")))
        return seeds[-1] if seeds else None


class _Profiles(dict):
    """name -> profile. A mod repository's own profile (profile_<name>.py beside its tools, e.g.
    Brave New World's profile_bnw.py) is imported the first time it's asked for, so the kit
    itself knows no mod's settings."""

    def __missing__(self, name):
        import importlib
        try:
            module = importlib.import_module("profile_" + name.replace("-", "_"))
        except ImportError:
            raise KeyError(name) from None
        self[name] = module.PROFILE
        return self[name]


PROFILES = _Profiles({p.name: p for p in (BeyondChaos(), WorldsCollide())})
