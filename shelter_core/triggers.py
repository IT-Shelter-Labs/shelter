"""События и расписания для сценариев — без нейросети и без постоянных запросов к модели.

Один поток раз в POLL секунд сравнивает снимок системы с прошлым: процессы,
звуковые устройства, питание, сеть, простой. Изменение подтверждается вторым
опросом подряд (подавление дребезга: наушники «моргнули» при подключении — это
одно событие). Каждое правило запускается не чаще cooldown; время последнего
запуска хранится в data/triggers.json, поэтому после перезапуска нет ни дублей,
ни повторного срабатывания расписания за ту же минуту.

Запуск сценария идёт в главную очередь событий тем же путём, что и голос:
("scenario", {id, source}). Цепочка «сценарий открыл программу → событие
запустило другой сценарий → …» обрывается после MAX_CHAIN звеньев.
"""

from shelter_core.paths import ROOT_DIR

import datetime
import json
import os
import queue
import tempfile
import threading
import time

from shelter_core import scenarios

ROOT = ROOT_DIR
STATE = os.path.join(ROOT, "data", "triggers.json")
POLL = 3.0
MAX_CHAIN = 3
CHAIN_WINDOW = 15.0
MISSED_GRACE = 6 * 3600

_engine = None
_lock = threading.Lock()

EVENT_TYPES = {"app_started", "app_closed", "audio_added", "audio_removed", "power_plugged", "power_unplugged",
               "battery_low", "online", "offline", "wifi", "idle", "returned"}


def _audio_devices():
    try:
        import soundcard
        names = {s.name for s in soundcard.all_speakers()} | {m.name for m in soundcard.all_microphones()}
        return names
    except Exception:
        try:
            import sounddevice
            return {d["name"] for d in sounddevice.query_devices() if d["max_input_channels"] or d["max_output_channels"]}
        except Exception:
            return None


