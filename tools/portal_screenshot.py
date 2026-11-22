"""System Python + python3-gi. The compositor asks the user before capture."""
import secrets
import sys
from urllib.parse import unquote, urlparse

from gi.repository import Gio, GLib

bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
token = "jarvis_" + secrets.token_hex(8)
sender = bus.get_unique_name().lstrip(":").replace(".", "_")
request = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
loop = GLib.MainLoop()
result = {}


def response(_bus, _sender, _path, _interface, _signal, params):
    code, values = params.unpack()
    result.update(code=code, **values)
    loop.quit()


subscription = bus.signal_subscribe("org.freedesktop.portal.Desktop", "org.freedesktop.portal.Request", "Response", request, None, Gio.DBusSignalFlags.NONE, response)
try:
    bus.call_sync("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop", "org.freedesktop.portal.Screenshot", "Screenshot",
                  GLib.Variant("(sa{sv})", ("", {"handle_token": GLib.Variant("s", token), "interactive": GLib.Variant("b", True)})),
                  GLib.VariantType.new("(o)"), Gio.DBusCallFlags.NONE, 5000, None)
    timeout = GLib.timeout_add_seconds(28, lambda: (loop.quit(), False)[1])
    if not result:
        loop.run()
    GLib.source_remove(timeout)
    uri = urlparse(result.get("uri", ""))
    if result.get("code") != 0 or uri.scheme != "file" or uri.netloc not in ("", "localhost"):
        bus.call_sync("org.freedesktop.portal.Desktop", request, "org.freedesktop.portal.Request", "Close", None, None, Gio.DBusCallFlags.NONE, 1000, None) if not result else None
        raise RuntimeError("Снимок отменён или системный портал не ответил")
    print(unquote(uri.path))
finally:
    bus.signal_unsubscribe(subscription)
