"""Объединение ранее импортированных вариантов без удаления исходных профилей.

Разовая миграция для своих загруженных моделей: запускается вручную
(python persona_groups.py), а не при каждом старте ядра.
"""
from pathlib import Path
from shelter_core import personas


def consolidate():
    with personas._storage_lock:
        profiles = personas.all_personas()
        active = personas.active_id()
        for source, name, aliases in (("tyc-3d-a.zip", "Цукуёми", ["цукуёми", "цукуеми", "цукуйоми"]),
                                       ("08_Pippa.zip", "Пиппа", ["пиппа", "пипа"])):
            group = [p for p in profiles if (p.get("imported") or {}).get("source") == source]
            if len(group) < 2:
                continue
            preferred = next((p for p in group if "стандартная, с контуром" in p["name"]), group[0])
            chosen = next((p for p in group if p["id"] == active), preferred)
            parent = personas.public(chosen)
            parent.update(name=name, aliases=aliases, appearance=chosen["id"],
                          switch_reply=personas.character_lines(name, chosen.get("gender", "f"),
                                                                chosen.get("address", "хозяин"))["switch_reply"])
            parent["appearances"] = [{"id": p["id"], "name": p["name"].split("—", 1)[-1].strip(),
                                       **{k: v for k, v in personas.public(p)["avatar"].items() if k in ("model", "preview", "credit")}}
                                      for p in group]
            personas.save(parent)  # сначала скопировать все файлы в папку владельца
            for p in group:
                if p["id"] != parent["id"]:
                    original = Path(p["folder"]) / "persona.json"
                    backup = original.with_name("persona.before-grouping.json")
                    if not backup.exists():
                        backup.write_bytes(original.read_bytes())
                    personas._write_json(str(original), {"redirect": parent["id"]})


if __name__ == "__main__":
    consolidate()
