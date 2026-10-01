"""Provision dual-architecture graphics in the isolated Thor Battle.net prefix only."""
import argparse
import json
import pathlib
import shlex
import subprocess
import tempfile


PACKAGE = "app.gamenative.span"
FILES = f"/data/data/{PACKAGE}/files"
# Container ids are my install's ids (GameNative derives them per install). Change them to yours:
# 1835007374 is the Battle.net container, 1285328983 the retail one it must leave untouched.
PREFIX = f"{FILES}/imagefs/home/xuser-CUSTOM_GAME_1835007374"
DIRECT = f"{FILES}/imagefs/home/xuser-CUSTOM_GAME_1285328983/.container"
CONTENT = f"{FILES}/contents/DXVK/3.1.1-arm64-bnet-x86"
ARM = f"{FILES}/contents/DXVK/3.1.1-40e0164-arm64/system32"
X86 = "/data/data/app.gamenative/files/contents/DXVK/2.7.1/syswow64"
BACKUP = "/data/adb/wow/backups/launcher-20260924/bnet-before-dualarch.container"
STAGE = "/data/local/tmp/wowlauncher-session"
PREFS = f"{PREFIX}/.wine/drive_c/users/xuser/AppData/Roaming/Battle.net/Battle.net.config"
PREFS_BACKUP = "/data/adb/wow/backups/launcher-20260924/bnet-before-render-pref.config"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--scratch", required=True)
    args = parser.parse_args()
    base = [args.adb, "-s", args.serial]

    def adb(*argv):
        return subprocess.check_output(base + list(argv), timeout=60)

    def root(command):
        return adb("shell", "/debug_ramdisk/su --mount-master -c " + shlex.quote(command)).decode()

    # Refuse even an idle active app: it can rewrite .container from its cached model.
    root(f"set -e; if pidof {PACKAGE} >/dev/null; then exit 3; fi; test -f {PREFIX}/.container; test -f {DIRECT}; "
         f"test -d {ARM}; test -d {X86}; test -d {STAGE}; test -f {PREFS}; realpath {PREFIX}")
    original = root(f"sha256sum {DIRECT}").split()[0]
    config = json.loads(root(f"cat {PREFIX}/.container"))
    if config.get("id") != "CUSTOM_GAME_1835007374":
        raise RuntimeError("Refusing an unexpected Battle.net container identity")
    parts = config["dxwrapperConfig"].split(",")
    if not any(item.startswith("version=") for item in parts):
        raise RuntimeError("Missing existing DXVK version field")
    config["dxwrapperConfig"] = ",".join(
        "version=3.1.1-arm64-bnet-x86-0" if item.startswith("version=") else item
        for item in parts
    )
    config["dxwrapper"] = "dxvk"
    with tempfile.TemporaryDirectory(dir=args.scratch) as tmp:
        path = pathlib.Path(tmp) / "bnet-dualarch.container"
        path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        adb("push", str(path), STAGE + "/bnet-dualarch.container")
    adb("push", str(pathlib.Path(__file__).with_name("dxvk-dualarch-profile.json")),
        STAGE + "/dxvk-dualarch-profile.json")
    root(f'''set -eu
if pidof {PACKAGE} >/dev/null; then exit 3; fi
if ps -A -o NAME | grep -iqE 'wow(classic|b|t)?([-_](arm64|64))?\\.exe$'; then exit 2; fi
OWNER_UID=$(pm list packages -U | awk '$1=="package:{PACKAGE}" {{sub(/^uid:/,"",$2);print $2}}')
[ -n "$OWNER_UID" ]
for file in dxgi.dll d3d11.dll d3d10core.dll; do test -s {ARM}/$file; test -s {X86}/$file; done
[ -f {BACKUP} ] || cp -p {PREFIX}/.container {BACKUP}
mkdir -p {CONTENT}/system32 {CONTENT}/syswow64
for file in dxgi.dll d3d11.dll d3d10core.dll; do
    cp {ARM}/$file {CONTENT}/system32/$file
    cp {X86}/$file {CONTENT}/syswow64/$file
    cmp -s {ARM}/$file {CONTENT}/system32/$file
    cmp -s {X86}/$file {CONTENT}/syswow64/$file
done
cp {STAGE}/dxvk-dualarch-profile.json {CONTENT}/profile.json
chown -R "$OWNER_UID:$OWNER_UID" {CONTENT}
CTX=$(ls -Zd {FILES}/contents/DXVK/3.1.1-40e0164-arm64/profile.json | awk '{{print $1}}')
chcon -R "$CTX" {CONTENT}
cp {STAGE}/bnet-dualarch.container {PREFIX}/.container
chown "$OWNER_UID:$OWNER_UID" {PREFIX}/.container
# Keep saved sign-in on the device: change only the CEF rendering preference in place.
C={PREFS}
B={PREFS_BACKUP}
COUNT=$(grep -c '"HardwareAcceleration":' "$C" || true)
[ "$COUNT" -le 1 ]
[ -f "$B" ] || cp -p "$C" "$B"
chmod 600 "$B"
cp -p "$C" "$C.render-new"
if [ "$COUNT" = 1 ]; then
    sed 's/"HardwareAcceleration": *"[^"]*"/"HardwareAcceleration": "false"/' "$C" > "$C.render-new"
else
    grep -q '"AutoStartMinimized":.*,[[:space:]]*$' "$C"
    sed '/"AutoStartMinimized":/a\\        "HardwareAcceleration": "false",' "$C" > "$C.render-new"
fi
grep -q '"HardwareAcceleration": "false"' "$C.render-new"
mv "$C.render-new" "$C"
chown "$OWNER_UID:$OWNER_UID" "$C"
''')
    if root(f"sha256sum {DIRECT}").split()[0] != original:
        raise RuntimeError("Original Direct configuration changed unexpectedly")
    installed = json.loads(root(f"cat {PREFIX}/.container"))
    if installed != config:
        raise RuntimeError("Installed Battle.net configuration does not match")
    print("Isolated dual-architecture DXVK installed; original Direct config unchanged.")
    print("ARM64 files match the existing imported build; x86 files match cached DXVK 2.7.1.")


if __name__ == "__main__":
    main()
