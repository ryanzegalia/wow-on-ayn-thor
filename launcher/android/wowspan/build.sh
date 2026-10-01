#!/bin/bash
# Builds wowspan.apk with the bare Android SDK tools (no Gradle). Written for Git Bash on
# Windows, hence the .exe/.bat tool names. On Linux or macOS drop those suffixes.
set -euo pipefail
export JAVA_HOME="${JAVA_HOME:?set JAVA_HOME to a JDK 17}"
JC="$JAVA_HOME/bin/javac.exe"; KT="$JAVA_HOME/bin/keytool.exe"
BT="${ANDROID_HOME:?set ANDROID_HOME}/build-tools/36.0.0"
ANDJAR="$ANDROID_HOME/platforms/android-36/android.jar"
cd "$(dirname "$0")"

printf '=== javac ===\n'
mkdir -p classes dexout
rm -f classes/com/ff/wowspan/*.class
# Package every nested class, and fail the build on compiler errors.
"$JC" --release 8 -cp "$ANDJAR" -d classes src/com/ff/wowspan/*.java

printf '=== d8 ===\n'
"$BT/d8.bat" --release --min-api 24 --lib "$ANDJAR" --output dexout classes/com/ff/wowspan/*.class

# The tile pictures (assets/*.jpg) and the icon (res/drawable/app_icon.png) are not in this
# repo. The app draws plain tiles without the pictures. Without an icon, build from a copy of
# the manifest that has no icon line, so Android shows its default icon. aapt only accepts a
# manifest file named AndroidManifest.xml, so the copy goes in its own folder.
mkdir -p assets
MANIFEST=AndroidManifest.xml
if [ ! -f res/drawable/app_icon.png ]; then
  mkdir -p build-manifest
  sed '/android:icon=/d' AndroidManifest.xml > build-manifest/AndroidManifest.xml
  MANIFEST=build-manifest/AndroidManifest.xml
fi

printf '=== aapt package ===\n'
"$BT/aapt.exe" package -f -M "$MANIFEST" -A assets -S res -I "$ANDJAR" -F app.unaligned.apk
cp dexout/classes.dex classes.dex
"$BT/aapt.exe" add app.unaligned.apk classes.dex

# Android only updates an installed app signed with the same key. If an older build is
# installed with another key, uninstall it first.
KS="$HOME/.android/debug.keystore"
if [ ! -f "$KS" ]; then
  mkdir -p "$HOME/.android"
  "$KT" -genkeypair -v -keystore "$KS" -storepass android -keypass android \
    -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 \
    -dname "CN=Android Debug,O=Android,C=US"
fi
printf '=== zipalign and sign ===\n'
"$BT/zipalign.exe" -f 4 app.unaligned.apk app.aligned.apk
"$BT/apksigner.bat" sign --ks "$KS" --ks-pass pass:android --key-pass pass:android --out wowspan.apk app.aligned.apk
"$BT/apksigner.bat" verify --print-certs wowspan.apk
printf 'BUILD_OK\n'
