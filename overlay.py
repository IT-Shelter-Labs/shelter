"""Окно-консоль Джарвиса: реальная телеметрия машины и реактор.

python overlay.py --seconds 8 --label "SYSTEM READY"
"""

import argparse
import collections
import json
import math
import os
import subprocess
import threading
import time
import tkinter as tk
import urllib.request

import psutil

# Файл-флаг ставит voice.say на время проигрывания фразы. Путь продублирован
# в voice.py: тащить сюда весь voice ради одной константы дороже.
SPEAK_FLAG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "logs", "speaking.flag")
# Сюда actions.py кладёт новый заголовок и срок, чтобы не перезапускать окно.
OVERLAY_STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "logs", "overlay.json")

W, H = 960, 600
# 24, а не 30: замеры показали, что на 30 каждый седьмой кадр не укладывался
# в бюджет и окно дёргалось. На 24 сцена рисуется с запасом.
FPS = 24
FADE_IN = 0.25
FADE_OUT = 0.5

BG = "#04090f"
PANEL = "#071219"
PANEL_HI = "#0b202c"
GRID = "#0a141c"
LINE = "#164e63"
DIM = "#1f6f8c"
MID = "#37b3d8"
BRIGHT = "#7fe6ff"
WHITE = "#dff8ff"
AMBER = "#ffb648"
GREEN = "#5ef2a0"
RED = "#ff6b6b"
OFF_C = "#0a1c25"
OFF_B = "#0d2833"
OFF_A = "#2a1c0c"
# Свечение имитируем стопкой заливок от тёмной к яркой: альфы у Canvas нет.
GLOW = ["#0a2b38", "#0f4a5f", "#177a99", "#2ba8cd", "#5fd4f2"]
GLOW_HOT = ["#134e63", "#1c7c9c", "#39b6db", "#8febff", "#ffffff"]

MONO = "Consolas"

HEAD_H, FOOT_H = 64, 46
PY0 = 78
PY1 = H - FOOT_H - 12
LEFT = (18, PY0, 262, PY1)
RIGHT = (W - 262, PY0, W - 18, PY1)
RCX, RCY, RR = 480, 322, 188

TABS = ["OVERVIEW", "SYSTEM", "PROTOCOLS", "LOGS"]
HIST = 26

# Тикер -> id в CoinGecko. Менять список можно прямо здесь.
COINS = [("BTC", "bitcoin"), ("ETH", "ethereum"), ("SOL", "solana"),
         ("TON", "the-open-network"), ("XRP", "ripple"), ("DOGE", "dogecoin")]
COINS_URL = ("https://api.coingecko.com/api/v3/simple/price?ids={}"
             "&vs_currencies=usd&include_24hr_change=true")

def empty_stats():
    return {
        "cpu": 0.0, "mem": 0.0, "gpu": 0.0, "gpu_temp": 0.0, "disk": 0.0,
        "net": 0.0, "net_max": 1.0, "freq": 0.0, "cores": [], "nproc": 0,
        "uptime": "", "mem_used": 0.0, "coins": [],
        "cpu_hist": collections.deque([0.0] * HIST, maxlen=HIST),
        "net_hist": collections.deque([0.0] * HIST, maxlen=HIST),
    }


# Потоки телеметрии пишут только цели. Canvas читает STATS, которые плавно
# приближаются к ним на каждом кадре: секундное обновление больше не дёргает UI.
STATS = empty_stats()
TARGET_STATS = empty_stats()
SMOOTH_KEYS = ("cpu", "mem", "gpu", "gpu_temp", "disk", "net",
               "net_max", "freq", "mem_used")


def smooth_stats(amount=0.18):
    for key in SMOOTH_KEYS:
        STATS[key] += (TARGET_STATS[key] - STATS[key]) * amount
    target_cores = TARGET_STATS["cores"]
    if len(STATS["cores"]) != len(target_cores):
        STATS["cores"] = list(target_cores)
    else:
        STATS["cores"] = [old + (new - old) * amount
                          for old, new in zip(STATS["cores"], target_cores)]
    for key in ("nproc", "uptime", "coins"):
        STATS[key] = TARGET_STATS[key]
    STATS["cpu_hist"] = collections.deque(TARGET_STATS["cpu_hist"], maxlen=HIST)
    STATS["net_hist"] = collections.deque(TARGET_STATS["net_hist"], maxlen=HIST)


