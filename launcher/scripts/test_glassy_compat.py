"""Regression tests for the Glassy ChatDock.lua retail anchor-replay compatibility patch in
wowgo.sh (requires bash).

Glassy hooks GeneralDockManager's scrollFrame:SetPoint and replays a cosmetic +5 BOTTOMRIGHT
yOffset AFTER Blizzard's own native call fires, via a retail-only SecureHook wrapper
(Utils.hookPresentation, Glassy's own utils.lua) -- plus a one-time replay of the same anchor
immediately after installing that hook. Forever's WOW_PROJECT_ID equals WOW_PROJECT_MAINLINE, so
Glassy's own Constants.ENV computation (constants.lua: `WOW_PROJECT_MAINLINE and WOW_PROJECT_ID
== WOW_PROJECT_MAINLINE and "retail" or "classic"`) already reads "retail" for Forever too --
gating both call sites on `Constants.ENV ~= "retail"` fixes real retail and Forever together with
no wowgo.sh-side flavor branching, while classic's original RawHook+replay is untouched.

Same discipline as test_consoleport_compat.py: the shell block under test
is extracted out of the real wowgo.sh by anchor text (not hand-retyped), and the OLD literals are
parsed straight out of wowgo.sh's own GLASSY_HOOK_OLD=/GLASSY_REPLAY_OLD= assignments, so this
file breaks loudly if wowgo.sh's patch text ever drifts instead of silently testing stale text.

This patch checks only the selected $DIR, independently of the existing Offhand loop. The
fixture reproduces the actual on-device AddOns/Glassy/Glassy/Components source depth.

No addon source is stored here, matching test_consoleport_compat.py: only
the guard-line literals wowgo.sh itself carries are used for the shell-side tests, and the
Lua-level semantics tests run an originally-written harness that reproduces the *verified*
branch contract of Glassy's own Utils.hookPresentation (read from the real utils.lua: non-retail
RawHooks; retail SecureHooks and manually stashes the pre-hook original) -- not a copy of
Glassy's MIT-licensed file. Those tests prove the call-count/call-identity contract the patch
changes (is the native method ever replaced; how many times does it fire per caller-side
SetPoint; does a later, independent SetPoint call see the same behavior as the initial one) --
they do NOT reproduce the actual in-game secure-frame anchor-cycle/taint bug, which needs a live
protected frame and combat lockdown and is out of reach of a unit test.
"""
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

try:
    import lupa
except ImportError:  # pragma: no cover - environment guard, mirrors the BASH skip below
    lupa = None

SOURCE = pathlib.Path(__file__).with_name("wowgo.sh").read_text(encoding="utf-8")
BASH = shutil.which("bash")

_START = "# Glassy compatibility: only the selected install."
_END = '\nif [ "$MODE" = direct ]; then'
BLOCK = SOURCE[SOURCE.index(_START):]
BLOCK = BLOCK[: BLOCK.index(_END)]


def _literal(varname):
    """Pulls VARNAME='...' verbatim out of wowgo.sh. Both assignments are single line,
    single-quoted, and contain no apostrophes, so a plain regex capture is exact."""
    match = re.search(r"^\s*" + varname + r"='(.*)'\s*$", SOURCE, re.MULTILINE)
    assert match, f"{varname}=... not found in wowgo.sh -- extraction is stale"
    return match.group(1)


# Android's toybox sed is byte-exact. The Windows (MSYS) sed that runs these tests on the PC opens
# files in text mode and silently drops every CR, which would make a CRLF test fail for a reason
# the device never has. Make the host behave like the device instead of weakening the assertion.
HOST_SED_SHIM = 'case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) sed() { command sed -b "$@"; } ;; esac'

GLASSY_HOOK_OLD = _literal("GLASSY_HOOK_OLD")
GLASSY_REPLAY_OLD = _literal("GLASSY_REPLAY_OLD")
GLASSY_HOOK_NEW = '  if Constants.ENV ~= "retail" and not self:IsHooked(self.scrollFrame, "SetPoint") then'
GLASSY_REPLAY_NEW = '  if Constants.ENV ~= "retail" and bottomPoint then'


