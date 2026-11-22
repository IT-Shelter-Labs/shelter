"""Инструменты, которые языковая модель вызывает тегами в начале ответа.

[app: Firefox]          открыть любую программу из меню «Пуск»
[weather: Москва]       погода (Open-Meteo, без ключа)
[search: курс евро]     поиск в интернете (DuckDuckGo без ключа; Brave или SearXNG по желанию)
[timer: 300 | чайник]   таймер или напоминание
[home: чайник | on]     умный дом — см. smarthome.py

Только стандартная библиотека: каждый инструмент — один-два HTTP-запроса.
"""

import netfix  # noqa: F401 — локальное мимо системного прокси
import difflib
import html
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import configparser
from pathlib import Path

ROOT = os.path.dirname(os.path.abspath(__file__))
APPS_CACHE = os.path.join(ROOT, "logs", "apps.json")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Jarvis/1.0"


def _get(url, data=None, headers=None, timeout=8):
    request = urllib.request.Request(
        url, data=data, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError:
        raise
    except OSError:
        time.sleep(0.3)               # разовый сбой сети — вторая попытка
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()


# ------------------------------------------------------------- программы

# Как люди называют программы — как они записаны в меню «Пуск».
APP_ALIASES = {
    "блокнот": ["блокнот", "notepad"],
    "калькулятор": ["калькулятор", "calculator"],
    "проводник": ["проводник", "file explorer", "explorer"],
    "настройки": ["параметры", "settings"],
    "параметры": ["параметры", "settings"],
    "диспетчер задач": ["диспетчер задач", "task manager"],
    "командная строка": ["командная строка", "command prompt"],
    "терминал": ["терминал", "terminal", "windows powershell"],
    "фотошоп": ["photoshop"],
    "ворд": ["word"],
    "эксель": ["excel"],
    "хром": ["google chrome", "chrome"],
    "яндекс браузер": ["yandex", "яндекс браузер"],
    "эдж": ["microsoft edge"],
    "опера": ["opera", "opera gx browser"],
    "файрфокс": ["firefox"],
    "стим": ["steam"],
    "дискорд": ["discord"],
    "телеграм": ["telegram"],
    "вс код": ["visual studio code"],
    "код": ["visual studio code"],
    "обс": ["obs studio"],
}

_apps = []
_apps_lock = threading.Lock()


def _scan_apps():
    """Все приложения из меню «Пуск»: имя и идентификатор для запуска."""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
         "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"],
        capture_output=True, timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    data = json.loads(out.stdout.decode("utf-8", "replace") or "[]")
    if isinstance(data, dict):
        data = [data]
    # Служебное — ссылки на сайты, справку и деинсталляторы — не открываем.
    skip = re.compile(r"uninstall|удалить|удаление|support|help|справка|readme|license|лицензия", re.I)
    return [{"name": item["Name"], "id": item["AppID"]} for item in data
            if item.get("Name") and item.get("AppID")
            and not str(item["AppID"]).startswith("http") and not skip.search(item["Name"])]


_STEAM_SKIP = re.compile(r"redistributable|proton|steamworks|steamvr|runtime|dedicated server|sdk\b", re.I)


