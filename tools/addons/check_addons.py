#!/usr/bin/env python3
"""Check the third-party addons this guide uses, without shipping any of them.

The guide never copies, ships or patches another author's addon. addons/third-party.json holds
only names, links, versions and checksums. You download each addon from its official page, and
this script tells you whether what you have is what I tested.

Subcommands:

    check <AddOns folder> [--profile single|dual]
    check --adb [--serial S] [--flavor retail] [--profile single|dual]
        Report every expected addon as OK, DIFFERENT VERSION, DIFFERENT FILES, MISSING or
        MISSING REQUIREMENT. Also compares FFScale, FFBinds and FFSpan with this repo's copies.
        Exit 0: everything required matches what I tested. Exit 1: something required is
        missing. Exit 2: everything is there, but some of it isn't the exact build I tested.

    install <your downloaded zip> <AddOns folder> [--replace]
        Unpack a zip YOU downloaded from the addon's own page into YOUR OWN local AddOns
        folder. It only accepts the exact zip I tested (same sha256 as the manifest). Any other
        zip is refused, and you unzip it yourself. It extracts only the addon's own folders and
        never overwrites without --replace. It never downloads anything and never copies
        anything to the device.

    settings <WTF folder> [--apply] [--write --wow-closed]
        Report the one saved setting this guide needs changed: TalentTreeTweaks' Scale Talent
        Frame module, which has to be off. --apply is a dry run. It prints the exact line it
        would change and writes nothing. --write makes the change. This script can't see
        whether WoW is running (the game runs on the Thor and this folder is a copy), so --write
        also needs --wow-closed, your word that WoW is closed. Before it writes a file it copies
        it to <file>.bak-<date>-<time> next to it and checks the copy. Only that one value
        changes. Every other byte of the file stays the same.

    hash <AddOns folder> [--folder NAME ...]  |  hash --adb [--folder NAME ...]
        Print the tree hash and .toc version of each folder (for updating the manifest).

Python 3, standard library only. Reading over adb needs the `adb` tool and USB debugging on.
Tests (fake addon trees only): python tools/addons/test_check_addons.py
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
DEFAULT_MANIFEST = os.path.join(REPO_ROOT, "addons", "third-party.json")
DEFAULT_DEVICE_ROOT = "/sdcard/Games/WoW"
FLAVOR_DIRS = {"retail": "_retail_", "classic": "_classic_"}
# Folders inside this repo's addon folders that are not part of the addon itself.
OWN_SKIP_DIRS = {"tests", "__pycache__"}
PROFILE_USED_FOR = {"single": {"single-screen", "both"}, "dual": {"dual-screen", "both"}}

OK = "OK"
DIFF_VERSION = "DIFFERENT VERSION"
DIFF_FILES = "DIFFERENT FILES"
MISSING = "MISSING"
MISSING_REQ = "MISSING REQUIREMENT"
NOT_INSTALLED = "NOT INSTALLED"  # optional addon that isn't there


# ---------------------------------------------------------------- tree hash

def tree_sha256(entries):
    """entries: iterable of (sha256 hex, relative path with forward slashes)."""
    ordered = sorted(entries, key=lambda e: e[1].encode("utf-8"))
    text = "".join("%s  %s\n" % (h, p) for h, p in ordered)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def local_entries(folder, skip_dirs=()):
    out = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d not in skip_dirs)
        for name in files:
            full = os.path.join(root, name)
            if os.path.islink(full) or not os.path.isfile(full):
                continue
            rel = os.path.relpath(full, folder).replace(os.sep, "/")
            out.append((file_sha256(full), rel))
    return out


def parse_sha256sum(text):
    """Parse `find . -type f -exec sha256sum {} +` output into entries (strips the ./)."""
    out = []
    for line in text.splitlines():
        line = line.rstrip("\r")
        if not line.strip():
            continue
        m = re.match(r"^([0-9a-fA-F]{64}) [ *]?(.*)$", line)
        if not m:
            raise ValueError("unexpected sha256sum line: %r" % line[:120])
        path = m.group(2)
        if path.startswith("./"):
            path = path[2:]
        out.append((m.group(1).lower(), path))
    return out


def toc_version(toc_text):
    for line in toc_text.splitlines():
        m = re.match(r"^\s*##\s*Version\s*:\s*(.*?)\s*$", line, re.I)
        if m:
            return m.group(1)
    return None


# ---------------------------------------------------------------- sources

class LocalSource:
    def __init__(self, path):
        self.path = path
        self.label = path

    def exists(self):
        return os.path.isdir(self.path)

    def folders(self):
        return {d for d in os.listdir(self.path) if os.path.isdir(os.path.join(self.path, d))}

    def entries(self, folder):
        return local_entries(os.path.join(self.path, folder))

    def version(self, folder):
        toc = os.path.join(self.path, folder, folder + ".toc")
        if not os.path.isfile(toc):
            return None
        with open(toc, "r", encoding="utf-8", errors="replace") as f:
            return toc_version(f.read())


def _q(s):
    return "'" + s.replace("'", "'\\''") + "'"


class AdbSource:
    """Reads the AddOns folder on the device. Read only: it never writes anything there."""

    def __init__(self, adb="adb", serial=None, device_root=DEFAULT_DEVICE_ROOT, flavor="retail"):
        self.adb = adb
        self.serial = serial
        self.path = "%s/%s/Interface/AddOns" % (device_root.rstrip("/"), FLAVOR_DIRS[flavor])
        self.label = "device: " + self.path

    def _shell(self, cmd):
        args = [self.adb] + (["-s", self.serial] if self.serial else []) + ["shell", cmd]
        try:
            r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=300)
        except FileNotFoundError:
            raise SystemExit("Can't find adb (%s). Install Android platform-tools or pass "
                             "--adb-path." % self.adb)
        if r.returncode != 0 and not r.stdout:
            raise SystemExit("adb failed: %s" % (r.stderr.strip() or "no output"))
        return r.stdout

    def exists(self):
        return self._shell("[ -d %s ] && echo yes" % _q(self.path)).strip() == "yes"

    def folders(self):
        out = self._shell("cd %s && for d in *; do [ -d \"$d\" ] && echo \"$d\"; done" % _q(self.path))
        return {l.rstrip("\r") for l in out.splitlines() if l.strip()}

    def entries(self, folder):
        return parse_sha256sum(self._shell(
            "cd %s && find . -type f -exec sha256sum {} +" % _q(self.path + "/" + folder)))

    def version(self, folder):
        out = self._shell("cat %s 2>/dev/null" % _q("%s/%s/%s.toc" % (self.path, folder, folder)))
        return toc_version(out) if out else None


def load_manifest(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- check

def _links(entry):
    pages = entry.get("pages") or {}
    return [pages[k] for k in ("curseforge", "wago", "github") if pages.get(k)]


def check_third_party(source, entry, present):
    """Return (status, detail lines) for one manifest entry."""
    folders = entry["folders"]
    missing = [f for f in folders if f not in present]
    if missing:
        status = NOT_INSTALLED if entry.get("optional") else MISSING
        lines = []
        if len(missing) < len(folders):
            lines.append("Some of its folders are missing: " + ", ".join(missing))
        lines.append("Get it from: " + (" or ".join(_links(entry)) or "(no link recorded)"))
        lines.append("Author: " + entry.get("author", "?"))
        if entry.get("why"):
            lines.append("Why: " + entry["why"])
        if entry.get("optional"):
            lines.append("It's optional. I use it, but nothing else depends on it.")
        return status, lines
    have = source.version(folders[0])
    want = entry.get("version_tested")
    if have != want:
        return DIFF_VERSION, ["You have %s, I tested %s. It may well work, I just haven't tried "
                              "that version." % (have or "(no version in its .toc)", want)]
    bad = [f for f in folders if tree_sha256(source.entries(f)) != entry["tree_sha256"].get(f)]
    if bad:
        return DIFF_FILES, ["Same version number, but the files aren't byte-for-byte the build I "
                            "tested (%s). That's probably fine. It's just not the exact build I "
                            "tested." % ", ".join(bad)]
    return OK, []


def check_own(source, entry, present, repo_root):
    name = entry["name"]
    folder = entry["folders"][0]
    repo_dir = os.path.join(repo_root, entry["path"])
    repo_version = LocalSource(os.path.dirname(repo_dir)).version(os.path.basename(repo_dir))
    if folder not in present:
        return MISSING, ["Copy it from this repo: %s/" % entry["path"],
                         "Why: " + entry.get("why", "")]
    have = source.version(folder)
    repo_tree = tree_sha256(local_entries(repo_dir, OWN_SKIP_DIRS))
    if tree_sha256(source.entries(folder)) == repo_tree:
        return OK, []
    if have != repo_version:
        return DIFF_VERSION, ["You have %s, this repo has %s. Copy the folder from %s/ to "
                              "match the guide." % (have or "(none)", repo_version, entry["path"])]
    return DIFF_FILES, ["Same version as this repo (%s) but different files. Copy the folder "
                        "from %s/ again if you want the exact copy." % (repo_version, entry["path"])]


def run_check(source, manifest, profile, repo_root=REPO_ROOT, out=sys.stdout):
    wanted = PROFILE_USED_FOR[profile]
    if not source.exists():
        print("Can't find the AddOns folder: %s" % source.label, file=out)
        return 1
    present = source.folders()
    print("Addon check (%s screen) in %s" % (profile, source.label), file=out)
    print("", file=out)
    results = []  # (name, status, lines, required)
    by_name = {e["name"]: e for e in manifest.get("third_party", [])}
    for e in manifest.get("third_party", []):
        if e.get("used_for") not in wanted:
            continue
        status, lines = check_third_party(source, e, present)
        if status not in (MISSING, NOT_INSTALLED):
            for req in e.get("requires", []):
                r = by_name.get(req)
                if r and any(f not in present for f in r["folders"]):
                    status = MISSING_REQ
                    lines = ["%s needs %s, and %s isn't installed. Get it from: %s"
                             % (e["name"], req, req, " or ".join(_links(r)))] + lines
        label = "%s %s" % (e["name"], e.get("version_tested", ""))
        results.append((label.strip(), status, lines, not e.get("optional")))
    for e in manifest.get("own", []):
        if e.get("used_for") not in wanted:
            continue
        status, lines = check_own(source, e, present, repo_root)
        results.append((e["name"] + " (from this repo)", status, lines, True))

    for label, status, lines, _ in results:
        print("%-20s %s" % (status, label), file=out)
        for l in lines:
            print("%-20s %s" % ("", l), file=out)
    print("", file=out)
    required = [r for r in results if r[3]]
    missing = [r for r in required if r[1] in (MISSING, MISSING_REQ)]
    differ = [r for r in required if r[1] in (DIFF_VERSION, DIFF_FILES)]
    if missing:
        print("%d required addon(s) missing. Nothing was changed." % len(missing), file=out)
        return 1
    if differ:
        print("Everything required is there. %d of them aren't byte-for-byte the build I tested "
              "or this repo's copy."
              % len(differ), file=out)
        return 2
    print("Everything required is there and matches what I tested.", file=out)
    return 0


# ---------------------------------------------------------------- install

def _unsafe_member(name):
    return (name.startswith("/") or name.startswith("\\") or re.match(r"^[A-Za-z]:", name)
            or ".." in re.split(r"[/\\]", name))


def run_install(zip_path, addons_dir, manifest, replace=False, out=sys.stdout):
    """Install a zip the reader downloaded, and only when it is byte-for-byte the zip I tested.

    It never downloads anything. It only reads the zip you give it and writes into the AddOns
    folder you give it."""
    if not os.path.isfile(zip_path):
        print("Can't find the zip: %s" % zip_path, file=out)
        return 1
    if not os.path.isdir(addons_dir):
        print("Can't find the AddOns folder: %s" % addons_dir, file=out)
        return 1
    digest = file_sha256(zip_path)
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        print("That file isn't a zip.", file=out)
        return 1
    with zf:
        names = [i.filename for i in zf.infolist()]
        bad = [n for n in names if _unsafe_member(n)]
        if bad:
            print("Refusing: the zip has paths that point outside its own folder (%s)." % bad[0],
                  file=out)
            return 1
        tops = {re.split(r"[/\\]", n)[0] for n in names if n}
        third = manifest.get("third_party", [])
        entry = None
        for e in third:
            dt = e.get("download_tested") or {}
            if dt.get("sha256") and dt["sha256"] == digest:
                entry = e
                break
        if entry is None:
            named = next((e for e in third if set(e["folders"]) & tops), None)
            if named is None:
                print("This zip doesn't contain any addon from the list. Top-level folders: %s"
                      % ", ".join(sorted(tops)), file=out)
                return 1
            dt = named.get("download_tested")
            if dt:
                print("This isn't the zip I tested for %s (%s, sha256 %s). Yours has sha256 %s."
                      % (named["name"], dt["filename"], dt["sha256"], digest), file=out)
            else:
                print("I didn't keep the zip I tested for %s, so there's nothing to compare "
                      "yours with." % named["name"], file=out)
            print("I only install the exact zip I tested. Nothing was installed. Unzip it into "
                  "your AddOns folder yourself, then run check to see how it compares.", file=out)
            return 1
        print("Addon: %s by %s. This is the zip I tested (%s)."
              % (entry["name"], entry.get("author", "?"), entry["download_tested"]["filename"]),
              file=out)
        wanted = [f for f in entry["folders"] if f in tops]
        absent = [f for f in entry["folders"] if f not in tops]
        skipped = sorted(tops - set(entry["folders"]))
        if not wanted:
            print("The zip has none of the addon's folders.", file=out)
            return 1
        exists = [f for f in wanted if os.path.exists(os.path.join(addons_dir, f))]
        if exists and not replace:
            print("Already in your AddOns folder: %s. Nothing was installed. Run again with "
                  "--replace to replace them." % ", ".join(exists), file=out)
            return 1
        stage = tempfile.mkdtemp(prefix=".check_addons-", dir=addons_dir)
        try:
            for info in zf.infolist():
                top = re.split(r"[/\\]", info.filename)[0]
                if top in wanted:
                    zf.extract(info, stage)
            for f in wanted:
                dest = os.path.join(addons_dir, f)
                if os.path.exists(dest):
                    shutil.rmtree(dest)
                shutil.move(os.path.join(stage, f), dest)
        finally:
            shutil.rmtree(stage, ignore_errors=True)
    print("Installed into %s: %s" % (addons_dir, ", ".join(wanted)), file=out)
    if skipped:
        print("Left out (not part of this addon): %s" % ", ".join(skipped), file=out)
    if absent:
        print("The zip didn't have these folders: %s" % ", ".join(absent), file=out)
    src = LocalSource(addons_dir)
    for f in wanted:
        match = tree_sha256(src.entries(f)) == entry["tree_sha256"].get(f)
        print("  %s: %s" % (f, "matches what I tested" if match else "not the exact build I tested"),
              file=out)
    print("Next: copy the AddOns folder to the Thor the way the guide describes.", file=out)
    return 0


# ---------------------------------------------------------------- settings

# The only saved values this script ever changes. Each one is described in docs/dual-screen.md
# and belongs to an addon listed in addons/third-party.json. A value is only touched when its
# addon is in the manifest, it sits at exactly this place in the file, and it is true or false.
DOCUMENTED_SETTINGS = (
    {
        "addon": "TalentTreeTweaks",
        "file": "TalentTreeTweaks.lua",
        "path": ("TalentTreeTweaksDB", "modules"),
        "key": "ScaleTalentFrame",
        "label": "Scale Talent Frame",
        "want": "false",
        "why": "It fights the talent window scaling.",
        "in_game": "In game: type /ttt (or open Options > AddOns > TalentTreeTweaks), find the "
                   "module 'Scale Talent Frame' and untick it.",
    },
)

_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<comment>--[^\n]*)
  | (?P<skey>\["(?:[^"\\\n]|\\.)*"\]\s*=)
  | (?P<nkey>\[-?\d+(?:\.\d+)?\]\s*=)
  | (?P<gkey>[A-Za-z_][A-Za-z0-9_]*\s*=)
  | (?P<open>\{)
  | (?P<close>\})
  | (?P<sep>[,;])
  | (?P<str>"(?:[^"\\\n]|\\.)*")
  | (?P<bool>true|false|nil)\b
  | (?P<num>-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?|-?nan|-?inf)
""", re.X)