_gpu_proc = None


def nvidia_stream(stop):
    """nvidia-smi запускаем ОДИН раз в режиме потока.

    Каждый новый процесс на Windows стоит десятки миллисекунд, и запуск его
    по таймеру давал видимый рывок анимации. В режиме -l он печатает сам.
    """
    global _gpu_proc
    try:
        _gpu_proc = subprocess.Popen(
            ["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu",
             "--format=csv,noheader,nounits", "-l", "2"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for line in _gpu_proc.stdout:
            if stop.is_set():
                return
            try:
                load, temp = line.split(",")
                TARGET_STATS["gpu"], TARGET_STATS["gpu_temp"] = float(load), float(temp)
            except ValueError:
                continue
    except Exception:
        pass


def stop_gpu():
    if _gpu_proc is not None and _gpu_proc.poll() is None:
        _gpu_proc.terminate()


def collect_fast(stop):
    """Раз в секунду: то, что читается мгновенно."""
    psutil.cpu_percent(percpu=True)
    last_net, last_time = psutil.net_io_counters(), time.monotonic()

    while not stop.is_set():
        # Осечка опроса не должна убивать поток, иначе окно застынет молча.
        try:
            cores = psutil.cpu_percent(percpu=True)
            TARGET_STATS["cores"] = cores
            TARGET_STATS["cpu"] = sum(cores) / len(cores) if cores else 0.0
            TARGET_STATS["cpu_hist"].append(TARGET_STATS["cpu"])
            memory = psutil.virtual_memory()
            TARGET_STATS["mem"] = memory.percent
            TARGET_STATS["mem_used"] = memory.used / 1073741824.0

            now, net = time.monotonic(), psutil.net_io_counters()
            span = max(now - last_time, 1e-3)
            TARGET_STATS["net"] = (net.bytes_sent + net.bytes_recv
                                   - last_net.bytes_sent - last_net.bytes_recv) / span / 1024.0
            last_net, last_time = net, now
            TARGET_STATS["net_hist"].append(TARGET_STATS["net"])
            TARGET_STATS["net_max"] = max(64.0, max(TARGET_STATS["net_hist"]))

            up = int(time.time() - psutil.boot_time())
            TARGET_STATS["uptime"] = f"{up // 3600:02d}:{up % 3600 // 60:02d}:{up % 60:02d}"
        except Exception:
            pass
        time.sleep(1.0)


def crypto():
    """Курсы с CoinGecko: цена и изменение за сутки."""
    url = COINS_URL.format(",".join(coin_id for _, coin_id in COINS))
    request = urllib.request.Request(url, headers={"User-Agent": "jarvis/1.0"})
    with urllib.request.urlopen(request, timeout=8) as response:
        data = json.loads(response.read())
    rows = []
    for ticker, coin_id in COINS:
        item = data.get(coin_id)
        if item:
            rows.append((ticker, item.get("usd", 0.0),
                         item.get("usd_24h_change", 0.0)))
    return rows


def collect_slow(stop):
    """Тяжёлые опросы. За один заход делаем ровно одну задачу, чтобы не
    держать GIL долго и не сбивать кадр."""
    tick = 0
    while not stop.is_set():
        try:
            if tick % 4 == 0:
                # Перебор всех процессов заметно дороже остального опроса,
                # поэтому здесь, а не каждую секунду.
                TARGET_STATS["nproc"] = len(psutil.pids())
                disk_root = os.path.abspath(os.sep) if os.name != "nt" else "C:\\"
                TARGET_STATS["disk"] = psutil.disk_usage(disk_root).percent
            elif tick % 4 == 1:
                frequency = psutil.cpu_freq()
                TARGET_STATS["freq"] = frequency.current / 1000.0 if frequency else 0.0
            elif tick % 20 == 2:
                # Курсы раз в минуту: чаще не нужно и упрёмся в лимит
                # CoinGecko. При сбое остаются последние значения.
                TARGET_STATS["coins"] = crypto()
        except Exception:
            pass
        tick += 1
        time.sleep(3.0)


def pol(cx, cy, r, deg):
    a = math.radians(deg)
    return cx + r * math.cos(a), cy - r * math.sin(a)


def mix(c1, c2, t):
    """Линейная интерполяция двух #rrggbb — переход между режимами."""
    t = max(0.0, min(1.0, t))
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(a[k] + (b[k] - a[k]) * t) for k in range(3))


def arc(c, r, start, extent, color, width):
    c.create_arc(RCX - r, RCY - r, RCX + r, RCY + r, start=start, extent=extent,
                 style="arc", outline=color, width=width, tags="dyn")


def pie(c, r, start, extent, color):
    c.create_arc(RCX - r, RCY - r, RCX + r, RCY + r, start=start, extent=extent,
                 style="pieslice", fill=color, outline="", tags="dyn")


def disc(c, cx, cy, r, fill, outline="", width=1, tag="dyn"):
    c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fill, outline=outline,
                  width=width, tags=tag)


