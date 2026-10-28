"""Package the built desktop host and matching native binaries."""

from pathlib import Path
import argparse
import hashlib
import json
import platform
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    metadata = json.loads(
        subprocess.check_output(
            ["cargo", "metadata", "--locked", "--no-deps", "--format-version", "1"],
            cwd=ROOT,
        )
    )
    versions = {
        package["version"]
        for package in metadata["packages"]
        if package["id"] in metadata["workspace_members"]
    }
    if len(versions) != 1:
        parser.error("workspace 版本不一致")
    version = versions.pop()
    system = {"Windows": "windows", "Linux": "linux", "Darwin": "macos"}[
        platform.system()
    ]
    arch = {"AMD64": "x86_64", "arm64": "aarch64"}.get(
        platform.machine(), platform.machine()
    )
    output = (
        args.output or ROOT / "dist" / f"htu-connect-{version}-{system}-{arch}.zip"
    ).resolve()
    if not output.is_relative_to(ROOT / "dist"):
        parser.error("输出文件须位于 dist 目录")
    name = {
        "windows": "htu_toolbox_lib.dll",
        "linux": "libhtu_toolbox_lib.so",
        "macos": "libhtu_toolbox_lib.dylib",
    }[system]
    cli = "htu-toolbox-cli.exe" if system == "windows" else "htu-toolbox-cli"
    files = [
        Path(name)
        for name in (
            "README.md",
            "LICENSE",
            "requirements.txt",
            "Setup.cmd",
            "scripts/setup.py",
            "scripts/start.sh",
            "scripts/install-user-service.py",
            "docs/功能接口与实现梳理.md",
        )
    ]
    files += [
        path.relative_to(ROOT)
        for path in (ROOT / "web").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    ]
    files += [Path("native") / name, Path("native") / cli, Path("native/build.json")]
    for file in files:
        if not (ROOT / file).is_file():
            parser.error(f"缺少发布文件：{file}，请先运行 scripts/build-core.py")
    source = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    if subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        cwd=ROOT,
        text=True,
    ).strip():
        parser.error("发布包必须来自已提交且干净的源码")
    build = json.loads((ROOT / "native/build.json").read_text())
    if (
        build["dirty"]
        or build["source_commit"] != source
        or build["version"] != version
    ):
        parser.error(
            "原生文件必须由当前已提交源码构建，请重新运行 scripts/build-core.py"
        )
    for filename in (name, cli):
        if (
            hashlib.sha256((ROOT / "native" / filename).read_bytes()).hexdigest()
            != build["files"][filename]
        ):
            parser.error("原生文件与构建记录不一致")
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(files):
            archive.write(ROOT / file, file.as_posix())
        archive.writestr(
            "RELEASE.json",
            json.dumps(
                {
                    "version": version,
                    "source_commit": source,
                    "platform": system,
                    "architecture": arch,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    Path(str(output) + ".sha256").write_text(digest + "  " + output.name + "\n")
    print(output)


if __name__ == "__main__":
    main()