def find_value(text, path, key):
    """Return a list of (start, end, value) for path[...][key]. Raise ValueError if the file
    isn't the plain table layout WoW writes, or if the value there isn't true/false."""
    stack, pending, hits, pos = [], None, [], 0
    path = tuple(path)
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise ValueError("unrecognised text at byte %d" % pos)
        kind, tok = m.lastgroup, m.group(0)
        if kind == "skey":
            pending = json.loads(tok[1:tok.rindex("]")])
        elif kind == "gkey":
            if stack:
                raise ValueError("unexpected name inside a table at byte %d" % pos)
            pending = tok.split("=")[0].strip()
        elif kind == "nkey":
            pending = "#"
        elif kind == "open":
            stack.append(pending)
            pending = None
        elif kind == "close":
            if not stack:
                raise ValueError("unbalanced } at byte %d" % pos)
            stack.pop()
        elif kind in ("str", "bool", "num"):
            if tuple(stack) == path and pending == key:
                if kind != "bool" or tok == "nil":
                    raise ValueError("%s is not true/false" % key)
                hits.append((m.start(), m.end(), tok))
            pending = None
        pos = m.end()
    if stack:
        raise ValueError("unbalanced { at end of file")
    return hits


def _find_sv_files(path, name):
    if os.path.isfile(path):
        return [path] if os.path.basename(path) == name else []
    found = []
    acct = os.path.join(path, "Account")
    if os.path.isdir(acct):
        for a in sorted(os.listdir(acct)):
            p = os.path.join(acct, a, "SavedVariables", name)
            if os.path.isfile(p):
                found.append(p)
    for p in (os.path.join(path, "SavedVariables", name), os.path.join(path, name)):
        if os.path.isfile(p):
            found.append(p)
    return found