def spoke(c, cx, cy, r1, r2, deg, color, width=1, tag="dyn"):
    x1, y1 = pol(cx, cy, r1, deg)
    x2, y2 = pol(cx, cy, r2, deg)
    c.create_line(x1, y1, x2, y2, fill=color, width=width, tags=tag)


# --------------------------------------------------------------- статика

def cut_panel(c, box, title, cut=14):
    x0, y0, x1, y1 = box
    c.create_polygon(x0 + cut, y0, x1, y0, x1, y1 - cut, x1 - cut, y1,
                     x0, y1, x0, y0 + cut,
                     fill=PANEL, outline=LINE, width=1, tags="static")
    c.create_rectangle(x0 + cut + 4, y0 + 6, x1 - 8, y0 + 26,
                       fill=PANEL_HI, outline="", tags="static")
    c.create_text(x0 + cut + 12, y0 + 16, text=title, fill=AMBER,
                  anchor="w", font=(MONO, 9, "bold"), tags="static")
    c.create_line(x0 + 6, y0 + 32, x1 - 6, y0 + 32, fill=LINE, tags="static")


def sub(c, x, y, x1, text):
    c.create_line(x - 8, y - 14, x1, y - 14, fill=LINE, tags="static")
    c.create_text(x, y, text=text, fill=DIM, anchor="w",
                  font=(MONO, 9, "bold"), tags="static")


