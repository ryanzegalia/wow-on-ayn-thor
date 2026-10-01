#!/system/bin/sh
# wowspan.sh -- launch retail WoW in the dual-screen GameNative fork (app.gamenative.span) with
# the SAME per-launch prep the stock tiles get.
#
# Lives at /data/adb/wow/wowspan.sh (copy it there by hand, wow_mirror.py doesn't). The
# "WoW Dual Screen" tile (com.ff.wowspan) runs it detached as root in the global mount namespace:
#     su --mount-master -c 'setsid sh /data/adb/wow/wowspan.sh &'
#
# The prep is NOT duplicated here: it is wowlaunch.sh's own --no-launch mode
# (launcher/scripts/wowlaunch.sh), which runs steps 2-6 (Config.wtf cvar overlay,
# GamePadConfig_Thor.json, shared addons, newest-wins SavedVariables, per-character
# ConsolePort_Bar .ffbar) and exits BEFORE it touches the stock app's container. The fork keeps
# its own container pinned to retail, so nothing here re-points anything.
#
# Guard: never prep or launch while a WoW client runs in EITHER app (a second client on the same
# account kicks the first, and a force-stop loses SavedVariables). Foreground the owner instead --
# wowlaunch.sh's own guard would foreground the stock app even when the fork owns the client.
# Then (span-only) it parks the Offhand addon if it reappeared (centre-game, see below).
# Log: /sdcard/wowlaunch.log (tag [span]).

SPAN=app.gamenative.span
STOCK=app.gamenative
APP_ID=1285328983
LAUNCHER=/data/adb/wow/wowlaunch.sh
LOG=/sdcard/wowlaunch.log

log() { echo "$(date '+%m-%d %H:%M:%S') [span] $*" >> "$LOG"; }
front() { am start --display 0 -n "$1/app.gamenative.MainActivity" >/dev/null 2>&1; }

# Match the process NAME, never ARGS (explorer.exe/winhandler.exe carry the exe path in theirs).
OWNER=$(ps -A -o USER,NAME 2>/dev/null | grep -iE 'wow[a-z]*-arm64\.exe$' | head -1 | awk '{print $1}')
if [ -n "$OWNER" ]; then
  if [ "$OWNER" = "$(stat -c %U /data/data/$SPAN)" ]; then
    log "WoW already running in the fork -> foreground only"; front "$SPAN"
  else
    log "WoW already running in the STOCK app ($OWNER) -> foreground it, not launching the fork"; front "$STOCK"
  fi
  exit 0
fi

log "start"
if [ -f "$LAUNCHER" ]; then
  sh "$LAUNCHER" retail --no-launch || log "prep exited $? (launching anyway)"
else
  log "MISSING $LAUNCHER -- launching without prep"
fi

# Offhand is RETIRED for span mode (2026-09-23, centre-game): the fork shows canvas x 620..2540 on
# the top screen and FFSpan centres WorldFrame there, so WoW's own centre (freelook cursor,
# crosshair, ConsolePort bars, dialogs) is the top screen's centre. Offhand's left-game layout no
# longer fits, and it reset WorldFrame and rewrote mouse CVars at every login for me. FFSpan
# refuses to centre while Offhand is loaded, so if an install brings it back, park it again
# (reversible: the folder is moved, never deleted).
PARK=/storage/emulated/0/Games/WoW/_parked-addons
for FL in _retail_ _classic_ _classic_beta_; do
  AO=/storage/emulated/0/Games/WoW/$FL/Interface/AddOns/Offhand
  [ -d "$AO" ] || continue
  DST=$PARK/$FL/Offhand
  [ -d "$DST" ] && DST=$DST.$(date +%Y%m%d-%H%M%S)
  mkdir -p "$PARK/$FL" && mv "$AO" "$DST" && log "parked Offhand ($FL) -> $DST"
done

# The action stays app.gamenative.LAUNCH_GAME for the fork too: GameNative's IntentLaunchManager
# matches that literal string (not <applicationId>.LAUNCH_GAME), and the fork's patches don't touch it.
am start --display 0 -n "$SPAN/app.gamenative.MainActivity" -a app.gamenative.LAUNCH_GAME \
  --ei app_id $APP_ID --es game_source CUSTOM_GAME -f 0x24000000 >/dev/null 2>&1
log "launched retail in $SPAN"

# Quit = back to the launcher. GameNative keeps its (black) Wine desktop up after WoW exits, so
# Game Menu -> Exit Game looked like nothing happened (2026-09-23 07:10). Wait for the fork's client
# to come up, then for it to go away, and close the fork. The WoW process is gone by then, so every
# SavedVariable is already on disk; force-stop only drops the idle Wine desktop.
SPAN_UID=$(stat -c %U /data/data/$SPAN)
span_wow() { ps -A -o USER,NAME 2>/dev/null | grep -iE 'wow[a-z]*-arm64\.exe$' | grep "^$SPAN_UID "; }
(
  i=0
  while [ -z "$(span_wow)" ] && [ $i -lt 600 ]; do sleep 2; i=$((i + 2)); done
  [ -n "$(span_wow)" ] || { log "no WoW client in the fork after 10 min -- exit watcher gave up"; exit 0; }
  while [ -n "$(span_wow)" ]; do sleep 3; done
  sleep 2
  [ -z "$(span_wow)" ] && pidof $SPAN >/dev/null && { log "WoW exited -> closing $SPAN"; am force-stop $SPAN; }
) </dev/null >/dev/null 2>&1 &
