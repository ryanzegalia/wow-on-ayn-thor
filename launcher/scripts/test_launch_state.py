"""Regression tests for the exact shell predicates used by wowgo.sh (requires bash)."""
import pathlib
import shutil
import subprocess
import tempfile
import unittest

SOURCE = pathlib.Path(__file__).with_name("wowgo.sh").read_text(encoding="utf-8")
AUTH = SOURCE[SOURCE.index("      AUTH=$("):].split("\n", 1)[0].strip()
PLAYABLE = SOURCE[SOURCE.index("        PLAYABLE=$("):].split("\n        if ", 1)[0].strip()
BASH = shutil.which("bash")
# Battle.net as Android's ps shows it: a Windows path inside the Wine prefix.
BNET_EXE = "C:" + r"\Battle.net.exe"


def login(message):
    return "I 2026-09-24 23:00:00 [BNLogin] {Main} " + message + "\n"


def product(fields, uid="wow_classic"):
    return "D 2026-09-24 23:00:00 [ProductState] {Main} InstallState (" + uid + "): " + fields + "\n"


@unittest.skipUnless(BASH, "bash is required to test the production shell predicates")
class LaunchStateTests(unittest.TestCase):
    def state(self, text, uid="wow_classic"):
        with tempfile.TemporaryDirectory(prefix="wow-launch-state-") as directory:
            log = pathlib.Path(directory) / "battle.net.log"
            log.write_bytes(text.encode("utf-8"))
            script = "\n".join([
                'CURRENT_LOG=$1; PRODUCT=$2', AUTH, PLAYABLE,
                "if printf '%s\\n' \"$AUTH\" | grep -q 'Logged into Battle.net successfully'; then printf 'signed-in\\n'; else printf 'signed-out\\n'; fi",
                "if printf '%s\\n' \"$PLAYABLE\" | grep -qE '(^| )playable=1( |$)'; then printf 'playable\\n'; else printf 'not-playable\\n'; fi",
            ])
            result = subprocess.run([BASH, "-c", script, "--", log.as_posix(), uid],
                                    capture_output=True, text=True, check=True, timeout=10)
            return tuple(result.stdout.splitlines())

    def test_empty_log_is_not_ready(self):
        self.assertEqual(self.state(""), ("signed-out", "not-playable"))

    def test_signed_in_and_playable(self):
        self.assertEqual(self.state(login("Logged into Battle.net successfully.") + product("playable=1")),
                         ("signed-in", "playable"))

    def test_disconnect_revokes_old_login(self):
        text = login("Logged into Battle.net successfully.") + login("Disconnected from Battle.net: err=ERROR_NETWORK_MODULE_SOCKET_CLOSED (1016)")
        self.assertEqual(self.state(text)[0], "signed-out")

    def test_reconnect_restores_login(self):
        text = login("Disconnected from Battle.net: err=1016") + login("Logged into Battle.net successfully.")
        self.assertEqual(self.state(text)[0], "signed-in")

    def test_permission_check_revokes_completed_update(self):
        text = product("playable=1") + "[InstallManager] Update completed: wow_classic\n" + product("currentOperation=Update playable=0 currentStage=Setup")
        self.assertEqual(self.state(text)[1], "not-playable")

    def test_partial_state_delta_retains_playable(self):
        text = product("playable=1") + product("progress=1 currentStage=Complete")
        self.assertEqual(self.state(text)[1], "playable")

    def test_regional_versions_are_not_top_level_playability(self):
        self.assertEqual(self.state(product("regionalVersions=(us: {playable:true})"))[1], "not-playable")

    def test_other_products_do_not_override_selected_product(self):
        text = product("playable=0") + product("playable=1", "wow") + product("playable=1", "wow_classic_beta")
        self.assertEqual(self.state(text)[1], "not-playable")
        self.assertEqual(self.state(text, "wow_classic_beta")[1], "playable")

    def test_crlf_and_doubled_carriage_return(self):
        text = (login("Logged into Battle.net successfully.") + product("playable=1")).replace("\n", "\r\r\n")
        self.assertEqual(self.state(text), ("signed-in", "playable"))

    def test_login_is_not_lost_after_many_unrelated_events(self):
        text = login("Logged into Battle.net successfully.") + "[Render process] ready\n" * 200 + product("playable=1")
        self.assertEqual(self.state(text), ("signed-in", "playable"))

    def live_log(self, processes, open_files, auth_ids, auth_text=None):
        function = SOURCE.split("bnet_log() {", 1)[1].split("\n}", 1)[0]
        with tempfile.TemporaryDirectory(prefix="wow-live-log-") as directory:
            root = pathlib.Path(directory)
            for pid in open_files:
                text = (auth_text if auth_text is not None else login("Logged into Battle.net successfully.")) if pid in auth_ids else "second-instance command\n"
                (root / f"battle.net-{pid}.log").write_text(text, encoding="utf-8")
            ps_lines = "\\n".join(processes)
            routes = []
            for pid in open_files:
                path = (root / f"battle.net-{pid}.log").as_posix()
                routes.append(f'/proc/{pid}/fd/*) printf \'%s\\n\' \'{path}\' ;;')
            script = "\n".join([
                'SPAN_UID=10187; LOGDIR=$1',
                "ps() { printf '%b\\n' '" + ps_lines + "'; }",
                'readlink() { case "$1" in ' + " ".join(routes) + ' esac; }',
                "bnet_log() {" + function + "\n}",
                'bnet_log || true',
            ])
            result = subprocess.run([BASH, "-c", script, "--", root.as_posix()],
                                    capture_output=True, text=True, check=True, timeout=10)
            return pathlib.PurePosixPath(result.stdout.strip()).name if result.stdout.strip() else ""

    def test_live_log_ignores_second_instance_and_foreign_owner(self):
        processes = ["200 10000 " + BNET_EXE, "201 10187 " + BNET_EXE, "202 10187 " + BNET_EXE]
        self.assertEqual(self.live_log(processes, [200, 201, 202], [200, 202]), "battle.net-202.log")

    def test_live_challenge_log_is_visible_but_not_authenticated(self):
        text = '[UnifiedAuth] UAuth: browser state changed: Challenge\n'
        processes = ["201 10187 " + BNET_EXE]
        self.assertEqual(self.live_log(processes, [201], [201], text), "battle.net-201.log")
        self.assertEqual(self.state(text)[0], "signed-out")

    def test_closed_old_log_cannot_authorize_new_session(self):
        processes = ["201 10187 " + BNET_EXE]
        self.assertEqual(self.live_log(processes, [200, 201], [200]), "")

    def test_absent_main_process_has_no_current_auth_log(self):
        self.assertEqual(self.live_log([], [200], [200]), "")

    def test_disconnect_rearms_beta_selection(self):
        branch = SOURCE.split("      if printf '%s\\n' \"$AUTH\"", 1)[1].split('\n      if [ "$LOGIN_AT"', 1)[0]
        script = 'AUTH="Disconnected from Battle.net"; LOGIN_AT=100; SELECTED=2; LAST_SELECT=110; NOW=120\n'
        script += "if printf '%s\\n' \"$AUTH\"" + branch
        script += '\nprintf "%s %s %s" "$LOGIN_AT" "$SELECTED" "$LAST_SELECT"'
        result = subprocess.run([BASH, "-c", script], capture_output=True, text=True, check=True, timeout=10)
        self.assertEqual(result.stdout, "0 0 0")

    def test_beta_selection_retry_is_bounded_and_delayed(self):
        gates = [line.strip() for line in SOURCE.splitlines() if 'if [ "$FLAVOR" = beta ] && [ "$SELECTED"' in line]
        self.assertEqual(len(gates), 1)
        gate = gates[0]
        for selected, last, now, expected in [(0, 0, 102, "wait"), (0, 0, 103, "send"),
                                               (1, 103, 127, "wait"), (1, 103, 128, "send"),
                                               (2, 128, 200, "wait")]:
            with self.subTest(selected=selected, last=last, now=now):
                script = f'FLAVOR=beta; LOGIN_AT=100; SELECTED={selected}; LAST_SELECT={last}; NOW={now}\n'
                script += gate + '\nprintf send\nelse\nprintf wait\nfi'
                result = subprocess.run([BASH, "-c", script], capture_output=True, text=True, check=True, timeout=10)
                self.assertEqual(result.stdout, expected)

    def test_client_guard_covers_architectures_but_not_voice_helper(self):
        pattern = SOURCE.split("CLIENT_PATTERN='", 1)[1].split("'", 1)[0]
        games = [r"20023 10187 B:\_classic_\WowClassic-arm64.exe", r"B:\_retail_\Wow.exe",
                 r"B:\_retail_\Wow-64.exe", r"B:\_classic_beta_\WowB-ARM64.exe",
                 "WowT.exe", "WowClassic.exe"]
        helpers = ["WowVoiceProxy.exe", "WowClassicCrashHandler.exe", "NotWow.exe", "winhandler.exe"]
        result = subprocess.run([BASH, "-c", 'grep -Ei "$1"', "--", pattern],
                                input="\n".join(games + helpers) + "\n", capture_output=True,
                                text=True, check=True, timeout=10)
        self.assertEqual(result.stdout.splitlines(), games)


if __name__ == "__main__":
    unittest.main()
