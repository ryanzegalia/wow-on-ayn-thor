"""Exercise the real Direct config construction without connecting to a device."""
import ast
import copy
import pathlib
import shutil
import subprocess
import textwrap
import unittest

import provision_direct

SOURCE = pathlib.Path(provision_direct.__file__).read_text(encoding="utf-8")
CONFIG = textwrap.dedent(SOURCE.split("    # Preserve the entire", 1)[1].split("    payload =", 1)[0].split("\n", 1)[1])
GUARD = next(node.value.value for node in ast.walk(ast.parse(SOURCE))
             if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "guard" for t in node.targets))


class DirectProvisionTests(unittest.TestCase):
    def config(self, extra=None):
        source = {"id": "CUSTOM_GAME_1285328983", "name": "original", "executablePath": "_retail_/Wow-ARM64.exe",
                  "execArgs": "legacy", "extraData": {"spanDisplay": "true", "spanBottom": "left"},
                  "screenSize": "4400x1080", "wineVersion": "proton-10.0-arm64ec-2",
                  "dxwrapper": "wined3d", "dxwrapperConfig": "version=old,fps=60,async=0"}
        if extra:
            source["extraData"].update(extra)
        result = copy.deepcopy(source)
        exec(CONFIG, {"config": result, "FOLDER": provision_direct.FOLDER, "PACKAGE": provision_direct.PACKAGE})
        return source, result

    def test_executable_is_at_the_real_top_level(self):
        source, result = self.config({"executablePath": "bad-nested-value"})
        self.assertEqual(result["executablePath"], "launch.bat")
        self.assertEqual(result["execArgs"], "")
        self.assertNotIn("executablePath", result["extraData"])
        self.assertEqual(source["executablePath"], "_retail_/Wow-ARM64.exe")

    def test_persistent_graphics_selects_pure_arm64_not_arm64ec(self):
        _, result = self.config()
        self.assertEqual(result["dxwrapper"], "dxvk")
        self.assertEqual(result["dxwrapperConfig"], "version=3.1.1-40e0164-arm64-0,fps=60,async=0")

    def test_wrapper_preserves_driver_and_display_settings(self):
        source, result = self.config()
        self.assertEqual(result["id"], "CUSTOM_GAME_1835007375")
        for key in ("screenSize", "wineVersion"):
            self.assertEqual(result[key], source[key])
        for key in ("spanDisplay", "spanBottom"):
            self.assertEqual(result["extraData"][key], source["extraData"][key])
        self.assertIn("A:" + provision_direct.FOLDER + "B:" + "/storage/emulated/0/Games/WoW", result["drives"])

    @unittest.skipUnless(shutil.which("bash"), "bash required")
    def test_real_guard_refuses_native_and_x64_clients_but_not_helpers(self):
        for name, refused in [(r"B:\_classic_beta_\WowB-ARM64.exe", True), ("Wow-64.exe", True),
                              ("WowClassic.exe", True), ("WowVoiceProxy.exe", False), ("NotWow.exe", False)]:
            with self.subTest(name=name):
                # Preserve the actual guard but replace ps with one fixture executable name.
                script = "ps() { printf '%s\\n' " + "'" + name + "'" + "; }\n" + GUARD
                result = subprocess.run([shutil.which("bash"), "-c", script], capture_output=True, text=True)
                self.assertEqual(result.returncode, 2 if refused else 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
