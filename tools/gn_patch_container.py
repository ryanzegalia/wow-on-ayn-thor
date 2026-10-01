#!/usr/bin/env python3
"""Patch a GameNative .container JSON on the Thor as root, the proven way.

Sequence: force-stop the app -> pull the
.container -> apply key=value edits -> push via /data/local/tmp -> cp over the
existing file (keeps inode) -> chown to the LIVE uid -> chmod 600 -> spell out
the file's own SELinux context back (sed/mv drop the categories). Always leaves a .bak.

Usage:
  python gn_patch_container.py CUSTOM_GAME_1285328983 executablePath=_classic_beta_/WowB-ARM64.exe screenSize=1920x1080
  python gn_patch_container.py CUSTOM_GAME_1285328983 --show
Values are strings unless they parse as JSON (true/false/numbers/objects).
"""
import json
import os
import subprocess
import sys
import time

ADB = os.environ.get("ADB", "adb")
HOME = "/data/user/0/app.gamenative/files/imagefs/home"
PKG = "app.gamenative"


def pick_serial():
    """Never hardcode a LAN IP -- it moves with the wifi SSID. Env override, else
    auto-pick an online AYN Thor transport, USB (no ':') first."""
    if os.environ.get("THOR_SERIAL"):
        return os.environ["THOR_SERIAL"]
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    r = subprocess.run([ADB, "devices", "-l"], capture_output=True, text=True, env=env)
    cands = []
    for line in r.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device" and "model:AYN_Thor" in line:
            cands.append(parts[0])
    if not cands:
        sys.exit("no online AYN Thor transport (set THOR_SERIAL to override)")
    cands.sort(key=lambda s: (":" in s, s))  # USB serial before ip:port
    return cands[0]


SERIAL = pick_serial()


def adb(*args, check=True):
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    r = subprocess.run([ADB, "-s", SERIAL, *args], capture_output=True, text=True, env=env)
    if check and r.returncode != 0:
        sys.exit(f"adb {' '.join(args)} failed: {r.stderr.strip()}")
    return r


def su(cmd):
    return adb("shell", f"su -c '{cmd}'").stdout


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cid = sys.argv[1]
    path = f"{HOME}/xuser-{cid}/.container"
    tmp = f"/data/local/tmp/{cid}.container"
    if ":" in SERIAL:
        adb("connect", SERIAL, check=False)
    uid = None
    for line in adb("shell", f"dumpsys package {PKG}", check=False).stdout.splitlines():
        if "userId=" in line:
            uid = line.split("userId=")[1].split()[0]
            break
    if not uid:
        sys.exit("could not read GameNative uid")

    # The categories in the context are derived from the app's uid, so they differ per
    # install. Read them off the live file instead of hardcoding them.
    ctx = su(f"stat -c %C {path}").strip()
    if not ctx.startswith("u:object_r:"):
        sys.exit(f"could not read the SELinux context of {path}: {ctx!r}")
    su(f"cp {path} {tmp} && chmod 644 {tmp}")
    local = os.path.join(os.environ.get("TEMP", "."), f"{cid}.container.json")
    adb("pull", tmp, local)
    data = json.load(open(local, encoding="utf-8"))

    if "--show" in sys.argv:
        for k in ("executablePath", "execArgs", "screenSize", "containerVariant", "emulator",
                  "wineVersion", "dxwrapper", "dxwrapperConfig", "graphicsDriver", "envVars"):
            print(f"{k} = {data.get(k)!r}")
        return

    edits = [a for a in sys.argv[2:] if "=" in a]
    for e in edits:
        k, v = e.split("=", 1)
        try:
            v = json.loads(v)
        except Exception:
            pass
        print(f"  {k}: {data.get(k)!r} -> {v!r}")
        data[k] = v
    # force a re-apply of runtime settings on next launch
    data.setdefault("extraData", {})["config_changed"] = "true"

    adb("shell", f"am force-stop {PKG}")
    time.sleep(1)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    json.dump(data, open(local, "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)
    adb("push", local, tmp)
    su(f"cp {path} {path}.bak-{stamp} && cp {tmp} {path} && chown {uid}:{uid} {path} "
       f"&& chmod 600 {path} && chcon {ctx} {path} && rm {tmp}")
    print(su(f"ls -lZ {path}").strip())
    print("patched; backup:", f"{path}.bak-{stamp}")


if __name__ == "__main__":
    main()
