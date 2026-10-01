#!/bin/bash
# Packages the files I import into GameNative, from my own build outputs, on a Linux PC.
# I don't publish these files. This script is here so you can build the same set yourself.
#
# Makes four files in $OUT_DIR, plus SHA256SUMS:
#   proton-10.0-1-arm64ec-wow.wcp          GameNative Wine/Proton package (Wine/Proton Manager)
#   proton-wine-<base>-wow-source.tar.xz   the complete source for the package above (LGPL)
#   dxvk-<version>-arm64.wcp               GameNative DXVK package (Contents Manager)
#   turnip-<version>-wow.zip               adrenotools driver zip (Driver Manager)
#
# Nothing here is downloaded from a third party except GameNative's own stock
# proton-10.0-arm64ec.wcp, which is only used for its prefixPack.tzst (the starting Wine
# prefix GameNative itself ships), and Mesa's MIT license text for the Turnip zip, which is
# checked against a pinned sha256. Everything else comes from the build outputs you point
# it at. Paths are environment variables so nothing is tied to one machine.
#
# Timestamps: the members this script writes itself (profile.json, the two patched DLLs, the
# source tarball's wow-build/ files, the DXVK and Turnip files) carry the time of the run, so
# two runs never give the same bytes. To rebuild an earlier set exactly, point TIMESTAMPS_FROM at a
# folder with those files. Only those members take their timestamps from the file of the
# same name there. Their content, names, modes and order still come from the inputs. Tar
# member order follows the directory order of the file system the script runs on.
set -euo pipefail
umask 002   # the file modes inside the archives follow the umask

: "${TOOLS_DIR:?repo tools/ folder}"
: "${OUT_DIR:?where to write the files}"
: "${WORK_DIR:=$OUT_DIR/.work}"
: "${TIMESTAMPS_FROM:=}"

# Wine (proton-wine) build
: "${PROTON_BUILD_TAR:?tar of bin/ lib/ share/ from the Wine install step}"
: "${PROTON_WINE_SRC:?git checkout of github.com/GameNative/proton-wine}"
: "${PROTON_WINE_BASE:=4f1adc72ef1c11d975e619795053ce5502dd16d0}"
: "${BUILD_STEP_DIFF:=$TOOLS_DIR/../patches/proton-wine/build-step-arm64ec.diff}"
: "${BUILD_WRAPPER:=$TOOLS_DIR/proton/build.sh}"
: "${STOCK_PROTON_WCP:=$WORK_DIR/stock/proton-10.0-arm64ec.wcp}"
# Address of the live __wine_syscall_dispatcher slot for THIS Wine build. It moves between
# builds. Measure it for yours (docs/wine.md, Fix 2) before changing it.
: "${NTDLL_PINSLOT:=0x7fffb6f750}"
# Home folder the Wine build ran in. The build compiles that path into a few binaries and
# into the debug info of the Windows DLLs. The package gets a same-length neutral name there.
: "${BUILD_HOME:=$HOME}"

# DXVK build
: "${DXVK_OUT_DIR:?folder with the aarch64 DXVK DLLs}"
: "${DXVK_SRC_DIR:?the DXVK git checkout they were built from}"

# Turnip build
: "${TURNIP_SO:?the built libvulkan_freedreno.so}"
: "${MESA_SRC_DIR:?the Mesa checkout it was built from}"
MESA_MIT_SHA256=323c587d0ccf10e376f8bf9a7f31fb4ca6078105194b42e0b1e0ee2bc9bde71f

PROTON_NAME=10.0-1-arm64ec           # must match GameNative's Wine name pattern, see docs
PROTON_CODE=1                        # single digit: GameNative strips exactly two characters
SHORT_BASE=${PROTON_WINE_BASE:0:8}

