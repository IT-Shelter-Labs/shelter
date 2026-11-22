"""Локальный мобильный пульт Jarvis без облака и отдельного приложения.

Телефон в той же сети открывает страницу пульта, вводит одноразовый код из
окна Джарвиса и получает свой ключ (companion_devices.py). Дальше: сценарии
кнопками (по устойчивому ID), просьбы текстом, статус, реальный итог задачи
и остановка. Повтор запроса с тем же request_id не выполняет действие второй
раз. Порт не предназначен для интернета — для доступа извне нужен VPN.
"""

from shelter_core.paths import ROOT_DIR

import json
import os
import secrets
import threading
import time
from shelter_core import assistant_store as store
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from shelter_core import companion_devices as devices
from shelter_core.audio import LISTENING, SPEAKING, THINKING


ROOT = ROOT_DIR
TOKEN_PATH = os.path.join(ROOT, "secrets", "companion_token.txt")
PROTOCOL = 2

PAGE = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport"
content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Джарвис — пульт</title><style>
:root{color-scheme:dark;--bg:#05090f;--panel:#0d1823;--line:#1f3a4a;--accent:#37b3d8;--text:#e3f3fa;--dim:#7d98a6;--ok:#4fe39a;--warn:#ffb648;--bad:#ff6b6b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px system-ui,sans-serif;min-height:100vh;padding:18px}
main{max-width:640px;margin:auto}.brand{letter-spacing:.3em;font-weight:800;color:var(--accent);font-size:13px}
.status{display:flex;align-items:center;gap:8px;margin:10px 0 16px;font-weight:600}.dot{width:9px;height:9px;border-radius:50%;background:var(--dim)}
.on .dot{background:var(--ok)}.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:16px;margin:12px 0}
h2{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--dim);margin:0 0 10px}
button{width:100%;text-align:left;border:1px solid var(--line);background:#132533;color:var(--text);border-radius:12px;padding:14px;margin:5px 0;font:inherit;font-weight:600}
button.primary{background:var(--accent);color:#031119;border:none;text-align:center}button.stop{background:var(--bad);color:#fff;border:none;text-align:center}
button:disabled{opacity:.5}input,textarea{width:100%;border:1px solid var(--line);background:#08131c;color:var(--text);padding:13px;border-radius:10px;margin-bottom:8px;font:inherit}
.hidden{display:none}.note{font-size:13px;color:var(--dim);line-height:1.45}.task{padding:8px 0;border-bottom:1px solid var(--line);font-size:14px}
.task:last-child{border:none}.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}.msg{white-space:pre-wrap;line-height:1.5;font-size:14px}
</style></head>
<body><main><div class="brand">J.A.R.V.I.S</div><div id="status" class="status"><span class="dot"></span><span id="statusText">Подключаюсь…</span></div>
<section id="pair" class="card hidden"><h2>Подключить телефон</h2>
<p class="note">В окне Джарвиса: Подключения → Телефон → «Получить код». Код действует 5 минут.</p>
<input id="code" inputmode="numeric" maxlength="6" placeholder="Код из 6 цифр"><input id="name" placeholder="Название устройства, например «Мой телефон»">
<button class="primary" onclick="pair()">Подключить</button><p id="pairError" class="note bad"></p></section>
<section id="ui" class="hidden">
<div class="card"><h2>Сценарии</h2><div id="scenarios"></div><p class="note" id="noScenarios"></p></div>
<div class="card"><h2>Попросить</h2><textarea id="question" maxlength="16000" rows="3" placeholder="Что нужно сделать?"></textarea>
<button class="primary" onclick="ask()">Передать Джарвису</button><button class="stop" onclick="stopAll()">Остановить всё</button>
<p class="note">Выполняет ваш компьютер — он должен быть включён и в той же сети. Диктовать можно микрофоном клавиатуры телефона.</p></div>
<div class="card"><h2>Итоги</h2><div id="tasks" class="note">Пока пусто</div></div>
<div class="card"><h2>Разговор</h2><div id="answers" class="msg note"></div></div>
<button onclick="forget()">Отключить этот телефон</button></section>
</main><script>
let token=localStorage.jarvisDevice||"";let timer;
const $=s=>document.querySelector(s);
const rid=()=>(crypto.randomUUID?crypto.randomUUID():Date.now()+"-"+Math.random());
async function api(path,options={}){options.headers={...(options.headers||{}),"Content-Type":"application/json",...(token?{Authorization:"Bearer "+token}:{})};
let r=await fetch(path,options);let d=await r.json().catch(()=>({}));if(r.status===401){showPair();throw Error("Нужно подключить телефон заново")}if(!r.ok)throw Error(d.error||r.statusText);return d}
function showPair(){$("#pair").classList.remove("hidden");$("#ui").classList.add("hidden");setStatus("Не подключён",false)}
function setStatus(t,on){$("#statusText").textContent=t;$("#status").classList.toggle("on",!!on)}
async function pair(){try{const d=await api("/api/pair",{method:"POST",body:JSON.stringify({code:$("#code").value.trim(),name:$("#name").value.trim()||"Телефон"})});
token=d.token;localStorage.jarvisDevice=token;$("#pair").classList.add("hidden");start()}catch(e){$("#pairError").textContent=e.message}}
function forget(){localStorage.removeItem("jarvisDevice");token="";showPair()}
const labels={running:"выполняется",done:"готово",failed:"не выполнено",queued:"в очереди",interrupted:"прервано",cancelled:"остановлено",partial:"готово с ошибками",skipped:"не запущено: условие"};
function render(s){setStatus(s.speaking?"Говорит":s.thinking?"Думает":s.listening?"Слушает":"В сети",true);
const list=$("#scenarios");list.replaceChildren();(s.scenarios||[]).forEach(x=>{const b=document.createElement("button");b.textContent=x.name;
b.onclick=async()=>{if(x.confirm&&!confirm(x.confirm))return;b.disabled=true;try{await api("/api/run",{method:"POST",body:JSON.stringify({scenario:x.id,request_id:rid(),confirmed:!!x.confirm})})}catch(e){alert(e.message)}finally{setTimeout(()=>b.disabled=false,1500)}};list.append(b)});
$("#noScenarios").textContent=(s.scenarios||[]).length?"":"Сценариев с запуском кнопкой пока нет — создайте их в окне Джарвиса.";
const t=[...(s.runs||[]).map(r=>`<div class="task">${esc(r.name)} · <span class="${r.status==="done"?"ok":r.status==="failed"?"bad":"warn"}">${labels[r.status]||r.status}</span>${r.error?`<br><span class="bad">${esc(r.error)}</span>`:""}</div>`),
...(s.tasks||[]).map(r=>`<div class="task">${esc(r.question.slice(0,90))} · <span class="${r.status==="done"?"ok":r.status==="failed"?"bad":"warn"}">${labels[r.status]||r.status}</span>${r.error?`<br><span class="bad">${esc(r.error)}</span>`:""}</div>`)];
$("#tasks").innerHTML=t.join("")||"Пока пусто";$("#answers").textContent=(s.messages||[]).map(m=>(m.role==="user"?"Вы: ":"Джарвис: ")+m.content).join("\n\n")}
function esc(t){return String(t).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
async function refresh(){try{render(await api("/api/state"))}catch(e){if(token)setStatus("Нет связи с компьютером",false)}}
async function ask(){const text=$("#question").value.trim();if(!text)return;try{await api("/api/ask",{method:"POST",body:JSON.stringify({text,request_id:rid()})});$("#question").value="";refresh()}catch(e){alert(e.message)}}
async function stopAll(){try{await api("/api/interrupt",{method:"POST",body:JSON.stringify({request_id:rid()})})}catch(e){alert(e.message)}}
function start(){$("#ui").classList.remove("hidden");refresh();clearInterval(timer);timer=setInterval(refresh,3000)}
if(token)start();else showPair();
</script></body></html>"""


def _token():
    configured = os.environ.get("JARVIS_COMPANION_TOKEN")
    if configured:
        return configured
    try:
        with open(TOKEN_PATH, encoding="utf-8") as file:
            value = file.read().strip()
            if value:
                return value
    except OSError:
        pass
    value = secrets.token_urlsafe(24)
    os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
    with open(TOKEN_PATH, "w", encoding="utf-8") as file:
        file.write(value)
    return value


def button_scenarios():
    """Сценарии с запуском кнопкой — по устойчивому ID, а не по номеру в списке."""
    try:
        from shelter_core import scenarios
        return [{"id": s["id"], "name": s["name"], "confirm": s.get("confirm") or ""} for s in scenarios.load()
                if s.get("enabled", True) and any(t.get("type") == "button" for t in s.get("triggers") or [])]
    except Exception:
        return []


def recent_runs():
    try:
        from shelter_core import scenarios
        return [{"name": r["name"], "status": r["status"], "error": r["error"]} for r in scenarios.recent()[:4]]
    except Exception:
        return []


class CompanionServer:
    FAILURE_LIMIT = 10
    FAILURE_WINDOW = 60.0

    def __init__(self, config, events):
        self.config = config
        self.events = events
        self.server = None
        self.thread = None
        self.token = ""
        self._failures = {}
        self._failures_lock = threading.Lock()

    def note_failure(self, address):
        """Притормозить перебор ключа и кода: в локальной сети он вполне реален."""
        now = time.monotonic()
        with self._failures_lock:
            recent = [t for t in self._failures.get(address, []) if now - t < self.FAILURE_WINDOW]
            recent.append(now)
            self._failures[address] = recent
            count = len(recent)
        if count > self.FAILURE_LIMIT:
            print(f">> COMPANION  //  подбор ключа с {address}, пауза")
            time.sleep(min(5.0, 0.5 * (count - self.FAILURE_LIMIT)))

    @property
    def enabled(self):
        return bool((self.config.get("companion") or {}).get("enabled"))

    def start(self):
        if not self.enabled:
            return
        cfg = self.config.get("companion") or {}
        host = cfg.get("host", "127.0.0.1")
        port = int(cfg.get("port", 8765))
        self.token = _token()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(20)

            def log_message(self, _format, *_args):
                return

            def _send(self, status, data, content_type="application/json; charset=utf-8"):
                if isinstance(data, (dict, list)):
                    data = json.dumps(data, ensure_ascii=False)
                body = data if isinstance(data, bytes) else data.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _device(self):
                # Только заголовок: ключ в адресе оседает в истории браузера и логах.
                supplied = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
                if not supplied:
                    return None
                device = devices.verify(supplied, legacy=owner.token)
                if device is None:
                    owner.note_failure(self.client_address[0])
                return device

            def do_GET(self):
                path = urlparse(self.path).path
                if path == "/":
                    self._send(200, PAGE, "text/html; charset=utf-8")
                    return
                if path not in ("/api/state", "/api/capabilities", "/api/audio"):
                    self._send(404, {"error": "not found"})
                    return
                device = self._device()
                if device is None:
                    self._send(401, {"error": "invalid token"})
                    return
                if path == "/api/audio":
                    from shelter_core import remote_audio
                    query = parse_qs(urlparse(self.path).query)
                    try:
                        result = remote_audio.read(device["id"], query.get("request", [""])[0], query.get("after", ["0"])[0])
                        self._send(200, result)
                    except ValueError as error:
                        self._send(404, {"error": str(error)})
                    return
                if path == "/api/capabilities":
                    self._send(200, {
                        "protocol_version": PROTOCOL, "mode": "paired_pc", "inference": "host",
                        "features": ["pairing", "text_requests", "conversation_state", "scenarios", "task_results",
                                     "interrupt", "idempotent_requests", "profiles", "audio_stream"],
                        "limits": {"request_characters": 16000},
                        "authentication": "bearer", "state_endpoint": "/api/state",
                        "request_endpoint": "/api/ask", "run_endpoint": "/api/run", "cancel_endpoint": "/api/interrupt",
                        "direct_cloud_credentials": False, "device_tools": "host_policy",
                    })
                    return
                commands = [", ".join(item.get("keywords") or ["Без названия"])
                            for item in owner.config.get("commands") or []]
                profiles = [{"name": name, "label": profile.get("label", name)}
                            for name, profile in (owner.config.get("profiles") or {}).items()]
                self._send(200, {
                    "commands": commands, "profiles": profiles, "scenarios": button_scenarios(), "runs": recent_runs(),
                    "listening": LISTENING.is_set(), "speaking": SPEAKING.is_set(), "thinking": THINKING.is_set(),
                    **store.mobile_state(),
                })

            def _json(self):
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536:
                    raise ValueError("неверный размер запроса")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("нужен JSON-объект")
                return data

            def do_POST(self):
                path = urlparse(self.path).path
                if path == "/api/pair":
                    try:
                        data = self._json()
                        device_id, token = devices.pair(data.get("code"), data.get("name"))
                    except (ValueError, TypeError, json.JSONDecodeError) as error:
                        owner.note_failure(self.client_address[0])
                        self._send(400, {"error": str(error)})
                        return
                    print(f">> COMPANION  //  подключено устройство {device_id}")
                    self._send(200, {"token": token, "device": device_id})
                    return
                if path not in ("/api/run", "/api/ask", "/api/interrupt"):
                    self._send(404, {"error": "not found"})
                    return
                device = self._device()
                if device is None:
                    self._send(401, {"error": "invalid token"})
                    return
                try:
                    data = self._json()
                    result, repeated = devices.remember(device["id"], data.get("request_id"), lambda: self._perform(path, data, device["id"]))
                except (ValueError, TypeError, IndexError, KeyError, json.JSONDecodeError) as error:
                    self._send(400, {"error": str(error) or "invalid command"})
                    return
                self._send(202, {**result, "repeated": repeated})

            def _perform(self, path, data, device_id=""):
                if path == "/api/ask":
                    text = data.get("text", "")
                    if not isinstance(text, str) or not text.strip() or len(text) > 16000:
                        raise ValueError("нужен текст до 16000 знаков")
                    request = {"text": text.strip(), "session_id": store.session_for()}
                    if data.get("audio"):
                        from shelter_core import remote_audio
                        audio_id = data.get("request_id")
                        remote_audio.open_stream(device_id, audio_id)
                        request["remote"] = {"device": device_id, "request": audio_id}
                    owner.events.put(("typed", request))
                elif path == "/api/interrupt":
                    owner.events.put(("interrupt", None))
                elif "scenario" in data:
                    allowed = {s["id"]: s for s in button_scenarios()}
                    item = allowed.get(str(data["scenario"]))
                    if item is None:
                        raise ValueError("сценарий не найден или не запускается кнопкой")
                    run = "run_" + secrets.token_hex(4)
                    owner.events.put(("scenario", {"id": item["id"], "source": "телефон", "run": run,
                                                   "confirmed": bool(data.get("confirmed")), "speak_errors": False}))
                    return {"accepted": True, "run": run}
                elif "command" in data:
                    commands = owner.config.get("commands") or []
                    index = int(data["command"])
                    if index < 0 or index >= len(commands):
                        raise ValueError("команда вне диапазона")
                    owner.events.put(("command", commands[index]))
                elif "profile" in data and data["profile"] in (owner.config.get("profiles") or {}):
                    owner.events.put(("command", {"actions": [{"type": "profile", "name": data["profile"]}]}))
                else:
                    raise ValueError("неизвестная команда")
                return {"accepted": True}

        self.server = ThreadingHTTPServer((host, port), Handler)
        tls = cfg.get("tls") or {}
        if tls.get("cert") or tls.get("key"):
            import ssl
            try:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                context.load_cert_chain(tls.get("cert"), tls.get("key"))
                self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
            except Exception:
                self.server.server_close()
                self.server = None
                raise
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       name="companion", daemon=True)
        self.thread.start()
        shown_host = "localhost" if host in ("127.0.0.1", "localhost") else host
        actual_port = self.server.server_address[1]
        scheme = "https" if tls.get("cert") else "http"
        print(f">> COMPANION  //  {scheme}://{shown_host}:{actual_port}  //  подключение телефона — код в окне Джарвиса")

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.thread is not None:
            self.thread.join(timeout=1.0)
            self.thread = None
