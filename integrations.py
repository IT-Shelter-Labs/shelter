"""Opt-in MCP clients: stdio and Streamable HTTP, no third-party dependency.

Only explicitly enabled tools are exposed. Server annotations never grant
permission; write access is confirmed unless the user explicitly marks a tool
as trusted in the integration settings.
"""
import hashlib
import json
import os
import queue
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request

import tasks
from policy import CONFIRMATIONS

VERSION = "2025-11-25"
_clients = {}
_lock = threading.Lock()


class Client:
    def __init__(self, config):
        self.config = config
        self.process = None
        self.session = ""
        self.protocol = VERSION
        self.number = 0
        self.lock = threading.RLock()
        self.replies = queue.Queue(maxsize=256)
        self.ready = False
        self.tools = None

    def _start(self):
        if self.config.get("transport", "stdio") != "stdio":
            return
        command = self.config.get("command")
        args = self.config.get("args", [])
        if not isinstance(command, str) or not command or not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise ValueError("Задайте путь программы MCP и список аргументов")
        env = dict(os.environ)
        for key, variable in (self.config.get("env_vars") or {}).items():
            env[key] = os.environ.get(variable, "")
        self.process = subprocess.Popen([command, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

        def read():
            try:
                while True:
                    line = self.process.stdout.readline(1_000_001)
                    if not line:
                        break
                    if len(line) > 1_000_000:
                        raise ValueError("Слишком большой ответ MCP")
                    message = json.loads(line)
                    if "method" in message:
                        if "id" in message:
                            self._write({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "Client-side requests are not supported"}})
                    else:
                        self.replies.put_nowait(message)
            except Exception as error:
                try:
                    self.replies.put_nowait(error)
                except queue.Full:
                    pass
            finally:
                try:
                    self.replies.put_nowait(EOFError("MCP завершил соединение"))
                except queue.Full:
                    pass
        threading.Thread(target=read, name="mcp-reader", daemon=True).start()

    def _write(self, message):
        self.process.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
        self.process.stdin.flush()

    def _http(self, message, timeout):
        url = self.config.get("url", "")
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")):
            raise ValueError("Удалённый MCP требует HTTPS; HTTP разрешён для localhost")
        if parsed.username or parsed.password:
            raise ValueError("Храните ключ в переменной окружения, а не в адресе")
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": self.protocol}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        token = os.environ.get(self.config.get("token_env", ""), "")
        if token:
            headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(url, data=json.dumps(message).encode(), headers=headers)
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                raise ValueError("Измените адрес MCP: перенаправления отключены")
        import netfix
        with urllib.request.build_opener(netfix._LocalBypass(), NoRedirect).open(request, timeout=timeout) as response:
            self.session = response.headers.get("Mcp-Session-Id", self.session)
            token = tasks.current()
            if token:
                token.register(response.close)
            if "id" not in message or response.status == 202:
                return {}
            if "text/event-stream" not in response.headers.get("Content-Type", ""):
                return json.loads(response.read(1_000_001))
            chunks, size = [], 0
            for line in response:
                tasks.check()
                size += len(line)
                if size > 1_000_000:
                    raise ValueError("Слишком большой ответ MCP")
                line = line.decode("utf-8").rstrip("\r\n")
                if line.startswith("data:"):
                    chunks.append(line[5:].lstrip())
                elif not line and chunks:
                    reply = json.loads("\n".join(chunks))
                    chunks.clear()
                    if reply.get("id") == message["id"]:
                        return reply
            raise RuntimeError("MCP не вернул результат запроса")

    def rpc(self, method, params=None, notification=False):
        with self.lock:
            self.number += 1
            message = {"jsonrpc": "2.0", "method": method, "params": params or {}}
            if not notification:
                message["id"] = self.number
            timeout = min(60, max(1, float(self.config.get("timeout", 15))))
            if self.config.get("transport", "stdio") == "http":
                reply = tasks.run(lambda: self._http(message, timeout))
            else:
                if not self.process:
                    self._start()
                self._write(message)
                if notification:
                    return {}
                deadline = time.monotonic() + timeout
                while True:
                    tasks.check()
                    left = deadline - time.monotonic()
                    if left <= 0:
                        self.close()
                        raise TimeoutError("MCP не ответил вовремя; действие не повторялось")
                    try:
                        reply = self.replies.get(timeout=min(0.1, left))
                    except queue.Empty:
                        continue
                    if isinstance(reply, Exception):
                        raise reply
                    if reply.get("id") == message["id"]:
                        break
            if reply.get("error"):
                raise RuntimeError(str(reply["error"].get("message", "Ошибка MCP")))
            return reply.get("result", {})

    def discover(self):
        with self.lock:
            if not self.ready:
                response = self.rpc("initialize", {"protocolVersion": VERSION, "capabilities": {}, "clientInfo": {"name": "jarvis", "version": "2.0.0"}})
                self.protocol = response.get("protocolVersion", VERSION)
                if self.protocol not in (VERSION, "2025-06-18", "2025-03-26"):
                    raise ValueError("Неподдерживаемая версия MCP: " + self.protocol)
                self.rpc("notifications/initialized", notification=True)
                self.ready = True
            if self.tools is None:
                found, cursor = [], None
                for _ in range(8):
                    page = self.rpc("tools/list", {"cursor": cursor} if cursor else {})
                    found.extend(page.get("tools", []))
                    cursor = page.get("nextCursor")
                    if not cursor:
                        break
                self.tools = found[:256]
            return self.tools

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
        if self.process:
            self.process.stdin.close()
            self.process.stdout.close()
        self.ready = False


def servers(config):
    cfg = config.get("integrations") or {}
    return cfg.get("servers", []) if cfg.get("enabled") else []


def client(config, id):
    cfg = next((s for s in servers(config) if s.get("id") == id and s.get("enabled")), None)
    if cfg is None:
        raise ValueError("Интеграция выключена")
    fingerprint = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()
    with _lock:
        if fingerprint not in _clients:
            _clients[fingerprint] = Client(cfg)
        return _clients[fingerprint]


def probe(config, id):
    found = client(config, id).discover()
    return {"ok": True, "tools": [{"name": t["name"], "description": str(t.get("description", ""))[:1000]} for t in found]}


def definitions(config):
    from agent_runtime import function
    result = []
    for server in servers(config):
        if not server.get("enabled") or not server.get("tools"):
            continue
        try:
            found = client(config, server["id"]).discover()
        except Exception as error:
            import bus
            bus.publish("error", text=f"Интеграция {server.get('id')}: {error}")
            continue
        for item in found:
            if item["name"] not in server["tools"]:
                continue
            name = "mcp_" + re.sub(r"[^a-zA-Z0-9_]", "_", server["id"])[:12] + "_" + hashlib.sha256((server["id"] + "\0" + item["name"]).encode()).hexdigest()[:12]
            spec = function(name, str(item.get("description", item["name"]))[:800], {})
            spec["function"]["parameters"] = item.get("inputSchema", {"type": "object", "properties": {}})
            result.append((spec, {"server": server["id"], "tool": item["name"]}))
    return result[:24]


def execute(config, argument, confirmed=False):
    from agent_runtime import validate
    request = json.loads(argument)
    server = next((s for s in servers(config) if s.get("id") == request.get("server") and s.get("enabled")), None)
    if not server or request.get("tool") not in server.get("tools", []):
        return "fail", "Инструмент интеграции выключен"
    connection = client(config, server["id"])
    spec = next((t for t in connection.discover() if t["name"] == request["tool"]), None)
    if not spec:
        return "fail", "Инструмент больше не доступен"
    validate(request.get("arguments"), spec.get("inputSchema", {}))
    if not confirmed and request["tool"] not in server.get("trusted_tools", []):
        CONFIRMATIONS.request({"actions": [{"type": "tool", "name": "mcp", "arg": argument, "confirmed": True}]})
        return "say", f"Разрешить {server['id']} выполнить {request['tool']} с параметрами {json.dumps(request['arguments'], ensure_ascii=False)}? Скажите «да» или «нет»."
    result = connection.rpc("tools/call", {"name": request["tool"], "arguments": request["arguments"]})
    text = "\n".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")
    return ("fail" if result.get("isError") else "data"), text[:12000] or "Инструмент вернул результат без текста"


def stop():
    with _lock:
        clients = list(_clients.values())
        _clients.clear()
    for connection in clients:
        connection.close()
