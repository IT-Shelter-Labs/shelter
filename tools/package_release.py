"""Assemble verified local Shelter builds and a fresh public source snapshot."""

import argparse
import hashlib
from pathlib import Path
import re
import runpy
import shutil
import tarfile
import zipfile

from export_public import ROOT, export


def release_version():
    version = runpy.run_path(str(ROOT / "app_version.py")).get("VERSION")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9a-z.-]+", version):
        raise ValueError("Invalid app_version.py")
    return version


def sha256(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def assemble(destination, windows, linux, android):
    prefix = f"Shelter-{release_version()}"
    apk = {
        "android-test/Shelter-android-test.apk": android / "debug" / "app-debug.apk",
        "android-unsigned/Shelter-android-unsigned.apk": android / "release" / "app-release-unsigned.apk",
    }
    linux_files = {
        "shelter-desktop": linux / "shelter-desktop",
        "bin/libjarvis_native.so": linux / "libjarvis_native.so",
    }
    for path in (windows, *linux_files.values(), *apk.values()):
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(path)
    for path in linux_files.values():
        with path.open("rb") as binary:
            header = binary.read(20)
        if header[:6] != b"\x7fELF\x02\x01" or int.from_bytes(header[18:20], "little") != 62:
            raise ValueError(f"{path.name} is not a Linux x86_64 ELF file")
    if destination.exists():
        raise FileExistsError(destination)

    snapshot = destination / "github-source"
    export(snapshot)
    artifacts = {}
    source_zip = destination / f"{prefix}-source.zip"
    with zipfile.ZipFile(source_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(snapshot.rglob("*")):
            if file.is_file():
                archive.write(file, (Path(prefix) / file.relative_to(snapshot)).as_posix())
    artifacts[source_zip.name] = source_zip

    linux_archive = destination / f"{prefix}-linux-x86_64.tar.gz"
    with tarfile.open(linux_archive, "w:gz") as archive:
        archive.add(snapshot, arcname=prefix)
        for name, file in linux_files.items():
            info = archive.gettarinfo(file, arcname=f"{prefix}/{name}")
            info.mode = 0o755
            with file.open("rb") as payload:
                archive.addfile(info, payload)
    artifacts[linux_archive.name] = linux_archive

    for name, file in {f"{prefix}-windows-x64-setup.exe": windows, **apk}.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, target)
        artifacts[name] = target

    digest_lines = [f"{sha256(file)}  {name}" for name, file in sorted(artifacts.items())]
    (destination / "SHA256SUMS.txt").write_text("\n".join(digest_lines) + "\n", encoding="ascii", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--windows", type=Path, required=True, help="built Windows x64 NSIS installer")
    parser.add_argument("--linux", type=Path, required=True, help="directory with the native Linux build")
    parser.add_argument("--android", type=Path, default=ROOT / "android/app/build/outputs/apk")
    args = parser.parse_args()
    assemble(args.destination.resolve(), args.windows.resolve(), args.linux.resolve(), args.android.resolve())


if __name__ == "__main__":
    main()
