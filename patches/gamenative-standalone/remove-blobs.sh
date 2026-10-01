#!/bin/sh
# Run from the root of a GameNative checkout, before or after applying 0002.
# Deletes the closed binaries that 0002-blob-free-build.patch stops referencing.
set -e
git rm -q \
  app/src/main/assets/redirect.tzst \
  app/src/main/jniLibs/arm64-v8a/libkgslshim.so \
  app/src/main/jniLibs/arm64-v8a/libsteambootstrap.so \
  app/src/main/lib/perfsdk-v1.0.0.jar \
  app/src/modern/assets/libredirect-bionic-wx-minimal.so \
  app/src/modern/assets/libredirect-bionic-wx.so
