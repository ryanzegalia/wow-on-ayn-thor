#!/usr/bin/env python3
"""One mirrored WoW config for every flavor on the Thor (retail, classic, forever beta).

    python wow_mirror.py push              # repo launcher/config/ -> device, deploy the launcher, seed
    python wow_mirror.py prep classic      # run the launcher's mirror steps, do not launch
    python wow_mirror.py launch classic    # mirror + point the container at classic + launch
    python wow_mirror.py log               # tail /sdcard/wowlaunch.log

THE MODEL
- `launcher/config/` in this repo is the source of truth for everything I own: the cvar overlay
  (overlay.wtf + overlay-<flavor>.wtf), GamePadConfig_Thor.json, the shared addon list, the
  shared account-SavedVariables list. The on-device launcher's source is launcher/scripts/wowlaunch.sh.
- `push` copies those to the device at Games/WoW/_mirror_/ and /data/adb/wow/wowlaunch.sh,
  pushes my own addons (FFScale, FFBinds) into EVERY installed flavor, and retires FFDiag.
- Third-party addons (ConsolePort, Glassy, Immersion) are mastered in the device's `_retail_`
  AddOns; the launcher copies them into the other flavors whenever a .toc differs.
- Account-wide SavedVariables sync NEWEST-WINS across flavors at every launch, seeded once
  from the retail account where the ConsolePort/Glassy tuning was done (SEED_ACCOUNT).
- The launcher (not this script) runs on every tile press, so the mirror holds without the
  workstation. See the header of launcher/scripts/wowlaunch.sh for the exact per-launch steps.

Account: the WTF folder is WTF/Account/<GAME ACCOUNT> (named after the game account, e.g. WOW1,
verified on Classic 2026-09-22), NOT the Battle.net id. For me Classic needed a subscription.
A free trial account only ran retail.
"""
import argparse
import os
import subprocess
import sys

ADB = os.environ.get("ADB", "adb")
SERIAL = os.environ.get("THOR_SERIAL") or os.environ.get("THOR_ADB") or sys.exit("set THOR_SERIAL to the Thor's adb serial or ip:port")
HERE = os.path.dirname(os.path.abspath(__file__))
MIRROR_SRC = os.path.join(HERE, "..", "launcher", "config")
LAUNCHER_SRC = os.path.join(HERE, "..", "launcher", "scripts", "wowlaunch.sh")
# My own addons, pushed into every flavor: FFScale (UI scale/placement), FFBinds (the one
# class-agnostic controller layout + ConsolePort keyboard + gamepad cvars).
MY_ADDONS = ["FFScale", "FFBinds"]

ROOT = "/storage/emulated/0/Games/WoW"
MIRROR = f"{ROOT}/_mirror_"
LAUNCHER = "/data/adb/wow/wowlaunch.sh"
SEED_ACCOUNT = os.environ.get("WOW_SEED_ACCOUNT", "")   # WTF/Account/<this>: where the tuning was done
SEED_CHAR = os.environ.get("WOW_SEED_CHAR", "")         # Realm/Character: its ConsolePort_Bar layout is the template
FLAVOR_DIRS = ["_retail_", "_classic_", "_classic_beta_"]
MIRROR_FILES = ["overlay.wtf", "overlay-retail.wtf", "overlay-classic.wtf", "overlay-beta.wtf",
                "GamePadConfig_Thor.json", "addons.list", "shared-sv.list"]


def adb(*args, check=True):
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    r = subprocess.run([ADB, "-s", SERIAL, *args], capture_output=True, text=True, env=env,
                       stdin=subprocess.DEVNULL)
    if check and r.returncode != 0:
        sys.exit(f"adb {' '.join(args)} failed: {(r.stdout + r.stderr).strip()}")
    return r.stdout


def su(cmd, check=True):
    return adb("shell", f"su --mount-master -c \"{cmd}\"", check=check)


def wow_running():
    # NAME (argv[0]), not ARGS: GameNative's explorer.exe/winhandler.exe outlive a clean exit
    # with the game's exe path in their ARGS.
    return adb("shell", "ps -A -o NAME | grep -iE 'wow[a-z]*-arm64\\.exe$'",
               check=False).strip()


def push():
    if wow_running():
        sys.exit("WoW is running on the Thor -- exit it via the Game Menu first "
                 "(SavedVariables only flush on logout, /reload or quit).")
    adb("shell", f"mkdir -p '{MIRROR}/sv'")
    for f in MIRROR_FILES:
        adb("push", os.path.join(MIRROR_SRC, f), f"{MIRROR}/{f}")
    print(f"mirror files -> {MIRROR}")

    adb("push", LAUNCHER_SRC, "/data/local/tmp/wowlaunch.sh")
    su(f"cp /data/local/tmp/wowlaunch.sh {LAUNCHER} && chmod 0644 {LAUNCHER}")
    print(f"launcher -> {LAUNCHER}")

    # seeds: account SVs + the per-character bar template, only if not already there
    seed_sv = f"{ROOT}/_retail_/WTF/Account/{SEED_ACCOUNT}/SavedVariables"
    for f in open(os.path.join(MIRROR_SRC, "shared-sv.list")).read().split():
        su(f"[ -f '{MIRROR}/sv/{f}' ] || [ ! -f '{seed_sv}/{f}' ] || cp -p '{seed_sv}/{f}' '{MIRROR}/sv/{f}'")
    bar = f"{ROOT}/_retail_/WTF/Account/{SEED_ACCOUNT}/{SEED_CHAR}/SavedVariables/ConsolePort_Bar.lua"
    su(f"[ -f '{MIRROR}/ConsolePort_Bar.lua' ] || cp -p '{bar}' '{MIRROR}/ConsolePort_Bar.lua'")
    print("seeds:\n" + adb("shell", f"ls -l '{MIRROR}' '{MIRROR}/sv'"))

    # my own addons go to every installed flavor; FFDiag (a one-off diagnostic) is retired
    for d in FLAVOR_DIRS:
        present = adb("shell", f"[ -d '{ROOT}/{d}' ] && echo y", check=False).strip()
        if present != "y":
            continue
        adb("shell", f"mkdir -p '{ROOT}/{d}/Interface/AddOns' && rm -rf '{ROOT}/{d}/Interface/AddOns/FFDiag'")
        for addon in MY_ADDONS:
            adb("push", os.path.join(HERE, "..", "addons", addon), f"{ROOT}/{d}/Interface/AddOns/")
            print(f"{addon} -> {d}")


def run_launcher(flavor, no_launch):
    if wow_running() and no_launch:
        sys.exit("WoW is running -- exit it first; the mirror step must not race its exit flush.")
    extra = " --no-launch" if no_launch else ""
    su(f"sh {LAUNCHER} {flavor}{extra}", check=False)
    print(adb("shell", "tail -25 /sdcard/wowlaunch.log", check=False))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("push")
    for name in ("prep", "launch"):
        p = sub.add_parser(name)
        p.add_argument("flavor", choices=["retail", "classic", "beta"])
    sub.add_parser("log")
    a = ap.parse_args()

    if a.cmd == "push":
        push()
    elif a.cmd == "prep":
        run_launcher(a.flavor, no_launch=True)
    elif a.cmd == "launch":
        run_launcher(a.flavor, no_launch=False)
    else:
        print(adb("shell", "tail -40 /sdcard/wowlaunch.log", check=False))


if __name__ == "__main__":
    main()
