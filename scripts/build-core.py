"""Build the only native core and CLI; never runs automatically in the host."""

from pathlib import Path
import json
import hashlib
import platform
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    subprocess.run(
        ["cargo", "build", "--workspace", "--release", "--locked", "--jobs", "2"],
        cwd=ROOT,
        check=True,
    )
    metadata = json.loads(
        subprocess.check_output(
            ["cargo", "metadata", "--no-deps", "--format-version", "1"], cwd=ROOT
        )
    )
    artifacts = Path(metadata["target_directory"]) / "release"
    name = {
        "Windows": "htu_toolbox_lib.dll",
        "Linux": "libhtu_toolbox_lib.so",
        "Darwin": "libhtu_toolbox_lib.dylib",
    }[platform.system()]
    cli = "htu-toolbox-cli.exe" if platform.system() == "Windows" else "htu-toolbox-cli"
    destination = ROOT / "native"
    destination.mkdir(exist_ok=True)
    for filename in (name, cli):
        with tempfile.NamedTemporaryFile(dir=destination, delete=False) as handle:
            temporary = Path(handle.name)
        try:
            shutil.copy2(artifacts / filename, temporary)
            temporary.replace(destination / filename)
        except PermissionError as error:
            raise SystemExit("请先停止桌面服务，再重新构建原生文件。") from error
        finally:
            temporary.unlink(missing_ok=True)
    version = next(
        package["version"]
        for package in metadata["packages"]
        if package["name"] == "htu-toolbox-lib"
    )
    info = {
        "version": version,
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "dirty": bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=ROOT, text=True
            ).strip()
        ),
        "files": {
            filename: hashlib.sha256((destination / filename).read_bytes()).hexdigest()
            for filename in (name, cli)
        },
    }
    (destination / "build.json").write_text(json.dumps(info, indent=2))
    print("Rust core and CLI built in native/")


if __name__ == "__main__":
    main()
