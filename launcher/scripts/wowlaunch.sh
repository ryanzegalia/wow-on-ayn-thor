#!/system/bin/sh
# wowlaunch.sh <retail|classic|beta> [--no-launch]
#
# THE one launcher for every WoW flavor on the Thor. Deployed to /data/adb/wow/wowlaunch.sh by
# tools/wow_mirror.py; run as root in the global mount namespace:
#     su --mount-master -c 'sh /data/adb/wow/wowlaunch.sh classic'
# The com.ff.wowlaunch tiles (launcher/android/wowlaunch) call exactly that.
#
# Every launch, for the chosen flavor, it:
#   1. refuses to touch anything while a WoW client is running (a force-stop would throw away
#      every SavedVariable change since the last logout or /reload).
#   2. re-asserts the shared cvar overlay in that flavor's Config.wtf (account, D3D11, gamepad,
#      UI scale, preset...). Only non-preset cvars live there: preset children revert on load.
#   3. copies GamePadConfig_Thor.json (the Nintendo face-button fix) into its WTF.
#   4. mirrors the shared addon set from the master flavor (_retail_) when a .toc differs.
#   5. mirrors account-wide SavedVariables NEWEST-WINS across flavors, so a ConsolePort/Glassy
#      change made in any flavor reaches the others on their next launch.
#   6. gives every character that has never had it the tuned ConsolePort_Bar layout (cluster
#      width 1360, per-character in ConsolePort) once -- marker file .ffbar.
#   7. points the ONE GameNative container at the flavor's ARM64 exe and re-pins the driver.
#   8. fires GameNative's LAUNCH_GAME intent.
# One container = one Wine prefix = one patched ntdll/winevulkan/DXVK for all flavors.
# Log: /sdcard/wowlaunch.log

FLAVOR="${1:-retail}"
NO_LAUNCH=0; [ "$2" = "--no-launch" ] && NO_LAUNCH=1

ROOT=/storage/emulated/0/Games/WoW
MIRROR=$ROOT/_mirror_
MASTER=_retail_
# The WTF folder is named after the GAME account, not the Battle.net id: Classic writes
# WTF/Account/<GAME ACCOUNT>/ (verified 2026-09-22). Before I fixed this the launcher used the
# Battle.net id, so no seeded SV and no .ffbar ever reached Classic (no radial keyboard,
# 1200-wide glyph cluster). Set WOW_ACCOUNT to your game account name (e.g. WOW1).
ACCOUNT="${WOW_ACCOUNT:-WOW1}"
APP_ID=1285328983
CONTAINER=/data/data/app.gamenative/files/imagefs/home/xuser-CUSTOM_GAME_$APP_ID/.container
DRIVER='Turnip FF 26.1.0 patched v2'
LOG=/sdcard/wowlaunch.log
TMP=/data/local/tmp/wowlaunch.$$

log() { echo "$(date '+%m-%d %H:%M:%S') [$FLAVOR] $*" >> "$LOG"; }
gn_front() { am start -n app.gamenative/.MainActivity >/dev/null 2>&1; }

case "$FLAVOR" in
  retail)  DIR=_retail_;       EXE=Wow-ARM64.exe ;;
  classic) DIR=_classic_;      EXE=WowClassic-ARM64.exe ;;
  beta)    DIR=_classic_beta_; EXE=WowB-ARM64.exe ;;
  *) log "unknown flavor '$FLAVOR'"; exit 1 ;;
esac

log "start"

# 1. never kill a running client
# Match the process NAME (argv[0]), never ARGS: after a clean exit GameNative keeps its Wine
# desktop up, and explorer.exe / winhandler.exe carry the game's exe path in their ARGS
# (2026-09-22: that made a dead client look alive and kept every watcher waiting forever).
wow_alive() { ps -A -o NAME 2>/dev/null | grep -iE 'wow[a-z]*-arm64\.exe$' | head -1; }
RUNNING=$(wow_alive)
if [ -n "$RUNNING" ]; then
  log "WoW already running -> foreground only: $RUNNING"
  gn_front; exit 0
