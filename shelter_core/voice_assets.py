"""Checks for Qwen assets shared by setup, repair and the voice server."""
from shelter_core.paths import ROOT_PATH

import json
import os
from pathlib import Path

BASE = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
OFFICIAL = {BASE, "Qwen/Qwen3-TTS-12Hz-1.7B-Base", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"}
REQUIRED = ("config.json", "generation_config.json", "model.safetensors", "tokenizer_config.json",
            "vocab.json", "merges.txt", "preprocessor_config.json", "speech_tokenizer/config.json",
            "speech_tokenizer/preprocessor_config.json", "speech_tokenizer/model.safetensors")


def present(path):
    try:
        return Path(path).is_file() and Path(path).stat().st_size > 0
    except OSError:
        return False


def missing(folder):
    folder = Path(folder)
    absent = [name for name in REQUIRED if not present(folder / name)]
    for name in ("config.json", "generation_config.json", "tokenizer_config.json",
                 "preprocessor_config.json", "speech_tokenizer/config.json", "speech_tokenizer/preprocessor_config.json"):
        if name not in absent:
            try:
                if not isinstance(json.loads((folder / name).read_text(encoding="utf-8")), dict):
                    absent.append(name)
            except (OSError, ValueError):
                absent.append(name)
    return absent


def legacy_hub_cache():
    home = Path(os.environ.get("HF_HOME") or Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "huggingface")
    return Path(os.environ.get("HF_HUB_CACHE") or os.environ.get("HUGGINGFACE_HUB_CACHE") or home / "hub")


def hub_cache():
    if any(os.environ.get(key) for key in ("HF_HOME", "HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE")):
        return legacy_hub_cache()
    return ROOT_PATH / "models" / "huggingface"


def cached(model):
    if model not in OFFICIAL:
        return None
    for cache in dict.fromkeys((hub_cache(), legacy_hub_cache())):
        repo = cache / ("models--" + model.replace("/", "--"))
        try:
            revision = (repo / "refs" / "main").read_text(encoding="ascii").strip()
            if len(revision) == 40 and all(c in "0123456789abcdef" for c in revision):
                folder = repo / "snapshots" / revision
                if not missing(folder):
                    return folder
        except (OSError, UnicodeError):
            continue
    return None
