#!/usr/bin/env python3
"""Size-verifying sync of the local WoW install to the AYN Thor over adb.

adb push has no resume and aborts the whole directory on the first locked file
(WowB.exe holds Cache/*.tmp open while the game runs on the PC). This walks the
local tree, compares sizes against one `stat` sweep on the device, and re-pushes
only what is missing or mismatched. Safe to re-run any number of times. The
final run with 0 pushes IS the integrity check. Also the re-sync path after a
Battle.net patch on the PC.

Usage: python wow_sync.py [--dry-run] [--src DIR] [--dst DEVICE_DIR]
"""
import argparse
import os
import subprocess
import sys

ADB = os.environ.get("ADB", "adb")
SERIAL = os.environ.get("THOR_SERIAL") or os.environ.get("THOR_ADB") or sys.exit("set THOR_SERIAL to the Thor's adb serial or ip:port")
SRC = os.environ.get("WOW_PC_INSTALL", "")   # the PC's "World of Warcraft" folder
DST = "/storage/emulated/0/Games/WoW"
# PC-only / runtime junk. WTF and Interface belong to the Thor (controller recipe, addons, account
# SavedVariables) and are owned by tools/wow_mirror.py. Never push the PC's copies over them.
SKIP_DIRS = {".battle.net", "Cache", "Logs", "Errors", "Screenshots", "WTF", "Interface"}
SKIP_FILES = {".product.db", "Launcher.db", ".patch.result", "World of Warcraft Launcher.exe", "Config.wtf",
              "shmem"}  # Config.wtf: Thor keeps its own tuned copy. shmem: CASC runtime inter-process
                        # lock/coordination file. Syncing the PC's copy hands the Thor a lock owned by
                        # a process that does not exist there. Never sync it.


def adb(*args, check=True, text=True):
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    return subprocess.run([ADB, "-s", SERIAL, *args], capture_output=True, text=text, env=env, check=check)


HASH_MAX = 4 * 1024 * 1024  # files at/below this size are compared by md5, not just size


def remote_sizes():
    out = adb("shell", f"find '{DST}' -type f -exec stat -c '%s %n' {{}} +", check=False).stdout
    sizes = {}
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        size, path = line.split(" ", 1)
        rel = path[len(DST) + 1:]
        sizes[rel] = int(size)
    return sizes


def remote_md5s(rels):
    """md5 of the given remote files (small ones only), one adb call."""
    if not rels:
        return {}
    quoted = " ".join(f"'{DST}/{r}'" for r in rels)
    out = adb("shell", f"md5sum {quoted}", check=False).stdout
    res = {}
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and len(parts[0]) == 32:
            res[parts[1][len(DST) + 1:]] = parts[0]
    return res


def local_md5(path):
    import hashlib
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def prune_stale(src):
    """Delete remote files that no longer exist locally (old CASC .idx/.lru/config after a patch)."""
    local = set()
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            local.add(os.path.relpath(os.path.join(root, f), src).replace("\\", "/"))
    stale = [r for r in remote_sizes() if r.startswith("Data/") and r not in local]
    for r in stale:
        adb("shell", f"rm -f '{DST}/{r}'", check=False)
    print(f"pruned {len(stale)} stale Data/ file(s) on device")


def local_files(src):
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f in SKIP_FILES:
                continue
            full = os.path.join(root, f)
            rel = os.path.relpath(full, src).replace("\\", "/")
            yield rel, full, os.path.getsize(full)


def main():
    global DST
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--dst", default=DST)
    a = ap.parse_args()
    DST = a.dst

    if ":" in SERIAL:
        adb("connect", SERIAL, check=False)

    # Guard 1: never push an ARM64 exe that is behind .build.info. Battle.net never updates
    # *-ARM64.exe, so after a patch the PC copy is stale. wow_arm64.py pulls the right one and
    # stamps a <exe>.build sidecar. (2026-09-22: the PC _retail_ exe was 69875 vs live 69933.)
    if not a.src:
        sys.exit("set WOW_PC_INSTALL (or --src) to the PC World of Warcraft folder")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from wow_arm64 import installed_flavors, sidecar_build
    stale = [f"{d}/{exe} (sidecar '{sidecar_build(os.path.join(a.src, d, exe)) or '-'}' vs {build})"
             for d, _p, exe, build in installed_flavors(a.src)
             if exe and os.path.isfile(os.path.join(a.src, d, exe))
             and sidecar_build(os.path.join(a.src, d, exe)) != build]
    if stale:
        print("REFUSING: stale ARM64 exe(s) in the PC install. Run tools/wow_arm64.py first:")
        for s in stale:
            print("  " + s)
        return 2

    # Guard 2: the client holds the shared CASC data.* files open. Rewriting them under a
    # running WoW corrupts its reads. Exit WoW on the Thor (Game Menu, not a kill) first.
    running = adb("shell", "ps -A -o ARGS | grep -iE 'wow[a-z]*-arm64\\.exe' | grep -v grep",
                  check=False).stdout.strip()
    if running and not a.dry_run:
        print(f"REFUSING: WoW is running on the Thor:\n  {running}")
        return 2

    remote = remote_sizes()
    todo, ok_bytes, todo_bytes = [], 0, 0
    same_size_small = []
    for rel, full, size in local_files(a.src):
        if remote.get(rel) == size:
            if size <= HASH_MAX:
                same_size_small.append((rel, full, size))
            else:
                ok_bytes += size
        else:
            todo.append((rel, full, size))
            todo_bytes += size
    # same-size small files: compare content (e.g. .build.info changes bytes, not size)
    rmd5 = {}
    batch = [r for r, _, _ in same_size_small]
    for i in range(0, len(batch), 60):
        rmd5.update(remote_md5s(batch[i:i + 60]))
    for rel, full, size in same_size_small:
        if rmd5.get(rel) == local_md5(full):
            ok_bytes += size
        else:
            todo.append((rel, full, size))
            todo_bytes += size
    print(f"in sync: {ok_bytes/1e9:.2f} GB   to push: {len(todo)} files / {todo_bytes/1e9:.2f} GB")
    if a.dry_run or not todo:
        for rel, _, size in todo[:40]:
            print(f"  {rel}  ({size} vs {remote.get(rel)})")
        return 0 if not todo else 1

    failed = []
    for i, (rel, full, size) in enumerate(todo, 1):
        rdir = f"{DST}/{os.path.dirname(rel)}".rstrip("/")
        adb("shell", f"mkdir -p '{rdir}'", check=False)
        r = adb("push", full, f"{DST}/{rel}", check=False)
        status = "ok" if r.returncode == 0 else "FAIL"
        print(f"[{i}/{len(todo)}] {status} {rel} ({size/1e6:.1f} MB)", flush=True)
        if r.returncode != 0:
            failed.append((rel, r.stderr.strip()[-200:]))
    # verify
    remote = remote_sizes()
    bad = [(rel, size, remote.get(rel)) for rel, _, size in todo if remote.get(rel) != size]
    for rel, err in failed:
        print(f"  push error {rel}: {err}")
    for rel, want, got in bad:
        print(f"  MISMATCH {rel}: local {want} device {got}")
    print("RESULT:", "ALL VERIFIED" if not bad else f"{len(bad)} file(s) still bad")
    if not bad:
        prune_stale(a.src)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
