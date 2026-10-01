#!/usr/bin/env python3
"""Stage a WoW flavor from the PC install to the Thor.

    python stage_flavor.py retail --dry-run
    python stage_flavor.py retail

WHAT ACTUALLY HAS TO MOVE (this is the part that surprises people): a WoW
install is NOT a self-contained flavor folder.  The CASC local storage lives at
the INSTALL ROOT and is SHARED by every installed flavor:

    World of Warcraft/
      .build.info          <- one row per installed product, read by the client
      Data/                <- CASC: config/, data/*.idx, indices/, <product>/
      _classic_beta_/      <- flavor dir (exe + Interface + WTF + Logs)
      _retail_/

So staging retail means syncing the GROWN root `Data/` tree plus `.build.info`
plus the new flavor dir, not just `_retail_`.  The Thor mirrors this
layout exactly under /storage/emulated/0/Games/WoW.

INCREMENTAL BY DESIGN: uses `adb push --sync`, which only sends files whose
timestamps differ from the device's.  On my device the timestamps survived the
Thor's FUSE layer: a dry-run sync of an already-staged directory reported
"0 files pushed".  That makes a stage resumable: re-run it after an
interruption and only the missing files move.

Compression is DISABLED (-Z): CASC data is already compressed, so the codec
only burns CPU.
"""
import argparse
import os
import subprocess
import sys

ADB = os.environ.get("ADB", "adb")
SERIAL = os.environ.get("THOR_SERIAL") or os.environ.get("THOR_ADB") or sys.exit("set THOR_SERIAL to the Thor's adb serial or ip:port")
SRC_ROOT = os.environ.get("WOW_PC_INSTALL") or sys.exit("set WOW_PC_INSTALL to the PC World of Warcraft folder")
DST_ROOT = "/storage/emulated/0/Games/WoW"

FLAVOR_DIRS = {
    "beta": "_classic_beta_",
    "retail": "_retail_",
    "classic": "_classic_",
    "classic_era": "_classic_era_",
}


def adb(*args, capture=True):
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    if capture:
        r = subprocess.run([ADB, "-s", SERIAL, *args], capture_output=True, text=True, env=env)
        return r.returncode, r.stdout + r.stderr
    r = subprocess.run([ADB, "-s", SERIAL, *args], env=env)
    return r.returncode, ""


def dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def free_bytes_on_device():
    _rc, out = adb("shell", "df -B1 /storage/emulated | tail -1")
    parts = out.split()
    for p in parts:
        if p.isdigit():
            pass
    try:
        return int(parts[3])
    except (IndexError, ValueError):
        return None


def push(src, dst, dry):
    args = ["push", "--sync", "-Z"]
    if dry:
        args.append("-n")
    args += [src, dst]
    print(f"\n>>> {'[dry-run] ' if dry else ''}{src}\n    -> {dst}")
    rc, out = adb(*args, capture=dry)
    if dry:
        print("    " + out.strip().splitlines()[-1] if out.strip() else "    (nothing)")
    return rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("flavor", choices=sorted(FLAVOR_DIRS))
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would move without sending anything")
    ap.add_argument("--sizes", action="store_true",
                    help="walk and report source sizes first (SLOW, and it fights an "
                         "in-progress Battle.net download for the disk)")
    a = ap.parse_args()

    sub = FLAVOR_DIRS[a.flavor]
    flavor_src = os.path.join(SRC_ROOT, sub)
    data_src = os.path.join(SRC_ROOT, "Data")
    build_info = os.path.join(SRC_ROOT, ".build.info")

    if not os.path.isdir(flavor_src):
        sys.exit(f"{flavor_src} does not exist. Has Battle.net finished installing {a.flavor}?")
    for name, exe in (("retail", "Wow-ARM64.exe"), ("beta", "WowB-ARM64.exe"),
                      ("classic", "WowClassic-ARM64.exe"), ("classic_era", "WowClassic-ARM64.exe")):
        if name == a.flavor and not os.path.isfile(os.path.join(flavor_src, exe)):
            sys.exit(f"{exe} missing from {flavor_src}. Run wow_arm64.py to pull it "
                     "(Battle.net doesn't install it for retail).")

    adb("connect", SERIAL)

    print(f"source: {SRC_ROOT}")
    free = free_bytes_on_device()
    if free is not None:
        print(f"device free: {free/2**30:.1f} GiB")

    # NOTE: do NOT walk Data/ to report its size. It is ~63 GiB+ of many small
    # CASC files, and during an active Battle.net download the walk contends
    # with the installer for the same disk. It hangs for minutes and slows the
    # download. `--sizes` is opt-in for when nothing else is using the disk.
    if a.sizes:
        fsz = dir_size(flavor_src)
        dsz = dir_size(data_src)
        print(f"  {sub}/ {fsz/2**30:.1f} GiB")
        print(f"  Data/  {dsz/2**30:.1f} GiB  (shared CASC, only the delta actually moves)")
        if free is not None and free < fsz:
            sys.exit("not enough free space on the device for the flavor dir alone. Stop.")

    # .build.info must land LAST: it is what tells the client the product exists,
    # so a half-synced Data/ with a complete .build.info is the bad ordering.
    rc = push(data_src, DST_ROOT + "/", a.dry_run)
    rc |= push(flavor_src, DST_ROOT + "/", a.dry_run)
    rc |= push(build_info, DST_ROOT + "/.build.info", a.dry_run)

    if rc:
        print("\nONE OR MORE PUSHES FAILED. Re-run. --sync means only the gaps move.")
        sys.exit(1)
    print("\nstaged." if not a.dry_run else "\ndry run complete, nothing was sent.")
    if not a.dry_run:
        print(f"next: python wow_flavor.py {a.flavor}")


if __name__ == "__main__":
    main()