def steam_games():
    """Установленные игры Steam — и те, у которых нет ярлыка в меню «Пуск»."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        steam = winreg.QueryValueEx(key, "SteamPath")[0]
    except OSError:
        return []
    libraries = [steam]
    try:
        with open(os.path.join(steam, "steamapps", "libraryfolders.vdf"), encoding="utf-8") as file:
            libraries += [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s+"([^"]+)"', file.read())]
    except OSError:
        pass
    games, seen = [], set()
    for library in dict.fromkeys(os.path.normcase(os.path.normpath(p)) for p in libraries):
        folder = os.path.join(library, "steamapps")
        try:
            names = [n for n in os.listdir(folder) if n.startswith("appmanifest_") and n.endswith(".acf")]
        except OSError:
            continue
        for name in names:
            try:
                with open(os.path.join(folder, name), encoding="utf-8", errors="replace") as file:
                    text = file.read()
            except OSError:
                continue
            appid = re.search(r'"appid"\s+"(\d+)"', text)
            title = re.search(r'"name"\s+"([^"]+)"', text)
            if appid and title and appid.group(1) not in seen and not _STEAM_SKIP.search(title.group(1)):
                seen.add(appid.group(1))
                games.append({"name": title.group(1), "id": f"steam://rungameid/{appid.group(1)}"})
    return games


def load_apps(max_age=24 * 3600):
    """Индекс программ: из кэша, если он свежий, иначе пересканировать."""
    global _apps
    if os.name != "nt":
        with _apps_lock:
            if not _apps:
                roots = [Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "applications"]
                roots += [Path(p) / "applications" for p in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")]
                for root in roots:
                    for path in root.glob("*.desktop"):
                        entry = configparser.ConfigParser(interpolation=None)
                        try:
                            entry.read(path, encoding="utf-8")
                            app = entry["Desktop Entry"]
                            if app.get("Type") == "Application" and app.get("NoDisplay", "false") != "true" and app.get("Hidden", "false") != "true":
                                _apps.append({"name": app.get("Name[ru]", app.get("Name", path.stem)), "id": str(path)})
                        except (OSError, KeyError, configparser.Error):
                            continue
            return _apps
    with _apps_lock:
        if _apps:
            return _apps
        try:
            if time.time() - os.path.getmtime(APPS_CACHE) < max_age:
                with open(APPS_CACHE, encoding="utf-8") as file:
                    _apps = json.load(file)
                    return _apps
        except (OSError, ValueError):
            pass
        try:
            _apps = _scan_apps()
            known = {_norm(a["name"]) for a in _apps}
            _apps += [g for g in steam_games() if _norm(g["name"]) not in known]
            os.makedirs(os.path.dirname(APPS_CACHE), exist_ok=True)
            with open(APPS_CACHE, "w", encoding="utf-8") as file:
                json.dump(_apps, file, ensure_ascii=False)
        except Exception as error:
            print(f"[apps] не прочитать меню «Пуск»: {error}")
        return _apps


def briefing(config):
    """Утренняя (или любая) сводка: время, погода дома, дела на сегодня — без нейросети."""
    import datetime as dt
    import memory
    import scheduler
    now = dt.datetime.now()
    greeting = ("Доброй ночи" if now.hour < 5 else "Доброе утро" if now.hour < 12
                else "Добрый день" if now.hour < 18 else "Добрый вечер")
    weekdays = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    parts = [f"{greeting}, сэр. Сейчас {now:%H:%M}, {weekdays[now.weekday()]}."]
    try:
        report = weather("", config)
        if not report.startswith("Город пользователя"):
            first = report.split(". ")
            parts.append(first[0].replace(", сейчас:", ": сейчас") + ".")
            today_line = next((p for p in report.split(". ") if p.startswith("Сегодня")), "")
            if today_line:
                parts.append(today_line.rstrip(".") + ".")
    except Exception as error:
        print(f"[briefing] погода: {error}")
    items = scheduler.today()
    if items:
        plans = ", ".join(f"{i['label']} в {dt.datetime.fromtimestamp(i['due']):%H:%M}" for i in items[:4])
        parts.append(f"На сегодня: {plans}.")
    else:
        parts.append("Напоминаний на сегодня нет.")
    return " ".join(parts)


def game_names():
    """Названия игр (Steam) — для подсказки модели: «ведьмак» -> The Witcher 3."""
    return [a["name"] for a in _apps if str(a.get("id", "")).startswith("steam://")
            and a["name"] not in ("DisplayFusion", "Wallpaper Engine", "ShareX", "Soundpad")]


def _norm(text):
    return re.sub(r"[^\w ]+", " ", str(text).lower().replace("ё", "е")).strip()


def find_app(name):
    """Лучшее совпадение по названию, None — если ничего похожего."""
    apps = load_apps()
    if not apps:
        return None
    wanted = _norm(name)
    candidates = [wanted] + APP_ALIASES.get(wanted, [])
    names = {_norm(app["name"]): app for app in apps}
    for candidate in candidates:
        if candidate in names:
            return names[candidate]
    # Начало названия: «steam» -> «Steam», но не «Steam Support Center» раньше него.
    for candidate in candidates:
        starts = [key for key in names if key.startswith(candidate + " ") or key == candidate]
        if starts:
            return names[min(starts, key=len)]
    # Все слова запроса есть в названии: «witcher 3» -> «The Witcher 3: Wild Hunt».
    for candidate in candidates:
        words = candidate.split()
        hits = [key for key in names if words and all(w in key.split() for w in words)]
        if hits:
            return names[min(hits, key=len)]
    for candidate in candidates:
        close = difflib.get_close_matches(candidate, list(names), n=1, cutoff=0.72)
        if close:
            return names[close[0]]
    return None


# Сайты, которые просят открыть как программы: «открой ютуб».
SITES = {
    "youtube": "https://www.youtube.com", "ютуб": "https://www.youtube.com",
    "ютьюб": "https://www.youtube.com", "вк": "https://vk.com", "вконтакте": "https://vk.com",
    "google": "https://www.google.com", "гугл": "https://www.google.com",
    "яндекс": "https://ya.ru", "почта": "https://mail.google.com", "gmail": "https://mail.google.com",
    "github": "https://github.com", "гитхаб": "https://github.com", "twitch": "https://www.twitch.tv",
    "твич": "https://www.twitch.tv", "chatgpt": "https://chatgpt.com", "карты": "https://yandex.ru/maps",
    "переводчик": "https://translate.yandex.ru", "кинопоиск": "https://www.kinopoisk.ru",
}

BROWSER_WORDS = {"браузер", "browser", "интернет", "веб браузер"}
_BROWSER_PROGIDS = {"firefox": "Firefox", "chrome": "Google Chrome", "msedge": "Microsoft Edge",
                    "yandex": "Yandex", "opera": "Opera", "brave": "Brave", "vivaldi": "Vivaldi"}


def default_browser():
    """Название браузера по умолчанию из реестра — чтобы «открой браузер» открыл именно его."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice")
        progid = winreg.QueryValueEx(key, "ProgId")[0].lower()
    except OSError:
        return None
    for marker, name in _BROWSER_PROGIDS.items():
        if marker in progid:
            return name
    return None


