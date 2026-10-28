import http.client
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from web.core import Core, DashboardError
from web.config import ConfigStore
from web.runtime import Controller
from web.server import DashboardServer, ServerConfig
from web.session import running_service_url

CONFIG = {
    "account": "example",
    "operator": "hsd",
    "portalUrl": "http://10.101.2.194:6060/portal.do?test=1",
    "password": "test-only-password",
    "autoStart": True,
}


def online():
    return {
        "state": "online",
        "online": True,
        "authenticated": False,
        "checkedAt": time.time(),
        "message": "网络在线。",
        "error": None,
        "failures": 0,
        "nextDelay": 10,
    }


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.store = ConfigStore(self.directory, Core())

    def tearDown(self):
        self.temp.cleanup()

    def test_real_native_validation_and_password_preservation(self):
        self.store.save(CONFIG)
        self.assertNotIn(CONFIG["password"], self.store.path.read_text())
        self.assertEqual(self.store.credentials()["password"], CONFIG["password"])
        encrypted = self.store.load()["password"]
        self.store.save({"password": "", "intervalSeconds": 30})
        self.assertEqual(self.store.load()["password"], encrypted)
        self.assertNotIn("password", self.store.summary())
        if os.name != "nt":
            self.assertEqual(self.store.key_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)

    def test_first_save_requires_password(self):
        with self.assertRaises(DashboardError):
            self.store.save({**CONFIG, "password": ""})
        self.assertFalse(self.store.path.exists())

    def test_native_rules_reject_invalid_types_and_removed_fields(self):
        for change in (
            {"intervalSeconds": True},
            {"autoStart": "yes"},
            {"restartCount": 3},
            {"account": "example@hsd"},
            {"operator": "other"},
            {"portalUrl": "http://8.8.8.8:6060/portal.do?q=1"},
            {"portalUrl": "http://10.101.2.194:6060/portal.do"},
            {"enabled": True},
        ):
            with self.subTest(change=change), self.assertRaises(DashboardError):
                self.store.save({**CONFIG, **change})

    def test_failed_atomic_save_retains_previous_value(self):
        self.store.save(CONFIG)
        before = self.store.path.read_bytes()
        with patch("web.config.os.replace", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                self.store.save({"password": "", "account": "changed"})
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(list(self.directory.glob(".htu-*")), [])

    def test_corrupt_credentials_fail_without_another_storage_path(self):
        self.store.save(CONFIG)
        data = self.store.load()
        data["password"] = "damaged"
        self.store.path.write_text(json.dumps(data))
        with self.assertRaises(DashboardError):
            self.store.credentials()

    def test_native_binding_owns_and_frees_each_result(self):
        for _ in range(200):
            self.assertEqual(
                self.store.core.call("validate", config=CONFIG)["operator"], "hsd"
            )
        with self.assertRaises(DashboardError) as error:
            self.store.core.call("unknown")
        self.assertEqual(error.exception.stage, "input")


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.controller = Controller(self.directory)
        self.server = DashboardServer(
            ServerConfig("127.0.0.1", 0), "test-token", self.controller
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.controller.close()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, method="GET", payload=None, headers=None):
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=5
        )
        try:
            body = json.dumps(payload) if payload is not None else None
            connection.request(
                method,
                path,
                body=body,
                headers={"X-HTU-Token": "test-token", **(headers or {})},
            )
            reply = connection.getresponse()
            return reply.status, reply.read()
        finally:
            connection.close()

    def cli(self, *args, input=None):
        binary = (
            Path(__file__).resolve().parents[1]
            / "native"
            / ("htu-toolbox-cli.exe" if os.name == "nt" else "htu-toolbox-cli")
        )
        return subprocess.run(
            [str(binary), "--runtime-dir", str(self.directory), "net", *args],
            input=input,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=8,
        )

    def test_status_reads_cached_result_without_network_or_logs(self):
        self.controller.store.save(CONFIG)
        self.controller.last_result = online()
        original = self.controller.core.call

        def call(op, **payload):
            if op != "validate":
                raise AssertionError("Status performed a network operation")
            return original(op, **payload)

        with patch.object(self.controller.core, "call", side_effect=call), patch(
            "web.server.read_log_tail", side_effect=AssertionError("Status read logs")
        ):
            status, body = self.request("/api/status")
        self.assertEqual(status, 200)
        data = json.loads(body)["data"]
        self.assertTrue(data["network"]["online"])
        self.assertNotIn("password", data["config"])
        self.assertEqual(
            data["network"]["checkedAt"], self.controller.last_result["checkedAt"]
        )

    def test_service_discovery_verifies_session_and_current_api(self):
        expected = f"http://127.0.0.1:{self.server.server_port}/"
        self.assertEqual(running_service_url(self.directory), expected)
        with patch.object(self.controller, "status", return_value={"task": {}, "config": {}, "network": {}}):
            self.assertIsNone(running_service_url(self.directory))
        session = self.directory / "session.json"
        for invalid in (
            b"not json",
            b"[]",
            json.dumps({"port": True, "token": "test-token"}).encode(),
            json.dumps({"port": "http://example.com", "token": "test-token"}).encode(),
            json.dumps({"port": self.server.server_port, "token": "bad\r\nheader"}).encode(),
            json.dumps({"port": self.server.server_port, "token": "stale-token"}).encode(),
            b" " * 4097,
        ):
            with self.subTest(session=invalid[:80]):
                session.write_bytes(invalid)
                self.assertIsNone(running_service_url(self.directory))
        session.unlink()
        self.assertIsNone(running_service_url(self.directory))

    def test_setup_reopens_live_service_without_install_or_second_process(self):
        from scripts import setup

        with patch("web.core.Core") as core, patch("web.session.webbrowser.open") as browser, patch(
            "scripts.setup.subprocess.run"
        ) as run, patch("sys.argv", ["setup.py", "--port", "8765"]), patch("builtins.print"):
            core.return_value.call.return_value = {"path": str(self.directory)}
            setup.main()
        browser.assert_called_once_with(f"http://127.0.0.1:{self.server.server_port}/")
        run.assert_not_called()

    def test_manual_server_launch_reopens_live_service_without_resuming_worker(self):
        from web import server

        fresh = Controller(self.directory)
        with patch("web.server.Controller", return_value=fresh), patch(
            "web.server.DashboardServer"
        ) as constructor, patch.object(fresh, "resume") as resume, patch(
            "web.session.webbrowser.open"
        ) as browser, patch("sys.argv", ["web.server", "--open-browser", "--port", "8765"]), patch("builtins.print"):
            self.assertEqual(server.main(), 0)
        constructor.assert_not_called()
        resume.assert_not_called()
        browser.assert_called_once_with(f"http://127.0.0.1:{self.server.server_port}/")

    def test_setup_without_live_service_keeps_install_and_start_flow(self):
        from scripts import setup

        self.server.session_path.unlink()
        root = self.directory / "setup-root"
        python = root / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
        for installed in (False, True):
            with self.subTest(installed=installed):
                if installed:
                    python.parent.mkdir(parents=True)
                    python.touch()
                with patch("scripts.setup.ROOT", root), patch("web.core.Core") as core, patch(
                    "web.session.webbrowser.open"
                ) as browser, patch("scripts.setup.subprocess.run") as run, patch(
                    "sys.argv", ["setup.py", "--port", "18765"]
                ):
                    core.return_value.call.return_value = {"path": str(self.directory)}
                    setup.main()
                browser.assert_not_called()
                self.assertEqual(run.call_count, 2 if installed else 3)
                if not installed:
                    self.assertIn("venv", run.call_args_list[0].args[0])
                self.assertIn("pip", run.call_args_list[-2].args[0])
                command = run.call_args_list[-1].args[0]
                self.assertIn("web.server", command)
                self.assertEqual(command[-1], "18765")

    def test_install_only_does_not_reopen_or_launch_service(self):
        from scripts import setup

        with patch("scripts.setup.ROOT", self.directory / "install-only-root"), patch(
            "web.core.Core"
        ), patch("web.session.webbrowser.open") as browser, patch(
            "scripts.setup.subprocess.run"
        ) as run, patch("sys.argv", ["setup.py", "--install-only"]):
            setup.main()
        browser.assert_not_called()
        self.assertEqual(run.call_count, 2)
        self.assertIn("venv", run.call_args_list[0].args[0])
        self.assertIn("pip", run.call_args.args[0])

    def test_server_reuses_service_started_after_first_discovery(self):
        from web import server

        fresh = Controller(self.directory)
        with patch("web.server.Controller", return_value=fresh), patch(
            "web.server.open_running_service", side_effect=[False, True]
        ) as reopen, patch("web.server.DashboardServer", side_effect=DashboardError("已有服务")), patch(
            "web.server.logging.basicConfig"
        ), patch("web.server.RotatingFileHandler"), patch.object(fresh, "resume") as resume, patch(
            "sys.argv", ["web.server", "--open-browser"]
        ):
            self.assertEqual(server.main(), 0)
        self.assertEqual(reopen.call_count, 2)
        resume.assert_not_called()

    def test_save_only_does_not_start_worker(self):
        status, body = self.request("/api/config", "POST", CONFIG)
        self.assertEqual(status, 200)
        self.assertFalse(self.controller.running())
        self.assertFalse(self.controller.store.load()["enabled"])
        self.assertNotIn(CONFIG["password"], body.decode())

    def test_manual_check_is_read_only_and_works_without_account(self):
        with patch.object(self.controller.core, "call", return_value=online()) as call:
            status, body = self.request("/api/action", "POST", {"action": "check"})
        self.assertEqual(status, 200)
        call.assert_called_once_with("check")
        self.assertFalse(json.loads(body)["data"]["authenticated"])
        self.assertFalse(self.controller.store.path.exists())

    def test_cli_and_browser_share_config_and_api(self):
        reply = self.cli("set", input=json.dumps(CONFIG))
        self.assertEqual(reply.returncode, 0, reply.stderr)
        self.assertNotIn(CONFIG["password"], reply.stdout)
        reply = self.cli("status")
        self.assertEqual(reply.returncode, 0, reply.stderr)
        self.assertEqual(json.loads(reply.stdout)["data"]["config"]["operator"], "hsd")
        with patch.object(self.controller.core, "call", return_value=online()) as call:
            reply = self.cli("check")
        self.assertEqual(reply.returncode, 0, reply.stderr)
        call.assert_called_once_with("check")

    def test_cli_reports_api_failure_as_nonzero(self):
        with patch.object(
            self.controller.core,
            "call",
            side_effect=DashboardError("检测失败", "probe"),
        ):
            reply = self.cli("check")
        self.assertNotEqual(reply.returncode, 0)
        self.assertIn("检测失败", reply.stderr)

    def test_explicit_stop_waits_for_inflight_tick_and_persists(self):
        self.controller.store.save(CONFIG)
        entered = threading.Event()
        release = threading.Event()
        stopped = threading.Event()
        original = self.controller.core.call

        def call(op, **payload):
            if op == "tick":
                self.assertEqual(payload["config"]["password"], CONFIG["password"])
                entered.set()
                release.wait(4)
                return online()
            return original(op, **payload)

        def stop():
            try:
                self.controller.mutate("action", {"action": "stop"})
            finally:
                stopped.set()

        with patch.object(self.controller.core, "call", side_effect=call):
            self.controller.mutate("action", {"action": "start"})
            self.assertTrue(entered.wait(3))
            stopper = threading.Thread(target=stop)
            stopper.start()
            self.assertTrue(self.controller.stop_event.wait(2))
            release.set()
            self.assertTrue(stopped.wait(4))
            stopper.join()
            self.controller.close()
        self.assertFalse(self.controller.store.load()["enabled"])
        restarted = Controller(self.directory)
        restarted.resume()
        self.assertFalse(restarted.running())
        restarted.close()

    def test_system_start_obeys_auto_start_and_enabled(self):
        self.controller.store.save({**CONFIG, "autoStart": False})
        self.controller.store.set_enabled(True)
        self.controller.resume(autostart=True)
        self.assertFalse(self.controller.running())

    def test_invalid_saved_password_stops_worker_but_keeps_management_available(self):
        self.controller.store.save(CONFIG)
        self.controller.store.set_enabled(True)
        data = self.controller.store.load()
        data["password"] = "damaged"
        self.controller.store.path.write_text(json.dumps(data))
        self.controller.resume(autostart=True)
        self.assertFalse(self.controller.running())
        self.assertEqual(self.controller.last_result["errorStage"], "credentials")
        status, _ = self.request("/api/config", "POST", CONFIG)
        self.assertEqual(status, 200)
        self.assertEqual(
            self.controller.store.credentials()["password"], CONFIG["password"]
        )

    def test_one_service_per_data_directory(self):
        with self.assertRaises(DashboardError):
            DashboardServer(
                ServerConfig("127.0.0.1", 0),
                "another-token",
                Controller(self.directory),
            )
        self.assertEqual(self.cli("status").returncode, 0)

    def test_log_tail_and_removed_routes(self):
        self.server.log_path.write_text("first\nsecond\n")
        status, body = self.request("/api/logs?tail=1")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["data"]["lines"], ["second"])
        self.assertEqual(self.request("/api/logs?tail=1001")[0], 400)
        self.assertEqual(self.request("/api/download-log")[0], 404)
        for action in ("restart", "force-login"):
            self.assertEqual(
                self.request("/api/action", "POST", {"action": action})[0], 400
            )

    def test_json_limits_origins_and_tokens(self):
        for payload in ([], "string", {"action": None}):
            self.assertEqual(self.request("/api/action", "POST", payload)[0], 400)
        self.assertEqual(
            self.request("/api/logs", headers={"X-HTU-Token": "wrong"})[0], 400
        )
        self.assertEqual(
            self.request("/api/logs", headers={"Origin": "http://other.example"})[0],
            400,
        )
        self.assertEqual(
            self.request("/api/action", "POST", headers={"Content-Length": "-1"})[0],
            400,
        )
        self.assertEqual(
            self.request("/api/config", "POST", {"password": "x" * (64 * 1024)})[0], 400
        )

    def test_home_static_paths_and_workspace_settings(self):
        status, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn(b"test-token", body)
        self.assertIn(b"themeButton", body)
        self.assertIn(b"settingsDialog", body)
        self.assertNotIn(b"windowsOptions", body)
        self.assertEqual(self.request("/static/../../README.md")[0], 404)
        self.assertEqual(self.request("/static/app.js")[0], 200)
        self.assertEqual(self.request("/static/theme-init.js")[0], 200)
        self.assertEqual(self.request("/static/styles.css")[0], 200)

    def test_busy_operations_are_conflicts(self):
        self.controller.operations.acquire()
        try:
            self.assertEqual(self.request("/api/config", "POST", CONFIG)[0], 409)
        finally:
            self.controller.operations.release()


if __name__ == "__main__":
    unittest.main()
