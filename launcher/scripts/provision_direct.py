"""Create the unified launcher's isolated Direct prefix without changing the legacy tile.

Run only after a clean in-game exit. Android paths are checked before copying; existing
new entries are refused rather than overwritten. No game data or login data leaves Thor.
"""
import argparse
import json
import os
import shlex
import subprocess

# Plain `adb` from PATH. Set ADB to a full path if yours is elsewhere.
ADB_DEFAULT = os.environ.get("ADB", "adb")
PACKAGE = "app.gamenative.span"
FILES = f"/data/data/{PACKAGE}/files"
# Container ids below are my install's ids (GameNative derives them per install). Change them.
SOURCE = f"{FILES}/imagefs/home/xuser-CUSTOM_GAME_1285328983"
TARGET = f"{FILES}/imagefs/home/xuser-CUSTOM_GAME_1835007375"
FOLDER = f"/storage/emulated/0/Android/data/{PACKAGE}/CustomGames/WoWDirect"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default=ADB_DEFAULT)
    parser.add_argument("--serial", default=os.environ.get("THOR_SERIAL"),
                        required="THOR_SERIAL" not in os.environ,
                        help="the Thor's adb serial or ip:port (or set THOR_SERIAL)")
    args = parser.parse_args()

    def root(command, timeout=30):
        result = subprocess.run(
            [args.adb, "-s", args.serial, "shell", "/debug_ramdisk/su --mount-master -c " + shlex.quote(command)],
            capture_output=True, text=True, timeout=timeout, check=True,
        )
        return result.stdout

    guard = """if ps -A -o NAME | grep -iqE '(^|[\\\\/[:space:]])wow(classic|b|t)?([-_](arm64|64))?\\.exe$|Battle.net.exe$'; then
  printf 'REFUSED: exit WoW and Battle.net first\\n'; exit 2
fi
"""
    print(root(f"""set -eu
{guard}
test -f {SOURCE}/.container
test -d {FILES}/imagefs/home
test -s {FILES}/contents/DXVK/3.1.1-40e0164-arm64/profile.json
test -d {FOLDER.rsplit('/', 1)[0]}
test ! -e {TARGET}
test ! -e {FOLDER}
readlink -f {SOURCE}
readlink -f {FOLDER.rsplit('/', 1)[0]}
"""))
    baseline = root(f"sha256sum {SOURCE}/.container {FILES}/imagefs_shared/proton/proton-10.0-arm64ec/bin/wineserver")
    config = json.loads(root(f"cat {SOURCE}/.container"))
    # Preserve the entire proven driver/DXVK/CPU/controller environment in a new entry.
    config["id"] = "CUSTOM_GAME_1835007375"
    config["name"] = "WoW Direct"
    config["drives"] = "".join(letter + ":" + path for letter, path in (
        ("A", FOLDER), ("B", "/storage/emulated/0/Games/WoW"), ("D", "/storage/emulated/0/Download"),
        ("E", "/data/data/" + PACKAGE + "/storage")))
    config["executablePath"] = "launch.bat"
    config["execArgs"] = ""
    config["extraData"].pop("executablePath", None)
    # The legacy entry's repair daemon is prefix-specific. Select the real ARM64
    # package so this new wrapper does not overwrite its copied DLLs with WineD3D.
    config["dxwrapper"] = "dxvk"
    parts = [part for part in config.get("dxwrapperConfig", "").split(",") if part and not part.startswith("version=")]
    config["dxwrapperConfig"] = ",".join(["version=3.1.1-40e0164-arm64-0"] + parts)
    config["extraData"]["config_changed"] = "true"
    payload = json.dumps(config, separators=(",", ":"))
    batch = '@echo off\r\nset HODLL=libwow64fex.dll\r\nstart "" "' + r'B:\_retail_\Wow-ARM64.exe' + '"\r\n'
    print(root(f"""set -eu
{guard}
test ! -e {TARGET}
test ! -e {FOLDER}
cp -a {SOURCE} {TARGET}
printf '%s' {shlex.quote(payload)} > {TARGET}/.container
mkdir {FOLDER}
printf '%s' '{{"appId":1835007375}}' > {FOLDER}/.gamenative
printf '%s' {shlex.quote(batch)} > {FOLDER}/launch.bat
ln -sfn {FOLDER} {TARGET}/.wine/dosdevices/a:
ln -sfn /storage/emulated/0/Games/WoW {TARGET}/.wine/dosdevices/b:
UID_APP=$(stat -c %u {SOURCE})
chown -hR "$UID_APP:$UID_APP" {TARGET}
find {TARGET} \\( -type f -o -type d \\) -exec chcon u:object_r:app_data_file:s0 {{}} +
printf 'Isolated Direct entry created\\n'
""", timeout=300))
    after = root(f"sha256sum {SOURCE}/.container {FILES}/imagefs_shared/proton/proton-10.0-arm64ec/bin/wineserver")
    if baseline != after:
        raise RuntimeError("Legacy Direct checksum changed unexpectedly; stop and inspect before launching")
    print("Verified: original Direct container and Wine server are byte-identical.")


if __name__ == "__main__":
    main()