def open_app(name):
    """(успех, что открыто). Программы — только из меню «Пуск», сайты — из списка SITES."""
    wanted = _norm(name)
    if os.name != "nt":
        site = SITES.get(wanted)
        if wanted in BROWSER_WORDS or site:
            return bool(webbrowser.open(site or "https://www.google.com")), name
        app = find_app(name)
        if not app:
            return False, name
        subprocess.Popen(["gio", "launch", app["id"]])
        return True, app["name"]
    if wanted in BROWSER_WORDS:
        browser = default_browser()
        app = find_app(browser) if browser else None
        if app is None:
            os.startfile("https://www.google.com")
            return True, "браузер"
    else:
        app = find_app(name)
    if app is None:
        domain = str(name).strip().lower().replace(" ", "")
        site = SITES.get(wanted) or (("https://" + domain)
                                     if re.fullmatch(r"[\w.-]+\.(ru|com|net|org|io|tv|рф|me|gg)", domain) else None)
        if site:
            os.startfile(site)
            return True, wanted
        return False, name
    if "://" in app["id"]:
        os.startfile(app["id"])           # игры Steam: steam://rungameid/<id>
    else:
        subprocess.Popen(["explorer.exe", "shell:appsFolder\\" + app["id"]])
    return True, app["name"]


# ---------------------------------------------------------------- погода

