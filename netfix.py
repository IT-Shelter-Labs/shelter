"""Локальные адреса — мимо системного прокси.

VPN-клиенты часто включают в Windows системный прокси без исключений для
127.0.0.1. Тогда Python шлёт через него даже запросы к Ollama и к серверу
голоса на этом же компьютере, прокси отвечает 502 — и кажется, что «модель не
отвечает», а голос переключается на запасной. Здесь всё локальное и домашняя
сеть (Home Assistant, лампы, розетки) идут напрямую, интернет — как настроено
в системе. Достаточно импортировать модуль один раз при старте.
"""

import ipaddress
import urllib.request


def is_local(host):
    host = (host or "").split("@")[-1]
    if host.startswith("["):                      # [::1]:11434
        host = host[1:].split("]")[0]
    elif host.count(":") == 1:
        host = host.split(":")[0]
    host = host.lower()
    if host in ("localhost", "") or host.endswith((".local", ".lan", ".localhost", ".home")):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


class _LocalBypass(urllib.request.ProxyHandler):
    def proxy_open(self, request, proxy, kind):
        if is_local(request.host):
            return None                           # дальше обычный обработчик — напрямую
        return super().proxy_open(request, proxy, kind)


urllib.request.install_opener(urllib.request.build_opener(_LocalBypass()))
