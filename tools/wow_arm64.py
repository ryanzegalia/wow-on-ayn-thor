#!/usr/bin/env python3
"""Pull the native ARM64 WoW exe for every installed flavor into the PC install.

    python wow_arm64.py            # pull whatever is stale, install it, write sidecars
    python wow_arm64.py --check    # report only (exit 1 if anything is stale)

WHY THIS EXISTS: Battle.net never installs or updates `*-ARM64.exe` for retail. It only
patches the x86 exe. So after every Blizzard patch the ARM64 exe sitting in the PC install is
one build behind, and wow_sync.py used to push it straight over the Thor's good copy.
2026-09-22: the PC `_retail_` still held the 69875 exe while the live build was 69933, and
the beta exe was 69913 against an installed 69977. Both would have broken realm select.

Every exe this tool installs gets a sidecar `<exe>.build` holding the build number it was
pulled for. wow_sync.py refuses to push an ARM64 exe whose sidecar does not match the
product's row in `.build.info`, so the stale-exe push cannot happen silently again.

TACTTool (TACTSharp) pulls the file from Blizzard's public CDN with no login. That pull is
a grey area, see docs/ban-risk.md. It fetches the same file Battle.net installs on a
Windows-on-ARM PC, for products already installed on this PC.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

SRC_ROOT = os.environ.get("WOW_PC_INSTALL", "")   # the PC's "World of Warcraft" folder
TACTTOOL = os.environ.get(
    "WOW_TACTTOOL",
    "TACTTool.exe",
)
HERE = os.path.dirname(os.path.abspath(__file__))

# product (from <flavor>/.flavor.info) -> ARM64 executable name
ARM64_EXE = {
    "wow": "Wow-ARM64.exe",
    "wow_classic": "WowClassic-ARM64.exe",
    "wow_classic_era": "WowClassic-ARM64.exe",
    "wow_anniversary": "WowClassic-ARM64.exe",
    "wow_classic_beta": "WowB-ARM64.exe",
}


def read_build_info(root):
    """{product: version} from the install root's .build.info (pipe-separated, typed header)."""
    with open(os.path.join(root, ".build.info"), encoding="utf-8") as f:
        rows = [line.rstrip("\n").split("|") for line in f if line.strip()]
    cols = [c.split("!")[0] for c in rows[0]]
    out = {}
    for row in rows[1:]:
        rec = dict(zip(cols, row))
        out[rec.get("Product", "")] = rec.get("Version", "")
    return out


def installed_flavors(root):
    """[(flavor_dir, product, arm64_exe_name, expected_build)] for every flavor dir in root."""
    versions = read_build_info(root)
    res = []
    for d in sorted(os.listdir(root)):
        info = os.path.join(root, d, ".flavor.info")
        if not (d.startswith("_") and os.path.isfile(info)):
            continue
        with open(info, encoding="utf-8") as f:
            product = [ln.strip() for ln in f if ln.strip()][-1]
        exe = ARM64_EXE.get(product)
        build = versions.get(product, "").split(".")[-1]
        res.append((d, product, exe, build))
    return res


def sidecar_build(exe_path):
    try:
        with open(exe_path + ".build", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def pull(product, exe, out_path):
    """Pull one exe with TACTTool. Returns the build number TACTTool resolved."""
    r = subprocess.run([TACTTOOL, "-p", product, "-m", "name", "-i", exe, "-o", out_path],
                       capture_output=True, text=True, cwd=os.path.dirname(TACTTOOL))
    m = re.search(r"Build WOW-(\d+)patch", r.stdout + r.stderr)
    if r.returncode != 0 or not m or not os.path.isfile(out_path):
        sys.exit(f"TACTTool failed for {product}/{exe}:\n{(r.stdout + r.stderr)[-800:]}")
    return m.group(1)


def is_pure_arm64(path):
    r = subprocess.run([sys.executable, os.path.join(HERE, "wine", "pe_machine.py"), path],
                       capture_output=True, text=True)
    return "-> ARM64 " in r.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report only, change nothing")
    ap.add_argument("--root", default=SRC_ROOT)
    a = ap.parse_args()
    if not a.root:
        sys.exit("set WOW_PC_INSTALL (or --root) to the PC World of Warcraft folder")

    if not a.check and not os.path.isfile(TACTTOOL):
        sys.exit(f"TACTTool not found at {TACTTOOL} (set WOW_TACTTOOL)")

    stale = 0
    for d, product, exe, build in installed_flavors(a.root):
        if not exe:
            print(f"{d:18} {product:18} no ARM64 exe known for this product, skipped")
            continue
        dst = os.path.join(a.root, d, exe)
        have = sidecar_build(dst) if os.path.isfile(dst) else ""
        state = "ok" if have == build else f"STALE (sidecar '{have or '-'}')"
        print(f"{d:18} {product:18} {exe:22} want {build}  {state}")
        if have == build:
            continue
        stale += 1
        if a.check:
            continue
        tmp = os.path.join(tempfile.mkdtemp(prefix="wowarm64-"), exe)
        got = pull(product, exe, tmp)
        if got != build:
            sys.exit(f"  CDN serves {got} but .build.info says {build}. Battle.net and the CDN "
                     f"disagree. Patch the PC first, then re-run.")
        if not is_pure_arm64(tmp):
            sys.exit(f"  {tmp} is not a pure ARM64 PE. Refusing to install it.")
        shutil.copy2(tmp, dst)
        with open(dst + ".build", "w", encoding="utf-8") as f:
            f.write(build + "\n")
        print(f"  installed {exe} {got} ({os.path.getsize(dst):,} bytes)")
        stale -= 1
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
