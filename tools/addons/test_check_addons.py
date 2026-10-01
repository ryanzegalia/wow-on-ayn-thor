#!/usr/bin/env python3
"""Tests for check_addons.py. Fake addon trees only, nothing from a real addon.

    python tools/addons/test_check_addons.py
"""
import ast
import contextlib
import datetime
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_addons as ca  # noqa: E402

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode("utf-8"))


def make_addon(root, folder, version):
    toc = "## Title: %s\n" % folder + ("## Version: %s\n" % version if version else "")
    write(os.path.join(root, folder, folder + ".toc"), toc)
    write(os.path.join(root, folder, "core.lua"), "-- %s core\nlocal x = 1\n" % folder)
    write(os.path.join(root, folder, "sub", "a b.lua"), "y = 2\n")


SAMPLE_SV = (
    "\r\n"
    "TalentTreeTweaksDB = {\r\n"
    "[\"modules\"] = {\r\n"
    "[\"InspectDiff\"] = true,\r\n"
    "[\"ScaleTalentFrame\"] = true,\r\n"
    "[\"MiscFixes\"] = true,\r\n"
    "},\r\n"
    "[\"moduleDb\"] = {\r\n"
    "[\"ScaleTalentFrame\"] = {\r\n"
    "[\"scale\"] = 1,\r\n"
    "},\r\n"
    "[\"Note\"] = {\r\n"
    "[1] = \"a } tricky { string\",\r\n"
    "},\r\n"
    "},\r\n"
    "}\r\n"
)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.tested = os.path.join(self.tmp, "tested")
        self.user = os.path.join(self.tmp, "user", "AddOns")
        self.repo = os.path.join(self.tmp, "repo")
        specs = [("Alpha", "1.0"), ("Beta", "2.0"), ("Pad", "3.0"), ("Pad_Bar", None), ("Chat", "1.0")]
        for folder, ver in specs:
            make_addon(self.tested, folder, ver)
        make_addon(os.path.join(self.repo, "addons"), "Mine", "0.1")
        write(os.path.join(self.repo, "addons", "Mine", "tests", "test_mine.py"), "pass\n")

        def th(f):
            return ca.tree_sha256(ca.local_entries(os.path.join(self.tested, f)))

        def entry(name, folders, ver, used_for, requires=(), optional=False):
            return {"name": name, "folders": folders, "author": name + " author",
                    "pages": {"curseforge": "https://example.org/%s" % name.lower(), "wago": None,
                              "github": None},
                    "version_tested": ver, "tree_sha256": {f: th(f) for f in folders},
                    "download_tested": None, "requires": list(requires), "used_for": used_for,
                    "optional": optional, "why": "because"}

        self.manifest = {"third_party": [
            entry("Alpha", ["Alpha"], "1.0", "dual-screen", requires=["Beta"]),
            entry("Beta", ["Beta"], "2.0", "dual-screen"),
            entry("Pad", ["Pad", "Pad_Bar"], "3.0", "both"),
            entry("Chat", ["Chat"], "1.0", "both", optional=True),
        ], "own": [{"name": "Mine", "folders": ["Mine"], "path": "addons/Mine", "version": "0.1",
                    "used_for": "both", "why": "mine"}]}
        shutil.copytree(self.tested, self.user)
        shutil.copytree(os.path.join(self.repo, "addons", "Mine"), os.path.join(self.user, "Mine"),
                        ignore=shutil.ignore_patterns("tests"))

    def tearDown(self):
        self._tmp.cleanup()

    def check(self, profile="dual"):
        out = io.StringIO()
        code = ca.run_check(ca.LocalSource(self.user), self.manifest, profile, self.repo, out)
        return code, out.getvalue()

    def status_of(self, text, name):
        for line in text.splitlines():
            if line[21:].split(" ")[0] == name:
                return line[:20].strip()
        return None


