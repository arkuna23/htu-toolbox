from __future__ import annotations
import logging
import os
import platform
import threading
import time
from pathlib import Path
from .core import Core, DashboardError
from .config import ConfigStore


class BusyError(DashboardError):
    pass


class Controller:
    """One desktop host, one execution lock, one worker on every supported OS."""

    def __init__(self, directory: Path | None = None):
        self.core = Core()
        self.store = ConfigStore(
            directory or Path(self.core.call("runtime-dir")["path"]), self.core
        )
        self.operations = threading.Lock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.last_result: dict = {}
        self.next_run: float | None = None
        self.failures = 0

    def running(self) -> bool:
        return bool(
            self.thread and self.thread.is_alive() and not self.stop_event.is_set()
        )

    def platform_info(self) -> dict:
        return {
            "name": {"Darwin": "macOS"}.get(platform.system(), platform.system()),
            "passwordStorage": "Windows DPAPI" if os.name == "nt" else "本机加密文件",
            "autostartHint": "系统自启需安装用户服务；关闭浏览器不会停止服务。",
        }

    def resume(self, autostart: bool = False) -> None:
        config = self.store.load()
        if config.get("enabled") and (not autostart or config.get("autoStart")):
            try:
                self.mutate("action", {"action": "start"})
            except DashboardError as error:
                # Keep management available so the user can repair credentials.
                self.last_result = {
                    "state": "error",
                    "online": False,
                    "authenticated": False,
                    "checkedAt": None,
                    "errorStage": error.stage,
                    "error": str(error),
                    "message": str(error),
                }
                logging.error("自动登录未启动：%s", error)

    def close(self) -> None:
        # Process exit does not change user intent; explicit stop does.
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=26)

    def status(self) -> dict:
        config = self.store.summary()
        running = self.running()
        return {
            "task": {
                "state": (
                    "Running"
                    if running
                    else "Ready" if config["passwordConfigured"] else "NotInstalled"
                ),
                "nextRunTime": self.next_run,
                "stopping": bool(
                    self.thread and self.thread.is_alive() and self.stop_event.is_set()
                ),
            },
            "network": dict(self.last_result),
            "config": config,
            "platform": self.platform_info(),
        }

    def run(self, op: str) -> dict:
        try:
            payload = {}
            if op in {"login", "tick"}:
                payload["config"] = self.store.credentials()
            if op == "tick":
                payload["failures"] = self.failures
            result = self.core.call(op, **payload)
        except DashboardError as error:
            self.last_result = {
                "state": "error",
                "online": False,
                "authenticated": False,
                "checkedAt": (
                    None if error.stage in {"config", "credentials"} else time.time()
                ),
                "errorStage": error.stage,
                "error": str(error),
                "message": str(error),
            }
            logging.warning("%s: %s", error.stage, error)
            raise
        self.last_result = result
        logging.info("%s", result["message"])
        return result

    def loop(self) -> None:
        try:
            while not self.stop_event.is_set():
                if not self.operations.acquire(timeout=0.2):
                    continue
                try:
                    if self.stop_event.is_set():
                        break
                    self.next_run = None
                    result = self.run("tick")
                    self.failures = result["failures"]
                    delay = result["nextDelay"]
                    self.next_run = time.time() + delay
                finally:
                    self.operations.release()
                if self.stop_event.wait(delay):
                    break
        except DashboardError as error:
            logging.error("后台服务已停止：%s", error)
        finally:
            self.next_run = None

    def action(self, action: str) -> dict:
        if action in {"check", "login", "logout"}:
            if action == "logout":
                self.store.set_enabled(False)
                self.stop_event.set()
                self.next_run = None
            result = self.run(action)
            return {"message": result["message"], "data": result}
        if action == "start":
            self.store.credentials()
            if self.thread and self.thread.is_alive() and not self.running():
                raise BusyError("后台请求正在结束，请稍后启动。")
            self.store.set_enabled(True)
            if not self.running():
                self.stop_event.clear()
                self.failures = 0
                self.thread = threading.Thread(
                    target=self.loop, name="htu-worker", daemon=True
                )
                self.thread.start()
            return {"message": "自动登录已启动。"}
        if action == "stop":
            self.store.set_enabled(False)
            self.stop_event.set()
            self.next_run = None
            return {"message": "自动登录已停止。"}
        raise DashboardError("未知操作。")

    def mutate(self, kind: str, payload: dict) -> dict:
        stopping = kind == "action" and payload.get("action") in {"stop", "logout"}
        if stopping:
            self.stop_event.set()
        acquired = (
            self.operations.acquire(timeout=26)
            if stopping
            else self.operations.acquire(blocking=False)
        )
        if not acquired:
            raise BusyError("另一项操作正在执行，请稍后重试。")
        try:
            if kind == "config":
                return {"message": "配置已保存。", "data": self.store.save(payload)}
            if kind == "detect":
                return {"data": self.core.call("detect-portal")}
            return self.action(payload.get("action", ""))
        finally:
            self.operations.release()