def draw_static(c):
    c.create_rectangle(0, 0, W, H, fill=BG, outline="", tags="static")
    for x in range(0, W, 32):
        c.create_line(x, 0, x, H, fill=GRID, tags="static")
    for y in range(0, H, 32):
        c.create_line(0, y, W, y, fill=GRID, tags="static")
    # Растровых полос через каждые 4 px здесь больше нет: полторы сотни линий
    # во всю ширину Tk перерисовывал при любом повреждении области, и кадр
    # переставал укладываться в бюджет.

    c.create_rectangle(2, 2, W - 2, H - 2, outline=DIM, width=2, tags="static")
    c.create_rectangle(6, 6, W - 6, H - 6, outline=LINE, width=1, tags="static")
    for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        x = 6 if sx > 0 else W - 6
        y = 6 if sy > 0 else H - 6
        c.create_line(x, y, x + sx * 46, y, fill=BRIGHT, width=3, tags="static")
        c.create_line(x, y, x, y + sy * 34, fill=BRIGHT, width=3, tags="static")

    c.create_rectangle(6, 6, W - 6, HEAD_H, fill=PANEL_HI, outline="", tags="static")
    c.create_line(6, HEAD_H, W - 6, HEAD_H, fill=MID, width=2, tags="static")
    c.create_text(26, 26, text="J . A . R . V . I . S", fill=WHITE,
                  anchor="w", font=(MONO, 16, "bold"), tags="static")

    c.create_rectangle(6, H - FOOT_H, W - 6, H - 6, fill=PANEL_HI,
                       outline="", tags="static")
    c.create_line(6, H - FOOT_H, W - 6, H - FOOT_H, fill=MID, width=2, tags="static")

    cut_panel(c, LEFT, "SYSTEM STATUS")
    cut_panel(c, RIGHT, "PROCESSOR")

    x0, y0, x1, _ = LEFT
    sub(c, x0 + 18, y0 + 176, x1 - 6, "NETWORK  KB/S")
    sub(c, x0 + 18, y0 + 302, x1 - 6, "MACHINE")
    rx0, ry0, rx1, _ = RIGHT
    sub(c, rx0 + 18, ry0 + 226, rx1 - 6, "CPU LOAD HISTORY")
    sub(c, rx0 + 18, ry0 + 352, rx1 - 6, "MARKETS  USD")

    disc(c, RCX, RCY, RR, PANEL, LINE, 1, "static")
    disc(c, RCX, RCY, RR - 4, "", DIM, 1, "static")
    for r in (150, 116, 96):
        disc(c, RCX, RCY, r, "", "#0d2a35", 1, "static")
    for deg in (0, 90, 180, 270):
        spoke(c, RCX, RCY, 20, RR - 8, deg, "#0d2430", 1, "static")
    for i in range(90):
        long = i % 5 == 0
        spoke(c, RCX, RCY, RR - 16, RR - 6 if long else RR - 11, i * 4,
              MID if long else DIM, 1, "static")
    # Подписи держим вне круга: внутри их перечёркивают вращающиеся дуги.
    c.create_text(282, 116, text="ARC REACTOR  //  STABLE", fill=DIM,
                  anchor="w", font=(MONO, 8), tags="static")
    c.create_text(282, 526, text="SYNC LOCKED", fill=DIM,
                  anchor="w", font=(MONO, 8), tags="static")

    for deg, name in ((90, "000"), (0, "090"), (270, "180"), (180, "270")):
        x, y = pol(RCX, RCY, RR + 16, deg)
        c.create_text(x, y, text=name, fill=DIM, font=(MONO, 8), tags="static")
        spoke(c, RCX, RCY, RR + 2, RR + 8, deg, MID, 2, "static")


# -------------------------------------------------------------- динамика

def tabs(c, f):
    sel = int(f / 40) % len(TABS)
    x, y = 282, PY0
    for i, name in enumerate(TABS):
        on = i == sel
        c.create_polygon(x + 8, y, x + 96, y, x + 88, y + 24, x, y + 24,
                         fill=PANEL_HI if on else PANEL,
                         outline=BRIGHT if on else LINE, width=1, tags="dyn")
        c.create_text(x + 48, y + 12, text=name, fill=WHITE if on else DIM,
                      font=(MONO, 8, "bold"), tags="dyn")
        x += 102


