#!/bin/bash
# Build upstream DXVK for plain ARM64 Windows (aarch64-w64-mingw32). Runs inside the
# mstorsjo/llvm-mingw Docker image, with a host directory mounted at /work that holds:
#   build.sh            this script
#   build-aarch64.txt   the cross file next to it
#   src/                a DXVK checkout with its submodules
#
# The downloadable package was built from DXVK commit 40e0164:
#   git clone --recursive https://github.com/doitsujin/dxvk.git ~/dxvk-arm64/src
#   git -C ~/dxvk-arm64/src checkout 40e01640396d03f9fddeb697f5ee00ae893ecb75
#   git -C ~/dxvk-arm64/src submodule update --init --recursive
#   cp build.sh build-aarch64.txt ~/dxvk-arm64/
#   docker run --rm --cpus 4 -v $HOME/dxvk-arm64:/work mstorsjo/llvm-mingw:latest bash /work/build.sh
#
# The DLLs end up under ~/dxvk-arm64/build.
set -e
echo '### installing build deps'
apt-get update -qq >/dev/null 2>&1
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ninja-build glslang-tools python3-pip >/dev/null 2>&1
pip3 install --quiet --break-system-packages meson 2>/dev/null || pip3 install --quiet meson
echo "meson $(meson --version)  ninja $(ninja --version)  glslang $(glslangValidator --version 2>&1|head -1)"
cd /work/src
rm -rf /work/build
echo '### meson setup'
meson setup --cross-file /work/build-aarch64.txt --buildtype release /work/build 2>&1 | tail -25
echo '### ninja'
ninja -C /work/build -j4 2>&1 | tail -40
echo '### produced DLLs'
find /work/build -name '*.dll' | sort
