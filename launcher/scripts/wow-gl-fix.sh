#!/system/bin/sh
# wow-gl-fix.sh -- Magisk service.d daemon (Thor). Pins the DLLs that the WoW GameNative
# container needs but that GameNative overwrites on EVERY launch. Only touches THIS container.
#
# WHY: WowB-ARM64.exe is a PURE ARM64 PE (machine 0xAA64, no CHPE). It can load ARM64/ARM64X
# DLLs but NOT ARM64EC (0x8664+CHPE) or x64 ones -- those fail "Bad EXE format". GameNative
# installs x64/ARM64EC components, so each one has to be replaced with a real aarch64 build.
#
#   d3d11 / d3d10core / dxgi -> my own DXVK 3.1.1 cross-built for aarch64-w64-mingw32
#                               (no public pure-ARM64 DXVK exists, every community build is
#                               ARM64EC and unloadable here). Built on a Linux PC with
#                               mstorsjo/llvm-mingw, see docs/graphics.md.
#   opengl32                 -> Wine's native aarch64 build, kept as the wined3d fallback
#                               (GameNative extracts an x64/ARM64EC Zink stub from zink_dlls.tzst).
#   ntdll                    -> my pinslot build. WoW's anti-tamper reads ntdll.dll OFF DISK from
#                               THIS prefix path (verified: fd 356 of WowB-ARM64.exe) -- NOT from
#                               the proton lib dir -- and calls Wine's syscall thunks in its own
#                               RWX copy. patch_ntdll_syscall.py --pinslot hardcodes the thunk
#                               literals to the real ntdll's dispatcher slot and strips their
#                               relocs so the copy cannot rebase them. If wineboot ever restores
#                               the stock file, WoW goes straight back to blr x16 with x16=0.
#
# Masters: /data/adb/wow/dxvk/{d3d11,d3d10core,dxgi}.dll, /data/adb/wow/ntdll.pinslot.dll, and
# Wine's own aarch64 opengl32.dll from the proton install.
CTR=/data/user/0/app.gamenative/files/imagefs/home/xuser-CUSTOM_GAME_1285328983
SYS=$CTR/.wine/drive_c/windows/system32
PROTON=/data/user/0/app.gamenative/files/imagefs_shared/proton/proton-10.0-arm64ec
GL_GOOD=$PROTON/lib/wine/aarch64-windows/opengl32.dll
# NOTE: on my device this finds no file. The log's start line shows an empty gl=, and my
# container runs proton-10.0-arm64ec-2. With GLSZ empty the opengl32 branch below never fires
# and GameNative's own opengl32 stays in the prefix. The game has run fine that way, so I left it.
DXVK=/data/adb/wow/dxvk
NTDLL_GOOD=/data/adb/wow/ntdll.pinslot.dll
LOG=/data/local/tmp/wow-gl-fix.log

md5of() { md5sum "$1" 2>/dev/null | cut -c1-32; }

GLSZ=$(stat -c %s "$GL_GOOD" 2>/dev/null)
echo "$(date '+%F %T') start gl=$GLSZ dxvk=$(ls $DXVK 2>/dev/null | tr '\n' ' ')" >> $LOG

while true; do
  # DXVK set: replace whenever the prefix copy differs from the master copy.
  for f in d3d11 d3d10core dxgi; do
    src=$DXVK/$f.dll
    dst=$SYS/$f.dll
    [ -f "$src" ] || continue
    [ -f "$dst" ] || continue
    want=$(md5of "$src")
    have=$(md5of "$dst")
    if [ -n "$want" ] && [ "$want" != "$have" ]; then
      cp "$src" "$dst" && echo "$(date '+%F %T') replaced $f.dll (dxvk aarch64)" >> $LOG
    fi
  done

  # ntdll: the file WoW's anti-tamper reads off disk. Must stay the pinslot build.
  if [ -f "$NTDLL_GOOD" ] && [ -f "$SYS/ntdll.dll" ]; then
    want=$(md5of "$NTDLL_GOOD")
    have=$(md5of "$SYS/ntdll.dll")
    if [ -n "$want" ] && [ "$want" != "$have" ]; then
      cp "$NTDLL_GOOD" "$SYS/ntdll.dll" && echo "$(date '+%F %T') replaced ntdll.dll (pinslot)" >> $LOG
    fi
  fi

  # opengl32: size check is enough (the Zink stub is ~200 KB, Wine's own build is a different size).
  sz=$(stat -c %s "$SYS/opengl32.dll" 2>/dev/null)
  if [ -n "$sz" ] && [ -n "$GLSZ" ] && [ "$sz" != "$GLSZ" ]; then
    cp "$GL_GOOD" "$SYS/opengl32.dll" && echo "$(date '+%F %T') replaced opengl32.dll ($sz -> $GLSZ)" >> $LOG
  fi

  sleep 0.3
done
