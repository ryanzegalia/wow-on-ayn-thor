#!/usr/bin/env python3
"""Point the Thor's WoW container at a different WoW flavor, safely.

    python wow_flavor.py --show
    python wow_flavor.py retail
    python wow_flavor.py beta

The retail and Classic ARM64 exes are pure ARM64 PEs (machine 0xAA64), so the same
patched stack runs both. See docs/ban-risk.md.

WHY A FLAVOR SWITCH AND NOT A SECOND CONTAINER: GameNative does NOT keep its
custom games in pluvia.db (that DB only holds steam/epic/gog/amazon tables) --
they live in a Jetpack `datastore`, so a hand-cloned container directory does
not show up in the UI and cannot be launched.  Swapping `executablePath` on the
existing container is one reversible key, and it has the added virtue of
running the new flavor on the EXACT prefix whose patched ntdll/winevulkan I
want to validate.  gn_patch_container.py always leaves a .bak.

TRAP: GameNative rewrites .container from its own in-memory model
when the app exits, so the driver pin (`graphicsDriverConfig version=`) survives
exactly ONE launch.  This script re-pins it every time, and you should re-run
the script before EVERY launch in an A/B.  Always confirm what a run actually
used from its own logcat env line: `ADRENOTOOLS_DRIVER_PATH=.../adrenotools/<name>/`.

Config.wtf notes carried over from the beta container:
  SET GxApi "D3D11"                              - D3D12 is not the working path here
  SET accessibilityScreenNarrationEnabled "0"    - REQUIRED. Without it WoW narrates the
                                                   login screen and asserts in
                                                   VoiceSpeakManager, since Wine has no TTS
"""
import argparse
import os
import subprocess
import sys

ADB = os.environ.get("ADB", "adb")
SERIAL = os.environ.get("THOR_SERIAL") or os.environ.get("THOR_ADB") or sys.exit("set THOR_SERIAL to the Thor's adb serial or ip:port")
CID = "CUSTOM_GAME_1285328983"
GAMES = "/storage/emulated/0/Games/WoW"
HERE = os.path.dirname(os.path.abspath(__file__))

# flavor -> (install subdir, ARM64 executable)
FLAVORS = {
    "beta":        ("_classic_beta_", "WowB-ARM64.exe"),
    "retail":      ("_retail_",       "Wow-ARM64.exe"),
    "classic":     ("_classic_",      "WowClassic-ARM64.exe"),
    "classic_era": ("_classic_era_",  "WowClassic-ARM64.exe"),
}

DRIVER = "Turnip FF 26.1.0 patched"
DRIVER_CFG = (
    "vulkanVersion=1.3,version={driver},blacklistedExtensions=,maxDeviceMemory=0,"
    "presentMode=mailbox,syncFrame=0,disablePresentWait=0,resourceType=auto,"
    "bcnEmulation=auto,bcnEmulationType=compute,bcnEmulationCache=0,gpuName=Device,"
    "adrenotoolsTurnip=1"
)

CONFIG_WTF = """SET GxApi "D3D11"
SET graphicsQuality "3"
SET accessibilityScreenNarrationEnabled "0"
"""


def adb(*args, check=True):
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    r = subprocess.run([ADB, "-s", SERIAL, *args], capture_output=True, text=True, env=env)
    if check and r.returncode != 0:
        sys.exit(f"adb {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def su(cmd):
    return adb("shell", f"su -c '{cmd}'")


def patch_container(*kvs):
    r = subprocess.run(
        [sys.executable, os.path.join(HERE, "gn_patch_container.py"), CID, *kvs],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        sys.exit(f"gn_patch_container failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout


def current():
    out = patch_container("--show")
    for line in out.splitlines():
        if "executablePath" in line:
            return line.strip()
    return "executablePath: <not found>"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("flavor", nargs="?", choices=sorted(FLAVORS))
    ap.add_argument("--show", action="store_true", help="print the current flavor and exit")
    ap.add_argument("--no-config", action="store_true",
                    help="do not write Config.wtf for the target flavor")
    ap.add_argument("--legacy", action="store_true", help="run this superseded tool anyway")
    a = ap.parse_args()

    # SUPERSEDED 2026-09-22 by the on-device launcher (launcher/scripts/wowlaunch.sh via
    # wow_mirror.py): it switches flavor AND mirrors the shared config, and pins the CURRENT
    # driver. This file still pins the old "Turnip FF 26.1.0 patched".
    if not a.legacy:
        sys.exit("superseded: use `python wow_mirror.py launch <retail|classic|beta>` "
                 "(or --legacy to run this anyway)")

    adb("connect", SERIAL, check=False)

    if a.show or not a.flavor:
        print(current())
        print("\ninstalled flavors on the device:")
        for name, (sub, exe) in sorted(FLAVORS.items()):
            got = su(f"[ -f {GAMES}/{sub}/{exe} ] && echo yes || echo no").strip()
            print(f"  {name:12} {sub}/{exe:24} {'PRESENT' if got == 'yes' else '-- not installed'}")
        return

    sub, exe = FLAVORS[a.flavor]
    rel = f"{sub}/{exe}"

    # Fail fast rather than leaving the container pointed at a missing exe.
    if su(f"[ -f {GAMES}/{rel} ] && echo yes || echo no").strip() != "yes":
        sys.exit(f"{GAMES}/{rel} is not on the device -- stage that flavor first.")

    if not a.no_config:
        wtf = f"{GAMES}/{sub}/WTF"
        existing = su(f"[ -f {wtf}/Config.wtf ] && echo yes || echo no").strip()
        if existing != "yes":
            su(f"mkdir -p {wtf}")
            body = CONFIG_WTF.replace('"', '\\"')
            su(f"printf '%s' \"{body}\" > {wtf}/Config.wtf")
            print(f"wrote a fresh Config.wtf to {wtf}")
        else:
            missing = []
            cur = su(f"cat {wtf}/Config.wtf")
            if "D3D11" not in cur:
                missing.append('SET GxApi "D3D11"')
            if "accessibilityScreenNarrationEnabled" not in cur:
                missing.append('SET accessibilityScreenNarrationEnabled "0"')
            if missing:
                print(f"WARNING: {wtf}/Config.wtf is missing: {', '.join(missing)}")
                print("         add them by hand, or delete Config.wtf and re-run.")

    patch_container(f"executablePath={rel}")
    patch_container(f"graphicsDriverConfig={DRIVER_CFG.format(driver=DRIVER)}")
    print(f"container now points at {rel}, driver re-pinned to '{DRIVER}'")
    print("re-run this script before EVERY launch -- GameNative reverts the driver pin on exit.")


if __name__ == "__main__":
    main()
