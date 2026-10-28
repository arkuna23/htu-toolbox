from __future__ import annotations

import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import secrets
import signal
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from dataclasses import dataclass

from .config import atomic_write
from .core import DashboardError
from .runtime import BusyError, Controller
from .session import open_running_service

ROOT_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT_DIR / "web" / "static"
TOKEN_PLACEHOLDER = "{{HTU_TOKEN}}"


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int


def read_log_tail(path: Path, lines: int = 200) -> list[str]:
    if not path.exists():
        return []
    lines = max(1, min(lines, 1000))
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            position = handle.tell()
            data = b""
            while position > 0 and data.count(b"\n") <= lines:
                size = min(position, 8192)
                position -= size
                handle.seek(position)
                data = handle.read(size) + data
                if len(data) > 1024 * 1024:
                    break
        return data.decode("utf-8-sig", errors="replace").splitlines()[-lines:]
    except OSError as error:
        raise DashboardError("无法读取日志文件。") from error


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "HTUToolbox/2.0"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, fmt: str, *args) -> None:
        logging.debug("HTTP %s", self.command)

    def allowed_origin(self) -> bool:
        try:
            host = urlsplit("http://" + self.headers.get("Host", ""))
            if (
                host.hostname not in {"127.0.0.1", "localhost"}
                or (host.port or 80) != self.server.server_port
            ):
                return False
            origin = self.headers.get("Origin")
            if not origin:
                return True
            parsed = urlsplit(origin)
            return (
                parsed.scheme == "http"
                and parsed.hostname == host.hostname
                and (parsed.port or 80) == self.server.server_port
            )
        except ValueError:
            return False

    def require_access(self) -> None:
        if not self.allowed_origin():
            raise DashboardError("拒绝非本机或跨来源请求。")
        if not secrets.compare_digest(
            self.headers.get("X-HTU-Token", ""), self.server.token
        ):
            raise DashboardError("页面令牌无效，请刷新页面。")

    def send_bytes(self, status: int, data: bytes, content_type: str) -> None:
        try:
            self.write_response(status, data, content_type)
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            # A cancelled browser request cannot receive another error response.
            self.close_connection = True

    def write_response(self, status: int, data: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, status: int, payload: dict) -> None:
        self.send_bytes(
            status,
            json.dumps(payload, ensure_ascii=False).encode(),
            "application/json; charset=utf-8",
        )

    def do_GET(self) -> None:
        try:
            if not self.allowed_origin():
                raise DashboardError("拒绝非本机请求。")
            parsed = urlsplit(self.path)
            if parsed.path == "/":
                text = (
                    (STATIC_DIR / "index.html")
                    .read_text(encoding="utf-8")
                    .replace(TOKEN_PLACEHOLDER, self.server.token)
                )
                self.send_bytes(200, text.encode(), "text/html; charset=utf-8")
                return
            if parsed.path.startswith("/static/"):
                path = (STATIC_DIR / parsed.path[len("/static/") :]).resolve()
                if STATIC_DIR not in path.parents or not path.is_file():
                    self.send_json(404, {"ok": False, "error": "文件不存在。"})
                    return
                types = {
                    ".css": "text/css",
                    ".js": "application/javascript",
                    ".svg": "image/svg+xml",
                    ".png": "image/png",
                }
                self.send_bytes(
                    200,
                    path.read_bytes(),
                    types.get(path.suffix, "application/octet-stream"),
                )
                return
            self.require_access()
            if parsed.path == "/api/status":
                self.send_json(
                    200,
                    {"ok": True, "data": self.server.controller.status()},
                )
            elif parsed.path == "/api/detect-portal":
                self.send_json(
                    200, {"ok": True, **self.server.controller.mutate("detect", {})}
                )
            elif parsed.path == "/api/logs":
                tail = int(parse_qs(parsed.query).get("tail", ["250"])[0])
                if not 1 <= tail <= 1000:
                    raise DashboardError("日志行数须为 1 到 1000。")
                lines = read_log_tail(self.server.log_path, tail)
                try:
                    modified = self.server.log_path.stat().st_mtime
                except FileNotFoundError:
                    modified = None
                self.send_json(
                    200,
                    {"ok": True, "data": {"lines": lines, "lastWriteTime": modified}},
                )
            else:
                self.send_json(404, {"ok": False, "error": "接口不存在。"})
        except BusyError as error:
            self.send_json(409, {"ok": False, "error": str(error)})
        except (DashboardError, ValueError, OSError) as error:
            self.send_json(400, {"ok": False, "error": str(error)})

    def do_POST(self) -> None:
        try:
            self.require_access()
            if self.headers.get("Transfer-Encoding"):
                raise DashboardError("不支持此请求体编码。")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 64 * 1024:
                raise DashboardError("请求体大小无效。")
            body = self.rfile.read(length)
            if len(body) != length:
                raise DashboardError("请求数据不完整。")
            payload = json.loads(body) if body else {}
            if not isinstance(payload, dict):
                raise DashboardError("请求数据必须是 JSON 对象。")
            path = urlsplit(self.path).path
            if path not in {"/api/action", "/api/config"}:
                self.send_json(404, {"ok": False, "error": "接口不存在。"})
                return
            if path == "/api/action" and not isinstance(payload.get("action"), str):
                raise DashboardError("action 必须是字符串。")
            result = self.server.controller.mutate(
                "config" if path == "/api/config" else "action", payload
            )
            self.send_json(200, {"ok": True, **result})
        except BusyError as error:
            self.send_json(409, {"ok": False, "error": str(error)})
        except (DashboardError, ValueError, OSError) as error:
            self.send_json(400, {"ok": False, "error": str(error)})
        except Exception:
            logging.error("控制操作失败。")
            self.send_json(
                500, {"ok": False, "error": "操作失败，请检查日志或重新保存配置。"}
            )


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self, config: ServerConfig, token: str, controller: Controller | None = None
    ):
        self.token = token
        self.controller = controller or Controller()
        directory = self.controller.store.directory
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.log_path = directory / "campus-auto-login.log"
        self.session_path = directory / "session.json"
        self.session_written = False
        self.instance = (directory / "service.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                if self.instance.tell() == 0:
                    self.instance.write(b"0")
                    self.instance.flush()
                self.instance.seek(0)
                msvcrt.locking(self.instance.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.instance.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.instance.close()
            raise DashboardError("此用户数据目录已有桌面服务运行。") from error
        try:
            super().__init__((config.host, config.port), DashboardHandler)
            atomic_write(
                self.session_path,
                json.dumps({"port": self.server_port, "token": token}).encode(),
            )
            self.session_written = True
        except Exception:
            self.server_close()
            raise

    def server_close(self):
        super().server_close()
        if self.session_written:
            self.session_path.unlink(missing_ok=True)
            self.session_written = False
        self.instance.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="HTU cross-platform campus dashboard")
    parser.add_argument(
        "--host", choices=["127.0.0.1", "localhost"], default="127.0.0.1"
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open-browser", action="store_true")
    parser.add_argument(
        "--autostart",
        action="store_true",
        help="系统启动：仅在 autoStart 和 enabled 都开启时恢复",
    )
    parser.add_argument("--runtime-dir", type=Path)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    if args.runtime_dir:
        if not args.runtime_dir.is_absolute():
            parser.error("runtime-dir must be absolute")
        os.environ["HTU_RUNTIME_DIR"] = str(args.runtime_dir)
    controller = Controller()
    directory = controller.store.directory
    if args.open_browser and open_running_service(directory):
        controller.close()
        return 0
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    handler = RotatingFileHandler(
        directory / "campus-auto-login.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=2,
        encoding="utf-8",
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[handler],
    )
    try:
        server = DashboardServer(
            ServerConfig(args.host, args.port), secrets.token_urlsafe(32), controller
        )
    except DashboardError as error:
        controller.close()
        # Another launcher may have finished starting after the initial check.
        if args.open_browser and open_running_service(directory):
            return 0
        print(str(error), file=__import__("sys").stderr)
        return 1
    except OSError:
        controller.close()
        print("无法启动：端口已占用或不可用。", file=__import__("sys").stderr)
        return 1

    # Raising through serve_forever allows a graceful SIGTERM without shutdown deadlock.
    def stop(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        controller.resume(args.autostart)
        if args.open_browser:
            import webbrowser

            webbrowser.open(f"http://{args.host}:{args.port}/")
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        controller.close()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