def wrap_chatdock_fixture(hook_guard_line, replay_guard_line):
    """A small ChatDock.lua-shaped fixture carrying both real guard lines verbatim, wired to the
    real handler-closure shape ChatDock itself uses (the yOffset+5-on-BOTTOMRIGHT replay) and to
    a module-level `hookPresentation`/`self` so the SAME text also runs as real Lua in
    LuaAnchorReplaySemanticsTests below -- one fixture, not two hand-maintained copies that could
    drift apart. Only the two guard lines are ever expected to change between OLD and NEW."""
    return (
        "function RefreshDock(self, bottomPoint, bottomRelativeTo, bottomRelativePoint, bottomX, bottomY)\n"
        + hook_guard_line + "\n"
        "    hookPresentation(self, self.scrollFrame, \"SetPoint\", function (frame, point, relativeTo, relativePoint, xOffset, yOffset)\n"
        "      if point == \"BOTTOMRIGHT\" then\n"
        "        yOffset = (yOffset or 0) + 5\n"
        "      end\n"
        "      self.hooks[self.scrollFrame].SetPoint(frame, point, relativeTo, relativePoint, xOffset, yOffset)\n"
        "    end)\n"
        "  end\n"
        "\n"
        "  -- Correct the anchor that Blizzard applied before Glassy installed its hook.\n"
        + replay_guard_line + "\n"
        "    self.scrollFrame:SetPoint(bottomPoint, bottomRelativeTo, bottomRelativePoint, bottomX, bottomY)\n"
        "  end\n"
        "end\n"
    )


ORIGINAL_CHATDOCK_LUA = wrap_chatdock_fixture(GLASSY_HOOK_OLD, GLASSY_REPLAY_OLD)


class _ShellHarnessMixin:
    """Runs the actual selected-install patch against a throwaway ROOT/BASE."""

    def run_block(self, dirs, base_extra=None, selected="_retail_"):
        """`dirs` maps flavor dir name ('_retail_'/'_classic_'/'_classic_beta_') -> ChatDock.lua
        content, or None to omit the file for that dir (the missing-addon-is-optional case).
        Returns (CompletedProcess, {dir: final_or_None}, {dir: backup_or_None}, log_text)."""
        directory = tempfile.mkdtemp(prefix="wow-glassy-compat-")
        try:
            root = pathlib.Path(directory) / "root"
            base = pathlib.Path(directory) / "base"
            base.mkdir(parents=True)
            targets = {}
            for dir_name, content in dirs.items():
                target = root / dir_name / "Interface" / "AddOns" / "Glassy" / "Glassy" / "Components" / "ChatDock.lua"
                if content is not None:
                    target.parent.mkdir(parents=True)
                    target.write_bytes(content.encode("utf-8"))
                targets[dir_name] = target
            if base_extra is not None:
                base_extra(base)
            logfile = pathlib.Path(directory) / "log.txt"
            script = "\n".join([
                "set -u", "umask 077", HOST_SED_SHIM,
                "ROOT=$1; BASE=$2; LOGFILE=$3; DIR=$4",
                "fail() { printf 'FAIL:%s\\n' \"$1\" >&2; exit 9; }",
                "log() { printf 'LOG:%s\\n' \"$*\" >> \"$LOGFILE\"; }",
                BLOCK,
            ])
            result = subprocess.run(
                [BASH, "-c", script, "--", root.as_posix(), base.as_posix(), logfile.as_posix(), selected],
                capture_output=True, text=True, timeout=10,
            )
            finals = {d: (t.read_bytes().decode("utf-8") if t.exists() else None) for d, t in targets.items()}
            backups = {}
            for d in dirs:
                backup_path = base / "backups" / "compat" / f"Glassy-ChatDock-{d}.lua"
                backups[d] = backup_path.read_bytes().decode("utf-8") if backup_path.exists() else None
            log_text = logfile.read_bytes().decode("utf-8") if logfile.exists() else ""
            return result, finals, backups, log_text
        finally:
            shutil.rmtree(directory, ignore_errors=True)