class TreeHash(unittest.TestCase):
    def test_definition(self):
        a, b = "a" * 64, "b" * 64
        want = hashlib.sha256(("%s  a.lua\n%s  b/c.lua\n" % (b, a)).encode()).hexdigest()
        self.assertEqual(ca.tree_sha256([(a, "b/c.lua"), (b, "a.lua")]), want)

    def test_adb_output_matches_local(self):
        with tempfile.TemporaryDirectory() as d:
            make_addon(d, "Alpha", "1.0")
            local = ca.local_entries(os.path.join(d, "Alpha"))
            fake = "".join("%s  ./%s\r\n" % (h, p) for h, p in reversed(local))
            self.assertEqual(ca.tree_sha256(ca.parse_sha256sum(fake)), ca.tree_sha256(local))


class Check(Base):
    def test_all_ok(self):
        code, text = self.check()
        self.assertEqual(code, 0, text)
        for name in ("Alpha", "Beta", "Pad", "Chat", "Mine"):
            self.assertEqual(self.status_of(text, name), "OK", text)

    def test_missing_folder(self):
        shutil.rmtree(os.path.join(self.user, "Pad_Bar"))
        code, text = self.check()
        self.assertEqual(code, 1)
        self.assertEqual(self.status_of(text, "Pad"), "MISSING")
        self.assertIn("Some of its folders are missing: Pad_Bar", text)
        self.assertIn("https://example.org/pad", text)
        self.assertIn("Pad author", text)

    def test_missing_requirement(self):
        shutil.rmtree(os.path.join(self.user, "Beta"))
        code, text = self.check()
        self.assertEqual(code, 1)
        self.assertEqual(self.status_of(text, "Alpha"), "MISSING REQUIREMENT")
        self.assertEqual(self.status_of(text, "Beta"), "MISSING")

    def test_different_version(self):
        write(os.path.join(self.user, "Alpha", "Alpha.toc"), "## Version: 1.1\n")
        code, text = self.check()
        self.assertEqual(code, 2)
        self.assertEqual(self.status_of(text, "Alpha"), "DIFFERENT VERSION")
        self.assertIn("You have 1.1, I tested 1.0", text)

    def test_different_files(self):
        write(os.path.join(self.user, "Alpha", "core.lua"), "-- changed\n")
        code, text = self.check()
        self.assertEqual(code, 2)
        self.assertEqual(self.status_of(text, "Alpha"), "DIFFERENT FILES")
        self.assertIn("probably fine", text)

    def test_optional_missing_is_not_a_failure(self):
        shutil.rmtree(os.path.join(self.user, "Chat"))
        code, text = self.check()
        self.assertEqual(code, 0, text)
        self.assertEqual(self.status_of(text, "Chat"), "NOT INSTALLED")

    def test_single_profile_skips_dual_only(self):
        shutil.rmtree(os.path.join(self.user, "Alpha"))
        shutil.rmtree(os.path.join(self.user, "Beta"))
        code, text = self.check("single")
        self.assertEqual(code, 0, text)
        self.assertNotIn("Alpha", text)

    def test_own_addon_version(self):
        write(os.path.join(self.user, "Mine", "Mine.toc"), "## Version: 0.0.9\n")
        code, text = self.check()
        self.assertEqual(code, 2)
        self.assertIn("this repo has 0.1", text)


