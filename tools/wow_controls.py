#!/usr/bin/env python3
"""Apply / verify the WoW-on-Thor controller recipe, per WoW product (retail, classic, forever).

Why this exists (2026-09-21, a full day lost): the AYN Thor's pad is LETTER-correct at the
wire (bottom=BTN_EAST=B, right=BTN_SOUTH=A, top=BTN_NORTH=X, left=BTN_WEST=Y), Android's
Vendor_2020_Product_0111.kl keeps the letters, and GameNative forwards them unchanged as the
matching XInput bits. WoW then reads XInput bits POSITIONALLY (0=bottom, 1=right, 2=left, 3=top),
and ConsolePort's "Nintendo Switch Pro" preset applies labelStyle=Reverse on top -- so every
letter was being flipped once by WoW and once more by ConsolePort. A GameNative controls
profile (controls-7.icp) "fixed" it by flipping a third time, and its two guest pipes
(socket = raw, shm = mapped) disagreed, which is where the doubled A+B came from.

The recipe that actually works, and what each layer must be:
  Android    gyropad DISABLED (/data/adb/gyropad.disabled) -> raw pad passthrough, letters intact.
  GameNative NO controls profile on the container (extraData.profileId absent). sdlControllerAPI
             stays at its default (true); do NOT touch SDL_* env vars (scrambles the axes).
  WoW        WTF/GamePadConfig_Thor.json swaps raw 0<->1 and 2<->3 for BOTH devices WoW sees
             (8224:273 = the Odin ids via GameNative's virtual joystick, 1118:654 = Wine's Xbox
             360 XInput pad) so each letter lands on its physical position;
             Config.wtf: GamePadEnable 1, GamePadSingleActiveID 1 (listen to ONE of the two pads).
  ConsolePort active device "Nintendo Switch Pro" (Reverse labels + Nintendo glyph layout) -- unchanged.

Usage:
  python wow_controls.py verify --product retail
  python wow_controls.py apply  --product classic     # WoW must be closed (Config.wtf is rewritten on exit)
  --serial IP:PORT  adb target (default: $THOR_SERIAL)
  --app-id N        GameNative app_id for the container check (retail default 1285328983)
"""
import argparse
import re
import json
import os
import subprocess
import sys

ADB = os.environ.get("ADB", "adb")
SERIALS = [os.environ.get("THOR_SERIAL"), os.environ.get("THOR_ADB")]
WOW_ROOT = "/sdcard/Games/WoW"
PRODUCTS = {"retail": "_retail_", "classic": "_classic_", "forever": "_classic_beta_"}
APP_IDS = {"retail": 1285328983}
CVARS = {"GamePadEnable": "1", "GamePadSingleActiveID": "1"}
DEVICES = [(8224, 273, "Odin Controller via GameNative virtual joystick", "PADSOCIAL"),
           (1118, 654, "Wine XInput pad (Xbox 360 ids)", "PAD5")]
GN_HOME = "/data/data/app.gamenative/files/imagefs_shared/home"
# Is a WoW client running? Match the process NAME, not the arguments, for every flavor's exe.
# This used to be `pgrep -f Wow-ARM64.exe`, which prints PIDs only (so the "WoW not running"
# check always passed) and only knew retail's exe.
WOW_PS = "ps -A -o NAME | grep -iE 'wow[a-z]*-arm64\\.exe$'; true"


def sh(serial, cmd, root=False):
    full = f"su -c '{cmd}'" if root else cmd
    r = subprocess.run([ADB, "-s", serial, "shell", full], capture_output=True, text=True, timeout=60)
    return r.stdout.replace("\r", "")


def pick_serial(explicit):
    cands = [explicit] if explicit else [s for s in SERIALS if s]
    out = subprocess.run([ADB, "devices"], capture_output=True, text=True).stdout
    for s in cands:
        if s and f"{s}\tdevice" in out:
            return s
    sys.exit(f"no Thor on adb; tried {cands}")


def thor_json():
    def cfg(v, p, name, raw15):
        btn = {0: "PAD2", 1: "PAD1", 2: "PAD4", 3: "PAD3", 4: "PADBACK", 5: "PADSYSTEM", 6: "PADFORWARD",
               7: "PADLSTICK", 8: "PADRSTICK", 9: "PADLSHOULDER", 10: "PADRSHOULDER", 11: "PADDUP",
               12: "PADDDOWN", 13: "PADDLEFT", 14: "PADDRIGHT", 15: raw15}
        axes = {0: "LStickX", 1: "LStickY", 2: "RStickX", 3: "RStickY", 4: "LTrigger", 5: "RTrigger"}
        return {"comment": f"Thor/GameNative: raw 0<->1, 2<->3 swapped for {v}:{p} '{name}' -- letters to positions.",
                "name": f"Thor letters-to-positions ({name})", "vendorID": v, "productID": p,
                "rawButtonMappings": [{"rawIndex": i, "button": b} for i, b in btn.items()],
                "rawAxisMappings": [{"rawIndex": i, "axis": a} for i, a in axes.items()]}
    return {"headerComments": ["Thor + GameNative face-button position fix.",
                               "Do NOT set labelStyle here -- ConsolePort owns it (Reverse for Switch Pro)."],
            "configVersion": 4, "configs": [cfg(*d) for d in DEVICES]}


