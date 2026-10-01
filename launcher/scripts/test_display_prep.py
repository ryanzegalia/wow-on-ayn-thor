"""Run the actual beta display-preparation shell against temporary shared WTF files."""
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

SOURCE = pathlib.Path(__file__).with_name("wowgo.sh").read_text(encoding="utf-8")
BLOCK = SOURCE.split("CONFIG=$ROOT/$DIR/WTF/Config.wtf", 1)[1].split('\nfor D in _retail_ _classic_ _classic_beta_; do', 1)[0]
BLOCK = "CONFIG=$ROOT/$DIR/WTF/Config.wtf" + BLOCK
BASH = shutil.which("bash")
OVERRIDES = b'SET gxWindow "1"\r\nSET gxMaximize "1"\r\nSET gxWindowedResolution "1920x1080"\r\nSET gxFullscreenResolution "1920x1058"\r\n'
KEEP = b'SET RenderScale "0.85"\r\nSET gxApi "D3D11"\r\nSET GamePadEnable "1"\r\n'


@unittest.skipUnless(BASH, "bash required")
class DisplayPrepTests(unittest.TestCase):
    def run_prep(self, directory, flavor="beta"):
        env = dict(os.environ, ROOT=directory.as_posix(), BASE=(directory / "root").as_posix(),
                   DIR="game", FLAVOR=flavor)
        script = 'set -u; umask 077\nfail() { printf "%s\\n" "$*" >&2; exit 1; }\nlog() { printf "%s\\n" "$*"; }\n'
        if os.name == "nt":
            # Git's Windows sed defaults to CRLF translation; Android sed uses binary I/O.
            script += 'sed() { command sed -b "$@"; }\n'
        script += BLOCK
        return subprocess.run([BASH, "-c", script], env=env, capture_output=True, text=True, check=True)

    def fixture(self, root, content):
        config = root / "game/WTF/Config.wtf"
        config.parent.mkdir(parents=True)
        config.write_bytes(content)
        return config, root / "root/backups/compat/beta-display.wtf"

    def test_only_four_display_overrides_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            config, backup = self.fixture(root, OVERRIDES + KEEP)
            self.run_prep(root)
            self.assertEqual(config.read_bytes(), KEEP)
            self.assertEqual(backup.read_bytes(), OVERRIDES + KEEP)
            self.assertNotIn(b"4400", config.read_bytes())

    def test_clean_defaults_are_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            config, backup = self.fixture(root, KEEP)
            self.assertEqual(self.run_prep(root).stdout, "")
            self.assertEqual(self.run_prep(root).stdout, "")
            self.assertEqual(config.read_bytes(), KEEP)
            self.assertFalse(backup.exists())

    def test_other_flavors_keep_their_settings(self):
        for flavor in ("retail", "classic"):
            with self.subTest(flavor=flavor), tempfile.TemporaryDirectory() as directory:
                root = pathlib.Path(directory)
                config, backup = self.fixture(root, OVERRIDES + KEEP)
                self.run_prep(root, flavor)
                self.assertEqual(config.read_bytes(), OVERRIDES + KEEP)
                self.assertFalse(backup.exists())

    def test_original_backup_survives_later_repairs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            config, backup = self.fixture(root, OVERRIDES + KEEP)
            self.run_prep(root)
            config.write_bytes(b'SET gxWindowedResolution "800x600"\n' + KEEP)
            self.run_prep(root)
            self.assertEqual(config.read_bytes(), KEEP)
            self.assertEqual(backup.read_bytes(), OVERRIDES + KEEP)


if __name__ == "__main__":
    unittest.main()
