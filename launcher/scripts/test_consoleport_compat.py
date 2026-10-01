"""Regression tests for the two beta-only ConsolePort compatibility patches in wowgo.sh:
the HousingFramesUtil availability guard (ConsolePort_Menu/Model/Buttons.lua) and the
LibActionButton-1.0 flyout numSlots type guard (embedded in ConsolePort).

The shell block under test is extracted out of the
real wowgo.sh by anchor text (not hand-retyped), and the OLD/NEW literals are parsed straight
out of wowgo.sh's own HOUSING_OLD=/HOUSING_NEW=/FLYOUT_OLD=/FLYOUT_NEW= assignments, so this
file breaks loudly if wowgo.sh's patch text ever drifts instead of silently testing stale text.

Lua-side semantics (does the guard actually stop the crash, does it leave good data alone) are
exercised through `lupa` against small harnesses built around those same real extracted
literals -- not hand-written stand-ins with a guessed WoW API tuple shape. GetFlyoutInfo's real
signature is (name, description, numSlots, isKnown); pcall prepends its own success boolean, so
`local success, _, _, numSlots, isKnown = pcall(GetFlyoutInfo, id)` destructures
(success, name, description, numSlots, isKnown) -- numSlots is pcall-return #4, i.e.
GetFlyoutInfo's 3rd real return, not its 4th.

No addon source is stored here: only the one-line guard expressions wowgo.sh itself carries,
wrapped in minimal, originally-written control-flow harnesses just large enough to prove the
guard changes crash/no-crash and preserve/discard-correctly behavior.
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

_START = 'if [ "$FLAVOR" = beta ]; then'
_END = "\nfor D in _retail_ _classic_ _classic_beta_; do"
BLOCK = SOURCE[SOURCE.index(_START):]
BLOCK = BLOCK[: BLOCK.index(_END)]


def _literal(varname):
    """Pulls VARNAME='...' verbatim out of wowgo.sh. All four assignments below are single
    line, single-quoted, and contain no apostrophes, so a plain regex capture is exact."""
    match = re.search(r"^\s*" + varname + r"='(.*)'\s*$", SOURCE, re.MULTILINE)
    assert match, f"{varname}=... not found in wowgo.sh -- extraction is stale"
    return match.group(1)


HOUSING_OLD = _literal("HOUSING_OLD")
HOUSING_NEW = _literal("HOUSING_NEW")
FLYOUT_OLD = _literal("FLYOUT_OLD")
FLYOUT_NEW = _literal("FLYOUT_NEW")


def wrap_buttons_fixture(guard_line):
    """A small Buttons.lua-shaped fixture carrying the real guard line verbatim, plus the
    sibling Scenarios housing-editor entry the real file already guards correctly, so a
    byte-diff between before/after only ever shows the one line the patch is meant to change."""
    return (
        "local nop = function() end\n"
        "local result = nil\n"
        "local function _(t) result = t end\n"
        "--[[ Housing Dashboard ]] " + guard_line + "\n"
        "\ttext  = BINDING_NAME_TOGGLEHOUSINGDASHBOARD;\n"
        "\tatlas = 'housing-dashboard-homestone-icon';\n"
        "\tclick = HousingFramesUtil.ToggleHousingDashboard;\n"
        "} end;\n"
        "--[[ Scenarios ]] do _{\n"
        "\tstates = {\n"
        "\t\t{ command = HousingFramesUtil and HousingFramesUtil.ToggleHouseEditor or nop; };\n"
        "\t};\n"
        "} end;\n"
    )


def wrap_flyout_fixture(gate_line):
    """Reproduces both real call sites' control flow (Discover + Update): each pairs the gate
    line with the `for slotID = 1, numSlots do` loop it guards. Not the full copyrighted
    function bodies -- just the shape that decides whether that loop ever runs with a nil bound.
    """
    template = (
        "function {fn}(GetFlyoutInfo)\n"
        "  local calls = {{}}\n"
        "  for flyoutID = 1, 3 do\n"
        "    local success, _, _, numSlots, isKnown = pcall(GetFlyoutInfo, flyoutID)\n"
        "    {gate}\n"
        "      for slotID = 1, numSlots do\n"
        "        calls[#calls + 1] = {{ flyoutID, slotID }}\n"
        "      end\n"
        "    end\n"
        "  end\n"
        "  return calls\n"
        "end\n"
    )
    return (
        template.format(fn="DiscoverFlyoutSpells", gate=gate_line)
        + template.format(fn="UpdateFlyoutSpells", gate=gate_line)
    )


ORIGINAL_BUTTONS_LUA = wrap_buttons_fixture(HOUSING_OLD)
ORIGINAL_FLYOUT_LUA = wrap_flyout_fixture(FLYOUT_OLD)


class _ShellHarnessMixin:
    """Runs the real extracted `if $FLAVOR = beta ... fi` block against a throwaway ROOT/BASE,
    with mocked fail()/log(). Subclasses set addon_rel_path (tuple of
    path parts under Interface/AddOns) and backup_name."""

    addon_rel_path = None
    backup_name = None

    def run_block(self, flavor, dir_name, content=None, pre_backup=None):
        directory = tempfile.mkdtemp(prefix="wow-consoleport-compat-")
        try:
            root = pathlib.Path(directory) / "root"
            base = pathlib.Path(directory) / "base"
            target = root.joinpath(dir_name, "Interface", "AddOns", *self.addon_rel_path)
            target.parent.mkdir(parents=True)
            base.mkdir(parents=True)
            if content is not None:
                target.write_bytes(content.encode("utf-8"))
            if pre_backup is not None:
                backup_dir = base / "backups" / "compat"
                backup_dir.mkdir(parents=True)
                (backup_dir / self.backup_name).write_bytes(pre_backup.encode("utf-8"))
            logfile = pathlib.Path(directory) / "log.txt"
            script = "\n".join([
                "set -u", "umask 077",
                "FLAVOR=$1; ROOT=$2; DIR=$3; BASE=$4; LOGFILE=$5",
                "fail() { printf 'FAIL:%s\\n' \"$1\" >&2; exit 9; }",
                "log() { printf 'LOG:%s\\n' \"$*\" >> \"$LOGFILE\"; }",
                BLOCK,
            ])
            result = subprocess.run(
                [BASH, "-c", script, "--", flavor, root.as_posix(), dir_name, base.as_posix(), logfile.as_posix()],
                capture_output=True, text=True, timeout=10,
            )
            final = target.read_bytes().decode("utf-8") if target.exists() else None
            backup_path = base / "backups" / "compat" / self.backup_name
            backup = backup_path.read_bytes().decode("utf-8") if backup_path.exists() else None
            log_text = logfile.read_bytes().decode("utf-8") if logfile.exists() else ""
            return result, final, backup, log_text
        finally:
            shutil.rmtree(directory, ignore_errors=True)


@unittest.skipUnless(BASH, "bash is required to test the production shell block")
class HousingButtonBetaCompatTests(_ShellHarnessMixin, unittest.TestCase):
    addon_rel_path = ("ConsolePort_Menu", "Model", "Buttons.lua")
    backup_name = "ConsolePort_Menu-Buttons.lua"

    def test_beta_patches_matching_guard(self):
        result, final, backup, log_text = self.run_block("beta", "_classic_beta_", ORIGINAL_BUTTONS_LUA)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(HOUSING_NEW, final)
        self.assertNotIn(HOUSING_OLD, final)
        self.assertEqual(backup, ORIGINAL_BUTTONS_LUA)
        self.assertIn("LOG:Applied the scoped Forever housing-button availability guard", log_text)

    def test_retail_and_classic_are_never_touched(self):
        for flavor, dir_name in [("retail", "_retail_"), ("classic", "_classic_")]:
            with self.subTest(flavor=flavor):
                result, final, backup, log_text = self.run_block(flavor, dir_name, ORIGINAL_BUTTONS_LUA)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(final, ORIGINAL_BUTTONS_LUA)
                self.assertIsNone(backup)
                self.assertEqual(log_text, "")

    def test_already_patched_is_idempotent(self):
        first, patched, _b, _l = self.run_block("beta", "_classic_beta_", ORIGINAL_BUTTONS_LUA)
        self.assertEqual(first.returncode, 0, first.stderr)
        second, still, backup_after_second, log_text = self.run_block("beta", "_classic_beta_", patched)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(still, patched)
        self.assertIsNone(backup_after_second)
        self.assertEqual(log_text, "")

    def test_existing_backup_is_preserved(self):
        sentinel = "-- pristine copy captured on an earlier install\n" + ORIGINAL_BUTTONS_LUA
        result, final, backup, _log = self.run_block("beta", "_classic_beta_", ORIGINAL_BUTTONS_LUA, pre_backup=sentinel)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(HOUSING_NEW, final)
        self.assertEqual(backup, sentinel)

    def test_unrecognized_upstream_code_is_left_unchanged(self):
        reworded = wrap_buttons_fixture('if HousingMicroButton and CPAPI.IsHousingSupported() then _{')
        result, final, backup, log_text = self.run_block("beta", "_classic_beta_", reworded)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(final, reworded)
        self.assertIsNone(backup)
        self.assertEqual(log_text, "")

    def test_missing_file_is_safe(self):
        result, final, backup, log_text = self.run_block("beta", "_classic_beta_", content=None)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(final)
        self.assertIsNone(backup)
        self.assertEqual(log_text, "")


@unittest.skipUnless(BASH, "bash is required to test the production shell block")
class FlyoutGuardBetaCompatTests(_ShellHarnessMixin, unittest.TestCase):
    addon_rel_path = ("ConsolePort", "Libs", "External", "LibActionButton-1.0", "LibActionButton-1.0.lua")
    backup_name = "ConsolePort-LibActionButton-1.0.lua"

    def test_beta_patches_both_matching_gates(self):
        result, final, backup, log_text = self.run_block("beta", "_classic_beta_", ORIGINAL_FLYOUT_LUA)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(final.count(FLYOUT_NEW), 2)
        self.assertEqual(final.count(FLYOUT_OLD), 0)
        self.assertEqual(backup, ORIGINAL_FLYOUT_LUA)
        self.assertIn("LOG:Applied the scoped Forever flyout numSlots-type guard", log_text)

    def test_retail_and_classic_are_never_touched(self):
        for flavor, dir_name in [("retail", "_retail_"), ("classic", "_classic_")]:
            with self.subTest(flavor=flavor):
                result, final, backup, log_text = self.run_block(flavor, dir_name, ORIGINAL_FLYOUT_LUA)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(final, ORIGINAL_FLYOUT_LUA)
                self.assertIsNone(backup)
                self.assertEqual(log_text, "")

    def test_already_patched_is_idempotent(self):
        first, patched, _b, _l = self.run_block("beta", "_classic_beta_", ORIGINAL_FLYOUT_LUA)
        self.assertEqual(first.returncode, 0, first.stderr)
        second, still, backup_after_second, log_text = self.run_block("beta", "_classic_beta_", patched)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(still, patched)
        self.assertIsNone(backup_after_second)
        self.assertEqual(log_text, "")

    def test_existing_backup_is_preserved(self):
        sentinel = "-- pristine copy captured on an earlier install\n" + ORIGINAL_FLYOUT_LUA
        result, final, backup, _log = self.run_block("beta", "_classic_beta_", ORIGINAL_FLYOUT_LUA, pre_backup=sentinel)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(final.count(FLYOUT_NEW), 2)
        self.assertEqual(backup, sentinel)

    def test_only_one_matching_gate_is_left_unchanged(self):
        # Upstream reshaped one of the two call sites -- count is 1, not 2. Narrow match must
        # skip rather than patch just one and leave the guard inconsistent between the two.
        content = (
            "function DiscoverFlyoutSpells(GetFlyoutInfo)\n"
            "  local success, _, _, numSlots = pcall(GetFlyoutInfo, 1)\n"
            "  " + FLYOUT_OLD + "\n"
            "    for slotID = 1, numSlots do end\n"
            "  end\n"
            "end\n"
            "function UpdateFlyoutSpells(GetFlyoutInfo)\n"
            "  local success, _, _, numSlots = pcall(GetFlyoutInfo, 1)\n"
            "  if success and isKnown ~= nil then\n"
            "    for slotID = 1, numSlots do end\n"
            "  end\n"
            "end\n"
        )
        result, final, backup, log_text = self.run_block("beta", "_classic_beta_", content)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(final, content)
        self.assertIsNone(backup)
        self.assertEqual(log_text, "")

    def test_missing_file_is_safe(self):
        result, final, backup, log_text = self.run_block("beta", "_classic_beta_", content=None)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(final)
        self.assertIsNone(backup)
        self.assertEqual(log_text, "")


class ExtractionShapeTests(unittest.TestCase):
    """Guards the extraction itself: fails
    loudly if wowgo.sh's beta block ever changes shape instead of silently going stale."""

    def test_block_still_contains_both_new_patches(self):
        self.assertTrue(BLOCK.startswith(_START))
        self.assertTrue(BLOCK.rstrip().endswith("\nfi"))
        self.assertIn("ConsolePort_Menu/Model/Buttons.lua", BLOCK)
        self.assertIn("ConsolePort/Libs/External/LibActionButton-1.0/LibActionButton-1.0.lua", BLOCK)
        self.assertIn(HOUSING_OLD, BLOCK)
        self.assertIn(HOUSING_NEW, BLOCK)
        self.assertIn(FLYOUT_OLD, BLOCK)
        self.assertIn(FLYOUT_NEW, BLOCK)


