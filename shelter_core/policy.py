"""Execution permissions and shared, expiring confirmations for every input."""
import copy
import re
import threading
import time

ALIASES = {"remember": "memory", "remember_project": "memory", "forget": "memory", "nowplaying": "media",
           "remind": "timer", "timers": "timer", "cancel": "timer", "briefing": "timer",
           "clipboard": "pc", "type": "pc", "textops": "pc", "desktop": "pc", "browser_episode": "media",
           "discord": "pc"}
TOOLS = {"app", "pc", "weather", "search", "timer", "memory", "media", "screen", "obs", "home", "mcp"}


def allowed(config, name):
    if name == "avatar":
        return (config.get("ui") or {}).get("mode") == "avatar"
    if name in ("offer", "display", "persona"):
        return True               # само предложение ничего не делает; действие проверяется при «да»
    name = ALIASES.get(name, name)
    wanted = (config.get("llm") or {}).get("tools", list(TOOLS))
    return isinstance(wanted, (list, tuple)) and name in wanted


def require(config, name):
    if not allowed(config, name):
        raise PermissionError("Эта возможность выключена в настройках.")


class Confirmations:
    def __init__(self):
        self._lock = threading.Lock()
        self._pending = None
        self._deadline = 0

    def request(self, command, timeout=20):
        with self._lock:
            self._pending = copy.deepcopy(command)
            self._deadline = time.monotonic() + timeout

    def active(self):
        with self._lock:
            return self._pending is not None and time.monotonic() < self._deadline

    def expire(self):
        with self._lock:
            if self._pending is not None and time.monotonic() >= self._deadline:
                self._pending = None
                return True
        return False

    def clear(self):
        with self._lock:
            self._pending = None

    def resolve(self, text, config):
        # Whole phrases only; a negation always wins over an incidental "да".
        norm = lambda s: re.sub(r"[^\w\s]", "", str(s).lower()).strip()
        phrase = norm(text)
        cfg = config.get("confirm") or {}
        no = {norm(w) for w in cfg.get("reject", ["нет", "отмена", "не надо"])}
        yes = {norm(w) for w in cfg.get("accept", ["да", "подтверждаю"])}
        with self._lock:
            if self._pending is None or time.monotonic() >= self._deadline:
                return None, None
            words = phrase.split()
            offer = bool(self._pending.get("offer"))
            if phrase in no or phrase.startswith(("нет ", "не надо")):
                self._pending = None
                if offer and len(words) > 2:
                    return None, None     # «нет, лучше включи ютуб» — это уже новая просьба
                return "cancelled", None
            # «Да, давай», «ага, включай» — короткое согласие без отрицания.
            if phrase in yes or (words and words[0] in yes and len(words) <= 4
                                 and not any(w in no or w.startswith("не") for w in words[1:])):
                command, self._pending = self._pending, None
                command.pop("confirm", None)
                # Internal marker is created only by this confirmation path.
                command["_confirmed"] = True
                return "command", command
            if offer:
                self._pending = None      # заговорили о другом — предложение снято
        return None, None


class _CurrentConfirmations:
    def __init__(self):
        self.desktop = Confirmations()

    def __getattr__(self, name):
        from shelter_core import tasks
        token = tasks.current()
        delivery = getattr(tasks._root(token), "delivery", None) if token else None
        return getattr(delivery["confirmations"] if delivery else self.desktop, name)


CONFIRMATIONS = _CurrentConfirmations()
