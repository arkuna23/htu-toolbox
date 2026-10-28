"""One system service per user: Windows task, systemd or LaunchAgent."""

from pathlib import Path
import argparse
import os
import platform
import plistlib
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from web.core import Core


def systemd_quote(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise ValueError("路径不能含换行")
    return (
        '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remove", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("端口须为 1024—65535")
    system = platform.system()
    python = ROOT / (
        ".venv/Scripts/pythonw.exe" if system == "Windows" else ".venv/bin/python"
    )
    if not args.remove and not python.exists():
        parser.error("请先运行 scripts/setup.py --install-only")
    directory = Path(Core().call("runtime-dir")["path"])
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if system == "Windows":
        powershell = (
            Path(os.environ["SystemRoot"])
            / "System32/WindowsPowerShell/v1.0/powershell.exe"
        )
        if args.remove:
            command = "$ErrorActionPreference='Stop'; Stop-ScheduledTask -TaskName 'HTU-Connect'; Unregister-ScheduledTask -TaskName 'HTU-Connect' -Confirm:$false"
        else:
            # Only this fixed script runs in PowerShell. Paths are data, not code.
            command = """$ErrorActionPreference='Stop'
$arguments='-m web.server --autostart --port {0} --runtime-dir "{1}"' -f $env:HTU_SERVICE_PORT,$env:HTU_SERVICE_DATA
$action=New-ScheduledTaskAction -Execute $env:HTU_SERVICE_PYTHON -Argument $arguments -WorkingDirectory $env:HTU_SERVICE_ROOT
$trigger=New-ScheduledTaskTrigger -AtLogOn -User ($env:USERDOMAIN+'\\'+$env:USERNAME)
$settings=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
$settings.ExecutionTimeLimit='PT0S'; $settings.RestartCount=3; $settings.RestartInterval='PT1M'
$principal=New-ScheduledTaskPrincipal -UserId ($env:USERDOMAIN+'\\'+$env:USERNAME) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'HTU-Connect' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName 'HTU-Connect'
"""
        environment = {
            **os.environ,
            "HTU_SERVICE_PYTHON": str(python),
            "HTU_SERVICE_ROOT": str(ROOT),
            "HTU_SERVICE_PORT": str(args.port),
            "HTU_SERVICE_DATA": str(directory),
        }
        subprocess.run(
            [str(powershell), "-NoProfile", "-NonInteractive", "-Command", command],
            env=environment,
            check=True,
        )
    elif system == "Linux":
        destination = (
            Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
            / "systemd/user/htu-connect.service"
        )
        if args.remove:
            subprocess.run(
                ["systemctl", "--user", "disable", "--now", "htu-connect.service"],
                check=True,
            )
            destination.unlink(missing_ok=True)
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                "[Unit]\nDescription=HTU Connect\nAfter=network.target\n\n[Service]\n"
                + f"WorkingDirectory={systemd_quote(str(ROOT))}\nExecStart={systemd_quote(str(python))} -m web.server --autostart --port {args.port}\n"
                + f"Environment={systemd_quote('HTU_RUNTIME_DIR='+str(directory))}\n"
                + "Restart=on-failure\nRestartSec=5\n\n[Install]\nWantedBy=default.target\n"
            )
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
            subprocess.run(
                ["systemctl", "--user", "enable", "--now", "htu-connect.service"],
                check=True,
            )
    elif system == "Darwin":
        destination = Path.home() / "Library/LaunchAgents/io.htu.connect.plist"
        domain = f"gui/{os.getuid()}"
        if args.remove:
            subprocess.run(
                ["launchctl", "bootout", domain, str(destination)], check=True
            )
            destination.unlink(missing_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(
                plistlib.dumps(
                    {
                        "Label": "io.htu.connect",
                        "ProgramArguments": [
                            str(python),
                            "-m",
                            "web.server",
                            "--autostart",
                            "--port",
                            str(args.port),
                        ],
                        "WorkingDirectory": str(ROOT),
                        "EnvironmentVariables": {"HTU_RUNTIME_DIR": str(directory)},
                        "RunAtLoad": True,
                        "KeepAlive": {"SuccessfulExit": False},
                        "StandardErrorPath": str(directory / "service.log"),
                    }
                )
            )
            subprocess.run(
                ["launchctl", "bootstrap", domain, str(destination)], check=True
            )
    else:
        parser.error("仅支持 Windows、Linux、macOS")
    print(
        "用户服务已移除，配置保留。"
        if args.remove
        else "用户服务已安装；启用自动恢复且未停止时会恢复自动登录。"
    )


if __name__ == "__main__":
    main()
