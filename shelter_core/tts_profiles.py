"""Switch a validated, small SFT delta in place; preserve CUDA graph addresses.

Call select only under the voice server's generation lock. The frozen speaker
encoder, speech tokenizer and predictor are shared and never modified.
"""
import hashlib
import json
from pathlib import Path


def manifest(folder):
    return json.loads((Path(folder)/"manifest.json").read_text(encoding="utf8"))


def revision(folder):
    try:
        return hashlib.sha256((Path(folder)/"manifest.json").read_bytes()).hexdigest()
    except OSError:
        return "missing"


class ModelProfiles:
    def __init__(self, model, base, adapter):
        import torch
        from safetensors import safe_open
        from safetensors.torch import load_file
        self.parameters=dict(model.named_parameters())
        self.active="default"
        meta=manifest(adapter)
        base=Path(base)
        if meta["base_revision"]!=base.name:
            raise ValueError("Обученный голос рассчитан на другую версию базовой модели")
        weights=Path(adapter)/"adapter.safetensors"
        if hashlib.sha256(weights.read_bytes()).hexdigest()!=meta["sha256"]:
            raise ValueError("Контрольная сумма обученного голоса не совпадает")
        self.adapted=load_file(str(weights),device="cpu")
        if set(self.adapted)!=set(meta["parameters"]):
            raise ValueError("Неполный набор весов голоса")
        self.original={}
        with safe_open(str(base/"model.safetensors"),framework="pt",device="cpu") as source:
            for name,value in self.adapted.items():
                if not name.startswith("talker.") or name.startswith("talker.code_predictor."):
                    raise ValueError("Обученный профиль меняет замороженные части модели")
                target=self.parameters.get(name)
                if target is None or target.shape!=value.shape or not torch.isfinite(value).all():
                    raise ValueError("Несовместимые веса обученного голоса: "+name)
                self.original[name]=source.get_tensor(name)
        self.revision=revision(adapter)
        self.sampling=meta.get("sampling",{})

    def select(self, name):
        import torch
        if name not in ("default","jarvis"):
            raise ValueError("Неизвестный профиль голоса")
        if name==self.active:return
        values=self.adapted if name=="jarvis" else self.original
        try:
            with torch.no_grad():
                for key,value in values.items():
                    self.parameters[key].copy_(value)
        except Exception:
            with torch.no_grad():
                for key,value in self.original.items():
                    self.parameters[key].copy_(value)
            self.active="default"
            raise
        self.active=name
