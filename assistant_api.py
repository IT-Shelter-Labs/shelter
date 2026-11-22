"""Authenticated control operations for the assistant's own UI."""
import assistant_store as store


def dispatch(data, config, events):
    op = data.get("op")
    if op == 'llm.catalog':
        import llm_connections
        return {'presets':llm_connections.PRESETS}
    elif op == 'llm.probe':
        import llm_connections
        connection=data.get('connection')
        llm_connections.validate({'connections':{'draft':connection}})
        return llm_connections.probe(connection)
    elif op == 'memory.index':
        import semantic_memory
        return semantic_memory.reindex(config.get('llm') or {})
    elif op == "project.save":
        store.save_project(data.get("name", ""), data.get("instructions", ""), data.get("id"))
    elif op == "project.activate":
        store.activate_project(str(data.get("id") or ""))
    elif op == "project.delete":
        store.delete_project(str(data.get("id") or ""))
    elif op == "session.new":
        store.session_for(new=True)
    elif op == "session.activate":
        store.activate_session(str(data.get("id") or ""))
    elif op == "session.delete":
        store.delete_session(str(data.get("id") or ""))
    elif op == "memory.save":
        store.remember(data.get("text", ""), str(data.get("project_id") or ""), "settings", data.get("id"))
    elif op == "memory.export":
        # Путь выбрал человек в диалоге «Сохранить как». Только факты памяти и проекты — без переписки и ключей.
        import json, time
        path = str(data.get("path") or "")
        if not path.lower().endswith(".json"):
            raise ValueError("файл памяти — .json")
        with store.db() as con:
            facts = store.rows(con, "SELECT * FROM memories ORDER BY updated DESC")
        payload = {"format": "jarvis.memory", "version": 1, "exported": time.time(),
                   "facts": [{k: m.get(k) for k in ("text", "project_id", "source", "topic", "updated")} for m in facts],
                   "projects": [{k: p.get(k) for k in ("id", "name", "instructions")} for p in store.snapshot().get("projects", [])]}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return {"ok": True, "count": len(payload["facts"])}
    elif op == "memory.delete":
        store.delete_memory(str(data.get("id") or ""))
    elif op == "context.add":
        store.add_context(store.session_for(), data.get("title", ""), data.get("text", ""))
    elif op == "context.clipboard":
        import pc
        # Explicit user action; the preview can be removed before asking a model.
        store.add_context(store.session_for(), "Буфер обмена", pc.clipboard_text(), "clipboard")
    elif op == "context.import":
        store.import_document(str(data.get("path") or ""), str(data.get("project_id") or ""), store.session_for(), bool(data.get("instructions")))
    elif op == "context.delete":
        store.remove_context(str(data.get("id") or ""))
    elif op == "document.delete":
        store.delete_document(str(data.get("id") or ""))
    elif op == "task.detail":
        return store.run_detail(str(data.get("id") or ""))
    elif op == "task.resume":
        session, text = store.retry_prompt(str(data.get("id") or ""))
        store.activate_session(session)
        events.put(("typed", {"text": text, "session_id": session}))
    elif op == "task.stop":
        events.put(("interrupt", None))
    elif op == "mcp.probe":
        import integrations
        return integrations.probe(config, str(data.get("id") or ""))
    else:
        raise ValueError("Неизвестная операция")
    return {"ok": True}
