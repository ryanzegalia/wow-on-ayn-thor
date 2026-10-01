#!/bin/bash
set -e
export JAVA_HOME="${JAVA_HOME:?set JAVA_HOME to a JDK 17}"
JC="$JAVA_HOME/bin/javac.exe"; KT="$JAVA_HOME/bin/keytool.exe"
BT="${ANDROID_HOME:?set ANDROID_HOME}/build-tools/35.0.0"
ANDJAR="$ANDROID_HOME/platforms/android-35/android.jar"
cd "$(dirname "$0")"

echo "=== javac ==="
rm -rf classes dexout classes.dex app.unaligned.apk app.aligned.apk wowlaunch.apk
mkdir -p classes dexout
"$JC" -source 8 -target 8 -bootclasspath "$ANDJAR" -cp "$ANDJAR" -d classes src/com/ff/wowlaunch/LaunchActivity.java 2>&1 | grep -viE "bootstrap class path|warning:" || true

echo "=== d8 ==="
"$BT/d8.bat" --release --lib "$ANDJAR" --output dexout classes/com/ff/wowlaunch/LaunchActivity.class
ls -la dexout/classes.dex

echo "=== aapt package ==="
"$BT/aapt.exe" package -f -M AndroidManifest.xml -I "$ANDJAR" -F app.unaligned.apk

echo "=== add dex ==="
cp dexout/classes.dex classes.dex
"$BT/aapt.exe" add app.unaligned.apk classes.dex

echo "=== keystore ==="
KS="$HOME/.android/debug.keystore"
if [ ! -f "$KS" ]; then
  mkdir -p "$HOME/.android"
  "$KT" -genkeypair -v -keystore "$KS" -storepass android -keypass android \
    -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 \
    -dname "CN=Android Debug,O=Android,C=US"
fi

echo "=== zipalign ==="
"$BT/zipalign.exe" -f 4 app.unaligned.apk app.aligned.apk

echo "=== apksigner ==="
"$BT/apksigner.bat" sign --ks "$KS" --ks-pass pass:android --key-pass pass:android \
  --out wowlaunch.apk app.aligned.apk

echo "=== verify ==="
"$BT/apksigner.bat" verify --print-certs wowlaunch.apk | head -3
ls -la wowlaunch.apk
echo "BUILD_OK"
