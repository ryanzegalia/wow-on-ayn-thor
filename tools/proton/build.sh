#!/bin/bash
# The build I ran for the rebuilt proton-10 (docs/wine.md, Fix 4), on a Linux PC.
#
# Needs: a checkout of github.com/GameNative/proton-wine at the base commit recorded at the
# bottom of patches/proton-wine/build-step-arm64ec.diff, with that diff applied, and the
# toolchain proton-wine's build scripts expect (Android NDK, llvm-mingw, a Termux aarch64
# sysroot; see build-scripts/ in that repo). About 22 minutes on my PC.
#
# build-step-arm64ec.sh installs to $HOME/compiled-files-aarch64 (hardcoded in that
# script). This packs bin/ lib/ share/ from there into one tar for tools/release/.
#
# The build scripts don't revert patches between runs. Before a second build, reset the
# tree (git checkout -- . && git clean -fd), then re-apply the diff.
set -u
: "${SRC:?path to the proton-wine checkout}"
: "${TAR_OUT:=$PWD/proton-build.tar}"
OUT=$HOME/compiled-files-aarch64

log(){ echo "$(date +%H:%M:%S) === $* ==="; }
cd "$SRC" || exit 1
log "autogen"
bash autogen.sh || { echo AUTOGEN_FAIL; exit 1; }
log "build-step0 (wine-tools, host)"
bash build-scripts/build-step0.sh || { echo STEP0_FAIL; exit 1; }
log "sysvshm"
bash build-scripts/build-step-arm64ec.sh --build-sysvshm || echo "sysvshm warn"
log "configure (12 thread-suspension patches left out)"
bash build-scripts/build-step-arm64ec.sh --configure || { echo CONFIGURE_FAIL; exit 1; }
log "check: SkipThreadAttach applied"
grep -n "SkipThreadAttach" dlls/ntdll/unix/thread.c include/winternl.h dlls/ntdll/loader.c | head
log "check: suspend patches not applied (want 0)"
grep -c "SuspendCount" server/thread.c 2>/dev/null || true
log "check: rejected hunks (want none)"
find . -name "*.rej" | head
log "build"
bash build-scripts/build-step-arm64ec.sh --build || { echo BUILD_FAIL; exit 1; }
log "install"
bash build-scripts/build-step-arm64ec.sh --install || { echo INSTALL_FAIL; exit 1; }
log "check: ntdll pair"
ls -l "$OUT/lib/wine/aarch64-unix/ntdll.so" "$OUT/lib/wine/aarch64-windows/ntdll.dll" || { echo NO_NTDLL; exit 1; }
log "pack bin/lib/share"
cd "$OUT" && tar -cf "$TAR_OUT" bin lib share && ls -la "$TAR_OUT"
log "done"