@unittest.skipUnless(BASH, "bash is required to test the production shell block")
class GlassyChatDockCompatTests(_ShellHarnessMixin, unittest.TestCase):
    def test_patches_matching_guard_independently_in_each_flavor_dir(self):
        for dir_name in ("_retail_", "_classic_", "_classic_beta_"):
            with self.subTest(dir_name=dir_name):
                result, finals, backups, log_text = self.run_block({dir_name: ORIGINAL_CHATDOCK_LUA}, selected=dir_name)
                self.assertEqual(result.returncode, 0, result.stderr)
                final = finals[dir_name]
                self.assertIn(GLASSY_HOOK_NEW, final)
                self.assertIn(GLASSY_REPLAY_NEW, final)
                self.assertNotIn(GLASSY_HOOK_OLD, final)
                self.assertNotIn(GLASSY_REPLAY_OLD, final)
                # Only the two guard lines changed -- every other line is byte-identical.
                original_lines = ORIGINAL_CHATDOCK_LUA.splitlines()
                final_lines = final.splitlines()
                self.assertEqual(len(original_lines), len(final_lines))
                changed = [i for i, (o, n) in enumerate(zip(original_lines, final_lines)) if o != n]
                self.assertEqual(len(changed), 2, changed)
                for i in changed:
                    self.assertIn(original_lines[i], (GLASSY_HOOK_OLD, GLASSY_REPLAY_OLD))
                    self.assertIn(final_lines[i], (GLASSY_HOOK_NEW, GLASSY_REPLAY_NEW))
                self.assertEqual(backups[dir_name], ORIGINAL_CHATDOCK_LUA)
                self.assertIn(f"LOG:Applied the scoped Glassy retail anchor-replay guard ({dir_name})", log_text)

    def test_only_selected_flavor_changes_or_gets_a_backup(self):
        dirs = {d: ORIGINAL_CHATDOCK_LUA for d in ("_retail_", "_classic_", "_classic_beta_")}
        for selected in dirs:
            with self.subTest(selected=selected):
                result, finals, backups, log_text = self.run_block(dirs, selected=selected)
                self.assertEqual(result.returncode, 0, result.stderr)
                for d in dirs:
                    if d == selected:
                        self.assertIn(GLASSY_HOOK_NEW, finals[d])
                        self.assertEqual(backups[d], ORIGINAL_CHATDOCK_LUA)
                    else:
                        self.assertEqual(finals[d], ORIGINAL_CHATDOCK_LUA)
                        self.assertIsNone(backups[d])
                self.assertEqual(log_text.count("Applied the scoped Glassy retail anchor-replay guard"), 1)

    def test_already_patched_is_idempotent(self):
        first, finals1, _b1, _l1 = self.run_block({"_retail_": ORIGINAL_CHATDOCK_LUA})
        self.assertEqual(first.returncode, 0, first.stderr)
        patched = finals1["_retail_"]
        second, finals2, backups2, log_text = self.run_block({"_retail_": patched})
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(finals2["_retail_"], patched)
        self.assertIsNone(backups2["_retail_"])
        self.assertEqual(log_text, "")

    def test_repeat_apply_against_the_same_tree_is_byte_stable(self):
        # Same ROOT/BASE reused for a second run (not a fresh tree) -- proves re-running the
        # whole block twice back-to-back never mutates the file a second time.
        directory = tempfile.mkdtemp(prefix="wow-glassy-compat-repeat-")
        try:
            root = pathlib.Path(directory) / "root"
            base = pathlib.Path(directory) / "base"
            target = root / "_retail_" / "Interface" / "AddOns" / "Glassy" / "Glassy" / "Components" / "ChatDock.lua"
            target.parent.mkdir(parents=True)
            base.mkdir(parents=True)
            target.write_bytes(ORIGINAL_CHATDOCK_LUA.encode("utf-8"))
            logfile = pathlib.Path(directory) / "log.txt"
            script = "\n".join([
                "set -u", "umask 077", HOST_SED_SHIM,
                "ROOT=$1; BASE=$2; LOGFILE=$3; DIR=$4",
                "fail() { printf 'FAIL:%s\\n' \"$1\" >&2; exit 9; }",
                "log() { printf 'LOG:%s\\n' \"$*\" >> \"$LOGFILE\"; }",
                BLOCK,
            ])
            args = [BASH, "-c", script, "--", root.as_posix(), base.as_posix(), logfile.as_posix(), "_retail_"]
            first = subprocess.run(args, capture_output=True, text=True, timeout=10)
            self.assertEqual(first.returncode, 0, first.stderr)
            after_first = target.read_bytes()
            second = subprocess.run(args, capture_output=True, text=True, timeout=10)
            self.assertEqual(second.returncode, 0, second.stderr)
            after_second = target.read_bytes()
            self.assertEqual(after_first, after_second)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_existing_backup_is_preserved(self):
        sentinel = "-- pristine copy captured on an earlier install\n" + ORIGINAL_CHATDOCK_LUA

        def seed_backup(base):
            backup_dir = base / "backups" / "compat"
            backup_dir.mkdir(parents=True)
            (backup_dir / "Glassy-ChatDock-_retail_.lua").write_bytes(sentinel.encode("utf-8"))

        result, finals, backups, _log = self.run_block({"_retail_": ORIGINAL_CHATDOCK_LUA}, base_extra=seed_backup)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(GLASSY_HOOK_NEW, finals["_retail_"])
        self.assertEqual(backups["_retail_"], sentinel)

    def test_unrecognized_partial_match_is_left_unchanged(self):
        # Both sites are mandatory together. If only one matches (an upstream fork reworded the
        # other), that is an unrecognized shape -- skip rather than half-patch it.
        only_hook = wrap_chatdock_fixture(GLASSY_HOOK_OLD, '  if bottomPoint and CPAPI.ShouldReplay() then')
        result, finals, backups, log_text = self.run_block({"_retail_": only_hook})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(finals["_retail_"], only_hook)
        self.assertIsNone(backups["_retail_"])
        self.assertIn("Skipped unrecognized Glassy anchor guards", log_text)

        only_replay = wrap_chatdock_fixture(
            '  if not self:IsHooked(self.scrollFrame, "SetPoint") and true then', GLASSY_REPLAY_OLD
        )
        result2, finals2, backups2, log_text2 = self.run_block({"_retail_": only_replay})
        self.assertEqual(result2.returncode, 0, result2.stderr)
        self.assertEqual(finals2["_retail_"], only_replay)
        self.assertIsNone(backups2["_retail_"])
        self.assertIn("Skipped unrecognized Glassy anchor guards", log_text2)

    def test_crlf_source_is_patched_and_keeps_its_line_endings(self):
        # The installed Glassy ships CRLF. Android's grep -x does not ignore the CR (the PC's
        # does), which is how an LF-only fixture hid a patch that refused the real file on-device.
        crlf = ORIGINAL_CHATDOCK_LUA.replace("\n", "\r\n")
        result, finals, backups, log_text = self.run_block({"_retail_": crlf})
        self.assertEqual(result.returncode, 0, result.stderr)
        final = finals["_retail_"]
        self.assertEqual(final.count("\r\n"), crlf.count("\r\n"))
        self.assertNotIn("\n", final.replace("\r\n", ""))
        changed = [(o, n) for o, n in zip(crlf.split("\r\n"), final.split("\r\n")) if o != n]
        self.assertEqual(sorted(changed), sorted([(GLASSY_HOOK_OLD, GLASSY_HOOK_NEW),
                                                  (GLASSY_REPLAY_OLD, GLASSY_REPLAY_NEW)]))
        self.assertEqual(backups["_retail_"], crlf)
        self.assertIn("Applied the scoped Glassy retail anchor-replay guard (_retail_)", log_text)
        again, finals2, backups2, log2 = self.run_block({"_retail_": final})
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(finals2["_retail_"], final)
        self.assertIsNone(backups2["_retail_"])
        self.assertEqual(log2, "")

    def test_ambiguous_duplicate_and_mixed_guards_are_untouched(self):
        candidates = [
            ORIGINAL_CHATDOCK_LUA + GLASSY_HOOK_OLD + "\n",
            ORIGINAL_CHATDOCK_LUA + GLASSY_REPLAY_NEW + "\n",
            wrap_chatdock_fixture("-- " + GLASSY_HOOK_OLD, GLASSY_REPLAY_OLD),
            wrap_chatdock_fixture(GLASSY_HOOK_NEW, GLASSY_REPLAY_OLD),
        ]
        for original in candidates:
            with self.subTest(original=original):
                result, finals, backups, log_text = self.run_block({"_retail_": original})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(finals["_retail_"], original)
                self.assertIsNone(backups["_retail_"])
                self.assertIn("Skipped unrecognized Glassy anchor guards", log_text)

    def test_similar_non_target_line_is_not_changed_by_sed(self):
        decoy = '  if not self:IsHooked(selfXscrollFrame, "SetPoint") then\n'
        original = ORIGINAL_CHATDOCK_LUA + decoy
        result, finals, _, _ = self.run_block({"_retail_": original})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(finals["_retail_"].endswith(decoy))

    def test_missing_glassy_is_skipped_as_optional(self):
        result, finals, backups, log_text = self.run_block({"_retail_": None})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(finals["_retail_"])
        self.assertIsNone(backups["_retail_"])
        self.assertEqual(log_text, "")