fi
if [ ! -f "$ROOT/$DIR/$EXE" ]; then
  log "MISSING $ROOT/$DIR/$EXE -- stage it with wow_sync.py"
  gn_front; exit 1
fi

WTF=$ROOT/$DIR/WTF
mkdir -p "$WTF"

# 2. cvar overlay: replace the SET line if present, append it if not; everything else untouched
CFG=$WTF/Config.wtf
[ -f "$CFG" ] || : > "$CFG"
cat "$MIRROR/overlay.wtf" "$MIRROR/overlay-$FLAVOR.wtf" 2>/dev/null > "$TMP.ov"
# WoW writes Config.wtf with CRLF; keep it CRLF so an unchanged file compares equal.
awk 'BEGIN { ORS="\r\n" } { sub(/\r$/, "") }
     NR==FNR { if ($1=="SET") { ov[$2]=$0; ord[++n]=$2 } next }
     { if ($1=="SET" && ($2 in ov)) { if (!($2 in seen)) print ov[$2]; seen[$2]=1 } else print }
     END { for (i=1; i<=n; i++) if (!(ord[i] in seen)) print ov[ord[i]] }' "$TMP.ov" "$CFG" > "$TMP.cfg"
if [ -s "$TMP.cfg" ] && ! cmp -s "$TMP.cfg" "$CFG"; then
  cat "$TMP.cfg" > "$CFG" && log "Config.wtf overlay applied"
fi

# 3. controller mapping
if ! cmp -s "$MIRROR/GamePadConfig_Thor.json" "$WTF/GamePadConfig_Thor.json"; then
  cp "$MIRROR/GamePadConfig_Thor.json" "$WTF/GamePadConfig_Thor.json" && log "GamePadConfig_Thor.json updated"
fi

# 4. shared addons from the master flavor (a changed .toc = a new version)
if [ "$DIR" != "$MASTER" ]; then
  mkdir -p "$ROOT/$DIR/Interface/AddOns"
  while read -r A; do
    [ -n "$A" ] || continue
    SRC=$ROOT/$MASTER/Interface/AddOns/$A
    DST=$ROOT/$DIR/Interface/AddOns/$A
    [ -d "$SRC" ] || { log "addon $A missing in $MASTER"; continue; }
    if ! cmp -s "$SRC/$A.toc" "$DST/$A.toc"; then
      rm -rf "$DST" && cp -r "$SRC" "$DST" && log "addon $A mirrored"
    fi
  done < "$MIRROR/addons.list"
fi

# 5. account-wide SavedVariables, newest wins (seed copies in _mirror_/sv are the fallback).
#    Sources are every account folder of every flavor, so a flavor on a different game account
#    still feeds the mirror. ConsolePort_Cursor.lua is NOT shared: its UI stack lists
#    flavor-specific windows (Classic QuestLogFrame/SpellBookFrame vs retail Garrison/Delves).
#    Targets are EVERY game-account folder of this flavor (retail/beta still hold numeric
#    folders named after an older account), plus $ACCOUNT pre-created so a
#    flavor's first login already finds the seeds. WTF/Account/SavedVariables is not
#    an account.
mkdir -p "$WTF/Account/$ACCOUNT/SavedVariables"
for ACC in "$WTF/Account"/*/; do
  [ "$(basename "$ACC")" = SavedVariables ] && continue
  SVDIR=${ACC}SavedVariables
  mkdir -p "$SVDIR"
  while read -r F; do
    [ -n "$F" ] || continue
    NEWEST=$(ls -t "$ROOT"/_*_/WTF/Account/*/SavedVariables/"$F" "$MIRROR/sv/$F" 2>/dev/null | head -1)
    [ -n "$NEWEST" ] || continue
    if [ "$NEWEST" != "$SVDIR/$F" ] && ! cmp -s "$NEWEST" "$SVDIR/$F"; then
      cp -p "$NEWEST" "$SVDIR/$F" && log "SV $F <- ${NEWEST#$ROOT/} -> $(basename "$ACC")"
    fi
  done < "$MIRROR/shared-sv.list"
