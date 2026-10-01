#!/system/bin/sh
# One controller-friendly entry point. Legacy wowspan.sh/wowlaunch.sh and Direct prefix stay intact.
# Usage: wowgo.sh retail|classic|beta direct|bnet [numeric request id]
set -u
BASE=/data/adb/wow
ROOT=/storage/emulated/0/Games/WoW
SPAN=app.gamenative.span
FILES=/data/data/$SPAN/files
# My install's container ids (GameNative derives them per install). Change them to yours.
BNET_ID=1835007374
DIRECT_ID=1835007375
BNET_PREFIX=$FILES/imagefs/home/xuser-CUSTOM_GAME_$BNET_ID
DIRECT_PREFIX=$FILES/imagefs/home/xuser-CUSTOM_GAME_$DIRECT_ID
GAME_ROOT=/storage/emulated/0/Android/data/$SPAN/CustomGames
STATUS=$BASE/launch-status
LOCK=$BASE/launch.lock
GEN=$BASE/launch-generation
LOG=$BASE/wowgo.log
# Include x64 clients as well as ARM64, but never mistake WowVoiceProxy for the game.
CLIENT_PATTERN='(^|[\\/[:space:]])wow(classic|b|t)?([-_](arm64|64))?\.exe$'
# A reboot or a stopped watcher must not strand the picker on an old busy phase.
if [ "${1:-}" = --status ]; then
  [ "$(id -u)" = 0 ] || exit 77
  REQUEST=$(cat "$GEN" 2>/dev/null || printf 0)
  OWNER=$(cat "$LOCK/pid" 2>/dev/null || true)
  if ps -A -o NAME | grep -iqE "$CLIENT_PATTERN"; then
    printf 'running\nWoW is running\n%s\n' "$REQUEST"
  elif [ -n "$OWNER" ] && kill -0 "$OWNER" 2>/dev/null && (tr '\000' '\n' < "/proc/$OWNER/cmdline" | grep -qxF "$BASE/wowgo.sh"); then
    cat "$STATUS" 2>/dev/null || true
  elif [ -f "$STATUS" ] && head -1 "$STATUS" | grep -qE '^(error|finished)$'; then
    cat "$STATUS"
  else
    printf 'idle\nReady for adventure\n%s\n' "$REQUEST"
  fi
  exit 0
fi
FLAVOR=${1:-}
MODE=${2:-}
REQUEST=${3:-$(date +%s)}
case "$FLAVOR" in
  retail) DIR=_retail_; EXE=Wow-ARM64.exe; PRODUCT=wow; TITLE=Retail ;;
  classic) DIR=_classic_; EXE=WowClassic-ARM64.exe; PRODUCT=wow_classic; TITLE=Classic ;;
  beta) DIR=_classic_beta_; EXE=WowB-ARM64.exe; PRODUCT=wow_classic_beta; TITLE=Forever ;;
  *) exit 64 ;;