HOUSING_LUA_TEMPLATE = (
    "local result = nil\n"
    "local function _(t) result = t end\n"
    "__GATE__\n"
    "  text  = \"Housing Dashboard\";\n"
    "  click = HousingFramesUtil.ToggleHousingDashboard;\n"
    "} end\n"
    "return result\n"
)


@unittest.skipUnless(lupa, "lupa is required for Lua-level guard semantics tests")
class LuaFlyoutGuardSemanticsTests(unittest.TestCase):
    """Executes the REAL extracted gate line (FLYOUT_OLD/FLYOUT_NEW) plus the real loop shape
    it guards through an actual Lua interpreter (lupa), driven by stubs matching GetFlyoutInfo's
    real signature: (name, description, numSlots, isKnown)."""

    @staticmethod
    def forever_stub(flyout_id):
        return "Flyout%d" % flyout_id, "desc", None, False

    @staticmethod
    def retail_stub(flyout_id):
        return "Flyout%d" % flyout_id, "desc", 2, True

    def _discover(self, gate_line):
        rt = lupa.LuaRuntime(unpack_returned_tuples=True)
        rt.execute(wrap_flyout_fixture(gate_line))
        return rt.globals().DiscoverFlyoutSpells

    def test_old_gate_throws_on_forever_shaped_data(self):
        discover = self._discover(FLYOUT_OLD)
        with self.assertRaises(lupa.LuaError):
            discover(self.forever_stub)

    def test_new_gate_does_not_throw_and_records_nothing(self):
        discover = self._discover(FLYOUT_NEW)
        calls = discover(self.forever_stub)
        self.assertEqual(len(calls), 0)

    def test_new_gate_preserves_real_slots_identically_to_old(self):
        old_calls = self._discover(FLYOUT_OLD)(self.retail_stub)
        new_calls = self._discover(FLYOUT_NEW)(self.retail_stub)
        self.assertEqual(len(old_calls), 6)  # 3 flyouts * 2 slots
        self.assertEqual(len(new_calls), 6)


