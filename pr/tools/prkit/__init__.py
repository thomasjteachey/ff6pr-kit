"""prkit: tooling shared by every Pixel Remaster mod in this project (FF1-FF6 PR).

    games      which PR games exist, where Steam put them, every path a tool needs
    data       read a game's extracted data (master CSV tables, message text)
    magicite   write and check Magicite mod folders
    mods       the mod manifest (pr/modkit.json): every mod, its game and its parts
    package    a player zip for any mod in the manifest
    deploy     build + install a mod on this PC (and the Steam Deck)
    bepinex    put BepInEx + Magicite into another PR game
    scaffold   start a new mod (plugin, data script, test, manifest entry)

Command line: .venv/Scripts/python tools/kit.py --help   (pr/MODDING.md has the guide)

Only developer tools import it (kit.py, package_mod.py, extract.py --game-id). The porter and the
Worlds Collide generator (prdata.py, port*.py, wc_*.py) never do, on purpose: the WC generator
bundle copies tools/*.py but not sub-folders into the player's game and must keep working there.
"""
import os

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the kit's tools/
KIT_PR = os.path.dirname(TOOLS)                                       # the kit's pr/ (plugin/PrKit)


def _host_pr():
    """The project's pr/ (its manifest, data, builds): the kit's own, or, when the kit is a mod
    repository's git submodule (<mod repo>/kit), the mod repository's pr/. FF6PR_ROOT overrides."""
    if os.environ.get("FF6PR_ROOT"):
        return os.path.normpath(os.environ["FF6PR_ROOT"])
    kit = os.path.dirname(KIT_PR)
    host = os.path.join(os.path.dirname(kit), "pr")
    return host if os.path.basename(kit) == "kit" and os.path.isdir(host) else KIT_PR


PR = _host_pr()
PROJECT = os.path.dirname(PR)