WEATHER_CODES = {
    0: "ясно", 1: "преимущественно ясно", 2: "переменная облачность", 3: "пасмурно",
    45: "туман", 48: "туман с изморозью", 51: "лёгкая морось", 53: "морось",
    55: "сильная морось", 56: "ледяная морось", 57: "ледяная морось",
    61: "небольшой дождь", 63: "дождь", 65: "сильный дождь", 66: "ледяной дождь",
    67: "сильный ледяной дождь", 71: "небольшой снег", 73: "снег", 75: "сильный снег",
    77: "снежные зёрна", 80: "небольшой ливень", 81: "ливень", 82: "сильный ливень",
    85: "снегопад", 86: "сильный снегопад", 95: "гроза", 96: "гроза с градом",
    99: "сильная гроза с градом",
}

_geo_cache = {}


def _city_forms(city):
    """Prefer a recognized place name in nominative, retaining the original as fallback."""
    city = re.sub(r"^во?\s+", "", city.strip(), flags=re.I)
    if not re.search(r"[а-яё]", city, re.I):
        return [city]
    from speech_text import morph
    analyzer = morph()
    words = city.split()
    if analyzer and words:
        places = [p for p in analyzer.parse(words[-1]) if "Geox" in p.tag]
        if places and all(p.tag.case != "nomn" for p in places):
            place = next((p for p in places if p.tag.case in ("loct", "loc2")), None)
            if place:
                form = place.inflect({"nomn"})
                if form:
                    words[-1] = form.word
                    for i, word in enumerate(words[:-1]):
                        adj = next((p for p in analyzer.parse(word) if p.tag.POS == "ADJF"
                                    and p.tag.case == "loct" and p.tag.gender == place.tag.gender), None)
                        if adj and (form := adj.inflect({"nomn"})):
                            words[i] = form.word
                    return list(dict.fromkeys([" ".join(words).title(), city]))
    return [city]


def _locate(city, country_code=""):
    key = (city.lower(), country_code)
    if key not in _geo_cache:
        for form in ([city] if country_code else _city_forms(city)):
            query = urllib.parse.urlencode({"name": form, "count": 10 if country_code else 1, "language": "ru",
                                           **({"countryCode": country_code} if country_code else {})})
            found = json.loads(_get("https://geocoding-api.open-meteo.com/v1/search?" + query))
            results = found.get("results") or []
            if results:
                break
        else:
            raise LookupError(f"город «{city}» не найден")
        place = next((p for p in results if p.get("feature_code") == "PPLC"), results[0]) if country_code else results[0]
        _geo_cache[key] = (place["name"], place["latitude"], place["longitude"])
    return _geo_cache[key]


_home_city = None


def home_city(config):
    """Город пользователя: из location.city, а при «auto» — по IP-адресу (один раз за запуск)."""
    global _home_city
    city = str((config.get("location") or {}).get("city") or "auto").strip()
    if city.lower() != "auto":
        return city
    if _home_city is None:
        for url in ("https://ipinfo.io/json", "https://ipwho.is/"):
            try:
                _home_city = json.loads(_get(url, timeout=4)).get("city") or ""
                if _home_city:
                    break
            except (OSError, ValueError):
                continue
    return _home_city or ""


_HERE = {"", "у меня", "здесь", "тут", "дома", "мой город", "у нас", "сейчас"}


def _country(city):
    from weather_countries import COUNTRIES

    def normalized(text):
        return " ".join(re.sub(r"[^\w]+", " ", text.casefold().replace("ё", "е")).split())

    aliases = {"сша": "US", "штаты": "US", "америке": "US", "великобритании": "GB", "соединенном королевстве": "GB",
               "германии": "DE", "оаэ": "AE", "южной корее": "KR", "северной корее": "KP",
               "чехии": "CZ", "российской федерации": "RU", "нидерландах": "NL"}
    key = normalized(city)
    if key in aliases:
        code = aliases[key]
        return code, COUNTRIES[code]
    for code, (local, english, capital) in COUNTRIES.items():
        name = normalized(local)
        words = name.split()
        words = [word[:-2] + ("ой" if word.endswith("ая") else "ей") if word.endswith(("ая", "яя")) else word for word in words]
        last = words[-1]
        inflected = next((last[:-len(suffix)] + ending for suffix, ending in
                         (("ия", "ии"), ("ья", "ье"), ("а", "е"), ("я", "е"), ("ы", "ах"), ("и", "ях"))
                         if last.endswith(suffix)), last + "е")
        if key in (name, normalized(english), " ".join((*words[:-1], inflected))):
            return code, (local, english, capital)
    return None