esac
case "$MODE" in direct|bnet) ;; *) exit 64 ;; esac
case "$REQUEST" in ''|*[!0-9]*) exit 64 ;; esac
[ "$(id -u)" = 0 ] || exit 77
umask 077
mkdir -p "$BASE"
log() { printf '%s %s\n' "$(date '+%F %T')" "$*" >> "$LOG"; }
status() {
  local current
  current=$(cat "$GEN" 2>/dev/null) || current=$REQUEST
  printf '%s\n%s\n%s\n' "$1" "$2" "$current" > "$STATUS.$$"
  if cmp -s "$STATUS.$$" "$STATUS"; then
    rm -f "$STATUS.$$"
  else
    mv -f "$STATUS.$$" "$STATUS"
    log "$1: $2"
  fi
}
# Android NAME, NOT ARGS: the Wine desktop keeps old executable names in its arguments.
client() { ps -A -o PID,UID,NAME 2>/dev/null | grep -iE "$CLIENT_PATTERN" | head -1; }
front() {
  local pkg ui paused
  pkg=$(pm list packages -U | awk -v id="$1" '$2=="uid:"id {sub(/^package:/,"",$1);print $1;exit}')
  case "$pkg" in app.gamenative|app.gamenative.span|app.gamenative.spantest|io.github.example.wowspan) ;; *) return 1 ;; esac
  am start -W --display 0 -n "$pkg/app.gamenative.MainActivity" -f 0x24000000 >/dev/null 2>&1 || return 1
  paused=$(ps -A -o UID,STAT,NAME | awk -v uid="$1" '$1==uid && $2~/^T/ && tolower($3)=="winhandler.exe" {print 1;exit}')
  if [ "$paused" = 1 ]; then
    # Manual suspend deliberately survives Activity.onResume. Use its real Resume control,
    # never an unconditional key into a live game, and never relaunch an existing container.
    ui=$BASE/resume-ui.$$
    if timeout 8 uiautomator dump "$ui" >/dev/null 2>&1 &&
       grep -q 'content-desc="Resume Game"' "$ui" &&
       grep -q "package=\"$pkg\"" "$ui" &&
       dumpsys activity activities 2>/dev/null | grep -q "topResumedActivity=.*$pkg/app.gamenative.MainActivity"; then
      input -d 0 keyevent KEYCODE_BUTTON_START
      log 'Resumed the existing GameNative session through its manual-resume control'
    else
      rm -f "$ui"
      return 1
    fi
    rm -f "$ui"
  fi
}
RUNNING=$(client)
if [ -n "$RUNNING" ]; then
  printf '%s\n' "$REQUEST" > "$GEN"
  status running 'WoW is already running'
  front "$(printf '%s\n' "$RUNNING" | awk '{print $2}')"
  exit 0
fi
# Android mksh closes extra descriptors across exec; stdin survives and is otherwise unused here.
# Kernel-held lock: no PID-reuse or mkdir/remove race, and reboot releases it automatically.
exec 0>"$BASE/launch.guard"
if ! /system/bin/flock -n 0 2>/dev/null; then
  sleep 1
  printf '%s\n' "$REQUEST" > "$GEN"
  OWNER=$(cat "$LOCK/pid" 2>/dev/null || true)
  if [ -z "$OWNER" ] || ! kill -0 "$OWNER" 2>/dev/null || ! (tr '\000' '\n' < "/proc/$OWNER/cmdline" | grep -qxF "$BASE/wowgo.sh"); then
    status error 'Could not acquire the launcher guard; no game was started'
    exit 1
  fi
  log 'Duplicate request attached to existing launch'
  if [ -f "$STATUS" ]; then
    P=$(sed -n '1p' "$STATUS"); M=$(sed -n '2p' "$STATUS"); status "$P" "$M"
  fi
  DUP_UID=$(pm list packages -U | awk '$1=="package:app.gamenative.span" {sub(/^uid:/,"",$2);print $2}')
  DUP_RUNNING=$(ps -A -o UID,NAME | awk -v uid="$DUP_UID" '$1==uid && tolower($2)=="winhandler.exe" {print 1;exit}')
  [ "$DUP_RUNNING" != 1 ] || front "$DUP_UID" || log 'Existing launch needs its visible Resume control'
  exit 0
fi
mkdir -p "$LOCK"
printf '%s\n' "$$" > "$LOCK/pid"
printf '%s\n' "$REQUEST" > "$GEN"
cleanup() { rm -f "$LOCK/pid" "$STATUS.$$"; rmdir "$LOCK" 2>/dev/null || true; }
trap cleanup EXIT
trap 'exit 130' INT TERM
fail() { status error "$1"; exit 1; }
[ ! -f "$LOG" ] || [ "$(wc -c < "$LOG")" -lt 131072 ] || mv -f "$LOG" "$LOG.previous"
status preparing "Preparing $TITLE"
[ -f "$ROOT/$DIR/$EXE" ] || fail "$TITLE's ARM64 client is missing"
[ -f "$BASE/wowlaunch.sh" ] || fail 'Shared preparation is not installed'
for FILE in overlay.wtf overlay-$FLAVOR.wtf GamePadConfig_Thor.json addons.list shared-sv.list; do
  [ -s "$ROOT/_mirror_/$FILE" ] || fail 'Shared controller configuration is incomplete'
