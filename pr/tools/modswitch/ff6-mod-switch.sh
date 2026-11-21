#!/bin/bash
# Switch FINAL FANTASY VI PR between the project's mods, all installed, one active: Worlds Collide,
# Brave New World, Beyond Chaos, T-Edition. Installed on the Steam Deck as
# ~/.local/share/ff6pr-mods/ff6-mod-switch.sh by tools/modswitch/install.sh, whose library tiles
# ("FINAL FANTASY VI - Worlds Collide", "... - Brave New World", "... - Beyond Chaos", "... - T-Edition")
# run it with --launch.
#
#   ff6-mod-switch.sh wc|bnw|bc|ted [--launch] [--dry-run]   make that mod the active one (then start FF6
#                                                            through Steam; --dry-run: only say what would move)
#   ff6-mod-switch.sh status                                 print the active mod and the shelved ones
#
# A mod is its plugin folder (BepInEx/plugins/<Mod>) and its Magicite folder
# (FINAL FANTASY VI_Data/StreamingAssets/Magicite/<Mod>); T-Edition has only the Magicite folder until
# its plugin exists. The inactive mods' folders wait in BepInEx/mod-shelf/<Mod> and
# BepInEx/mod-shelf/magicite/<Mod>, where neither BepInEx nor Magicite loads anything (the shelf
# pr/tools/deploy.sh and deck_push.sh use). Switching only moves folders; nothing is deleted. Saves are
# untouched: each mod has its own save files (PrKit ModSaves).
# Nothing moves while the game is running; the launch then just brings the running game up.
set -u
APPID=1173820
MODS="WorldsCollide BraveNewWorld BeyondChaos TEdition"
state="$HOME/.local/share/ff6pr-mods"
mkdir -p "$state"
dry=0
log() { [ $dry = 1 ] || printf '%s %s\n' "$(date -Is)" "$*" >> "$state/switch.log"; echo "$*"; }

find_game() {
  [ -n "${FF6_GAME:-}" ] && { echo "$FF6_GAME"; return; }
  local lib vdf="$HOME/.local/share/Steam/steamapps/libraryfolders.vdf"
  for lib in "$HOME/.local/share/Steam" $(sed -n 's/^[[:space:]]*"path"[[:space:]]*"\(.*\)"/\1/p' "$vdf" 2>/dev/null); do
    [ -d "$lib/steamapps/common/FINAL FANTASY VI PR/BepInEx" ] && { echo "$lib/steamapps/common/FINAL FANTASY VI PR"; return; }
  done
}
GAME="$(find_game)"
[ -n "$GAME" ] || { log "FINAL FANTASY VI PR with BepInEx not found"; exit 1; }
P=BepInEx/plugins; S=BepInEx/mod-shelf; SM=BepInEx/mod-shelf/magicite
M="FINAL FANTASY VI_Data/StreamingAssets/Magicite"
cd "$GAME" || exit 1

active() { local m; for m in $MODS; do { [ -d "$P/$m" ] || [ -d "$M/$m" ]; } && echo "$m"; done; }
shelved() {
  local m
  for m in $MODS; do
    if ! [ -d "$P/$m" ] && ! [ -d "$M/$m" ] && { [ -d "$S/$m" ] || [ -d "$SM/$m" ]; }; then echo "$m"; fi
  done
}
# installed (active or shelved): its Magicite folder, and its plugin folder unless it has none yet
installed() {
  { [ -d "$M/$1" ] || [ -d "$SM/$1" ]; } || return 1
  [ "$1" = TEdition ] || [ -d "$P/$1" ] || [ -d "$S/$1" ]
}

mod=""; launch=0
for a in "$@"; do
  case "$a" in
    wc|WorldsCollide) mod=WorldsCollide ;;
    bnw|BraveNewWorld) mod=BraveNewWorld ;;
    bc|BeyondChaos) mod=BeyondChaos ;;
    ted|TEdition) mod=TEdition ;;
    status) echo "active: $(echo $(active)); shelved: $(echo $(shelved))"; exit 0 ;;
    --launch) launch=1 ;;
    --dry-run) dry=1 ;;
    *) mod=""; break ;;
  esac
done
[ -n "$mod" ] || { sed -n '8,10p' "$0"; exit 1; }
[ $dry = 1 ] && launch=0

failed=0
move() {   # <from> <to>: the folder to its other place (a stale copy already there replaced)
  if [ $dry = 1 ]; then echo "  would move $1 -> $2"; return; fi
  rm -rf "$2" && mkdir -p "$(dirname "$2")" && mv "$1" "$2" || { log "could not move $1 to $2"; failed=1; }
}
if pgrep -f 'FINAL FANTASY VI[.]exe' >/dev/null; then
  log "the game is running ($(active | tr '\n' ' ')active): nothing moved"
elif ! installed "$mod"; then
  log "$mod isn't installed here (pr/tools/deck_push.sh or deploy.sh puts it in): nothing moved"
  launch=0
else
  for o in $MODS; do
    [ "$o" = "$mod" ] && continue
    [ -d "$P/$o" ] && move "$P/$o" "$S/$o"
    [ -d "$M/$o" ] && move "$M/$o" "$SM/$o"
  done
  { [ -d "$P/$mod" ] || [ ! -d "$S/$mod" ]; } || move "$S/$mod" "$P/$mod"
  [ -d "$M/$mod" ] || move "$SM/$mod" "$M/$mod"
  if [ $dry = 1 ]; then echo "dry run: $mod would be active, the others on the shelf; nothing moved"
  elif [ $failed = 1 ]; then log "switch to $mod incomplete (see above): active now: $(active | tr '\n' ' ')"; launch=0
  else log "$mod active (the others on the shelf)"; fi
fi

if [ $launch = 1 ]; then
  # Steam starts the game a moment after this tile's own process has ended, as the normal game
  # (its cloud saves, playtime, controller layout). A fixed unit name: a second press while one is
  # pending does nothing. Same method as the Ivalice ReMixed tile (ivalice-remixed docs/STEAM_DECK.md).
  unset LD_PRELOAD LD_LIBRARY_PATH
  systemd-run --user --quiet --collect --unit=ff6pr-mods-play --on-active=3 \
      --timer-property=AccuracySec=50ms \
      -p EnvironmentFile=-/run/user/"$(id -u)"/gamescope-environment \
      /usr/bin/steam -ifrunning steam://rungameid/$APPID \
    || log "could not schedule the game's start (systemd-run status $?)"
fi
[ $failed = 0 ]
