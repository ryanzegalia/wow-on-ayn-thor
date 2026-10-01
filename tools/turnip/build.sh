#!/bin/bash
# Build Turnip (Mesa freedreno Vulkan) for Android arm64 on a Linux PC, and
# package it as an adrenotools driver the Thor's GameNative can load.
#
#   bash build.sh [--patch] [--clean]     (on the Linux build machine)
#
# --patch  revert local changes under src/ in the checkout, then apply
#          $ROOT/patches/*.patch (copy patches/mesa/ff-turnip.patch there)
# --clean  wipe the build dir and reconfigure from scratch
#
# Expects (it downloads nothing):
#   ~/wow-turnip/src                   a Mesa git checkout. The driver I run was built
#                                      from tag mesa-26.1.0 (commit 1d7b6318b9).
#   ~/wow-turnip/android-aarch64.txt   a copy of android-aarch64.txt, with its
#                                      pkg_config_libdir pointed at an empty directory
#   ~/wow-turnip/patches/*.patch       only needed for --patch
#   the Android NDK in ~/android-ndk-r27c, or NDK=<path to your NDK>
#
# Output: ~/wow-turnip/out/libvulkan_freedreno.so  +  turnip-ff-<ver>-ffpatched.zip
#         (turnip-ff-<ver>-stock.zip without --patch)
#
# WHY -Dandroid-strict=false: the option DEFAULTS TO TRUE, which defines ANDROID_STRICT and
# makes Mesa's vk_common_EnumerateDeviceExtensionProperties() filter the advertised device
# extensions through vk_android_allowed_device_extensions.  That silently strips the 13
# Vulkan-1.4-promoted KHR extensions (load_store_op_none, maintenance5/6, index_type_uint8,
# line_rasterization, shader_float_controls2, dynamic_rendering_local_read, ...).  DXVK 3.x
# hard-requires VK_KHR_load_store_op_none, so with the default the driver builds, loads and
# reports itself correctly, and DXVK then refuses it with
#   Skipping: Device does not support required feature 'khrLoadStoreOpNone'
#   DXVK: No adapters found
# The driver's own supported_extensions table STILL lists them.  Only ENUMERATION is filtered,
# which is why dumping the table in tu_device.cc looks fine.  Diagnosed on an AYN Thor
# 2026-09-20.
#
# WHY API 33: the Thor is Android 13.  A newer platform level pulls in bionic
# symbols A13 lacks, dlopen fails, and adrenotools SILENTLY falls back to the
# stock Adreno blob, which looks like "built fine, bug unchanged".  Always
# confirm the driver version string after deploying.
set -euo pipefail

ROOT=~/wow-turnip
SRC=$ROOT/src
BUILD=$ROOT/build
OUT=$ROOT/out
NDK=${NDK:-~/android-ndk-r27c}
NDKBIN=$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin

[ -d "$NDKBIN" ] || { echo "NDK not found at $NDK"; exit 1; }
# ~/.local/bin carries the pip-installed meson (Ubuntu's apt meson is too old)
export PATH="$NDKBIN:$HOME/.local/bin:$PATH"

DO_PATCH=0; DO_CLEAN=0
for a in "$@"; do
  case "$a" in
    --patch) DO_PATCH=1 ;;
    --clean) DO_CLEAN=1 ;;
  esac
done

echo "### toolchain"
aarch64-linux-android33-clang --version | head -1
meson --version | sed 's/^/meson /'
ninja --version | sed 's/^/ninja /'

cd "$SRC"
echo "### source: mesa $(cat VERSION)  @ $(git rev-parse --short HEAD)"

if [ "$DO_PATCH" = 1 ]; then
  echo "### reverting any previous patches"
  git checkout -- src/ 2>/dev/null || true
  for p in "$ROOT"/patches/*.patch; do
    [ -e "$p" ] || continue
    echo "--- applying $(basename "$p")"
    git apply --verbose "$p"
  done
  echo "### patched tree diffstat"
  git diff --stat
fi

if [ "$DO_CLEAN" = 1 ]; then rm -rf "$BUILD"; fi

if [ ! -d "$BUILD" ]; then
  echo "### meson setup"
  meson setup "$BUILD" \
    --cross-file "$ROOT/android-aarch64.txt" \
    --buildtype release \
    -Dplatforms=android \
    -Dplatform-sdk-version=33 \
    -Dandroid-stub=true \
    -Dandroid-strict=false \
    -Dgallium-drivers= \
    -Dvulkan-drivers=freedreno \
    -Dfreedreno-kmds=kgsl \
    -Dopengl=false \
    -Degl=disabled \
    -Dgles1=disabled \
    -Dgles2=disabled \
    -Dglx=disabled \
    -Dgbm=disabled \
    -Dshared-glapi=disabled \
    -Dllvm=disabled \
    -Dvideo-codecs= \
    -Db_lto=false \
    -Dspirv-tools=disabled \
    -Dstrip=true 2>&1 | tail -30
fi

echo "### ninja"
ninja -C "$BUILD" -j"$(nproc)" 2>&1 | tail -25

SO=$(find "$BUILD" -name 'libvulkan_freedreno.so' | head -1)
[ -n "$SO" ] || { echo "BUILD FAILED: no libvulkan_freedreno.so produced"; exit 1; }

mkdir -p "$OUT"
cp "$SO" "$OUT/libvulkan_freedreno.so"
VER=$(cat "$SRC/VERSION")
SUFFIX=$([ "$DO_PATCH" = 1 ] && echo "-ffpatched" || echo "-stock")

# adrenotools driver package: meta.json + the .so, zipped flat.
cat > "$OUT/meta.json" <<EOF
{
  "schemaVersion": 1,
  "name": "Turnip ${VER}${SUFFIX}",
  "description": "Mesa ${VER} Turnip, built for Android 13 (API 33). ${SUFFIX#-}",
  "author": "self-built",
  "packageVersion": "1",
  "vendor": "Mesa",
  "driverVersion": "${VER}",
  "minApi": 27,
  "libraryName": "libvulkan_freedreno.so"
}
EOF

cd "$OUT"
ZIP="turnip-ff-${VER}${SUFFIX}.zip"
rm -f "$ZIP"
zip -j -q "$ZIP" libvulkan_freedreno.so meta.json
echo
echo "### BUILT"
ls -la "$OUT/libvulkan_freedreno.so" "$OUT/$ZIP"
echo "so md5: $(md5sum "$OUT/libvulkan_freedreno.so" | cut -d' ' -f1)"
echo
echo "### bionic symbol check (must be EMPTY for Android 13)"
"$NDKBIN/llvm-nm" -uD "$OUT/libvulkan_freedreno.so" 2>/dev/null \
  | grep -E 'pthread_getaffinity_np|pthread_setaffinity_np|android_get_device_api_level' \
  || echo "  clean - no post-A13 bionic symbols"