@unittest.skipUnless(lupa, "lupa is required for Lua-level guard semantics tests")
class LuaHousingGuardSemanticsTests(unittest.TestCase):
    """Executes the REAL extracted gate line (HOUSING_OLD/HOUSING_NEW) through lupa, with
    HousingMicroButton/HousingFramesUtil as real Lua globals -- not renamed stand-ins."""

    def _run(self, gate_line, housing_micro_button, housing_frames_util):
        rt = lupa.LuaRuntime(unpack_returned_tuples=True)
        g = rt.globals()
        g.HousingMicroButton = housing_micro_button
        g.HousingFramesUtil = housing_frames_util
        return rt.execute(HOUSING_LUA_TEMPLATE.replace("__GATE__", gate_line))

    def test_old_gate_throws_when_backend_module_is_nil(self):
        with self.assertRaises(lupa.LuaError):
            self._run(HOUSING_OLD, True, None)

    def test_new_gate_does_not_throw_and_omits_the_button(self):
        result = self._run(HOUSING_NEW, True, None)
        self.assertIsNone(result)

    def test_new_gate_preserves_the_real_toggle_function_untouched(self):
        # The guard checks Lua's own type(...) == "function". A Python callable crossing into
        # Lua through lupa is exposed as callable userdata, not Lua's "function" type, so it
        # would wrongly fail that check regardless of the patch. Build the stand-in toggle as
        # an actual Lua closure (rt.eval) so this exercises the same type() Lua sees for a real
        # in-addon Lua function, and confirm the guard neither replaces nor double-wraps it.
        rt = lupa.LuaRuntime(unpack_returned_tuples=True)
        rt.execute("_calls = {}")
        real_toggle = rt.eval("function() _calls[#_calls + 1] = true end")
        g = rt.globals()
        g.HousingMicroButton = True
        g.HousingFramesUtil = rt.table(ToggleHousingDashboard=real_toggle)
        result = rt.execute(HOUSING_LUA_TEMPLATE.replace("__GATE__", HOUSING_NEW))
        self.assertIsNotNone(result)
        # lupa wraps each access to a Lua value in a fresh Python proxy, so proxy `==` is not
        # Lua identity (both sides here print the same underlying address but compare unequal
        # in Python) -- calling it and observing the real closure's side effect is the actual
        # property that matters: the guard preserved the real function rather than replacing it.
        result["click"]()
        self.assertEqual(len(rt.globals()._calls), 1)

    def test_old_gate_is_also_fine_when_backend_is_present(self):
        # Sanity check: the OLD line only ever crashed because of Forever's nil
        # HousingFramesUtil, not because the gate itself was wrong on well-formed data.
        rt = lupa.LuaRuntime(unpack_returned_tuples=True)
        g = rt.globals()
        g.HousingMicroButton = True
        g.HousingFramesUtil = rt.table(ToggleHousingDashboard=(lambda: None))
        result = rt.execute(HOUSING_LUA_TEMPLATE.replace("__GATE__", HOUSING_OLD))
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