def reactor(c, p, pp, act):
    """p — фаза вращения, pp — фаза пульса, act — 0..1 режим речи."""
    hot = mix(MID, "#bff3ff", act)
    hot_dim = mix(DIM, MID, act)

    for i in range(4):
        s = p * 0.4 + i * 90
        arc(c, 160, s, 62, mix(GLOW[1], GLOW_HOT[1], act), 10)
        arc(c, 160, s, 62, hot, 3)
        x, y = pol(RCX, RCY, 160, s + 62)
        disc(c, x, y, 4 + 2 * act, BRIGHT)

    for i in range(3):
        s = -p * 0.85 + i * 120
        arc(c, 138, s, 84, mix(GLOW[0], GLOW_HOT[0], act), 14)
        arc(c, 138, s, 84, BRIGHT, 4)

    for i in range(60):
        arc(c, 122, p * 1.5 + i * 6, 3, hot_dim if i % 2 else hot, 3)

    for i in range(36):
        deg = -p * 0.7 + i * 10
        spoke(c, RCX, RCY, 104, 114 if i % 3 else 118, deg,
              hot if i % 3 == 0 else hot_dim, 2 if i % 3 == 0 else 1)

    head = p * 2.0
    for ext, color in ((-46, GLOW[0]), (-30, GLOW[1]), (-14, GLOW[2])):
        pie(c, 112, head, ext, color)
    x, y = pol(RCX, RCY, 112, head)
    c.create_line(RCX, RCY, x, y, fill=BRIGHT, width=2, tags="dyn")
    disc(c, x, y, 4, BRIGHT)

    disc(c, RCX, RCY, 78, mix("#081d27", "#0d2f3e", act), "#12384a", 1)

    # Режим речи: от ядра расходятся волны.
    if act > 0.02:
        for i in range(3):
            r = 40 + ((p * 2.4 + i * 38) % 114)
            fade = ((1.0 - (r - 40) / 114) ** 0.6) * act
            disc(c, RCX, RCY, r, "", mix("#081d27", BRIGHT, fade), 3)

    for i in range(6):
        deg = -p * 0.5 + i * 60
        x, y = pol(RCX, RCY, 100, deg)
        c.create_polygon(x, y - 8, x + 8, y, x, y + 8, x - 8, y,
                         fill=PANEL_HI, outline=AMBER if i % 2 else hot,
                         width=2, tags="dyn")

    for sign, color, r in ((1, hot_dim, 84), (-1, hot, 68)):
        pts = []
        for i in range(3):
            pts += list(pol(RCX, RCY, r, sign * p + i * 120 + 90))
        c.create_polygon(pts, fill="", outline=color, width=2, tags="dyn")

    pulse = (4 + 9 * act) * math.sin(math.radians(pp))
    arc(c, 60 + pulse, p * 2.6, 300, BRIGHT, 2 + int(act * 2))
    for i in range(12):
        spoke(c, RCX, RCY, 64, 70 + 4 * act, p * 1.4 + i * 30, hot, 2)
    for k in range(len(GLOW)):
        disc(c, RCX, RCY, 46 + pulse - k * 8 + 4 * act,
             mix(GLOW[k], GLOW_HOT[k], act))
    disc(c, RCX, RCY, 9 + pulse * 0.3 + 3 * act, WHITE)

    # Загрузка CPU кольцом вокруг ядра — реактор дышит вместе с машиной.
    load = max(0.0, min(100.0, STATS["cpu"]))
    if load > 1:
        arc(c, 92, 90, -3.6 * load, AMBER if load > 80 else BRIGHT, 3)


def gauges(c):
    x0, y0, x1, _ = LEFT
    rows = (("CPU", STATS["cpu"]), ("MEM", STATS["mem"]),
            ("GPU", STATS["gpu"]), ("DISK", STATS["disk"]))
    for i, (name, value) in enumerate(rows):
        y = y0 + 56 + i * 28
        c.create_text(x0 + 18, y, text=name, fill=DIM, anchor="w",
                      font=(MONO, 9), tags="dyn")
        bx0, bx1 = x0 + 62, x1 - 52
        c.create_rectangle(bx0, y - 6, bx1, y + 6, fill=BG, outline=LINE, tags="dyn")
        c.create_rectangle(bx0, y - 6, bx0 + (bx1 - bx0) * value / 100, y + 6,
                           fill=MID if value < 85 else AMBER, outline="", tags="dyn")
        for gx in range(int(bx0) + 6, int(bx1), 7):
            c.create_line(gx, y - 6, gx, y + 6, fill=BG, tags="dyn")
        c.create_text(x1 - 14, y, text=f"{value:3.0f}%", fill=WHITE, anchor="e",
                      font=(MONO, 9), tags="dyn")