done
SPAN_UID=$(pm list packages -U | awk '$1=="package:app.gamenative.span" {sub(/^uid:/,"",$2);print $2}')
[ -n "$SPAN_UID" ] || fail 'GameNative Span is not installed'
# Never inject a packet into another package's Wine session.
FOREIGN=$(ps -A -o UID,NAME | awk -v uid="$SPAN_UID" '$1!=uid && tolower($2)=="winhandler.exe" {print;exit}')
[ -z "$FOREIGN" ] || fail 'Close the other GameNative session first'
# Reusing an already-running Battle.net avoids destroying its signed-in session.
BNET_RUNNING=$(ps -A -o UID,NAME | grep -i 'Battle.net.exe$' || true)
if [ -n "$BNET_RUNNING" ]; then
  [ "$MODE" = bnet ] || fail 'Exit Battle.net before switching to Direct'
  printf '%s\n' "$BNET_RUNNING" | awk -v uid="$SPAN_UID" '$1!=uid {exit 1}' || fail 'Battle.net is open in another GameNative app'
fi
sh "$BASE/wowlaunch.sh" "$FLAVOR" --no-launch || fail 'Shared preparation failed; the game was not started'
for ADDON in FFSpan FFScale FFBinds Syndicator Baganator; do
  [ -s "$ROOT/$DIR/Interface/AddOns/$ADDON/$ADDON.toc" ] || fail "Missing $ADDON for $TITLE"
done
# Inherited beta window overrides stretched a 1920 render across the 4400 desktop.
# Defaults adapt to either desktop; never persist a fixed span width in the shared WTF.
CONFIG=$ROOT/$DIR/WTF/Config.wtf
DISPLAY_KEYS='^SET gx(Window|Maximize|FullscreenResolution|WindowedResolution) '
if [ "$FLAVOR" = beta ] && grep -qE "$DISPLAY_KEYS" "$CONFIG"; then
  mkdir -p "$BASE/backups/compat" || fail 'Could not prepare the display settings backup'
  [ -f "$BASE/backups/compat/beta-display.wtf" ] || cp -p "$CONFIG" "$BASE/backups/compat/beta-display.wtf" || fail 'Could not back up the display settings'
  cp -p "$CONFIG" "$CONFIG.ff-new" || fail 'Could not stage the display settings'
  sed -E "/$DISPLAY_KEYS/d" "$CONFIG" > "$CONFIG.ff-new" || fail 'Could not reset inherited display sizing'
  mv "$CONFIG.ff-new" "$CONFIG" || fail 'Could not apply desktop-adaptive sizing'
  log 'Removed inherited beta display overrides; using the current desktop size'
fi
if [ "$FLAVOR" = beta ]; then
  # Syndicator: my own copy also relaxes one English stat-label assert in its
  # Search/CheckItem.lua for Forever. Syndicator is All Rights Reserved, so that edit
  # isn't in this copy. docs/dual-screen.md says what it changes.
  # Forever exposes the housing button without its backend. Do not create a dead menu item.
  HOUSING_FILE=$ROOT/$DIR/Interface/AddOns/ConsolePort_Menu/Model/Buttons.lua
  HOUSING_OLD='if HousingMicroButton then _{'
  HOUSING_NEW='if HousingMicroButton and HousingFramesUtil and type(HousingFramesUtil.ToggleHousingDashboard) == "function" then _{'
  if [ -f "$HOUSING_FILE" ] && grep -qF "$HOUSING_OLD" "$HOUSING_FILE"; then
    mkdir -p "$BASE/backups/compat" || fail 'Could not prepare the beta addon backups'
    [ -f "$BASE/backups/compat/ConsolePort_Menu-Buttons.lua" ] || cp -p "$HOUSING_FILE" "$BASE/backups/compat/ConsolePort_Menu-Buttons.lua" || fail 'Could not back up the beta housing-button fix'
    cp -p "$HOUSING_FILE" "$HOUSING_FILE.ff-new" || fail 'Could not stage the beta housing-button fix'
    sed 's/if HousingMicroButton then _{/if HousingMicroButton and HousingFramesUtil and type(HousingFramesUtil.ToggleHousingDashboard) == "function" then _{/' "$HOUSING_FILE" > "$HOUSING_FILE.ff-new" || fail 'Could not prepare the beta housing-button fix'
    mv "$HOUSING_FILE.ff-new" "$HOUSING_FILE" || fail 'Could not apply the beta housing-button fix'
    log 'Applied the scoped Forever housing-button availability guard'
  fi
  # GetFlyoutInfo can succeed with no slot count. Require both known call sites to match;
  # unrelated success checks and unknown upstream revisions are never rewritten.
  FLYOUT_FILE=$ROOT/$DIR/Interface/AddOns/ConsolePort/Libs/External/LibActionButton-1.0/LibActionButton-1.0.lua
  FLYOUT_OLD='if success then'
  FLYOUT_NEW='if success and type(numSlots) == "number" then'
  if [ -f "$FLYOUT_FILE" ] && [ "$(awk '/local success, _, _, numSlots, isKnown = pcall\(GetFlyoutInfo, flyoutID\)/ {getline; if ($0 ~ /^[[:space:]]*if success then[[:space:]]*$/) n++} END {print n+0}' "$FLYOUT_FILE")" = 2 ]; then
    mkdir -p "$BASE/backups/compat" || fail 'Could not prepare the beta addon backups'
    [ -f "$BASE/backups/compat/ConsolePort-LibActionButton-1.0.lua" ] || cp -p "$FLYOUT_FILE" "$BASE/backups/compat/ConsolePort-LibActionButton-1.0.lua" || fail 'Could not back up the beta flyout-count fix'
    cp -p "$FLYOUT_FILE" "$FLYOUT_FILE.ff-new" || fail 'Could not stage the beta flyout-count fix'
    sed '/local success, _, _, numSlots, isKnown = pcall(GetFlyoutInfo, flyoutID)/{n;s/if success then/if success and type(numSlots) == "number" then/;}' "$FLYOUT_FILE" > "$FLYOUT_FILE.ff-new" || fail 'Could not prepare the beta flyout-count fix'
    mv "$FLYOUT_FILE.ff-new" "$FLYOUT_FILE" || fail 'Could not apply the beta flyout-count fix'
    log 'Applied the scoped Forever flyout numSlots-type guard'
  fi
