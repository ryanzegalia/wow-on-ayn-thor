#!/bin/bash
# Install a locally built Turnip into GameNative on the Thor as an adrenotools
# driver, and point the WoW container at it.
#
#   deploy_driver.sh <local libvulkan_freedreno.so> "<Driver Name>"
#
# GameNative expects  files/contents/adrenotools/<Driver Name>/{libvulkan_freedreno.so,meta.json}
# and the container's graphicsDriverConfig carries  version=<Driver Name>.
#
# TRAP: if the .so fails to dlopen (e.g. it references a bionic symbol newer
# than the device's Android 13), adrenotools SILENTLY falls back to the stock
# Adreno blob.  That looks like "the driver loaded but nothing changed".
# ALWAYS confirm the driver string DXVK reports after launching.
set -euo pipefail

# Values specific to my install and build.  Set yours before running.
#   CID             the WoW container id.  GameNative assigns it when you add the game
#                   as a custom game, so yours will be different (see docs/launcher.md).
#   APP_UID         the Android user GameNative runs as.  It owns the app's data dir:
#                     adb shell su -c 'ls -ld /data/user/0/app.gamenative'
#   DRIVER_VERSION  the version GameNative shows for the driver.  Set it to the Mesa
#                   version you built (the VERSION file in the Mesa checkout).
CID=CUSTOM_GAME_1285328983
APP_UID=u0_a143
DRIVER_VERSION=26.1.0

ADB="${ADB:-adb}"
# Prefer the USB serial. Android randomizes the wifi MAC per network, so the Thor's LAN ip
# changes when it switches networks and a saved ip:5555 goes "offline".
S="${THOR_SERIAL:-${THOR_ADB:?set THOR_SERIAL to the Thor adb serial or ip:port}}"
export MSYS_NO_PATHCONV=1

SO=${1:?usage: deploy_driver.sh <libvulkan_freedreno.so> "<Driver Name>"}
NAME=${2:?usage: deploy_driver.sh <libvulkan_freedreno.so> "<Driver Name>"}
DIR="/data/user/0/app.gamenative/files/contents/adrenotools/$NAME"

echo "### stopping GameNative"
"$ADB" -s "$S" shell "am force-stop app.gamenative" >/dev/null

echo "### pushing $(basename "$SO")"
"$ADB" -s "$S" push "$SO" /data/local/tmp/libvulkan_freedreno.so | tail -1

META="$(dirname "$SO")/ff_meta.json"
cat > "$META" <<EOF
{
  "schemaVersion": 1,
  "name": "$NAME",
  "description": "built from mesa source, API 33 (Android 13)",
  "author": "self-built",
  "packageVersion": "1",
  "vendor": "Mesa",
  "driverVersion": "$DRIVER_VERSION",
  "minApi": 28,
  "libraryName": "libvulkan_freedreno.so"
}
EOF
"$ADB" -s "$S" push "$META" /data/local/tmp/ff_meta.json | tail -1

echo "### installing into GameNative contents"
"$ADB" -s "$S" shell "su -c '
  mkdir -p \"$DIR\"
  cp /data/local/tmp/libvulkan_freedreno.so \"$DIR/libvulkan_freedreno.so\"
  cp /data/local/tmp/ff_meta.json \"$DIR/meta.json\"
  chown -R $APP_UID:$APP_UID \"$DIR\"
  chmod 771 \"$DIR\"
  chmod 771 \"$DIR/libvulkan_freedreno.so\" \"$DIR/meta.json\"
  chcon -R u:object_r:app_data_file:s0 \"$DIR\" 2>/dev/null || true
  ls -laZ \"$DIR\"
  md5sum \"$DIR/libvulkan_freedreno.so\"
'"

echo "### pointing the WoW container at it"
cd "$(dirname "$0")/../.."
python tools/gn_patch_container.py "$CID" \
  "graphicsDriverConfig=vulkanVersion=1.3,version=$NAME,blacklistedExtensions=,maxDeviceMemory=0,presentMode=mailbox,syncFrame=0,disablePresentWait=0,resourceType=auto,bcnEmulation=auto,bcnEmulationType=compute,bcnEmulationCache=0,gpuName=Device,adrenotoolsTurnip=1" \
  | tail -2

echo
echo "### done. Now LAUNCH and confirm the driver string in logcat:"
echo "    grep 'Found device' in the DXVK output. It must NOT say the old driver."
