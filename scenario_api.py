"""Окно приложения <-> сценарии: список, редактор, проверка фразы, запуск, наборы."""

import secrets

import packs
import router_check
import scenarios


def snapshot(config):
    try:
        items = scenarios.load(config)
        error = ""
    except scenarios.ScenarioError as problem:
        items, error = [], str(problem)
    import triggers
    return {"items": items, "error": error, "platform": scenarios.PLATFORM, "version": scenarios.VERSION,
            "actions": scenarios.registry_for_platform(scenarios.ACTIONS), "conditions": scenarios.registry_for_platform(scenarios.CONDITIONS), "triggers": scenarios.TRIGGERS,
            "recent": scenarios.recent(), "events": triggers.recent(), "backups": scenarios.backups(),
            "conflicts": router_check.conflicts(config) if not error else [], "choices": choices(config)}


def choices(config):
    """Что предложить в полях формы: программы, мониторы, устройства, движения, персонажи."""
    out = {"apps": [], "monitors": 1, "devices": [], "animations": [], "personas": []}
    try:
        import tools
        out["apps"] = sorted({a["name"] for a in tools.load_apps() or []})[:600]
    except Exception:
        pass
    try:
        import pc
        out["monitors"] = max(1, len(pc.monitors()))
    except Exception:
        pass
    try:
        import smarthome
        out["devices"] = smarthome.names()
    except Exception:
        pass
    try:
        import avatar_motion
        out["animations"] = [k for k in avatar_motion.GESTURES if k != "stop"]
    except Exception:
        pass
    try:
        import personas
        out["personas"] = [{"id": p["id"], "name": p.get("name", p["id"])} for p in personas.all_personas()]
    except Exception:
        pass
    try:
        import plugins_manager
        out["plugins"] = [{"id": p["id"], "name": p["name"], "actions": p.get("actions") or [], "enabled": p.get("enabled", True)}
                          for p in plugins_manager.installed() if not p.get("broken") and "action" in (p.get("kinds") or ["action"])]
    except Exception:
        out["plugins"] = []
    return out


def dispatch(data, config, events):
    op = str(data.get("op") or "")
    if op == "save":
        item = scenarios.save(data.get("item") or {})
        scenarios.DRAFTS.pop(item["id"], None)
        return {"ok": True, "item": item, "conflicts": router_check.conflicts(config, item)}
    if op == "validate":
        item = scenarios.normalize(data.get("item") or {})
        return {"problems": scenarios.validate(item), "conflicts": router_check.conflicts(config, item)}
    if op == "delete":
        scenarios.delete(str(data.get("id") or ""))
        return {"ok": True}
    if op == "toggle":
        item = scenarios.get(str(data.get("id") or ""))
        if item is None:
            raise scenarios.ScenarioError("нет такого сценария")
        item["enabled"] = bool(data.get("enabled"))
        scenarios.save(item)
        return {"ok": True}
    if op == "test":
        draft = data.get("draft")
        return router_check.explain(str(data.get("phrase") or ""), config, draft if isinstance(draft, dict) else None,
                                    semantic=data.get("semantic") is True)
    if op == "plan":
        return scenarios.plan(data.get("item") or {})
    if op in ("run", "run_draft"):
        if op == "run_draft":
            item = scenarios.normalize(data.get("item") or {})
            problems = scenarios.validate(item)
            if problems:
                raise scenarios.ScenarioError("; ".join(problems))
            item["id"] = "draft_" + item["id"]
            scenarios.DRAFTS[item["id"]] = item
            scenario_id = item["id"]
        else:
            scenario_id = str(data.get("id") or "")
        run = "run_" + secrets.token_hex(4)
        # confirmed — человек нажал «Запустить» в окне и подтвердил там же.
        events.put(("scenario", {"id": scenario_id, "source": "кнопка в окне", "run": run,
                                 "confirmed": bool(data.get("confirmed")), "speak_errors": False}))
        return {"ok": True, "run": run}
    if op == "cancel":
        stopped = scenarios.cancel(data.get("run") or None)
        if not data.get("run"):
            events.put(("interrupt", None))
        return {"ok": True, "stopped": stopped}
    if op == "export":
        ids = data.get("ids")
        return scenarios.export(set(ids) if isinstance(ids, list) else None)
    if op == "export_file":
        # Путь выбрал человек в системном диалоге «Сохранить как».
        path = str(data.get("path") or "")
        if not path.lower().endswith(".json"):
            raise scenarios.ScenarioError("файл сценариев — .json")
        ids = data.get("ids")
        payload = scenarios.export(set(ids) if isinstance(ids, list) else None)
        import json
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return {"ok": True, "count": len(payload["items"]), "removed": payload["removed"]}
    if op == "import_file":
        import json
        import os
        path = str(data.get("path") or "")
        if os.path.getsize(path) > 2_000_000:
            raise scenarios.ScenarioError("файл больше 2 МБ — это не похоже на сценарии")
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        return scenarios.import_items(payload, bool(data.get("replace")))
    if op == "import":
        return scenarios.import_items(data.get("payload"), bool(data.get("replace")))
    if op == "restore":
        return {"ok": True, "count": scenarios.restore(str(data.get("backup") or ""))}
    if op == "from_run":
        import assistant_store as store
        return scenarios.from_run(store.run_detail(str(data.get("run") or "")))
    if op in ("demo_start", "demo_stop", "demo_status"):
        import demo_recorder
        return {"demo_start": demo_recorder.start, "demo_stop": demo_recorder.stop, "demo_status": demo_recorder.status}[op]()
    if op == "packs":
        return {"packs": packs.catalog()}
    if op == "install_pack":
        include = data.get("include")
        return packs.install(str(data.get("id") or ""), data.get("params") or {},
                             set(include) if isinstance(include, list) else None)
    raise scenarios.ScenarioError(f"неизвестная операция {op!r}")