# Neutral name for the build's home folder: "wowbuild" cut or padded to the same length.
BUILD_HOME=${BUILD_HOME%/}
BUILD_USER=${BUILD_HOME##*/}
[ -n "$BUILD_USER" ] && [ "${BUILD_HOME%/*}" != "$BUILD_HOME" ] || { echo "BUILD_HOME must be a folder like /home/<name>"; exit 1; }
NEUTRAL=wowbuild
while [ ${#NEUTRAL} -lt ${#BUILD_USER} ]; do NEUTRAL=${NEUTRAL}x; done
NEUTRAL=${NEUTRAL:0:${#BUILD_USER}}
[ ${#NEUTRAL} -eq ${#BUILD_USER} ] || { echo "no same-length neutral name"; exit 1; }
NEUTRAL_HOME=${BUILD_HOME%/*}/$NEUTRAL

rm -rf "$WORK_DIR/proton" "$WORK_DIR/src" "$WORK_DIR/dxvk" "$WORK_DIR/turnip"
mkdir -p "$WORK_DIR" "$OUT_DIR"
STAMP=$WORK_DIR/.run-start
touch "$STAMP"
log(){ echo "== $*"; }

# Same-length replacement of the build's home folder in every file under $1, in place (same
# inode, mode and mtime). Two forms: the plain path, and the same path inside MSVC-mangled
# string-literal symbol names, where each / is written as ?1. Fails if any file changes size
# or if the home folder's name is still anywhere in the tree (ASCII any case, or UTF-16LE).
neutralise_home(){
    python3 - "$1" "$BUILD_HOME" "$NEUTRAL_HOME" "$BUILD_USER" <<'PY'
import os, stat, sys
root, old, new, name = sys.argv[1:5]
if old == new:
    print('   build home is already neutral, nothing to replace')
    sys.exit(0)
pats = [(old.encode(), new.encode()),
        (old.replace('/', '?1').encode(), new.replace('/', '?1').encode())]
assert all(len(a) == len(b) for a, b in pats)
needles = [name.lower().encode(), name.lower().encode('utf-16-le')]
files = occ = 0
left = []
for dp, dns, fns in os.walk(root):
    for fn in fns:
        p = os.path.join(dp, fn)
        st = os.lstat(p)
        if not stat.S_ISREG(st.st_mode):
            continue
        with open(p, 'rb') as f:
            d = f.read()
        n = sum(d.count(a) for a, _ in pats)
        if n:
            for a, b in pats:
                d = d.replace(a, b)
            mode = stat.S_IMODE(st.st_mode)
            os.chmod(p, mode | stat.S_IWUSR)
            with open(p, 'r+b') as f:
                f.write(d)
            os.chmod(p, mode)
            os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
            files += 1
            occ += n
        if os.lstat(p).st_size != st.st_size or len(d) != st.st_size:
            sys.exit(f'size changed: {os.path.relpath(p, root)}')
        low = d.lower()
        if any(x in low for x in needles):
            left.append(os.path.relpath(p, root))
print(f'   {occ} occurrences in {files} files, every file kept its size')
if left:
    print('\n'.join(left[:20]))
    sys.exit(f'the build home folder name is still in {len(left)} files (a common word as a user name also trips this)')
PY
}

# With TIMESTAMPS_FROM set: members under $2 written during this run take the mtime of the
# member of the same name in $TIMESTAMPS_FROM/$1. Stops if that file lacks one of them.
pin_times(){
    [ -n "$TIMESTAMPS_FROM" ] || return 0
    local ref=$TIMESTAMPS_FROM/$1
    [ -f "$ref" ] || { echo "no $1 in TIMESTAMPS_FROM"; exit 1; }
    case $1 in *.zip) cat "$ref" ;; *) xz -T0 -dc "$ref" ;; esac |
        python3 -c '
import calendar, io, os, sys, tarfile, zipfile
name, root, stamp = sys.argv[1], sys.argv[2], os.stat(sys.argv[3]).st_mtime_ns
src = sys.stdin.buffer
if name.endswith(".zip"):
    zf = zipfile.ZipFile(io.BytesIO(src.read()))
    ref = {i.filename.rstrip("/"): calendar.timegm(i.date_time + (0, 0, 0)) for i in zf.infolist()}
else:
    ref = {m.name.rstrip("/"): m.mtime for m in tarfile.open(fileobj=src, mode="r|")}
    while src.read(1 << 20):
        pass
n = 0
for dp, dns, fns in os.walk(root):
    for f in dns + fns:
        p = os.path.join(dp, f)
        if os.lstat(p).st_mtime_ns <= stamp:
            continue
        rel = os.path.relpath(p, root)
        if rel not in ref:
            sys.exit(f"{name} in TIMESTAMPS_FROM has no {rel}")
        os.utime(p, (ref[rel], ref[rel]), follow_symlinks=False)
        n += 1
print(f"   {n} timestamps from {name}")
' "$1" "$2" "$STAMP"
}

# ---------------------------------------------------------------- Wine / Proton
log "proton: unpack build"
P=$WORK_DIR/proton
mkdir -p "$P"
tar -xf "$PROTON_BUILD_TAR" -C "$P"
AW=$P/lib/wine/aarch64-windows
[ -f "$AW/ntdll.dll" ] && [ -f "$AW/winevulkan.dll" ] || { echo "not a Wine install tar"; exit 1; }

log "proton: patch ntdll.dll (Fix 2) and winevulkan.dll (Fix 3)"
cp "$AW/ntdll.dll" "$WORK_DIR/ntdll.build.dll"
cp "$AW/winevulkan.dll" "$WORK_DIR/winevulkan.build.dll"
python3 "$TOOLS_DIR/wine/patch_ntdll_syscall.py" "$WORK_DIR/ntdll.build.dll" \
    --pinslot "$NTDLL_PINSLOT" --force -o "$AW/ntdll.dll"
python3 "$TOOLS_DIR/wine/patch_winevulkan_assert.py" "$WORK_DIR/winevulkan.build.dll" \
    --out "$AW/winevulkan.dll"

log "proton: build home folder -> $NEUTRAL_HOME (same length)"
neutralise_home "$P"

log "proton: GameNative's stock prefixPack"
if [ ! -f "$STOCK_PROTON_WCP" ]; then
    mkdir -p "$(dirname "$STOCK_PROTON_WCP")"
    curl -fsSL -o "$STOCK_PROTON_WCP" https://downloads.gamenative.app/proton-10.0-arm64ec.wcp
fi
xz -dc "$STOCK_PROTON_WCP" | tar -x -C "$P" prefixPack.tzst 2>/dev/null
[ -f "$P/prefixPack.tzst" ] || { echo "no prefixPack.tzst in the stock package"; exit 1; }

cat > "$P/profile.json" <<EOF
{
  "type": "Proton",
  "versionName": "$PROTON_NAME",
  "versionCode": $PROTON_CODE,
  "description": "GameNative proton-wine $SHORT_BASE (Proton 10 arm64ec), rebuilt for the ARM64 World of Warcraft client: 12 thread-suspension patches left out, ntdll syscall-stub and winevulkan assert patches applied.",
  "files": [],
  "wine": {
    "binPath": "bin",
    "libPath": "lib",
    "prefixPack": "prefixPack.tzst"
  }
}
EOF

log "proton: pack"
pin_times "proton-$PROTON_NAME-wow.wcp" "$P"
(cd "$P" && tar --owner=0 --group=0 -cf - profile.json prefixPack.tzst bin lib share) \
    | xz -T0 -6 > "$OUT_DIR/proton-$PROTON_NAME-wow.wcp"

# ---------------------------------------------------------------- Wine source (LGPL)
log "source: proton-wine $SHORT_BASE + build changes + byte-patch tools"
S=$WORK_DIR/src/proton-wine-$SHORT_BASE-wow
mkdir -p "$WORK_DIR/src"
git -C "$PROTON_WINE_SRC" archive --format=tar --prefix="proton-wine-$SHORT_BASE-wow/" "$PROTON_WINE_BASE" \
    | tar -x -C "$WORK_DIR/src"
(cd "$S" && git apply "$BUILD_STEP_DIFF")
mkdir -p "$S/wow-build"
# modes as in my source tarball, whatever the modes of the repo copy
install -m 0775 "$BUILD_WRAPPER" "$S/wow-build/build.sh"
install -m 0755 "$TOOLS_DIR"/wine/patch_ntdll_syscall.py "$TOOLS_DIR"/wine/patch_winevulkan_assert.py "$S/wow-build/"
cat > "$S/wow-build/README.txt" <<EOF
Source for proton-$PROTON_NAME-wow.wcp.

1. This tree is github.com/GameNative/proton-wine at $PROTON_WINE_BASE with one change: build-scripts/build-step-arm64ec.sh leaves out 12 thread-suspension patches.

2. wow-build/build.sh is the script that ran the build (autogen, build-step0, sysvshm, configure, build, install, then a tar of bin/ lib/ share/). I replaced my own folder names with variables and took out two environment lines that nothing in this tree reads. The steps and their order are unchanged.

3. After the build, two byte patches were applied to lib/wine/aarch64-windows:
     python3 patch_ntdll_syscall.py ntdll.dll --pinslot $NTDLL_PINSLOT --force -o ntdll.dll
     python3 patch_winevulkan_assert.py winevulkan.dll --out winevulkan.dll

4. The build ran inside my home folder, and that path ended up in the package, as install paths in a few binaries and in the debug info of the Windows DLLs. In every file of the package I replaced the home folder part of those paths with $NEUTRAL_HOME/. It has the same length, so no file changed size or layout.

5. prefixPack.tzst in the package is GameNative's own, unchanged, from https://downloads.gamenative.app/proton-10.0-arm64ec.wcp

Where the rest comes from

The toolchain and the Android libraries are not in this tarball. build-scripts/build-step-arm64ec.sh expects them at fixed places under \$HOME. I used these:

- Android NDK r27d (27.3.13750724) from https://dl.google.com/android/repository/android-ndk-r27d-linux.zip, unpacked to \$HOME/Android/Sdk/ndk/27.3.13750724
- llvm-mingw 20250920 (ucrt, ubuntu-22.04, x86_64) from https://github.com/bylaws/llvm-mingw/releases/tag/20250920, unpacked to \$HOME/toolchains
- the Termux aarch64 prefix with the Android builds of the libraries Wine links against, termuxfs-aarch64.tar from https://github.com/GameNative/termux-on-gha/releases/tag/build-20260218, unpacked to \$HOME/termuxfs/aarch64
- an Ubuntu 24.04 host with these packages: build-essential git wget curl unzip flex bison gettext autoconf automake libtool pkg-config ccache zstd mingw-w64 gcc-multilib g++-multilib libfreetype6-dev libpng-dev zlib1g-dev (the last three also as :i386)

.github/workflows/build-proton-sdk28.yml in this tree fetches the same toolchain and libraries and is the easiest reference.

prefixPack.tzst holds GameNative's own starting Wine prefix. The Wine DLLs inside it come from GameNative's own Wine build, not from this tree. Their source is GameNative's proton-wine repository, https://github.com/GameNative/proton-wine. The workflow in this tree downloads its prefix pack from https://github.com/GameNative/bionic-prefix-files.
EOF
pin_times "proton-wine-$SHORT_BASE-wow-source.tar.xz" "$WORK_DIR/src"
tar -C "$WORK_DIR/src" --owner=0 --group=0 -cf - "proton-wine-$SHORT_BASE-wow" \
    | xz -T0 -6 > "$OUT_DIR/proton-wine-$SHORT_BASE-wow-source.tar.xz"

# ---------------------------------------------------------------- DXVK
DXVK_COMMIT=$(git -C "$DXVK_SRC_DIR" rev-parse --short=7 HEAD)
DXVK_VER=$(sed -n "s/.*version *: *'\([0-9.]*\)'.*/\1/p" "$DXVK_SRC_DIR/meson.build" | head -1)
DXVK_NAME=$DXVK_VER-$DXVK_COMMIT-arm64
log "dxvk: $DXVK_NAME"
D=$WORK_DIR/dxvk
mkdir -p "$D/system32"
for dll in d3d11 dxgi d3d10core; do cp "$DXVK_OUT_DIR/$dll.dll" "$D/system32/"; done
cp "$DXVK_SRC_DIR/LICENSE" "$D/LICENSE"
cat > "$D/profile.json" <<EOF
{
  "type": "DXVK",
  "versionName": "$DXVK_NAME",
  "versionCode": 0,
  "description": "DXVK $DXVK_COMMIT (after $DXVK_VER), unmodified, compiled for plain ARM64 Windows (aarch64-w64-mingw32), not ARM64EC.",
  "files": [
    {"source": "system32/d3d11.dll", "target": "\${system32}/d3d11.dll"},
    {"source": "system32/dxgi.dll", "target": "\${system32}/dxgi.dll"},
    {"source": "system32/d3d10core.dll", "target": "\${system32}/d3d10core.dll"}
  ]
}
EOF
pin_times "dxvk-$DXVK_NAME.wcp" "$D"
(cd "$D" && tar --owner=0 --group=0 -cf - profile.json LICENSE system32) \
    | xz -T0 -6 > "$OUT_DIR/dxvk-$DXVK_NAME.wcp"

# ---------------------------------------------------------------- Turnip
MESA_VER=$(cat "$MESA_SRC_DIR/VERSION")
log "turnip: $MESA_VER"
T=$WORK_DIR/turnip
mkdir -p "$T"
cp "$TURNIP_SO" "$T/libvulkan_freedreno.so"
cp "$MESA_SRC_DIR/docs/license.rst" "$T/MESA-LICENSE.rst"
curl -fsSL -o "$T/MESA-MIT-LICENSE.txt" "https://gitlab.freedesktop.org/mesa/mesa/-/raw/mesa-$MESA_VER/licenses/MIT"
echo "$MESA_MIT_SHA256  $T/MESA-MIT-LICENSE.txt" | sha256sum -c --quiet - \
    || { echo "Mesa's MIT license text does not match the pinned sha256"; exit 1; }
chmod 644 "$T/MESA-MIT-LICENSE.txt"
cat > "$T/meta.json" <<EOF
{
  "schemaVersion": 1,
  "name": "Turnip $MESA_VER WoW patch",
  "description": "Mesa $MESA_VER Turnip with three ir3/tu fixes for the ARM64 World of Warcraft client. Built with -Dandroid-strict=false.",
  "author": "Mesa, patched for WoW (see the guide repo)",
  "packageVersion": "1",
  "vendor": "Mesa",
  "driverVersion": "$MESA_VER",
  "minApi": 27,
  "libraryName": "libvulkan_freedreno.so"
}
EOF
pin_times "turnip-$MESA_VER-wow.zip" "$T"
rm -f "$OUT_DIR/turnip-$MESA_VER-wow.zip"
# zip stores local clock time. With TIMESTAMPS_FROM the clock is UTC so it matches pin_times.
(cd "$T" && ${TIMESTAMPS_FROM:+env TZ=UTC0} zip -X -9 -q "$OUT_DIR/turnip-$MESA_VER-wow.zip" \
    meta.json libvulkan_freedreno.so MESA-LICENSE.rst MESA-MIT-LICENSE.txt)

# ---------------------------------------------------------------- checksums
log "checksums"
(cd "$OUT_DIR" && sha256sum *.wcp *.zip *.tar.xz > SHA256SUMS && cat SHA256SUMS)
ls -la "$OUT_DIR"