def net_graph(c):
    x0, y0, x1, _ = LEFT
    bx0, bx1 = x0 + 18, x1 - 18
    by0, by1 = y0 + 190, y0 + 252
    c.create_rectangle(bx0, by0, bx1, by1, fill=BG, outline=LINE, tags="dyn")
    for gy in range(1, 3):
        y = by0 + (by1 - by0) * gy / 3
        c.create_line(bx0, y, bx1, y, fill="#0b2029", tags="dyn")

    hist = list(STATS["net_hist"])
    top = STATS["net_max"]
    pts = []
    for i, value in enumerate(hist):
        x = bx0 + (bx1 - bx0) * i / (len(hist) - 1)
        pts += [x, by1 - 4 - (by1 - by0 - 8) * min(value / top, 1.0)]
    c.create_line(pts, fill=BRIGHT, width=2, tags="dyn")
    c.create_text(bx0 + 6, by0 + 10, text=f"{STATS['net']:.0f} KB/S",
                  fill=MID, anchor="w", font=(MONO, 9, "bold"), tags="dyn")
    c.create_text(bx1 - 6, by0 + 10, text=f"peak {top:.0f}", fill=DIM,
                  anchor="e", font=(MONO, 8), tags="dyn")


def net_bar(c):
    x0, y0, x1, _ = LEFT
    bx0, bx1 = x0 + 18, x1 - 18
    y = y0 + 262
    n = 26
    step = (bx1 - bx0) / n
    level = min(STATS["net"] / STATS["net_max"], 1.0)
    for i in range(n):
        on = i / n < level
        if i > n * 0.86:
            color = AMBER if on else OFF_A
        elif i > n * 0.66:
            color = BRIGHT if on else OFF_B
        else:
            color = MID if on else OFF_C
        c.create_rectangle(bx0 + i * step, y, bx0 + i * step + step - 2, y + 11,
                           fill=color, outline="", tags="dyn")


def machine(c):
    x0, y0, x1, _ = LEFT
    rows = (("UPTIME", STATS["uptime"] or "--:--:--"),
            ("PROCESSES", str(STATS["nproc"])),
            ("CPU CLOCK", f"{STATS['freq']:.2f} GHz" if STATS["freq"] else "--"),
            ("GPU TEMP", f"{STATS['gpu_temp']:.0f} C" if STATS["gpu_temp"] else "--"),
            ("MEM USED", f"{STATS['mem_used']:.1f} GB"))
    for i, (name, value) in enumerate(rows):
        y = y0 + 322 + i * 22
        c.create_text(x0 + 20, y, text=name, fill=DIM, anchor="w",
                      font=(MONO, 9), tags="dyn")
        c.create_text(x1 - 16, y, text=value, fill=WHITE, anchor="e",
                      font=(MONO, 9), tags="dyn")


def chart_frame(c, x0, y0, x1, y1):
    """Рамка с сеткой: без неё график с низкими значениями читается как пустота."""
    c.create_rectangle(x0, y0, x1, y1, fill=BG, outline=LINE, tags="dyn")
    for part in (0.25, 0.5, 0.75):
        y = y1 - (y1 - y0) * part
        c.create_line(x0 + 1, y, x1 - 1, y, fill="#0b2029", tags="dyn")
        c.create_text(x0 + 4, y - 6, text=f"{int(part * 100)}", fill="#14455a",
                      anchor="w", font=(MONO, 7), tags="dyn")


def cores(c):
    x0, y0, x1, _ = RIGHT
    values = STATS["cores"] or [0.0]
    top, height = y0 + 46, 140
    chart_frame(c, x0 + 18, top, x1 - 18, top + height)
    step = (x1 - x0 - 36) / len(values)
    for i, value in enumerate(values):
        x = x0 + 18 + i * step
        h = 3 + (height - 6) * value / 100.0
        c.create_rectangle(x, top + height - h, x + step - 3, top + height - 1,
                           fill=AMBER if value > 85 else MID, outline="", tags="dyn")
    c.create_text(x0 + 18, top + height + 16, text=f"{len(values)} LOGICAL CORES",
                  fill=DIM, anchor="w", font=(MONO, 8), tags="dyn")
    c.create_text(x1 - 16, top + height + 16, text=f"MAX {max(values):.0f}%",
                  fill=DIM, anchor="e", font=(MONO, 8), tags="dyn")


