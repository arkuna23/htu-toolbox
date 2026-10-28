"""ctypes binding: argument conversion only; all campus rules live in Rust."""

from __future__ import annotations
import ctypes
import json
import platform
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DashboardError(RuntimeError):
    def __init__(self, message: str, stage: str = "config"):
        super().__init__(message)
        self.stage = stage


class Core:
    def __init__(self):
        name = {
            "Windows": "htu_toolbox_lib.dll",
            "Linux": "libhtu_toolbox_lib.so",
            "Darwin": "libhtu_toolbox_lib.dylib",
        }.get(platform.system())
        if name is None:
            raise DashboardError("仅支持 Windows、Linux、macOS。", "core")
        try:
            self.library = ctypes.CDLL(str(ROOT / "native" / name))
        except OSError as error:
            raise DashboardError(
                "无法加载 Rust 核心，请运行 python scripts/build-core.py 或重新解压对应系统的发布包。",
                "core",
            ) from error
        self.library.htu_call.argtypes = [ctypes.c_char_p]
        self.library.htu_call.restype = ctypes.c_void_p
        self.library.htu_free.argtypes = [ctypes.c_void_p]
        self.library.htu_free.restype = None

    def call(self, op: str, **payload) -> dict:
        data = json.dumps(
            {"op": op, **payload}, ensure_ascii=False, allow_nan=False
        ).encode()
        pointer = self.library.htu_call(data)
        if not pointer:
            raise DashboardError("Rust 核心没有返回结果。", "core")
        try:
            result = json.loads(ctypes.string_at(pointer))
        finally:
            self.library.htu_free(pointer)
        if not result["ok"]:
            error = result["error"]
            raise DashboardError(error["message"], error["stage"])
        return result["data"]