def weather(city, config, *, period=None):
    """Сводка погоды текстом — её модель перескажет своими словами.

    Город из фразы («погода в Сочи») — главный. Без него — домашний: сказанный
    голосом («запомни, я живу в Казани»), из настроек, а в крайнем случае по IP.
    """
    city = (city or "").strip()
    candidates = [city]
    if city.lower() in _HERE:
        import memory
        configured = str((config.get("location") or {}).get("city") or "auto").strip()
        candidates = memory.cities() or [home_city(config)]
        if configured.lower() != "auto" and not memory.cities():
            candidates = [configured]
    candidates = [c for c in candidates if c]
    if not candidates:
        return "Назовите город, и я проверю погоду."
    prefix = ""
    for index, candidate in enumerate(candidates):
        try:
            country = _country(candidate)
            if country:
                code, (country_name, _, capital) = country
                name, lat, lon = _locate(capital, code)
                prefix = f"{country_name} — страна, и погода в разных регионах различается. Вот данные по столице. "
            else:
                name, lat, lon = _locate(candidate)
            break
        except LookupError:
            if index == len(candidates) - 1:
                raise
    query = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 3,
        "wind_speed_unit": "ms",
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,precipitation",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
    })
    data = json.loads(_get("https://api.open-meteo.com/v1/forecast?" + query))
    now, daily = data["current"], data["daily"]
    current = f"{name}, сейчас: {now['temperature_2m']:.0f}°C, ощущается как " \
             f"{now['apparent_temperature']:.0f}°C, {WEATHER_CODES.get(now['weather_code'], 'без осадков')}, " \
             f"ветер {now['wind_speed_10m']:.0f} м/с."
    if period == "current":
        return prefix + current
    lines = [current] if period is None else []
    for index, label in ((0, "Сегодня"), (1, "Завтра"), (2, "Послезавтра")):
        if period is not None and period != index:
            continue
        lines.append(
            f"{label}{f', {name}' if period is not None else ''}: от {daily['temperature_2m_min'][index]:.0f} до "
            f"{daily['temperature_2m_max'][index]:.0f}°C, "
            f"{WEATHER_CODES.get(daily['weather_code'][index], '')}, вероятность осадков "
            f"{daily['precipitation_probability_max'][index] or 0}%.")
    return prefix + " ".join(lines)


# ----------------------------------------------------------------- поиск

def _strip(fragment):
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


# Ссылки последнего поиска: «открой источник» откроет страницу, по которой ответили.
SOURCES = []


