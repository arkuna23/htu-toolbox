import importlib.util
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location(
    "service_installer",
    Path(__file__).resolve().parents[1] / "scripts/install-user-service.py",
)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class ServiceTests(unittest.TestCase):
    def test_generated_services_use_one_host_and_one_runtime_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            root = directory / "project with spaces"
            (root / ".venv/bin").mkdir(parents=True)
            (root / ".venv/bin/python").touch()
            (root / ".venv/Scripts").mkdir()
            (root / ".venv/Scripts/pythonw.exe").touch()
            core = Mock()
            core.call.return_value = {"path": str(directory / "private data")}
            for system in ("Linux", "Darwin", "Windows"):
                with self.subTest(system=system), patch.object(
                    installer, "ROOT", root
                ), patch.object(installer, "Core", return_value=core), patch.object(
                    installer.platform, "system", return_value=system
                ), patch.object(
                    installer.Path, "home", return_value=directory
                ), patch.object(
                    installer.os, "getuid", return_value=1000, create=True
                ), patch.dict(
                    os.environ,
                    {
                        "XDG_CONFIG_HOME": str(directory / "config"),
                        "SystemRoot": str(directory / "Windows"),
                    },
                ), patch.object(
                    installer.sys, "argv", ["install-user-service.py"]
                ), patch.object(
                    installer.subprocess, "run"
                ) as run:
                    installer.main()
                    self.assertTrue(run.called)
                    if system == "Linux":
                        unit = (
                            directory / "config/systemd/user/htu-connect.service"
                        ).read_text()
                        self.assertIn("-m web.server --autostart", unit)
                        self.assertIn(
                            "Environment="
                            + installer.systemd_quote(
                                "HTU_RUNTIME_DIR=" + str(directory / "private data")
                            ),
                            unit,
                        )
                    elif system == "Darwin":
                        data = plistlib.loads(
                            (
                                directory / "Library/LaunchAgents/io.htu.connect.plist"
                            ).read_bytes()
                        )
                        self.assertEqual(
                            data["EnvironmentVariables"]["HTU_RUNTIME_DIR"],
                            str(directory / "private data"),
                        )
                        self.assertIn("--autostart", data["ProgramArguments"])
                    else:
                        command = run.call_args.args[0][-1]
                        self.assertIn("HTU-Connect", command)
                        self.assertIn("--runtime-dir", command)
                        self.assertNotIn("CampusNetAutoLogin", command)
                        self.assertEqual(
                            run.call_args.kwargs["env"]["HTU_SERVICE_DATA"],
                            str(directory / "private data"),
                        )

    def test_systemd_paths_escape_specifiers_and_reject_newlines(self):
        self.assertEqual(installer.systemd_quote('/a%/b"c'), '"/a%%/b\\"c"')
        with self.assertRaises(ValueError):
            installer.systemd_quote("a\nb")


if __name__ == "__main__":
    unittest.main()