def cpu_graph(c):
    x0, y0, x1, _ = RIGHT
    top, height = y0 + 238, 74
    chart_frame(c, x0 + 18, top, x1 - 18, top + height)
    hist = list(STATS["cpu_hist"])
    step = (x1 - x0 - 36) / len(hist)
    for i, value in enumerate(hist):
        h = 3 + (height - 6) * value / 100.0
        x = x0 + 18 + i * step
        c.create_rectangle(x, top + height - h, x + step - 3, top + height - 1,
                           fill=AMBER if value > 85 else MID, outline="", tags="dyn")
    c.create_text(x0 + 18, y0 + 326, text=f"NOW {STATS['cpu']:.0f}%", fill=DIM,
                  anchor="w", font=(MONO, 8), tags="dyn")
    c.create_text(x1 - 16, y0 + 326, text=f"PEAK {max(hist):.0f}%", fill=DIM,
                  anchor="e", font=(MONO, 8), tags="dyn")


def price(value):
    """Диапазон от десятых долей цента до десятков тысяч — формат подбираем."""
    if value >= 1000:
        return f"{value:,.0f}".replace(",", " ")
    if value >= 1:
        return f"{value:,.2f}".replace(",", " ")
    return f"{value:.4f}"


def markets(c):
    x0, y0, x1, _ = RIGHT
    rows = STATS["coins"]
    if not rows:
        c.create_text(x0 + 18, y0 + 372, text="нет связи", fill=DIM,
                      anchor="w", font=(MONO, 9), tags="dyn")
        return
    for i, (ticker, value, change) in enumerate(rows[:6]):
        y = y0 + 370 + i * 16
        c.create_text(x0 + 18, y, text=ticker, fill=WHITE, anchor="w",
                      font=(MONO, 9, "bold"), tags="dyn")
        c.create_text(x1 - 74, y, text=price(value), fill=MID, anchor="e",
                      font=(MONO, 9), tags="dyn")
        c.create_text(x1 - 16, y, text=f"{change:+.2f}%",
                      fill=GREEN if change >= 0 else RED, anchor="e",
                      font=(MONO, 9), tags="dyn")


def header(c, label, act):
    now = time.localtime()
    c.create_text(W - 28, 24, text=time.strftime("%H:%M:%S", now), fill=WHITE,
                  anchor="e", font=(MONO, 15, "bold"), tags="dyn")
    c.create_text(W - 28, 46, text=time.strftime("%d.%m.%Y  %a", now).upper(),
                  fill=DIM, anchor="e", font=(MONO, 8), tags="dyn")
    c.create_text(28, 47, text=f"UPTIME {STATS['uptime']}  //  "
                               f"{STATS['nproc']} PROC", fill=DIM,
                  anchor="w", font=(MONO, 8), tags="dyn")
    c.create_text(W // 2, 32, text=label, fill=mix(AMBER, WHITE, act),
                  font=(MONO, 14, "bold"), tags="dyn")


def footer(c, f, act):
    y = H - FOOT_H // 2 - 3
    if act > 0.5:
        text, color = ">> SPEAKING", AMBER
    else:
        text, color = "LISTENING" + "." * (1 + int(f / 8) % 3), BRIGHT
    c.create_text(28, y, text=text, fill=color, anchor="w",
                  font=(MONO, 10, "bold"), tags="dyn")
    bx0, bx1 = 210, W - 250
    c.create_rectangle(bx0, y - 6, bx1, y + 6, fill=BG, outline=LINE, tags="dyn")
    p = (f * 1.6) % (bx1 - bx0)
    c.create_rectangle(bx0 + p, y - 6, bx0 + min(p + 90, bx1 - bx0), y + 6,
                       fill=mix(MID, AMBER, act), outline="", tags="dyn")