fi
for D in _retail_ _classic_ _classic_beta_; do
  if [ -d "$ROOT/$D/Interface/AddOns/Offhand" ]; then
    mkdir -p "$ROOT/$D/Interface/_disabled" || fail 'Could not park Offhand'
    mv "$ROOT/$D/Interface/AddOns/Offhand" "$ROOT/$D/Interface/_disabled/Offhand-$(date +%s)" || fail 'Could not park Offhand'
  fi
done
# Glassy compatibility: only the selected install. Its source lives under a second Glassy/
# directory (verified on-device). Retail's SecureHook replays an already-completed native anchor;
# Classic's RawHook needs its original call-through. Drop only the retail cosmetic +5 adjustment.
# Require exactly one of each old site, or exactly one of each new site; never half-patch a fork.
# Glassy ships CRLF line endings: lines are compared with the CR stripped and rewritten keeping it
# (Android's grep -x, unlike the PC's, does not ignore a trailing CR).
GLASSY_FILE=$ROOT/$DIR/Interface/AddOns/Glassy/Glassy/Components/ChatDock.lua
GLASSY_HOOK_OLD='  if not self:IsHooked(self.scrollFrame, "SetPoint") then'
GLASSY_REPLAY_OLD='  if bottomPoint then'
GLASSY_HOOK_NEW='  if Constants.ENV ~= "retail" and not self:IsHooked(self.scrollFrame, "SetPoint") then'
GLASSY_REPLAY_NEW='  if Constants.ENV ~= "retail" and bottomPoint then'
CR=$(printf '\r')
glassy_shape() {
  for want in "$GLASSY_HOOK_OLD" "$GLASSY_REPLAY_OLD" "$GLASSY_HOOK_NEW" "$GLASSY_REPLAY_NEW"; do
    printf '%s:' "$(tr -d "$CR" < "$1" | grep -Fxc "$want" || true)"
  done
}
if [ -f "$GLASSY_FILE" ]; then
  case "$(glassy_shape "$GLASSY_FILE")" in
    1:1:0:0:)
      mkdir -p "$BASE/backups/compat" || fail 'Could not prepare the Glassy addon backups'
      [ -f "$BASE/backups/compat/Glassy-ChatDock-$DIR.lua" ] || cp -p "$GLASSY_FILE" "$BASE/backups/compat/Glassy-ChatDock-$DIR.lua" || fail 'Could not back up the Glassy anchor-replay fix'
      cp -p "$GLASSY_FILE" "$GLASSY_FILE.ff-new" || fail 'Could not stage the Glassy anchor-replay fix'
      sed -e 's/^  if not self:IsHooked(self\.scrollFrame, "SetPoint") then\(['"$CR"']*\)$/  if Constants.ENV ~= "retail" and not self:IsHooked(self.scrollFrame, "SetPoint") then\1/' \
          -e 's/^  if bottomPoint then\(['"$CR"']*\)$/  if Constants.ENV ~= "retail" and bottomPoint then\1/' \
          "$GLASSY_FILE" > "$GLASSY_FILE.ff-new" || fail 'Could not prepare the Glassy anchor-replay fix'
      [ "$(glassy_shape "$GLASSY_FILE.ff-new")" = 0:0:1:1: ] || fail 'Glassy staged patch did not verify'
      mv "$GLASSY_FILE.ff-new" "$GLASSY_FILE" || fail 'Could not apply the Glassy anchor-replay fix'
      log "Applied the scoped Glassy retail anchor-replay guard ($DIR)"
      ;;
    0:0:1:1:) ;; # already patched
    *) log "Skipped unrecognized Glassy anchor guards ($DIR); source left untouched" ;;
  esac