class Install(Base):
    def make_zip(self, name, folders, extra=None):
        path = os.path.join(self.tmp, name)
        with zipfile.ZipFile(path, "w") as z:
            for f in folders:
                for h, rel in ca.local_entries(os.path.join(self.tested, f)):
                    z.write(os.path.join(self.tested, f, rel), f + "/" + rel)
            for arc, data in (extra or {}).items():
                z.writestr(arc, data)
        return path

    def install(self, zp, dest, **kw):
        out = io.StringIO()
        return ca.run_install(zp, dest, self.manifest, out=out, **kw), out.getvalue()

    def test_other_zip_refused(self):
        zp = self.make_zip("Alpha-9.zip", ["Alpha"], {"Junk/Junk.toc": "x"})
        self.manifest["third_party"][0]["download_tested"] = {
            "filename": "Alpha-1.0.zip", "sha256": "0" * 64, "curseforge_file_id": 1}
        dest = os.path.join(self.tmp, "fresh")
        os.makedirs(dest)
        code, text = self.install(zp, dest)
        self.assertEqual(code, 1)
        self.assertIn("isn't the zip I tested", text)
        self.assertIn("Nothing was installed", text)
        self.assertEqual(os.listdir(dest), [])

    def test_no_tested_zip_recorded_refused(self):
        zp = self.make_zip("Beta.zip", ["Beta"])
        dest = os.path.join(self.tmp, "fresh")
        os.makedirs(dest)
        code, text = self.install(zp, dest)
        self.assertEqual(code, 1)
        self.assertIn("didn't keep the zip I tested for Beta", text)
        self.assertEqual(os.listdir(dest), [])

    def test_no_way_to_skip_the_hash(self):
        with self.assertRaises(TypeError):
            ca.run_install("x.zip", self.tmp, self.manifest, any_version=True)
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            ca.main(["install", "x.zip", self.tmp, "--any-version"])

    def test_exact_zip_installs(self):
        zp = self.make_zip("Pad-3.0.zip", ["Pad", "Pad_Bar"])
        self.manifest["third_party"][2]["download_tested"] = {
            "filename": "Pad-3.0.zip", "sha256": ca.file_sha256(zp), "curseforge_file_id": 2}
        dest = os.path.join(self.tmp, "fresh")
        os.makedirs(dest)
        code, text = self.install(zp, dest)
        self.assertEqual(code, 0, text)
        self.assertIn("Pad: matches what I tested", text)
        self.assertEqual(sorted(os.listdir(dest)), ["Pad", "Pad_Bar"])
        code, text = self.install(zp, dest)
        self.assertEqual(code, 1)
        self.assertIn("--replace", text)
        code, text = self.install(zp, dest, replace=True)
        self.assertEqual(code, 0, text)
        self.assertEqual(sorted(os.listdir(dest)), ["Pad", "Pad_Bar"])

    def test_path_escape_refused(self):
        zp = self.make_zip("bad.zip", ["Alpha"], {"../escape.lua": "x"})
        dest = os.path.join(self.tmp, "fresh")
        os.makedirs(dest)
        self.manifest["third_party"][0]["download_tested"] = {
            "filename": "bad.zip", "sha256": ca.file_sha256(zp), "curseforge_file_id": 1}
        code, text = self.install(zp, dest)
        self.assertEqual(code, 1)
        self.assertIn("Refusing", text)
        self.assertEqual(os.listdir(dest), [])