def checks(serial, product, app_id):
    wtf = f"{WOW_ROOT}/{PRODUCTS[product]}/WTF"
    res = []
    res.append(("gyropad disabled", "gyropad.disabled" in sh(serial, "ls /data/adb/", root=True)))
    if app_id:
        c = sh(serial, f"cat {GN_HOME}/xuser-CUSTOM_GAME_{app_id}/.container", root=True)
        res.append((f"container {app_id} exists", bool(c.strip())))
        res.append(("container has NO profileId", bool(c.strip()) and '"profileId"' not in c))
        res.append(("container sdlControllerAPI true", '"sdlControllerAPI":true' in c))
        res.append(("container envVars has no SDL_*", "SDL_" not in c))
    tj = sh(serial, f"cat {wtf}/GamePadConfig_Thor.json 2>/dev/null")
    ok = False
    try:
        d = json.loads(tj)
        ok = {(x["vendorID"], x["productID"]) for x in d["configs"]} >= {(v, p) for v, p, *_ in DEVICES}
    except Exception:
        pass
    res.append(("GamePadConfig_Thor.json present + both devices", ok))
    cfg = sh(serial, f"cat {wtf}/Config.wtf 2>/dev/null")
    for k, v in CVARS.items():
        res.append((f'Config.wtf {k} "{v}"', f'SET {k} "{v}"' in cfg))
    addons = sh(serial, f"ls {WOW_ROOT}/{PRODUCTS[product]}/Interface/AddOns 2>/dev/null")
    res.append(("ConsolePort installed", "ConsolePort" in addons.split()))
    sv = sh(serial, f"cat {wtf}/Account/*/SavedVariables/ConsolePort.lua 2>/dev/null")
    res.append(("ConsolePort active device = Nintendo Switch Pro",
                bool(re.search(r'\["Nintendo Switch Pro"\]\s*=\s*\{.*?\["Active"\]\s*=\s*true', sv, re.S))))
    res.append(("WoW not running", not sh(serial, WOW_PS).strip()))
    return res


def apply(serial, product):
    wtf = f"{WOW_ROOT}/{PRODUCTS[product]}/WTF"
    if sh(serial, WOW_PS).strip():
        sys.exit("WoW is running -- close it first (Config.wtf is rewritten on exit).")
    if not sh(serial, f"ls -d {wtf} 2>/dev/null").strip():
        sys.exit(f"{wtf} does not exist -- has {product} been run once?")
    tmp = os.path.join(os.environ.get("TEMP", "/tmp"), "GamePadConfig_Thor.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(thor_json(), f, indent=2)
    subprocess.run([ADB, "-s", serial, "push", tmp, f"{wtf}/GamePadConfig_Thor.json"], check=True,
                   env={**os.environ, "MSYS_NO_PATHCONV": "1"})
    sh(serial, f"cp {wtf}/Config.wtf {wtf}/Config.wtf.bak-controls 2>/dev/null; true")
    cfg = sh(serial, f"cat {wtf}/Config.wtf 2>/dev/null")
    lines = [l for l in cfg.splitlines() if not any(l.startswith(f"SET {k} ") for k in CVARS)]
    lines += [f'SET {k} "{v}"' for k, v in CVARS.items()]
    body = "\r\n".join(lines) + "\r\n"
    subprocess.run([ADB, "-s", serial, "shell", f"cat > {wtf}/Config.wtf"], input=body, text=True, check=True)
    print(f"applied to {product} ({wtf})")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["verify", "apply"])
    ap.add_argument("--product", choices=PRODUCTS, default="retail")
    ap.add_argument("--serial")
    ap.add_argument("--app-id", type=int)
    a = ap.parse_args()
    serial = pick_serial(a.serial)
    app_id = a.app_id or APP_IDS.get(a.product)
    if a.action == "apply":
        apply(serial, a.product)
    bad = 0
    for name, ok in checks(serial, a.product, app_id):
        print(f"  [{'OK' if ok else '!!'}] {name}")
        bad += (not ok)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