done

# 6. per-character ConsolePort_Bar layout, once per character, in every account folder
for C in "$WTF/Account"/*/*/*/; do
  [ -d "${C}SavedVariables" ] || continue
  [ -f "${C}.ffbar" ] && continue
  cp "$MIRROR/ConsolePort_Bar.lua" "${C}SavedVariables/ConsolePort_Bar.lua" && : > "${C}.ffbar" \
    && log "bar layout -> ${C#$WTF/Account/}"
done

rm -f "$TMP.ov" "$TMP.cfg"
[ "$NO_LAUNCH" = 1 ] && { log "prepared (--no-launch)"; exit 0; }

# 7. point the one container at this flavor and re-pin the driver. Edit via a temp copy and
#    cat it back so the file keeps GameNative's owner and SELinux label.
am force-stop app.gamenative
sleep 1
if [ -f "$CONTAINER" ]; then
  sed -e "s#\"executablePath\":\"[^\"]*\"#\"executablePath\":\"$DIR\\\\/$EXE\"#" \
      -e "s#\"graphicsDriverVersion\":\"[^\"]*\"#\"graphicsDriverVersion\":\"$DRIVER\"#" \
      -e "s#\(\"graphicsDriverConfig\":\"[^\"]*,version=\)[^,\"]*#\1$DRIVER#" \
      "$CONTAINER" > "$TMP.ct" && cat "$TMP.ct" > "$CONTAINER"
  rm -f "$TMP.ct"
  grep -q "\"executablePath\":\"$DIR\\\\/$EXE\"" "$CONTAINER" || log "FAILED to set executablePath"
  grep -q ",version=$DRIVER" "$CONTAINER" || log "FAILED to pin driver"
else
  log "container missing: $CONTAINER"
fi

# 8. launch
am start -n app.gamenative/.MainActivity -a app.gamenative.LAUNCH_GAME \
  --ei app_id $APP_ID --es game_source CUSTOM_GAME -f 0x24000000 >/dev/null 2>&1
log "launched $DIR/$EXE"

# 9. health check for the session: DXVK's "pipeline: -13" lines (needs DXVK_LOG_LEVEL=info in the
#    container envVars). -13 = a pipeline the driver failed to build, i.e. effects that never draw.
#    The count must be 0 on "Turnip FF 26.1.0 patched v2" (see docs/graphics.md).
#    One capture file per launch, and a session token: a watcher left over from an earlier launch
#    retires quietly instead of reporting on (or killing) this session's capture.
SESSION=$(date +%m%d-%H%M%S)
TOKF=/data/local/tmp/wowlaunch.session
CAP=/data/local/tmp/wowlaunch-$FLAVOR-$SESSION.dxvk.log
echo "$SESSION" > "$TOKF"
ls -t /data/local/tmp/wowlaunch-*.dxvk.log 2>/dev/null | tail -n +6 | xargs rm -f 2>/dev/null
(
  logcat -v time -T 1 2>/dev/null | grep --line-buffered -iE 'dxvk|pipeline' > "$CAP" &
  GP=$!
  sleep 120
  while [ "$(cat "$TOKF" 2>/dev/null)" = "$SESSION" ] &&
        [ -n "$(wow_alive)" ]; do sleep 20; done
  kill "$GP" 2>/dev/null   # the grep; its logcat dies on the next write (SIGPIPE)
  if [ "$(cat "$TOKF" 2>/dev/null)" = "$SESSION" ]; then
    log "session over: $(grep -c ': -13' "$CAP") x -13 in DXVK output ($CAP)"
  fi
) </dev/null >/dev/null 2>&1 &