def _masked(path, root):
    if os.path.isfile(root):
        return os.path.basename(path)
    rel = os.path.relpath(path, root).replace(os.sep, "/")
    parts = rel.split("/")
    if len(parts) >= 2 and parts[0] == "Account":
        parts[1] = "<account>"
    return "/".join(parts)


def _state(value):
    return {"true": "ON", "false": "OFF"}.get(value, value)


def _change_preview(text, start, end, want):
    """Line number plus the before/after text of the one line that changes."""
    ls = text.rfind("\n", 0, start) + 1
    le = text.find("\n", start)
    le = len(text) if le < 0 else le
    line = text[ls:le].rstrip("\r")
    col = start - ls
    after = line[:col] + want + line[col + (end - start):]
    s0 = max(0, col - 60)
    before_show = line[s0:col + (end - start) + 40]
    after_show = after[s0:col + len(want) + 40]
    return text.count("\n", 0, start) + 1, before_show.strip(), after_show.strip()


def _backup_path(path, now):
    base = "%s.bak-%s" % (path, now.strftime("%Y%m%d-%H%M%S"))
    cand, n = base, 1
    while os.path.exists(cand):
        n += 1
        cand = "%s-%d" % (base, n)
    return cand


def _write_value(path, raw, start, end, want, now):
    """Back up the file, check the backup, then replace bytes start:end with want. Returns the
    backup path. Raises OSError, with the original file untouched, if anything doesn't add up."""
    new = raw[:start] + want.encode("ascii") + raw[end:]
    if new[:start] != raw[:start] or new[start + len(want):] != raw[end:]:
        raise OSError("the new file would differ outside the one value")
    with open(path, "rb") as f:
        if f.read() != raw:
            raise OSError("the file changed while I was reading it")
    backup = _backup_path(path, now)
    shutil.copy2(path, backup)
    with open(backup, "rb") as f:
        if f.read() != raw:
            raise OSError("the backup %s doesn't match the original" % os.path.basename(backup))
    tmp = path + ".check_addons-tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(new)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return backup


