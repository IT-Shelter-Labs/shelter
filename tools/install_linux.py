#!/usr/bin/env python3
"""Install Shelter from a clean package into a user-selected Linux folder."""
import argparse
from ctypes.util import find_library
from importlib.util import find_spec
import os
from pathlib import Path
import shutil
import subprocess
import sys

from export_public import ROOT, export


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "Shelter"
    location = parser.add_mutually_exclusive_group()
    location.add_argument("--directory", type=Path, help=f"new installation folder (default: {default})")
    location.add_argument("--choose-directory", action="store_true", help="choose the parent folder in a graphical dialog")
    included = ROOT / "shelter-desktop"
    parser.add_argument("--desktop-binary", type=Path, default=included if included.is_file() else None,
                        help="use a prebuilt Linux desktop executable")
    parser.add_argument("--light-recognition", action="store_true", help="use Vosk without downloading GigaAM")
    args = parser.parse_args()
    if sys.platform != "linux" or sys.version_info < (3, 11):
        parser.error("Linux and Python 3.11 or newer are required")
    if not find_spec("ensurepip") or not find_library("portaudio"):
        parser.error("install Python venv and PortAudio first (Ubuntu/Debian: python3-venv and libportaudio2)")
    target = args.directory or default
    if args.choose_directory:
        import tkinter
        from tkinter import filedialog

        dialog = tkinter.Tk()
        dialog.withdraw()
        try:
            parent = filedialog.askdirectory(title="Куда установить Shelter", initialdir=Path.home())
        finally:
            dialog.destroy()
        if not parent:
            return
        target = Path(parent) / "Shelter"
    target = target.expanduser().resolve()
    desktop = args.desktop_binary.expanduser().resolve() if args.desktop_binary else None
    if desktop and not desktop.is_file():
        parser.error("the desktop executable does not exist")
    try:
        export(target)
    except ValueError as error:
        parser.error(str(error))

    def run(*command):
        subprocess.run(command, cwd=target, check=True)

    try:
        run(sys.executable, "-m", "venv", ".venv")
        python = target / ".venv/bin/python"
        run(python, "-m", "pip", "install", "--no-cache-dir", "-r", "requirements.txt")
        components = ["vosk", "kws", "vad", "piper:ruslan", "piper:irina"]
        if args.light_recognition:
            import json

            settings = target / "data/settings.json"
            settings.parent.mkdir()
            settings.write_text(json.dumps({"asr": {"engine": "vosk"}}), encoding="utf-8")
        else:
            components.append("gigaam")
        run(python, "setup_tool.py", "install", *components)
    except subprocess.CalledProcessError:
        raise SystemExit(f"Installation interrupted. See output above. Partial installation: {target}") from None
    if desktop:
        executable = target / "shelter-desktop"
        shutil.copy2(desktop, executable)
        executable.chmod(0o755)
        native = ROOT / "bin" / "libjarvis_native.so"
        if native.is_file():
            (target / "bin").mkdir(exist_ok=True)
            shutil.copy2(native, target / "bin" / native.name)
        command = 'exec "$root/shelter-desktop" "$@"'
    else:
        command = 'exec "$root/.venv/bin/python" "$root/main.py" "$@"'
    launcher = target / "shelter"
    launcher.write_text('#!/bin/sh\nset -eu\nroot=$(cd -- "$(dirname -- "$0")" && pwd)\n'
                        'cd -- "$root"\nexport JARVIS_CORE="$root"\n' + command + '\n', encoding="utf-8")
    launcher.chmod(0o755)
    print(f"Installed. Start: {launcher}")


if __name__ == "__main__":
    main()
