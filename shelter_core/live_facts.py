"""Answer current weather and selected cryptocurrency quotes directly from data sources."""
import json
import math
import os
import re
import time
import urllib.parse

from shelter_core import policy
from shelter_core import tools


def _text(question):
    text = " ".join(question.casefold().replace("ё", "е").strip(" ,.?!").split())
    return re.sub(r"^(?:пожалуйста |скажи(?: мне)? |назови(?: мне)? |узнай |покажи(?: мне)? )+", "", text)


COINS = {
    "bitcoin": (r"биткоин[а]?|биткойн[а]?|btc|bitcoin", "биткоин (BTC)", "биткоина (BTC)"),
    "ethereum": (r"эфир(?:а)?|эфириум(?:а)?|этериум(?:а)?|ethereum|eth", "Ethereum (ETH)", "Ethereum (ETH)"),
    "solana": (r"солан[аыу]|solana|sol", "Solana (SOL)", "Solana (SOL)"),
    "dogecoin": (r"дог(?:е?коин)[а]?|dogecoin|doge", "Dogecoin (DOGE)", "Dogecoin (DOGE)"),
    "ripple": (r"рипл[а]?|ripple|xrp", "XRP", "XRP"),
    "binancecoin": (r"bnb", "BNB", "BNB"),
}
CURRENCIES = {
    "rub": (r"рубл(?:ях|и|ей)|руб|rub|rur|₽", "₽", "в рублях"),
    "usd": (r"доллар(?:ах|ы|ов)(?: сша)?|usd|us\$|\$", "$", "в долларах"),
    "eur": (r"евро|eur|€", "€", "в евро"),
}
_ASSET = "|".join(spec[0] for spec in COINS.values())
_CURRENCY = "|".join(spec[0] for spec in CURRENCIES.values())
_PRICE = r"(?:(?:какой|какая) )?(?:(?:текущий|текущая|актуальный|актуальная) )?(?:курс(?: у)?|цен[ау]|стоимость|(?:(?:what is|what's) (?:the )?)?price(?: of)?)"
_COST = r"(?:сколько (?:стоит|стоят)|почем|how much (?:is|does))"
_CURRENCY_TAIL = rf"(?:(?:\s+(?:(?:в|к|in|to)\s+)?|\s*[/–-]\s*)(?P<currency>{_CURRENCY}))?"


def quote_request(text):
    cleaned = " ".join(re.sub(r"\b(?:(?:на )?сегодня|сейчас|now|today|current|latest)\b", "", text).split())
    asset = rf"(?:1 |один |одна |одного )?(?P<asset>{_ASSET})"
    match = re.fullmatch(rf"(?:{_PRICE}|{_COST}) {asset}(?: cost)?{_CURRENCY_TAIL}", cleaned)
    if not match:
        match = re.fullmatch(rf"{asset} (?:{_PRICE}|сколько стоит|cost){_CURRENCY_TAIL}", cleaned)
    if not match:
        match = re.fullmatch(rf"{asset}\s*(?:/|\s+(?:в|in|to)\s+)\s*(?P<currency>{_CURRENCY})", cleaned)
    if not match:
        return None
    coin = next(key for key, spec in COINS.items() if re.fullmatch(spec[0], match["asset"]))
    currency = next((key for key, spec in CURRENCIES.items() if re.fullmatch(spec[0], match["currency"] or "")), "usd")
    return coin, currency


def quote(coin, currency):
    key = os.environ.get("COINGECKO_DEMO_API_KEY", "")
    query = urllib.parse.urlencode({"ids": coin, "vs_currencies": currency, "include_last_updated_at": "true"})
    data = json.loads(tools._get("https://api.coingecko.com/api/v3/simple/price?" + query,
                                 headers={"x-cg-demo-api-key": key} if key else None, timeout=6))[coin]
    if type(data[currency]) not in (int, float) or type(data["last_updated_at"]) not in (int, float):
        raise ValueError("Неверный формат котировки")
    price, timestamp = float(data[currency]), float(data["last_updated_at"])
    if not math.isfinite(price) or price <= 0 or not -60 <= time.time() - timestamp <= 1200:
        raise ValueError("Котировка отсутствует или устарела")
    precision = 0 if price >= 1000 else 2 if price >= 1 else 6
    amount = f"{price:,.{precision}f}".replace(",", " ").replace(".", ",")
    return f"По данным CoinGecko, 1 {COINS[coin][1]} стоит примерно {amount} {CURRENCIES[currency][1]}."


def answer(question, config):
    text = _text(question)
    requested = quote_request(text)
    if requested:
        if not policy.allowed(config, "search"):
            return "Веб-поиск выключен в настройках."
        coin, currency = requested
        try:
            return quote(coin, currency)
        except (OSError, ValueError, TypeError, KeyError) as error:
            print(f">> QUOTE  //  {type(error).__name__}", flush=True)
            return f"Не удалось получить свежий курс {COINS[coin][2]} {CURRENCIES[currency][2]}. Попробуйте чуть позже."

    match = re.fullmatch(r"(?:(?:какая|какая будет|какая сейчас|какая сегодня|какая завтра) )?погод[ау]"
                         r"(?: (.{1,140}))?", text)
    if not match:
        return None
    if not policy.allowed(config, "weather"):
        return "Прогноз погоды выключен в настройках."
    place = match[1] or ""
    period = next((day for word, day in (("послезавтра", 2), ("завтра", 1), ("сегодня", 0))
                   if re.search(r"\b" + word + r"\b", text)), "current")
    place = " ".join(re.sub(r"\b(?:послезавтра|завтра|сегодня|сейчас)\b", "", place).split())
    place = re.sub(r"^(?:в|во|по) ", "", place)
    try:
        return tools.weather(place, config, period=period)
    except LookupError:
        return f"Не нашёл место «{place}». Назовите город или страну."
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        return "Сейчас не удалось получить данные о погоде. Попробуйте позже."