CANT_SEE_WOW = ("I can't tell whether WoW is running. The game runs on the Thor and this folder "
                "is a copy on this computer, so there is nothing here for me to check. If WoW is "
                "running when the file goes back, it writes its own SavedVariables when it exits "
                "and the old value comes back.")


def run_settings(wtf, manifest, apply=False, write=False, wow_closed=False, out=sys.stdout,
                 now=None):
    """Report, dry-run (apply) or write (write + wow_closed) the documented settings."""
    if write:
        apply = True
    in_manifest = {e["name"] for e in manifest.get("third_party", [])}
    specs = [s for s in DOCUMENTED_SETTINGS if s["addon"] in in_manifest]
    if not specs:
        print("No addon in the manifest has a setting this script changes. Nothing to do.",
              file=out)
        return 0
    if write and not wow_closed:
        print(CANT_SEE_WOW, file=out)
        print("Nothing was changed. Close WoW on the Thor, then run again with --write "
              "--wow-closed.", file=out)
        return 1
    now = now or datetime.datetime.now()
    all_ok, pending, written = True, 0, 0
    for spec in specs:
        files = _find_sv_files(wtf, spec["file"])
        if not files:
            print("No %s found under %s. Log in once with %s enabled, then quit WoW and run this "
                  "again." % (spec["file"], wtf, spec["addon"]), file=out)
            print(spec["in_game"], file=out)
            all_ok = False
            continue
        for path in files:
            shown = _masked(path, wtf)
            with open(path, "rb") as f:
                raw = f.read()
            text = raw.decode("latin-1")  # one byte per character, so offsets are byte offsets
            try:
                hits = find_value(text, spec["path"], spec["key"])
            except ValueError as ex:
                print("%s: I don't recognise this file's layout (%s). Nothing was changed."
                      % (shown, ex), file=out)
                all_ok = False
                continue
            if len(hits) > 1:
                print("%s: %s appears more than once. Nothing was changed." % (shown, spec["key"]),
                      file=out)
                all_ok = False
                continue
            if not hits:
                print("%s: %s isn't saved in this file, so the addon uses its own default. I "
                      "haven't checked what that default is. Nothing was changed."
                      % (shown, spec["label"]), file=out)
                all_ok = False
                continue
            start, end, value = hits[0]
            if value == spec["want"]:
                print("%s: %s is %s. Nothing to do." % (shown, spec["label"], _state(value)),
                      file=out)
                continue
            if not apply:
                all_ok = False
                print("%s: %s is %s. %s Turn it %s (run again with --apply to see the change)."
                      % (shown, spec["label"], _state(value), spec["why"],
                         _state(spec["want"]).lower()), file=out)
                continue
            line_no, before, after = _change_preview(text, start, end, spec["want"])
            if not write:
                all_ok = False
                pending += 1
                print("%s: %s is %s. Would change line %d:" % (shown, spec["label"],
                                                               _state(value), line_no), file=out)
                print("    before: %s" % before, file=out)
                print("    after:  %s" % after, file=out)
                print("    and first copy the file to %s"
                      % os.path.basename(_backup_path(path, now)), file=out)
                continue
            try:
                backup = _write_value(path, raw, start, end, spec["want"], now)
            except OSError as ex:
                print("%s: not written (%s). Nothing was changed." % (shown, ex), file=out)
                all_ok = False
                continue
            written += 1
            print("%s: line %d changed. %s was %s, now %s. Backup: %s"
                  % (shown, line_no, spec["label"], _state(value), _state(spec["want"]),
                     os.path.basename(backup)), file=out)
    if not apply and not all_ok:
        for spec in specs:
            print(spec["in_game"], file=out)
    if pending:
        print("Dry run: nothing was written. To make the change, close WoW, then run again with "
              "--apply --write --wow-closed.", file=out)
    if written:
        print("Only that value changed. Put the file back on the Thor before you start WoW "
              "again.", file=out)
    return 0 if all_ok else 1


