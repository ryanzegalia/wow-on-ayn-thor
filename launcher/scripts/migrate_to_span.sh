#!/usr/bin/env bash
# migrate_to_span.sh -- copy the WoW GameNative setup from the stock app (app.gamenative)
# into the side-by-side span fork (app.gamenative.span), so the fork finds the imagefs,
# the WoW wine container, the patched proton, the patched Turnip driver and the library
# entry without running its own first-launch UI.
#
# Based on reading GameNative's source
# (GameNative aa03ebc0: ImageFsInstaller.installIfNeededFuture checks imagefs/.winlator/
# .img_version (=31) + .variant, ContainerManager scans imagefs/home/xuser-*, ContentsManager
# scans contents/<type>/*/profile.json, the library card comes from
# PrefManager.customGameManualFolders in files/datastore/PluviaPreferences.preferences_pb).
#
# NEVER writes under the stock app's dirs: guard_dst() refuses any destination that is not
# under /data/data/app.gamenative.span or /data/user/0/app.gamenative.span.
#
# Usage:  ./migrate_to_span.sh --dry-run     (prints every device command, runs only reads)
#         ./migrate_to_span.sh               (does it)
#         THOR=<serial|ip:port> ./migrate_to_span.sh
#
# Preconditions (checked, abort if unmet): fork installed and NEVER launched (no imagefs /
# container yet in its data dir); no WoW client running. Only then both apps are force-stopped.

set -euo pipefail

ADB="${ADB:-adb}"
THOR="${THOR:-${THOR_SERIAL:?set THOR_SERIAL to the Thor adb serial or ip:port}}"

SRC_PKG="app.gamenative"
DST_PKG="app.gamenative.span"
CONTAINER_ID="CUSTOM_GAME_1285328983"
DRIVER_NAME="Turnip FF 26.1.0 patched v2"
PROTON_DIR="proton-10.0-arm64ec"

SRC_DATA="/data/data/${SRC_PKG}"
DST_DATA="/data/data/${DST_PKG}"
DST_USER0="/data/user/0/${DST_PKG}"
SRC_CTR="${SRC_DATA}/files/imagefs_shared/home/xuser-${CONTAINER_ID}"
DST_CTR="${DST_DATA}/files/imagefs_shared/home/xuser-${CONTAINER_ID}"

# Idempotent rewrite: app.gamenative and app.gamenative.span both become app.gamenative.span.
SED_EXPR='s#app\.gamenative(\.span)?#app.gamenative.span#g'

DRY_RUN=0
FROM=start
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --from=patch) FROM=patch ;;   # resume after a completed copy+rewrite (skips precheck/copy)
        --thor=*) THOR="${arg#--thor=}" ;;
        -h|--help) sed -n '1,22p' "$0"; exit 0 ;;
        *) echo "Unknown argument: $arg" >&2; exit 1 ;;
    esac
done
[ "$DRY_RUN" = "1" ] && echo "[dry-run] device WRITES are printed, not run (reads still run)."