class ExtractionShapeTests(unittest.TestCase):
    """Keep extraction separate from unrelated launcher behavior."""

    def test_block_targets_the_verified_nested_path_and_selected_install(self):
        self.assertTrue(BLOCK.startswith(_START))
        self.assertTrue(BLOCK.rstrip().endswith("\nfi"))
        self.assertNotIn('Interface/AddOns/Offhand', BLOCK)
        self.assertIn('$ROOT/$DIR/Interface/AddOns/Glassy/Glassy/Components/ChatDock.lua', BLOCK)
        self.assertIn(GLASSY_HOOK_OLD, BLOCK)
        self.assertIn(GLASSY_REPLAY_OLD, BLOCK)
        self.assertIn('Constants.ENV ~= "retail"', BLOCK)
        self.assertIn('Glassy-ChatDock-$DIR.lua', BLOCK)


LUA_HARNESS_PRELUDE = """
function new_owner()
  local owner = { hooks = {} }
  function owner:IsHooked(object, method)
    return self.hooks[object] ~= nil and self.hooks[object][method] ~= nil
  end
  function owner:RawHook(object, method, handler)
    self.hooks[object] = self.hooks[object] or {}
    self.hooks[object][method] = object[method]
    object[method] = handler
  end
  function owner:SecureHook(object, method, handler)
    -- Mirrors WoW's real hooksecurefunc semantics: the protected method itself is never
    -- replaced -- the original always runs first, then every registered callback runs after,
    -- with the same arguments. Does NOT auto-populate owner.hooks: Utils.hookPresentation must
    -- do that itself, which is exactly what the real function (and hookPresentation below) does.
    self.hooks[object] = self.hooks[object] or {}
    local original = object[method]
    object[method] = function(...)
      original(...)
      handler(...)
    end
  end
  return owner
end

-- Originally-written reproduction of the verified branch contract of Glassy's own
-- Utils.hookPresentation (utils.lua, MIT license, (c) Mitchel Cabuloy): non-retail RawHooks;
-- retail SecureHooks and manually stashes the pre-hook original. Signature matches the real
-- function's four parameters. This is NOT a copy of Glassy's file -- see the module docstring.
function hookPresentation(owner, object, method, handler)
  if Constants.ENV ~= "retail" then
    owner:RawHook(object, method, handler)
    return
  end
  local original = object[method]
  local updating = false
  owner:SecureHook(object, method, function(...)
    if updating then return end
    updating = true
    local ok, err = pcall(handler, ...)
    updating = false
    if not ok then error(err, 0) end
  end)
  owner.hooks[object][method] = original
end
"""