class NoNetworkNoDevice(unittest.TestCase):
    """The script reads what you give it. It has no code that downloads or pushes anything."""

    def setUp(self):
        with open(ca.__file__, encoding="utf-8") as f:
            self.tree = ast.parse(f.read())

    def test_no_network_modules(self):
        mods = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                mods |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                mods.add((node.module or "").split(".")[0])
        self.assertFalse(mods & {"urllib", "http", "socket", "ssl", "ftplib", "requests",
                                 "urllib3", "httpx", "webbrowser"}, mods)

    def test_adb_is_only_used_to_read(self):
        strings = {n.value for n in ast.walk(self.tree)
                   if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        for word in ("push", "pull"):
            self.assertNotIn(word, strings)
        self.assertFalse([t for t in strings if "adb push" in t or "adb install" in t])


NOW = datetime.datetime(2026, 9, 24, 12, 0, 0)

# Other keys, a same-named key elsewhere, a string that looks like the key, a comment, a
# non-ASCII byte and a second saved variable. None of it may change.
RICH_SV = (
    b"\r\n"
    b"-- a comment with [\"ScaleTalentFrame\"] = true in it\r\n"
    b"TalentTreeTweaksDB = {\r\n"
    b"[\"modules\"] = {\r\n"
    b"[\"InspectDiff\"] = true,\r\n"
    b"[\"ScaleTalentFrame\"] = true,\r\n"
    b"[\"MiscFixes\"] = false,\r\n"
    b"},\r\n"
    b"[\"moduleDb\"] = {\r\n"
    b"[\"ScaleTalentFrame\"] = {\r\n"
    b"[\"scale\"] = 1.25,\r\n"
    b"[\"enabled\"] = true,\r\n"
    b"},\r\n"
    b"[\"Note\"] = {\r\n"
    b"[1] = \"[\\\"ScaleTalentFrame\\\"] = true } {\",\r\n"
    b"[2] = \"caf\xe9\",\r\n"
    b"},\r\n"
    b"},\r\n"
    b"}\r\n"
    b"TalentTreeTweaksCharDB = {\r\n"
    b"[\"modules\"] = {\r\n"
    b"[\"ScaleTalentFrame\"] = true,\r\n"
    b"},\r\n"
    b"}\r\n"
)


class Settings(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.wtf = os.path.join(self._tmp.name, "WTF")
        self.svdir = os.path.join(self.wtf, "Account", "EXAMPLEACCT", "SavedVariables")
        self.sv = os.path.join(self.svdir, "TalentTreeTweaks.lua")
        write(self.sv, SAMPLE_SV)
        self.manifest = {"third_party": [{"name": "TalentTreeTweaks",
                                          "folders": ["TalentTreeTweaks"]}]}

    def tearDown(self):
        self._tmp.cleanup()

    def run_settings(self, **kw):
        out = io.StringIO()
        kw.setdefault("now", NOW)
        manifest = kw.pop("manifest", self.manifest)
        return ca.run_settings(self.wtf, manifest, out=out, **kw), out.getvalue()

    def read(self, path):
        with open(path, "rb") as f:
            return f.read()

    def listing(self):
        return sorted(os.listdir(self.svdir))

    def test_report_on(self):
        code, text = self.run_settings()
        self.assertEqual(code, 1)
        self.assertIn("is ON", text)
        self.assertIn("/ttt", text)
        self.assertNotIn("EXAMPLEACCT", text)
        self.assertEqual(self.read(self.sv), SAMPLE_SV.encode())

    def test_dry_run_is_default_and_writes_nothing(self):
        code, text = self.run_settings(apply=True)
        self.assertEqual(code, 1)
        self.assertIn("Would change line 5", text)
        self.assertIn('before: ["ScaleTalentFrame"] = true,', text)
        self.assertIn('after:  ["ScaleTalentFrame"] = false,', text)
        self.assertIn("TalentTreeTweaks.lua.bak-20260924-120000", text)
        self.assertIn("nothing was written", text)
        self.assertNotIn("EXAMPLEACCT", text)
        self.assertEqual(self.read(self.sv), SAMPLE_SV.encode())
        self.assertEqual(self.listing(), ["TalentTreeTweaks.lua"])

    def test_write_refused_when_wow_state_unknown(self):
        code, text = self.run_settings(write=True)
        self.assertEqual(code, 1)
        self.assertIn("can't tell whether WoW is running", text)
        self.assertIn("--wow-closed", text)
        self.assertEqual(self.read(self.sv), SAMPLE_SV.encode())
        self.assertEqual(self.listing(), ["TalentTreeTweaks.lua"])

    def test_write_backs_up_first(self):
        code, text = self.run_settings(write=True, wow_closed=True)
        self.assertEqual(code, 0, text)
        backup = self.sv + ".bak-20260924-120000"
        self.assertEqual(self.read(backup), SAMPLE_SV.encode())
        self.assertIn("Backup: TalentTreeTweaks.lua.bak-20260924-120000", text)
        new = self.read(self.sv)
        self.assertEqual(new, SAMPLE_SV.replace('["ScaleTalentFrame"] = true',
                                                '["ScaleTalentFrame"] = false').encode())
        self.assertEqual(new.count(b"\r\n"), SAMPLE_SV.count("\r\n"))
        code, text = self.run_settings(write=True, wow_closed=True)
        self.assertEqual(code, 0)
        self.assertIn("is OFF", text)
        # A second change in the same second never overwrites the first backup.
        write(self.sv, SAMPLE_SV)
        code, text = self.run_settings(write=True, wow_closed=True)
        self.assertEqual(code, 0, text)
        self.assertEqual(self.read(backup + "-2"), SAMPLE_SV.encode())
        self.assertEqual(self.read(backup), SAMPLE_SV.encode())
        self.assertFalse([n for n in self.listing() if n.endswith("-tmp")])

    def test_everything_else_is_byte_identical(self):
        write(self.sv, RICH_SV)
        code, text = self.run_settings(write=True, wow_closed=True)
        self.assertEqual(code, 0, text)
        new = self.read(self.sv)
        i = RICH_SV.index(b'["ScaleTalentFrame"] = true,\r\n["MiscFixes"]')
        i += len(b'["ScaleTalentFrame"] = ')
        self.assertEqual(RICH_SV[i:i + 4], b"true")
        self.assertEqual(new, RICH_SV[:i] + b"false" + RICH_SV[i + 4:])
        self.assertEqual(self.read(self.sv + ".bak-20260924-120000"), RICH_SV)
        self.assertEqual(new.count(b'["ScaleTalentFrame"] = true'), 2)
        self.assertIn(b'["enabled"] = true', new)
        self.assertIn(b"caf\xe9", new)

    def test_only_addons_in_the_manifest(self):
        code, text = self.run_settings(write=True, wow_closed=True,
                                       manifest={"third_party": []})
        self.assertEqual(code, 0)
        self.assertIn("Nothing to do", text)
        self.assertEqual(self.read(self.sv), SAMPLE_SV.encode())
        self.assertEqual(self.listing(), ["TalentTreeTweaks.lua"])

    def test_unrecognised_layout_refused(self):
        odd = "TalentTreeTweaksDB = { modules = { ScaleTalentFrame = true } }\n"
        write(self.sv, odd)
        code, text = self.run_settings(write=True, wow_closed=True)
        self.assertEqual(code, 1)
        self.assertIn("don't recognise", text)
        self.assertEqual(self.read(self.sv), odd.encode())
        self.assertEqual(self.listing(), ["TalentTreeTweaks.lua"])

    def test_key_missing(self):
        write(self.sv, SAMPLE_SV.replace('["ScaleTalentFrame"] = true,\r\n', ""))
        code, text = self.run_settings(write=True, wow_closed=True)
        self.assertEqual(code, 1)
        self.assertIn("isn't saved", text)
        self.assertEqual(self.listing(), ["TalentTreeTweaks.lua"])

    def test_cli_flags(self):
        mpath = os.path.join(self._tmp.name, "m.json")
        with open(mpath, "w", encoding="utf-8") as f:
            json.dump(self.manifest, f)
        for extra in (["--apply"], ["--write"], ["--apply", "--wow-closed"]):
            with contextlib.redirect_stdout(io.StringIO()):
                code = ca.main(["--manifest", mpath, "settings", self.wtf] + extra)
            self.assertEqual(code, 1, extra)
            self.assertEqual(self.read(self.sv), SAMPLE_SV.encode())
            self.assertEqual(self.listing(), ["TalentTreeTweaks.lua"])
        with contextlib.redirect_stdout(io.StringIO()):
            code = ca.main(["--manifest", mpath, "settings", self.wtf, "--write", "--wow-closed"])
        self.assertEqual(code, 0)
        self.assertEqual(len(self.listing()), 2)


class RealManifest(unittest.TestCase):
    def setUp(self):
        self.m = ca.load_manifest(os.path.join(REPO_ROOT, "addons", "third-party.json"))

    def test_curseforge_links_use_the_addon_page(self):
        for e in self.m["third_party"]:
            self.assertRegex(e["pages"]["curseforge"],
                             r"^https://www\.curseforge\.com/wow/addons/[a-z0-9-]+$", e["name"])

    def test_documented_settings_belong_to_listed_addons(self):
        names = {e["name"] for e in self.m["third_party"]}
        for spec in ca.DOCUMENTED_SETTINGS:
            self.assertIn(spec["addon"], names)


if __name__ == "__main__":
    unittest.main(verbosity=1)
