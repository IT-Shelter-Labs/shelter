"""Собрать встроенный каталог: plugins/catalog-src/<id>/ -> plugins/catalog/<id>-<версия>.jarvis-plugin.zip."""

import json
import hashlib
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "plugins", "catalog-src")
TARGET = os.path.join(ROOT, "plugins", "catalog")

os.makedirs(TARGET, exist_ok=True)
packages = []
for plugin in sorted(os.listdir(SOURCE)):
    folder = os.path.join(SOURCE, plugin)
    with open(os.path.join(folder, "plugin.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    path = os.path.join(TARGET, f"{manifest['id']}-{manifest['version']}.jarvis-plugin.zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(os.listdir(folder)):
            if name.endswith((".py", ".json", ".md", ".txt")) and os.path.isfile(os.path.join(folder, name)):
                info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))   # одинаковые байты при каждой сборке
                with open(os.path.join(folder, name), "rb") as f:
                    archive.writestr(info, f.read(), zipfile.ZIP_DEFLATED)
    print(path)
    with open(path, "rb") as stream:
        digest = hashlib.sha256(stream.read()).hexdigest()
    packages.append({"id": manifest["id"], "name": manifest["name"], "version": manifest["version"],
                     "description": manifest.get("description", ""), "file": os.path.basename(path), "sha256": digest})
with open(os.path.join(TARGET, "index.json"), "w", encoding="utf-8") as stream:
    json.dump({"format": "jarvis.catalog", "version": 1, "name": "Jarvis · пример источника", "packages": packages}, stream, ensure_ascii=False, indent=2)
