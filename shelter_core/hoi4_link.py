"""Campaign operations against the explicitly configured HOI4 Live Tools server."""
import json

from shelter_core import integrations, policy


SERVER = "hoi4-live"
TOOLS = ("hoi4_status", "hoi4_briefing", "hoi4_clock", "hoi4_advance", "hoi4_research", "hoi4_production", "hoi4_focus")


def _call(config, name, arguments, *, confirmed=False):
    policy.require(config, "mcp")
    request = json.dumps({"server": SERVER, "tool": name, "arguments": arguments}, ensure_ascii=False)
    outcome, result = integrations.execute(config, request, confirmed=confirmed, max_chars=64_000)
    if outcome != "data":
        raise ValueError(result)
    title, separator, body = result.partition("\n{")
    try:
        data = json.loads("{" + body if separator else result)
    except ValueError:
        return {"text": result[:12_000]}
    if isinstance(data, dict):
        if data.get("ok") is False or data.get("error"):
            raise ValueError(str(data.get("error") or data.get("reason") or result)[:2000])
        response = {"text": (data.get("markdown") or (title if separator else result))[:12_000]}
        if name == "hoi4_advance" and data.get("background") is True:
            response["running"] = True
        if name == "hoi4_clock":
            response["running"] = data.get("running_in_background") is True
            if data.get("progress"):
                response["text"] += "\n" + json.dumps(data["progress"], ensure_ascii=False, indent=2)
        if name in ("hoi4_research", "hoi4_production", "hoi4_focus") and separator:
            response["text"] = result[:12_000]
        return response
    return {"text": result[:12_000]}


def action(config, operation, *, days=None, equipment="", factories=None, target=""):
    if not isinstance(operation, str):
        raise ValueError("Укажите действие кампании.")
    if operation == "connect":
        policy.require(config, "mcp")
        allowed = next((server.get("tools", []) for server in integrations.servers(config)
                        if server.get("id") == SERVER and server.get("enabled")), [])
        found = integrations.probe(config, SERVER)["tools"]
        return {"text": "HOI4 Live Tools", "available": [item["name"] for item in found
                                                        if item["name"] in TOOLS and item["name"] in allowed]}
    actions = {
        "status": ("hoi4_status", {"look": True}),
        "briefing": ("hoi4_briefing", {"save": "latest", "world": False, "remember": False}),
        "research": ("hoi4_research", {"action": "slots"}),
        "focus": ("hoi4_focus", {"action": "progress"}),
        "production": ("hoi4_production", {"action": "lines"}),
        "progress": ("hoi4_clock", {"action": "status"}),
        "result": ("hoi4_clock", {"action": "join", "wait_s": 0}),
        "stop": ("hoi4_clock", {"action": "stop"}),
    }
    if operation == "advance":
        if type(days) is not int or not 1 <= days <= 14:
            raise ValueError("Укажите число игровых дней от 1 до 14.")
        name, args = "hoi4_advance", {"days": days, "popups": "stop", "background": True, "max_seconds": 90}
    elif operation == "line":
        if not isinstance(equipment, str) or not equipment.strip() or len(equipment.strip()) > 120:
            raise ValueError("Укажите ID или имя снаряжения.")
        if type(factories) is not int or not 1 <= factories <= 5:
            raise ValueError("Укажите от 1 до 5 военных заводов.")
        name, args = "hoi4_production", {"action": "add", "equipment": equipment.strip(), "factories": factories}
    elif operation in ("start-research", "start-focus"):
        if not isinstance(target, str) or not target.strip() or len(target.strip()) > 120:
            raise ValueError("Укажите ID или точное имя в игре.")
        if operation == "start-research":
            name, args = "hoi4_research", {"action": "start", "tech": target.strip(), "replace": False}
        else:
            name, args = "hoi4_focus", {"action": "select", "focus": target.strip(), "if_idle": True, "replace": False}
    elif operation in actions:
        name, args = actions[operation]
    else:
        raise ValueError("Неизвестная операция кампании.")
    # This route receives explicit UI operations. Read-only voice requests
    # use the same fixed argument mapping below.
    return _call(config, name, args, confirmed=True)