def _idle_seconds():
    if os.name != "nt":
        return None
    import ctypes

    class LastInput(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    info = LastInput()
    info.cbSize = ctypes.sizeof(LastInput)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0


def _wifi():
    if os.name != "nt":
        return None
    import subprocess
    try:
        out = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, timeout=4,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.decode("cp866", "ignore")
    except Exception:
        return None
    for line in out.splitlines():
        key, _, value = line.partition(":")
        if key.strip().upper() == "SSID":
            return value.strip()
    return ""


class Engine:
    def __init__(self, events, config):
        self.events = events
        self.config = config
        self.rules = []
        self.state = self._load_state()
        self.snapshot = {}
        self.pending = {}            # событие ждёт подтверждения вторым опросом
        self.chain = []              # времена автозапусков — защита от цепочек
        self.stop_event = threading.Event()
        self.thread = None
        self.log = []                # последние срабатывания для окна
        self.plugin_edges = {}
        self.plugin_errors = set()
        self.manual = queue.Queue(maxsize=256)
        from shelter_core.scenario_hotkeys import Hotkeys
        self.hotkeys = Hotkeys(self._hotkey)
        self.reload()

    # ------------------------------------------------------------ правила

    def reload(self):
        try:
            items = scenarios.load(self.config)
        except Exception as error:
            print(f"[triggers] сценарии не прочитаны: {error}")
            items = []
        rules = []
        for item in items:
            if not item.get("enabled", True):
                continue
            for trigger in item.get("triggers") or []:
                kind = trigger.get("type")
                if kind in EVENT_TYPES or kind in ("schedule", "assistant_started", "plugin_event", "hotkey"):
                    spec = scenarios.TRIGGERS.get(kind, {})
                    if scenarios.PLATFORM in spec.get("platforms", [scenarios.PLATFORM]):
                        rules.append((item, trigger))
        with _lock:
            self.rules = rules
        self.hotkeys.update([(item["id"] + ":" + trigger["combo"], trigger["combo"]) for item, trigger in rules if trigger.get("type") == "hotkey"])

    def _hotkey(self, tag, error):
        try: self.manual.put_nowait((tag, error))
        except queue.Full: pass

    def hotkey_step(self):
        while True:
            try: tag, error = self.manual.get_nowait()
            except queue.Empty: return
            with _lock: rules = list(self.rules)
            for item, trigger in rules:
                if trigger.get("type") != "hotkey" or tag != item["id"] + ":" + trigger.get("combo", ""): continue
                if error: self._note(item, "горячая клавиша", error)
                else: self.fire(item, trigger, "горячая клавиша " + trigger["combo"])

    def needs(self, kinds):
        with _lock:
            return any(t.get("type") in kinds for _, t in self.rules)

    # ------------------------------------------------------------ состояние

    def _load_state(self):
        try:
            with open(STATE, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_state(self):
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=os.path.dirname(STATE), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False)
            os.replace(temporary, STATE)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    # --------------------------------------------------------------- запуск

    def fire(self, item, trigger, why):
        now = time.time()
        key = f"{item['id']}:{trigger.get('type')}"
        cooldown = float(item.get("cooldown", 30))
        last = float(self.state.get(key, 0))
        if now - last < cooldown:
            return False
        if item["id"] in scenarios.running():
            return False                        # сам себя не запускает, пока идёт
        self.chain = [t for t in self.chain if now - t < CHAIN_WINDOW]
        if len(self.chain) >= MAX_CHAIN:
            self._note(item, why, "остановлено: слишком много автозапусков подряд")
            return False
        self.chain.append(now)
        self.state[key] = now
        self._save_state()
        self._note(item, why, "запущен")
        self.events.put(("scenario", {"id": item["id"], "source": f"событие: {why}"}))
        return True

    def _note(self, item, why, result):
        self.log.insert(0, {"time": time.time(), "scenario": item["id"], "name": item["name"], "why": why, "result": result})
        del self.log[30:]
        from shelter_core import bus
        bus.publish("trigger", name=item["name"], text=f"{why} — {result}")

    # ---------------------------------------------------------------- опрос

    def measure(self):
        """Снимок системы. Опрашивается только то, что нужно правилам."""
        snap = {}
        if self.needs({"app_started", "app_closed"}):
            snap["apps"] = scenarios._process_names()
        if self.needs({"audio_added", "audio_removed"}):
            devices = _audio_devices()
            if devices is not None:
                snap["audio"] = devices
        if self.needs({"power_plugged", "power_unplugged", "battery_low"}):
            try:
                import psutil
                battery = psutil.sensors_battery()
                if battery is not None:
                    snap["plugged"] = bool(battery.power_plugged)
                    snap["battery"] = float(battery.percent)
            except Exception:
                pass
        if self.needs({"online", "offline"}):
            snap["online"] = scenarios._online(1.0)
        if self.needs({"wifi"}) and int(time.time()) % 15 < POLL:
            snap["wifi"] = _wifi()
        elif "wifi" in self.snapshot:
            snap["wifi"] = self.snapshot["wifi"]
        if self.needs({"idle", "returned"}):
            idle = _idle_seconds()
            if idle is not None:
                snap["idle"] = idle
        return snap

    def changes(self, old, new):
        """Список событий (тип, значение) между двумя снимками."""
        out = []
        if "apps" in old and "apps" in new:
            out += [("app_started", a) for a in new["apps"] - old["apps"]]
            out += [("app_closed", a) for a in old["apps"] - new["apps"]]
        if "audio" in old and "audio" in new:
            out += [("audio_added", a) for a in new["audio"] - old["audio"]]
            out += [("audio_removed", a) for a in old["audio"] - new["audio"]]
        if "plugged" in old and "plugged" in new and old["plugged"] != new["plugged"]:
            out.append(("power_plugged" if new["plugged"] else "power_unplugged", ""))
        if "battery" in new:
            out.append(("battery_level", new["battery"]))
        if "online" in old and "online" in new and old["online"] != new["online"]:
            out.append(("online" if new["online"] else "offline", ""))
        if new.get("wifi") and new.get("wifi") != old.get("wifi"):
            out.append(("wifi", new["wifi"]))
        if "idle" in new:
            out.append(("idle_seconds", new["idle"]))
        return out

    def step(self):
        """Один опрос: сравнить, подтвердить, запустить. Возвращает запущенные id."""
        fired = self._plugin_step()
        new = self.measure()
        old, self.snapshot = self.snapshot, new
        if not old:
            return fired
        confirmed = []
        seen = set()
        for event in self.changes(old, new):
            if event[0] in ("battery_level", "idle_seconds"):
                confirmed.append(event)
                continue
            # Подтверждение вторым опросом подряд.
            seen.add(event)
            if self.pending.get(event) is not None:
                continue
            self.pending[event] = time.monotonic()
        for event, since in list(self.pending.items()):
            kind, value = event
            still = (kind == "app_started" and value in new.get("apps", ()) or
                     kind == "app_closed" and value not in new.get("apps", {value}) or
                     kind == "audio_added" and value in new.get("audio", ()) or
                     kind == "audio_removed" and value not in new.get("audio", {value}) or
                     kind in ("power_plugged", "power_unplugged", "online", "offline", "wifi"))
            if not still:
                del self.pending[event]
                continue
            if event in seen:
                continue                       # только что появилось — ждём следующий опрос
            del self.pending[event]
            confirmed.append(event)
        with _lock:
            rules = list(self.rules)
        for kind, value in confirmed:
            for item, trigger in rules:
                why = self._matches(trigger, kind, value)
                if why and self.fire(item, trigger, why):
                    fired.append(item["id"])
        return fired

    def _plugin_step(self):
        from shelter_core import plugin_extensions
        with _lock:
            rules = [(item, trigger) for item, trigger in self.rules if trigger.get("type") == "plugin_event"]
        fired = []
        for item, trigger in rules:
            key = (item["id"], trigger.get("plugin"), trigger.get("event"))
            try:
                active, event = plugin_extensions.poll(trigger.get("plugin"), trigger.get("event", "default"), self.config)
                self.plugin_errors.discard(key)
                old = self.plugin_edges.get(key)
                self.plugin_edges[key] = (active, event)
                if active and old is not None and old != (active, event):
                    if self.fire(item, trigger, "событие дополнения: " + event):
                        fired.append(item["id"])
            except Exception as error:
                self.plugin_edges[key] = (False, "")
                if key not in self.plugin_errors:
                    self.plugin_errors.add(key)
                    self._note(item, str(error)[:200], "failed")
        return fired

    def _matches(self, trigger, kind, value):
        want = trigger.get("type")
        if want in ("app_started", "app_closed") and kind == want:
            if scenarios._app_matches(trigger.get("app"), {value}):
                return f"{'открылась' if want == 'app_started' else 'закрылась'} {value}"
        if want in ("audio_added", "audio_removed") and kind == want:
            name = str(trigger.get("name") or "").lower()
            if not name or name in str(value).lower():
                return f"{'подключено' if want == 'audio_added' else 'отключено'} {value}"
        if want in ("power_plugged", "power_unplugged", "online", "offline") and kind == want:
            return scenarios.TRIGGERS[want]["label"].lower()
        if want == "wifi" and kind == "wifi" and str(trigger.get("ssid", "")).strip().lower() == str(value).lower():
            return f"Wi-Fi {value}"
        if want == "battery_low" and kind == "battery_level":
            limit = float(trigger.get("percent", 20))
            key = f"battery_armed:{limit}"
            if value > limit + 3:
                self.state[key] = True          # снова взвести, когда зарядили
            elif value <= limit and self.state.get(key, True):
                self.state[key] = False
                return f"заряд {round(value)}%"
        if want in ("idle", "returned") and kind == "idle_seconds":
            limit = float(trigger.get("minutes", 10)) * 60 if want == "idle" else 0
            if want == "idle":
                key = f"idle_armed:{limit}"
                if value < limit:
                    self.state[key] = True
                elif self.state.get(key, True):
                    self.state[key] = False
                    return f"не трогали {round(value / 60)} мин"
            else:
                was_idle = self.state.get("was_idle", False)
                if value > 300:
                    self.state["was_idle"] = True
                elif was_idle and value < POLL * 2:
                    self.state["was_idle"] = False
                    return "вернулись к компьютеру"
        return None

    # --------------------------------------------------------- расписание

    def schedule_step(self, now=None):
        now = now or datetime.datetime.now()
        fired = []
        with _lock:
            rules = [(i, t) for i, t in self.rules if t.get("type") == "schedule"]
        for item, trigger in rules:
            hour, minute = (int(x) for x in str(trigger.get("time", "09:00")).split(":"))
            days = trigger.get("days") or list(range(7))
            due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if due > now:
                due -= datetime.timedelta(days=1)
            while due.weekday() not in days and now - due < datetime.timedelta(days=8):
                due -= datetime.timedelta(days=1)
            key = f"{item['id']}:schedule:{trigger.get('time')}"
            last = float(self.state.get(key + ":slot", 0))
            slot = due.timestamp()
            if slot <= last:
                continue
            late = now.timestamp() - slot
            if late > 90:
                # Пропущенный запуск: компьютер был выключен или ядро не работало.
                if trigger.get("missed") != "run" or late > MISSED_GRACE or not last:
                    self.state[key + ":slot"] = slot
                    self._save_state()
                    continue
            self.state[key + ":slot"] = slot
            self.state.pop(f"{item['id']}:schedule", None)   # слот уже защищает от повтора
            if self.fire(item, trigger, f"расписание {trigger.get('time')}" + (" (пропущенный запуск)" if late > 90 else "")):
                fired.append(item["id"])
        return fired

    # ------------------------------------------------------------- поток

    def start(self):
        if self.thread and self.thread.is_alive():
            return                              # повторный старт не плодит потоки
        self.stop_event.clear()
        self.hotkeys.start()
        self.thread = threading.Thread(target=self._loop, name="triggers", daemon=True)
        self.thread.start()
        with _lock:
            boot = [(i, t) for i, t in self.rules if t.get("type") == "assistant_started"]
        for item, trigger in boot:
            self.fire(item, trigger, "Джарвис запустился")

    def _loop(self):
        next_poll = time.monotonic() + POLL
        while not self.stop_event.wait(.1):
            try:
                self.hotkey_step()
                if time.monotonic() < next_poll: continue
                next_poll = time.monotonic() + POLL
                self.step()
                self.schedule_step()
            except Exception as error:
                print(f"[triggers] опрос упал: {error}")

    def stop(self):
        self.stop_event.set()
        self.hotkeys.stop()


def start(events, config):
    """Один движок на процесс: повторный вызов только обновляет правила."""
    global _engine
    if _engine is None:
        _engine = Engine(events, config)
    else:
        _engine.events, _engine.config = events, config
        _engine.reload()
    _engine.start()
    return _engine


def reload():
    if _engine is not None:
        _engine.reload()


def stop():
    if _engine is not None:
        _engine.stop()


def recent():
    return list(_engine.log) if _engine is not None else []
