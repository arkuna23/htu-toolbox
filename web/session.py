"""Find and reopen this user's existing 2.x desktop service."""

from __future__ import annotations

import http.client
import json
from pathlib import Path
import re
import webbrowser


def running_service_url(directory: Path) -> str | None:
    try:
        with (directory / "session.json").open("rb") as handle:
            raw = handle.read(4097)
        if len(raw) > 4096:
            return None
        session = json.loads(raw)
        if not isinstance(session, dict):
            return None
        port, token = session.get("port"), session.get("token")
        if type(port) is not int or not 1024 <= port <= 65535:
            return None
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", token):
            return None
        # A direct loopback connection uses neither proxies nor redirects.
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            connection.request("GET", "/api/status", headers={"X-HTU-Token": token})
            response = connection.getresponse()
            body = response.read(65537)
            if response.status != 200 or len(body) > 65536:
                return None
            reply = json.loads(body)
        finally:
            connection.close()
        if not isinstance(reply, dict) or reply.get("ok") is not True:
            return None
        data = reply.get("data")
        if not isinstance(data, dict) or not all(
            isinstance(data.get(key), dict) for key in ("task", "config", "platform")
        ):
            return None
        return f"http://127.0.0.1:{port}/"
    except (OSError, ValueError, http.client.HTTPException):
        return None


def open_running_service(directory: Path) -> bool:
    url = running_service_url(directory)
    if url is None:
        return False
    webbrowser.open(url)
    print(f"新版后台服务已在运行，打开网页：{url}")
    return True