# ---------------------------------------------------------------- hash

def run_hash(source, folders, out=sys.stdout):
    names = folders or sorted(source.folders())
    for f in names:
        print("%s  %s  %s" % (tree_sha256(source.entries(f)), source.version(f) or "-", f), file=out)
    return 0


# ---------------------------------------------------------------- cli

def _source(args):
    if args.adb:
        return AdbSource(args.adb_path, args.serial, args.device_root, args.flavor)
    if not args.addons:
        raise SystemExit("Give the AddOns folder, or --adb to read it from the device.")
    return LocalSource(args.addons)


def main(argv=None):
    p = argparse.ArgumentParser(description="Check the third-party addons this guide uses.")
    p.add_argument("--manifest", default=DEFAULT_MANIFEST)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_src(sp):
        sp.add_argument("addons", nargs="?", help="your AddOns folder")
        sp.add_argument("--adb", action="store_true", help="read the AddOns folder on the device")
        sp.add_argument("--serial", help="adb device serial (when more than one is connected)")
        sp.add_argument("--flavor", default="retail", choices=sorted(FLAVOR_DIRS))
        sp.add_argument("--adb-path", default="adb")
        sp.add_argument("--device-root", default=DEFAULT_DEVICE_ROOT)

    c = sub.add_parser("check", help="check an AddOns folder")
    add_src(c)
    c.add_argument("--profile", default="single", choices=sorted(PROFILE_USED_FOR))
    i = sub.add_parser("install", help="unpack your own download into your own AddOns folder")
    i.add_argument("zip")
    i.add_argument("addons")
    i.add_argument("--replace", action="store_true",
                   help="replace folders already in your AddOns folder")
    s = sub.add_parser("settings", help="the one saved setting the guide needs changed")
    s.add_argument("wtf", help="your WTF folder (a copy on this computer)")
    s.add_argument("--apply", action="store_true",
                   help="dry run: print the exact change, write nothing")
    s.add_argument("--write", action="store_true",
                   help="make the change (backs up each file first, needs --wow-closed)")
    s.add_argument("--wow-closed", action="store_true",
                   help="you confirm WoW is closed (this script can't see it)")
    h = sub.add_parser("hash", help="print tree hashes (manifest upkeep)")
    add_src(h)
    h.add_argument("--folder", action="append", default=[])
    args = p.parse_args(argv)

    if args.cmd == "check":
        return run_check(_source(args), load_manifest(args.manifest), args.profile)
    if args.cmd == "install":
        return run_install(args.zip, args.addons, load_manifest(args.manifest), args.replace)
    if args.cmd == "settings":
        return run_settings(args.wtf, load_manifest(args.manifest), args.apply, args.write,
                            args.wow_closed, out=sys.stdout)
    if args.cmd == "hash":
        return run_hash(_source(args), args.folder)
    return 1


if __name__ == "__main__":
    sys.exit(main())