@unittest.skipUnless(lupa, "lupa is required for Lua-level guard semantics tests")
class LuaAnchorReplaySemanticsTests(unittest.TestCase):
    """Runs the REAL extracted guard lines (GLASSY_HOOK_OLD/NEW, GLASSY_REPLAY_OLD/NEW) inside
    the REAL ChatDock-shaped fixture (wrap_chatdock_fixture) through an actual Lua interpreter
    (lupa), against the harness above. Proves: retail's native SetPoint is invoked once and
    unmodified with no hook ever installed; classic gets the unchanged once-with-+5 behavior;
    and both the initial replay AND a later, independent SetPoint call are covered identically.
    This is a call-count/call-identity proof, not a reproduction of the live secure-frame
    anchor-cycle bug itself.
    """

    def _setup(self, env, hook_guard, replay_guard):
        rt = lupa.LuaRuntime(unpack_returned_tuples=True)
        rt.execute(LUA_HARNESS_PRELUDE + wrap_chatdock_fixture(hook_guard, replay_guard) + """
calls = {}
function real_set_point(frame, point, relativeTo, relativePoint, xOffset, yOffset)
  calls[#calls + 1] = { point = point, xOffset = xOffset, yOffset = yOffset }
end
Constants = { ENV = "%s" }
self = new_owner()
self.scrollFrame = {}
self.scrollFrame.SetPoint = real_set_point
""" % env)
        g = rt.globals()
        g.RefreshDock(g.self, "BOTTOMRIGHT", None, "BOTTOMRIGHT", -3, 3)
        return g

    def test_retail_new_guard_never_hooks_and_native_call_stays_unmodified(self):
        g = self._setup("retail", GLASSY_HOOK_NEW, GLASSY_REPLAY_NEW)
        self.assertFalse(g.self.IsHooked(g.self, g.self.scrollFrame, "SetPoint"))
        self.assertEqual(len(g.calls), 0)  # no initial replay at all
        # A later, independent SetPoint call (e.g. Blizzard resizing the dock) is untouched too.
        g.self.scrollFrame.SetPoint(g.self.scrollFrame, "BOTTOMRIGHT", None, "BOTTOMRIGHT", -3, 3)
        self.assertEqual(len(g.calls), 1)
        self.assertEqual(g.calls[1]["xOffset"], -3)
        self.assertEqual(g.calls[1]["yOffset"], 3)  # native value; +5 never applied

    def test_retail_old_guard_hooks_and_replays_once_after_the_native_call(self):
        # Sanity check on the PRE-patch text: proves the bug the patch removes actually existed.
        g = self._setup("retail", GLASSY_HOOK_OLD, GLASSY_REPLAY_OLD)
        self.assertTrue(g.self.IsHooked(g.self, g.self.scrollFrame, "SetPoint"))
        self.assertEqual(len(g.calls), 2)  # initial replay: native call, then Glassy's +5 replay
        self.assertEqual(g.calls[1]["yOffset"], 3)      # native, unmodified, fires first
        self.assertEqual(g.calls[2]["yOffset"], 8)      # 3 + 5, Glassy's replay AFTER it

    def test_classic_keeps_the_unchanged_once_with_5_behavior_for_both_guard_texts(self):
        # Classic must be unaffected by the patch: same hook, same +5, same call count, whether
        # the OLD or the NEW guard text is in the file (Constants.ENV ~= "retail" is true either
        # way for classic, so the extra clause never changes classic's behavior).
        for guards in [(GLASSY_HOOK_OLD, GLASSY_REPLAY_OLD), (GLASSY_HOOK_NEW, GLASSY_REPLAY_NEW)]:
            with self.subTest(guards=guards):
                g = self._setup("classic", *guards)
                self.assertTrue(g.self.IsHooked(g.self, g.self.scrollFrame, "SetPoint"))
                self.assertEqual(len(g.calls), 1)  # RawHook replaces the method outright
                self.assertEqual(g.calls[1]["xOffset"], -3)
                self.assertEqual(g.calls[1]["yOffset"], 8)  # 3 + 5, initial replay
                # A later, independent SetPoint call sees the identical +5 behavior.
                g.self.scrollFrame.SetPoint(g.self.scrollFrame, "BOTTOMRIGHT", None, "BOTTOMRIGHT", -3, 3)
                self.assertEqual(len(g.calls), 2)
                self.assertEqual(g.calls[2]["xOffset"], -3)
                self.assertEqual(g.calls[2]["yOffset"], 8)


if __name__ == "__main__":
    unittest.main()
