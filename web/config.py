from __future__ import annotations
import base64
import ctypes
from ctypes import wintypes
import json
import os
import tempfile
from pathlib import Path
from .core import Core, DashboardError


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(prefix=".htu-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def dpapi(data: bytes, decrypt: bool = False) -> bytes:
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    operation = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    operation.argtypes = [
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(Blob),
    ]
    operation.restype = wintypes.BOOL
    if not operation(
        ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)
    ):
        raise DashboardError(
            "密码加密或解密失败，请在当前用户下重新保存密码。", "credentials"
        )
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(ctypes.cast(output.data, ctypes.c_void_p))


class ConfigStore:
    def __init__(self, directory: Path, core: Core):
        self.directory = directory
        self.path = directory / "config.json"
        self.key_path = directory / "credential.key"
        self.core = core

    def load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or not isinstance(
                value.get("password"), str
            ):
                raise ValueError()
            checked = self.core.call(
                "validate",
                config={**value, "password": ""},
                passwordConfigured=bool(value["password"]),
            )
            checked["password"] = value["password"]
            return checked
        except (OSError, ValueError) as error:
            raise DashboardError("配置文件无效，请检查本机配置。") from error

    def save(self, payload: dict) -> dict:
        if "enabled" in payload:
            raise DashboardError("enabled 由启动和停止操作设置。")
        previous = self.load()
        config = self.core.call(
            "validate",
            config={**previous, "password": "", **payload},
            passwordConfigured=bool(previous.get("password")),
        )
        if config["password"]:
            if os.name == "nt":
                config["password"] = base64.b64encode(
                    dpapi(config["password"].encode())
                ).decode()
            else:
                from cryptography.fernet import Fernet

                if not self.key_path.exists():
                    atomic_write(self.key_path, Fernet.generate_key())
                config["password"] = (
                    Fernet(self.key_path.read_bytes())
                    .encrypt(config["password"].encode())
                    .decode()
                )
        else:
            config["password"] = previous["password"]
        atomic_write(
            self.path, json.dumps(config, ensure_ascii=False, indent=2).encode()
        )
        return self.summary()

    def credentials(self) -> dict:
        config = self.load()
        if not config.get("password"):
            raise DashboardError("请先保存账号配置。")
        try:
            if os.name == "nt":
                password = dpapi(
                    base64.b64decode(config["password"], validate=True), True
                )
            else:
                from cryptography.fernet import Fernet

                password = Fernet(self.key_path.read_bytes()).decrypt(
                    config["password"].encode()
                )
            return {**config, "password": password.decode()}
        except DashboardError:
            raise
        except Exception as error:
            raise DashboardError(
                "密码无法解密，请在本机重新保存密码。", "credentials"
            ) from error

    def set_enabled(self, value: bool) -> None:
        config = self.load()
        if not config and not value:
            return
        if not config:
            raise DashboardError("请先保存账号配置。")
        config["enabled"] = value
        atomic_write(
            self.path, json.dumps(config, ensure_ascii=False, indent=2).encode()
        )

    def summary(self) -> dict:
        config = self.load()
        return {
            **{key: value for key, value in config.items() if key != "password"},
            "passwordConfigured": bool(config.get("password")),
        }