def _ddg_url(href):
    """DuckDuckGo отдаёт ссылки через свой редирект: //duckduckgo.com/l/?uddg=<адрес>."""
    href = html.unescape(href)
    if "uddg=" in href:
        return urllib.parse.unquote(urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg", [""])[0])
    return "https:" + href if href.startswith("//") else href


def _remember(items):
    """[(заголовок, ссылка, текст)] -> строки для модели; ссылки — в SOURCES."""
    SOURCES[:] = [(title, url) for title, url, _ in items if url.startswith("http")]
    return [f"{title}: {text}" for title, _, text in items]


def _duckduckgo(query, limit):
    """Две вёрстки DuckDuckGo: при частых запросах одна иногда отвечает пусто или 202."""
    form = urllib.parse.urlencode({"q": query, "kl": "ru-ru"}).encode()
    try:
        page = _get("https://html.duckduckgo.com/html/", data=form, timeout=5).decode("utf-8", "replace")
        anchors = re.findall(r'<a([^>]*class="result__a"[^>]*)>(.*?)</a>', page, re.S)
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', page, re.S)
        items = [(_strip(title), _ddg_url((re.search(r'href="([^"]+)"', attrs) or [None, ""])[1]), _strip(text))
                 for (attrs, title), text in zip(anchors, snippets)][:limit]
        if items:
            return _remember(items)
    except OSError as error:
        print(f"[search] html.duckduckgo: {error}")
    page = _get("https://lite.duckduckgo.com/lite/", data=form, timeout=5).decode("utf-8", "replace")
    links = re.findall(r"""<a[^>]*href="([^"]+)"[^>]*class='result-link'>(.*?)</a>""", page, re.S)
    snippets = re.findall(r"class='result-snippet'>(.*?)</td>", page, re.S)
    return _remember([(_strip(title), _ddg_url(url), _strip(text))
                      for (url, title), text in zip(links, snippets)][:limit])


def wikipedia(query, lang="ru"):
    """Краткое содержание самой подходящей статьи Википедии — для фактов надёжнее сниппетов."""
    api = f"https://{lang}.wikipedia.org"
    found = json.loads(_get(f"{api}/w/api.php?" + urllib.parse.urlencode(
        {"action": "query", "list": "search", "srsearch": query, "srlimit": 1, "format": "json"}), timeout=3))
    hits = (found.get("query") or {}).get("search") or []
    if not hits:
        return None
    title = hits[0]["title"]
    summary = json.loads(_get(f"{api}/api/rest_v1/page/summary/" + urllib.parse.quote(title.replace(" ", "_")),
                              timeout=3))
    extract = (summary.get("extract") or "").strip()
    url = ((summary.get("content_urls") or {}).get("desktop") or {}).get("page", "")
    return (f"Википедия «{title}»", url, extract[:700]) if extract else None


def _brave(query, limit, cfg):
    key = os.environ.get(cfg.get("api_key_env", "BRAVE_API_KEY"), "") or cfg.get("api_key", "")
    if not key:
        raise RuntimeError("нет ключа Brave Search")
    url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(
        {"q": query, "count": limit, "search_lang": "ru"})
    data = json.loads(_get(url, headers={"X-Subscription-Token": key, "Accept": "application/json"}))
    return _remember([(r.get("title", ""), r.get("url", ""), _strip(r.get("description", "")))
                      for r in (data.get("web") or {}).get("results", [])][:limit])


def _searxng(query, limit, cfg):
    url = cfg.get("url", "http://127.0.0.1:8888").rstrip("/") + "/search?" + urllib.parse.urlencode(
        {"q": query, "format": "json", "language": "ru"})
    data = json.loads(_get(url))
    return _remember([(r.get("title", ""), r.get("url", ""), r.get("content", ""))
                      for r in data.get("results", [])][:limit])


CURRENCIES = {"доллар": "USD", "usd": "USD", "евро": "EUR", "eur": "EUR", "юан": "CNY", "cny": "CNY",
               "фунт": "GBP", "тенге": "KZT", "лир": "TRY", "иен": "JPY", "белорусск": "BYN", "гривн": "UAH",
               "дирхам": "AED", "франк": "CHF"}


def cbr_rates(query):
    """Официальный курс ЦБ РФ — в сниппетах поисковиков самих цифр часто нет."""
    text = query.lower()
    if "курс" not in text and not any(word in text for word in CURRENCIES):
        return ""
    codes = list(dict.fromkeys(code for word, code in CURRENCIES.items() if word in text)) or ["USD", "EUR"]
    try:
        data = json.loads(_get("https://www.cbr-xml-daily.ru/daily_json.js", timeout=5))
    except (OSError, ValueError):
        return ""
    parts = []
    for code in codes:
        item = (data.get("Valute") or {}).get(code)
        if item:
            per = item["Value"] / item["Nominal"]
            change = item["Value"] - item["Previous"]
            parts.append(f"{item['Name']}: {per:.2f} руб. (за день {'+' if change >= 0 else ''}{change / item['Nominal']:.2f})")
    if not parts:
        return ""
    return f"Официальный курс ЦБ РФ на {data.get('Date', '')[:10]}: " + "; ".join(parts) + "."


def search(query, config):
    """Сниппеты из поисковика — модель ответит по ним, а не по памяти."""
    rates = cbr_rates(query)
    if rates:
        try:
            return rates + "\n" + _search(query, config)
        except OSError:
            return rates
    return _search(query, config)


def _search(query, config):
    cfg = config.get("search") or {}
    limit = int(cfg.get("results", 5))
    provider = str(cfg.get("provider", "duckduckgo")).lower()
    # Википедия — параллельно с поиском: для фактов («кто такой», «когда было») её
    # краткое содержание надёжнее обрывков сниппетов, а ждать её отдельно не нужно.
    wiki_box = {}
    wiki_thread = None
    if cfg.get("wikipedia", True):
        def fetch_wiki():
            try:
                wiki_box["item"] = wikipedia(query)
            except (OSError, ValueError) as error:
                print(f"[search] википедия: {error}")
        wiki_thread = threading.Thread(target=fetch_wiki, daemon=True)
        wiki_thread.start()
    if provider == "brave":
        results = _brave(query, limit, cfg)
    elif provider == "searxng":
        results = _searxng(query, limit, cfg)
    else:
        try:
            results = _duckduckgo(query, limit)
        except OSError:
            time.sleep(0.3)               # разовый сбой сети — вторая попытка
            results = _duckduckgo(query, limit)
    if wiki_thread is not None:
        # Википедия — дополнение: если не успела к концу веб-поиска (+1.2 с), отвечаем без неё.
        wiki_thread.join(timeout=1.2)
    wiki = wiki_box.get("item")
    if wiki:
        title, url, extract = wiki
        results = [f"{title}: {extract}"] + list(results)
        if url:
            SOURCES.append((title, url))
    if not results:
        return f"По запросу «{query}» ничего не найдено."
    return "\n".join(f"- {line}" for line in results)


# --------------------------------------------------------------- таймеры

_timers = []


def set_timer(seconds, label, on_fire):
    """Таймер в памяти: по истечении вызовет on_fire(label)."""
    seconds = max(1, int(seconds))
    timer = threading.Timer(seconds, on_fire, args=(label,))
    timer.daemon = True
    timer.start()
    _timers.append((time.monotonic() + seconds, label, timer))
    return seconds


def cancel_timers():
    for _, _, timer in _timers:
        timer.cancel()
    _timers.clear()


# ------------------------------------------------------------ разбор чисел

_NUMBERS = {
    "ноль": 0, "один": 1, "одна": 1, "одну": 1, "два": 2, "две": 2, "три": 3, "четыре": 4,
    "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10,
    "пятнадцать": 15, "двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50,
    "шестьдесят": 60, "семьдесят": 70, "восемьдесят": 80, "девяносто": 90, "сто": 100,
    "половина": 50, "половину": 50, "полностью": 100, "максимум": 100, "минимум": 1,
}


def number(text):
    """«50», «пятьдесят», «двадцать пять», «половину» -> число; None, если не число."""
    text = str(text).strip().lower().replace(",", ".")
    match = re.search(r"-?\d+(\.\d+)?", text)
    if match:
        return float(match.group())
    words = [_NUMBERS[w] for w in re.findall(r"[а-яё]+", text) if w in _NUMBERS]
    return float(sum(words)) if words else None


def number_exact(text):
    """Parse a device value in full; arbitrary text containing digits is invalid."""
    import math
    text = str(text).strip().lower().replace(",", ".")
    text = re.sub(r"\s*(?:%|процент|процента|процентов)$", "", text).strip()
    numeric = re.fullmatch(r"-?\d+(?:\.\d+)?", text)
    if not numeric and not (text and all(w in _NUMBERS for w in text.split())):
        return None
    value = number(text)
    return value if math.isfinite(value) else None
