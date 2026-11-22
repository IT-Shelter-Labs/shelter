"""Build the optional Rust runtime and publish it to the existing bin folder."""
import os
import hashlib
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent.parent

def publish(source, destination):
    destination.parent.mkdir(exist_ok=True)
    if destination.is_file() and hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(destination.read_bytes()).digest():
        print(destination)
        return
    try: shutil.copy2(source,destination)
    except PermissionError as error: raise SystemExit("Закройте Джарвиса через меню трея и повторите сборку: библиотека используется.") from error
    print(destination)

def main():
    subprocess.run(["cargo","build","--release","--locked","--manifest-path",str(ROOT/"native/Cargo.toml")],check=True,cwd=ROOT)
    name = "jarvis_native.dll" if os.name == "nt" else "libjarvis_native.so"
    publish(ROOT/"native/target/release"/name,ROOT/"bin"/name)
    if os.name == "nt":
        subprocess.run(["cargo","build","--release","--locked","--manifest-path",str(ROOT/"hud/Cargo.toml")],check=True,cwd=ROOT)
        publish(ROOT/"hud/target/release/jarvis-hud.exe",ROOT/"bin/jarvis-hud.exe")

if __name__ == "__main__": main()