def draw(c, f, p, pp, act, label):
    c.delete("dyn")
    tabs(c, f)
    reactor(c, p, pp, act)
    gauges(c)
    net_graph(c)
    net_bar(c)
    machine(c)
    cores(c)
    cpu_graph(c)
    markets(c)
    header(c, label, act)
    footer(c, f, act)


def place(root, pos):
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    if pos == "top-right":
        x, y = sw - W - 30, 30
    elif pos == "bottom-right":
        x, y = sw - W - 30, sh - H - 90
    else:
        x, y = (sw - W) // 2, (sh - H) // 2
    root.geometry(f"{W}x{H}+{x}+{y}")


def main():
    parser = argparse.ArgumentParser(description="Окно-консоль Джарвиса")
    parser.add_argument("--seconds", type=float, default=8.0,
                        help="0 — не закрываться самому")
    parser.add_argument("--pos", default="center",
                        choices=["center", "top-right", "bottom-right"])
    parser.add_argument("--label", default="STANDING BY")
    parser.add_argument("--speaking", action="store_true",
                        help="принудительно показать режим речи")
    args = parser.parse_args()

    stop = threading.Event()
    for worker in (collect_fast, collect_slow, nvidia_stream):
        threading.Thread(target=worker, args=(stop,), daemon=True).start()

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.0)
    root.configure(bg=BG)
    place(root, args.pos)

    canvas = tk.Canvas(root, width=W, height=H, bg=BG, highlightthickness=0)
    canvas.pack()
    root.bind("<Escape>", lambda e: root.destroy())
    canvas.bind("<Button-1>", lambda e: root.destroy())

    draw_static(canvas)
    canvas.tag_lower("static")

    frame = 0
    phase = 0.0        # фаза копится сама, иначе смена скорости даст рывок
    pulse = 0.0
    act = 0.0          # 0 молчит, 1 говорит; между ними плавно
    started = time.monotonic()
    label = args.label
    # None — висеть, пока не закроют кликом или командой.
    expires = None if args.seconds <= 0 else started + args.seconds
    try:
        state_seen = os.path.getmtime(OVERLAY_STATE)
    except OSError:
        state_seen = None

    def reload_state():
        """Новый заголовок и срок от actions.py, без перезапуска окна."""
        nonlocal label, expires, state_seen
        try:
            mtime = os.path.getmtime(OVERLAY_STATE)
        except OSError:
            return
        if mtime == state_seen:
            return
        state_seen = mtime
        try:
            with open(OVERLAY_STATE, encoding="utf-8") as state:
                data = json.load(state)
        except (OSError, ValueError):
            return
        label = data.get("label", label)
        seconds = float(data.get("seconds", 0))
        expires = None if seconds <= 0 else time.monotonic() + seconds
        return True

    def tick():
        nonlocal frame, phase, pulse, act
        reload_state()
        now = time.monotonic()
        if expires is not None and now >= expires:
            stop.set()
            stop_gpu()
            root.destroy()
            return

        elapsed = now - started
        if elapsed < FADE_IN:
            alpha = elapsed / FADE_IN
        elif expires is not None and expires - now < FADE_OUT:
            alpha = max(0.0, (expires - now) / FADE_OUT)
        else:
            alpha = 1.0
        root.attributes("-alpha", alpha)

        target = 1.0 if (args.speaking or os.path.exists(SPEAK_FLAG)) else 0.0
        act += (target - act) * 0.16
        smooth_stats()
        phase += 2.0 * (1.0 + 0.8 * act)
        pulse += 3.5 * (1.0 + 1.8 * act)

        draw(canvas, frame * 2.0, phase, pulse, act, label)
        frame += 1
        # Ждём до следующего кадра по абсолютному времени, а не фиксированные
        # 33 мс после отрисовки: иначе любой затянувшийся кадр сдвигает всю
        # последующую цепочку и анимация дёргается.
        delay = started + frame / FPS - time.monotonic()
        root.after(max(1, int(delay * 1000)), tick)

    tick()
    root.mainloop()
    stop.set()
    stop_gpu()


if __name__ == "__main__":
    main()
