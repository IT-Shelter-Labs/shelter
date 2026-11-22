"""Create a NEW, reviewable source snapshot; never copy the personal Git history."""
import argparse
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent.parent
SKIP = {
    "node_modules", "target", "dist", "build", ".gradle", ".kotlin", ".cxx", "__pycache__", "gen", ".git", ".idea",
    "data", "secrets", "models", "logs", "run", "release", "reports", "datasets", "runtime",
}
DOCS = {"DEVELOPMENT.md","DESKTOP_INPUT.md","PLATFORMS.md","LINUX.md","ANDROID_CLIENT.md","AVATARS.md","COMPANION.md","CLOUD_MODELS.md","GAMES.md","MINECRAFT.md","SCENARIOS.md","PLUGINS.md","PUBLIC_RELEASE.md","RUNTIME.md"}
ROOT_FILES = {"README.md","LICENSE","SECURITY.md","CONTRIBUTING.md","THIRD_PARTY.md",".gitignore","config.public.yaml","requirements.txt","requirements-lock.windows.txt","requirements-optional.txt","requirements-tts.txt"}
DOC_MEDIA = ("shelter-cover.webp", "shelter-desktop.webp", "shelter-personas.webp", "shelter-android.webp")
EXT = {".py",".rs",".toml",".lock",".json",".svelte",".ts",".css",".html",".mjs",".cjs",".sh",".yml",".yaml",".md",".nsh",".xml",".kt",".kts",".properties",".jar",".java",".sc",".bat",".ico",".png",".vrma",".svg",".lua"}

def selected(root=ROOT):
    for path in root.iterdir():
        if path.is_file() and (path.suffix==".py" or path.name in ROOT_FILES): yield path
    for folder in ("app","native","hud","android","minecraft","games","tests","tools",".github"):
        for path in (root/folder).rglob("*"):
            relative=path.relative_to(root/folder)
            if any(p.lower() in SKIP for p in relative.parts) or path.is_symlink(): continue
            if not path.is_file(): continue
            if path.name in {"local.properties","linux_review_env.py","compare_jarvis_qwen.py"} or path.name.endswith((".bak",".tmp")): continue
            if path.suffix in EXT or path.name in {
                "gradlew", "gradlew.bat", "Cargo.lock", "MINDCRAFT-LICENSE", "MINEPAL-LICENSE"
            }: yield path
    for name in DOCS:
        if (root/"docs"/name).is_file(): yield root/"docs"/name
    for name in DOC_MEDIA:
        image = root / "docs" / "media" / name
        if image.is_file():
            yield image
    for name in ("example.py","README.md"):
        if (root/"plugins"/name).is_file(): yield root/"plugins"/name
    for path in (root/"plugins/catalog-src").glob("*.json"): yield path
    for path in (root/"plugins/catalog").glob("*.zip"): yield path

def export(destination,root=ROOT):
    destination=destination.resolve()
    if destination.exists(): raise ValueError("Нужна новая пустая папка назначения; существующие файлы не перезаписываются")
    sources=list(selected(root))
    destination.mkdir(parents=True)
    count=0
    for source in sources:
        if source.is_symlink(): continue
        target=destination/source.relative_to(root)
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target);count+=1
    shutil.copy2(root/"config.public.yaml",destination/"config.yaml")
    for name in ("jarvis","anime"):
        value=json.loads((root/"personas"/name/"persona.json").read_text(encoding="utf8"))
        value.get("voice",{}).pop("reference",None);value.get("voice",{}).pop("reference_text",None)
        if value.get("avatar",{}).get("type")=="vrm": value["avatar"]={"type":"hud"}
        target=destination/"personas"/name/"persona.json";target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    return count

def main():
    parser=argparse.ArgumentParser();parser.add_argument("destination",type=Path);args=parser.parse_args()
    print(json.dumps({"path":str(args.destination.resolve()),"source_files":export(args.destination),"git_history_included":False,"private_data_included":False}))

if __name__=="__main__":main()