elif [ -d "$ROOT/$DIR/Interface/AddOns/Glassy" ]; then
  log "Skipped unrecognized Glassy source layout ($DIR); source left untouched"
fi
if [ "$MODE" = direct ]; then
  [ -f "$DIRECT_PREFIX/.container" ] || fail 'The isolated Direct launcher has not been prepared'
  [ -d "$GAME_ROOT/WoWDirect" ] || fail 'Direct launcher folder is missing'
  # Only the new wrapper changes; the original Direct prefix and its launch code are never edited.
  printf '@echo off\r\nset HODLL=libwow64fex.dll\r\nstart "" "B:\\%s\\%s"\r\n' "$DIR" "$EXE" > "$GAME_ROOT/WoWDirect/launch.bat" || fail 'Could not select the Direct client'
  ID=$DIRECT_ID
else
  [ -f "$BNET_PREFIX/.container" ] || fail 'The Battle.net launcher has not been prepared'
  [ -s "$BASE/exec-$FLAVOR.bin" ] || fail 'The Battle.net launch command is missing'
  ID=$BNET_ID
fi
START=$(date +%s)
LOGDIR=$(readlink -f "$BNET_PREFIX/.wine/drive_c/users/xuser/AppData/Local/Battle.net/Logs")
# Second-instance requests create newer logs without auth state. Follow the live main
# process's open log, not whichever file was most recently touched on disk.
bnet_log() {
  local pid path
  for pid in $(ps -A -o PID,UID,NAME | awk -v uid="$SPAN_UID" '$2==uid && tolower($0)~/battle.net.exe$/ {print $1}'); do
    path=$(readlink /proc/"$pid"/fd/* 2>/dev/null | grep -F "$LOGDIR/battle.net-" | head -1)
    case "$path" in "$LOGDIR"/battle.net-*.log) ;; *) continue ;; esac
    [ -f "$path" ] && grep -qE '\[(BNLogin|LoginController|UnifiedAuth)\]' "$path" || continue
    printf '%s\n' "$path"
    return 0
  done
  return 1
}
if [ -z "$BNET_RUNNING" ]; then
  [ -z "$(client)" ] || fail 'WoW started elsewhere; this launch was stopped'
  am force-stop "$SPAN"
  status starting "Opening $TITLE with $MODE"
  am start --display 0 -n "$SPAN/app.gamenative.MainActivity" -a app.gamenative.LAUNCH_GAME \
    --ei app_id "$ID" --es game_source CUSTOM_GAME -f 0x24000000 >> "$LOG" 2>&1 || fail 'GameNative did not accept the launch'
else
  front "$SPAN_UID" || fail 'GameNative is paused; press its Resume button, then retry'
fi
SELECTED=0
LAST_SELECT=0
SENT=0
LAST_SEND=0
LOGIN_AT=0
CURRENT_LOG=
SEEN_PID=
while [ $(( $(date +%s) - START )) -lt 300 ]; do
  NOW=$(date +%s)
  RUNNING=$(client)
  if [ -n "$RUNNING" ]; then
    SEEN_PID=$(printf '%s\n' "$RUNNING" | awk '{print $1}')
    OWNER_UID=$(printf '%s\n' "$RUNNING" | awk '{print $2}')
    [ "$OWNER_UID" = "$SPAN_UID" ] || fail 'A different GameNative session started WoW'
    printf '%s\n' "$RUNNING" | grep -iqF "$EXE" || fail 'Battle.net opened a different WoW edition'
    status running "$TITLE is running"
    log "Native client pid=$SEEN_PID startup_seconds=$((NOW-START)) mode=$MODE"
    break
  fi
  if [ "$MODE" = bnet ]; then
    CANDIDATE=$(bnet_log)
    if [ "$CANDIDATE" != "$CURRENT_LOG" ]; then LOGIN_AT=0; SELECTED=0; LAST_SELECT=0; fi
    CURRENT_LOG=$CANDIDATE
    if [ -n "$CURRENT_LOG" ]; then
      AUTH=$(grep -E '\[BNLogin\].*(Logged into Battle.net successfully|Disconnected from Battle.net)' "$CURRENT_LOG" | tail -1)
      if printf '%s\n' "$AUTH" | grep -q 'Logged into Battle.net successfully'; then
        [ "$LOGIN_AT" != 0 ] || LOGIN_AT=$NOW
      else
        LOGIN_AT=0
        SELECTED=0
        LAST_SELECT=0
      fi
      if [ "$LOGIN_AT" = 0 ]; then
        status signin 'Finish signing in to Battle.net'
      else
        # ProductState lines are deltas. Retain the latest explicit playable value,
        # not the last update-completed event (a later permission check can revoke it).
        PLAYABLE=$(grep -F "InstallState ($PRODUCT):" "$CURRENT_LOG" | tr -d '\r' |
          grep -E '(^| )playable=[01]( |$)' | tail -1)
        if ! printf '%s\n' "$PLAYABLE" | grep -qE '(^| )playable=1( |$)'; then
          status updating "Battle.net is checking $TITLE's files"
          if [ "$FLAVOR" = beta ] && [ "$SELECTED" -lt 2 ] && [ $((NOW-LOGIN_AT)) -ge 3 ] && [ $((NOW-LAST_SELECT)) -ge 25 ]; then
            # launch_uid selects/prioritizes Forever but does not launch it. Its genuine
            # launch family is WoWF, sent below only after current auth and playable=1.
            [ -s "$BASE/select-beta.bin" ] || fail 'The Forever selection command is missing'
            timeout 4 toybox nc -u -w1 -q 1 -W 2 127.0.0.1 7946 < "$BASE/select-beta.bin" >> "$LOG" 2>&1 || log 'Forever selection transport timed out'
            SELECTED=$((SELECTED+1)); LAST_SELECT=$NOW
          fi
        elif [ $((NOW-LOGIN_AT)) -ge 15 ] && [ "$SENT" -lt 2 ] && [ $((NOW-LAST_SEND)) -ge 25 ]; then
          status launching "Launching $TITLE"
          timeout 4 toybox nc -u -w1 -q 1 -W 2 127.0.0.1 7946 < "$BASE/exec-$FLAVOR.bin" >> "$LOG" 2>&1 || log 'EXEC transport timed out; observing client before any retry'
          SENT=$((SENT+1)); LAST_SEND=$NOW
        fi
      fi
    fi
    if [ $((NOW-START)) -gt 45 ] && ! ps -A -o NAME | grep -iq 'Battle.net.exe$'; then
      fail 'Battle.net exited before launching WoW'
    fi
  fi
  sleep 2
done
[ -n "$SEEN_PID" ] || fail 'Launch timed out. Battle.net was left open; finish sign-in or its update, then retry.'
# Only after the actual native client exits cleanly may its idle Wine desktop be closed.
while ps -p "$SEEN_PID" -o NAME 2>/dev/null | grep -iqE "$CLIENT_PATTERN"; do sleep 3; done
sleep 2
[ -z "$(client)" ] || exit 0
if ! ps -A -o NAME | grep -iq 'Battle.net.exe$'; then am force-stop "$SPAN"; fi
status finished 'Ready for another adventure'
am start --display 0 -n com.ff.wowspan/.LaunchActivity -f 0x24000000 >/dev/null 2>&1