guard_dst() {
    case "$1" in
        "$DST_DATA"|"$DST_DATA"/*|"$DST_USER0"|"$DST_USER0"/*) return 0 ;;
        *) echo "REFUSING non-fork destination: $1" >&2; exit 1 ;;
    esac
}

# Read-only probe (runs even in dry-run). The remote command must not contain single quotes.
rd() { MSYS_NO_PATHCONV=1 "$ADB" -s "$THOR" shell "su -c '$1'" </dev/null; }
# Device write (printed in dry-run). The remote command must not contain single quotes.
wr() {
    if [ "$DRY_RUN" = "1" ]; then printf '[dry-run] su -c: %s\n' "$1"; return 0; fi
    MSYS_NO_PATHCONV=1 "$ADB" -s "$THOR" shell "su -c '$1'" </dev/null
}
cp_g()    { guard_dst "$2"; wr "cp -a \"$1\" \"$2\""; }
mkdir_g() { guard_dst "$1"; wr "mkdir -p \"$1\""; }
relink_g(){ guard_dst "$1"; wr "rm -f \"$1\" && ln -s \"$2\" \"$1\""; }
sed_g()   { guard_dst "$1"; wr "test -f \"$1\" && sed -i -E \"${SED_EXPR}\" \"$1\" || true"; }

step_precheck() {
    echo "== precheck =="
    rd "test -d ${DST_DATA} && echo FORK_INSTALLED" | grep -q FORK_INSTALLED \
        || { echo "ABORT: ${DST_PKG} is not installed." >&2; exit 1; }
    if rd "test -e ${DST_DATA}/files/imagefs -o -e ${DST_CTR} && echo EXISTS" | grep -q EXISTS; then
        echo "ABORT: the fork already has an imagefs or WoW container (was it launched?)." >&2
        echo "       Refusing to cp -a on top of it (cp would nest a second copy)." >&2
        exit 1
    fi
    for p in "${SRC_CTR}/.container" "${SRC_DATA}/files/imagefs_shared/proton/${PROTON_DIR}" \
             "${SRC_DATA}/files/contents/adrenotools/${DRIVER_NAME}" "${SRC_DATA}/files/imagefs/.winlator/.img_version"; do
        rd "test -e \"$p\" && echo OK" | grep -q OK || { echo "ABORT: missing source $p" >&2; exit 1; }
    done
    # Windows exes show up in ps NAME as e.g. A:\_retail_\Wow-ARM64.exe. Do not match
    # com.ff.wowlaunch or the wow-* Magisk daemons.
    local running
    running="$(rd "ps -A -o NAME" | grep -iE 'wow[a-z]*-arm64\.exe' || true)"
    if [ -n "$running" ]; then echo "ABORT: WoW is running: $running" >&2; exit 1; fi
    echo "precheck OK"
}

step_forcestop() {
    echo "== force-stop both apps =="
    wr "am force-stop ${SRC_PKG}"
    wr "am force-stop ${DST_PKG}"
}

step_copy() {
    echo "== copy (about 5.3 GB) =="
    mkdir_g "${DST_DATA}/files"
    cp_g "${SRC_DATA}/files/imagefs" "${DST_DATA}/files/imagefs"
    mkdir_g "${DST_DATA}/files/imagefs_shared/proton"
    cp_g "${SRC_DATA}/files/imagefs_shared/proton/${PROTON_DIR}" "${DST_DATA}/files/imagefs_shared/proton/${PROTON_DIR}"
    mkdir_g "${DST_CTR}"
    cp_g "${SRC_CTR}/.container" "${DST_CTR}/.container"
    cp_g "${SRC_CTR}/.wine" "${DST_CTR}/.wine"
    # Small guest-home dotdirs (NOT .cache, NOT .wine.* / .container.bak-* backups, NOT Logs).
    for d in .startmenu .config .local .fex-emu; do
        guard_dst "${DST_CTR}/${d}"
        wr "test -e \"${SRC_CTR}/${d}\" && cp -a \"${SRC_CTR}/${d}\" \"${DST_CTR}/${d}\" || true"
    done
    mkdir_g "${DST_DATA}/files/contents/adrenotools"
    cp_g "${SRC_DATA}/files/contents/adrenotools/${DRIVER_NAME}" "${DST_DATA}/files/contents/adrenotools/${DRIVER_NAME}"
    cp_g "${SRC_DATA}/files/profiles" "${DST_DATA}/files/profiles"
    mkdir_g "${DST_DATA}/shared_prefs"
    cp_g "${SRC_DATA}/shared_prefs/${SRC_PKG}_preferences.xml" "${DST_DATA}/shared_prefs/${DST_PKG}_preferences.xml"
    mkdir_g "${DST_DATA}/files/datastore"
    cp_g "${SRC_DATA}/files/datastore/PluviaPreferences.preferences_pb" "${DST_DATA}/files/datastore/PluviaPreferences.preferences_pb"
    cp_g "${SRC_DATA}/files/datastore/WinlatorPreferences.preferences_pb" "${DST_DATA}/files/datastore/WinlatorPreferences.preferences_pb"
    cp_g "${SRC_DATA}/storage" "${DST_DATA}/storage"
}

step_rewrite() {
    echo "== rewrite absolute package references (fork copies only) =="
    sed_g "${DST_CTR}/.container"
    sed_g "${DST_CTR}/.wine/user.reg"
    sed_g "${DST_CTR}/.wine/system.reg"
    sed_g "${DST_CTR}/.wine/userdef.reg"
    # Text files in the small dotdirs that mention the stock package.
    for d in .config .local .fex-emu; do
        guard_dst "${DST_CTR}/${d}"
        wr "test -d \"${DST_CTR}/${d}\" && grep -rlI app.gamenative \"${DST_CTR}/${d}\" | while read -r f; do sed -i -E \"${SED_EXPR}\" \"\$f\"; done || true"
    done
    relink_g "${DST_DATA}/files/imagefs/home" "${DST_USER0}/files/imagefs_shared/home"
    relink_g "${DST_DATA}/files/imagefs/opt/proton-10.0-arm64ec-2" "${DST_USER0}/files/imagefs_shared/proton/${PROTON_DIR}"
    guard_dst "${DST_DATA}/files/imagefs/opt/wine"
    wr "test -L \"${DST_DATA}/files/imagefs/opt/wine\" && rm -f \"${DST_DATA}/files/imagefs/opt/wine\" && ln -s \"${DST_DATA}/files/imagefs/opt/proton-10.0-ffpatch-arm64ec-1\" \"${DST_DATA}/files/imagefs/opt/wine\" || true"
    relink_g "${DST_CTR}/.wine/dosdevices/e:" "${DST_DATA}/storage"
    relink_g "${DST_CTR}/.wine/dosdevices/z:" "${DST_USER0}/files/imagefs"
}

step_patch_container() {
    echo "== span settings in the fork's .container copy =="
    if [ "$DRY_RUN" = "1" ]; then
        echo "[dry-run] would set screenSize=3160x1080, extraData.spanDisplay=true, executablePath=_retail_/Wow-ARM64.exe"
        return 0
    fi
    local tmp; tmp="$(mktemp -d)"
    # Pull via a world-readable temp copy (adb pull cannot read app data directly).
    wr "cp \"${DST_CTR}/.container\" /data/local/tmp/span_container.json && chmod 644 /data/local/tmp/span_container.json"
    local wtmp; wtmp="$(cygpath -w "$tmp")"   # adb.exe is a Windows binary: give it a Windows local path
    MSYS_NO_PATHCONV=1 "$ADB" -s "$THOR" pull /data/local/tmp/span_container.json "${wtmp}\c.json" </dev/null >/dev/null
    python - "$tmp/c.json" <<'PYEOF'
import json, sys
p = sys.argv[1]
d = json.load(open(p, encoding="utf-8"))
d["screenSize"] = "3160x1080"
d["executablePath"] = "_retail_/Wow-ARM64.exe"
x = d.get("extraData")
if not isinstance(x, dict):
    x = {}
x["spanDisplay"] = "true"
d["extraData"] = x
json.dump(d, open(p, "w", encoding="utf-8"), separators=(",", ":"))
print("patched:", d["screenSize"], d["executablePath"], x)
PYEOF
    MSYS_NO_PATHCONV=1 "$ADB" -s "$THOR" push "${wtmp}\c.json" /data/local/tmp/span_container.json </dev/null >/dev/null
    wr "cp /data/local/tmp/span_container.json \"${DST_CTR}/.container\" && rm -f /data/local/tmp/span_container.json"
    rm -rf "$tmp"
}

step_perms() {
    echo "== ownership + SELinux (copied dirs only) =="
    local uid
    uid="$(rd "stat -c %u ${DST_DATA}" | tr -d '\r\n')"
    [ -n "$uid" ] || { echo "ABORT: cannot read fork uid" >&2; exit 1; }
    echo "fork uid = ${uid}"
    for p in "${DST_DATA}/files" "${DST_DATA}/shared_prefs" "${DST_DATA}/storage"; do
        guard_dst "$p"
        wr "chown -R -h ${uid}:${uid} \"$p\""
    done
    guard_dst "${DST_DATA}"
    wr "restorecon -RF \"${DST_DATA}\""
}

step_verify() {
    echo "== verify =="
    [ "$DRY_RUN" = "1" ] && { echo "[dry-run] skipping verify"; return 0; }
    echo "-- pinslot ntdll: prefix (stock vs fork) --"
    rd "md5sum \"${SRC_CTR}/.wine/drive_c/windows/system32/ntdll.dll\" \"${DST_CTR}/.wine/drive_c/windows/system32/ntdll.dll\""
    echo "-- pinslot ntdll: proton (stock vs fork) --"
    rd "find \"${SRC_DATA}/files/imagefs_shared/proton/${PROTON_DIR}\" \"${DST_DATA}/files/imagefs_shared/proton/${PROTON_DIR}\" -path \"*aarch64-windows/ntdll.dll\" -exec md5sum {} +"
    echo "-- sizes --"
    rd "du -sh \"${DST_DATA}/files/imagefs\" \"${DST_DATA}/files/imagefs_shared/proton/${PROTON_DIR}\" \"${DST_CTR}/.wine\" \"${DST_DATA}/storage\""
    echo "-- stale links (should print nothing) --"
    rd "find \"${DST_DATA}/files/imagefs\" \"${DST_CTR}\" -maxdepth 4 -type l -lname \"*/app.gamenative/*\" 2>/dev/null | head -20" || true
    echo "-- span fields --"
    rd "grep -o -E \"screenSize.{0,14}|spanDisplay.{0,10}|executablePath.{0,30}\" \"${DST_CTR}/.container\""
    echo "-- owner --"
    rd "stat -c \"%u %n\" \"${DST_DATA}/files/imagefs\" \"${DST_CTR}/.container\" \"${DST_CTR}/.wine\""
}

if [ "$FROM" = "start" ]; then
    step_precheck
    step_forcestop
    step_copy
    step_rewrite
else
    echo "== resume from patch: checking no WoW running and the copy exists =="
    if rd "ps -A -o NAME" | grep -iqE 'wow[a-z]*-arm64\.exe'; then echo "ABORT: WoW is running" >&2; exit 1; fi
    rd "test -f ${DST_CTR}/.container -a -d ${DST_DATA}/files/imagefs && echo OK" | grep -q OK || { echo "ABORT: no copied container/imagefs to resume on" >&2; exit 1; }
    wr "am force-stop ${DST_PKG}"
fi
step_patch_container
step_perms
step_verify
echo "DONE. Launch: am start -n ${DST_PKG}/app.gamenative.MainActivity -a app.gamenative.LAUNCH_GAME --ei app_id 1285328983 --es game_source CUSTOM_GAME"
