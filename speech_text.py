"""Русский текст для озвучки: числа, даты, единицы — словами и в нужном падеже.

Модель голоса читает цифры как придётся, поэтому всё переводится в слова здесь.
Падеж и род берутся из соседних слов (pymorphy3): «в 1 комнате» -> «в одной
комнате», «с 3 до 5 часов» -> «с трёх до пяти часов», «в 2026 году» -> «в две
тысячи двадцать шестом году», «до 1 декабря» -> «до первого декабря».
Нет pymorphy3 — числа читаются в именительном падеже, как раньше.
Текст в окне не меняется: это только то, что слышно.
"""
import re
from datetime import date

VERSION = 2
PRONUNCIATIONS = {}
ONES = ("ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять")
TEENS = ("десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать",
         "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать")
TENS = ("", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто")
HUNDREDS = ("", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот")
SCALES = ((10**9, "миллиард", False), (10**6, "миллион", False), (1000, "тысяча", True))

ORD_ONES = ("", "первый", "второй", "третий", "четвёртый", "пятый", "шестой", "седьмой", "восьмой", "девятый")
ORD_TEENS = ("десятый", "одиннадцатый", "двенадцатый", "тринадцатый", "четырнадцатый", "пятнадцатый",
             "шестнадцатый", "семнадцатый", "восемнадцатый", "девятнадцатый")
ORD_TENS = ("", "", "двадцатый", "тридцатый", "сороковой", "пятидесятый", "шестидесятый", "семидесятый",
            "восьмидесятый", "девяностый")
ORD_HUNDREDS = ("", "сотый", "двухсотый", "трёхсотый", "четырёхсотый", "пятисотый", "шестисотый",
                "семисотый", "восьмисотый", "девятисотый")
GENITIVE_STEMS = {1: "", 2: "двух", 3: "трёх", 4: "четырёх", 5: "пяти", 6: "шести", 7: "семи", 8: "восьми",
                  9: "девяти", 10: "десяти", 20: "двадцати", 30: "тридцати", 40: "сорока", 50: "пятидесяти",
                  60: "шестидесяти", 70: "семидесяти", 80: "восьмидесяти", 90: "девяноста", 100: "сто"}

MONTHS = ("", "января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября",
          "октября", "ноября", "декабря")
MONTH_LEMMAS = {"январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь",
                "октябрь", "ноябрь", "декабрь"}

# Какой падеж требует предлог перед числом (если существительное после числа не подскажет).
PREPOSITIONS = {
    "до": "gent", "от": "gent", "из": "gent", "с": "gent", "со": "gent", "около": "gent", "после": "gent",
    "без": "gent", "для": "gent", "у": "gent", "кроме": "gent", "более": "gent", "менее": "gent",
    "больше": "gent", "меньше": "gent", "свыше": "gent", "порядка": "gent", "вместо": "gent",
    "к": "datv", "ко": "datv", "согласно": "datv", "благодаря": "datv",
    "над": "ablt", "под": "ablt", "перед": "ablt", "между": "ablt",
    "о": "loct", "об": "loct", "при": "loct",
    "через": "accs", "за": "accs", "про": "accs", "на": "accs", "в": "accs", "во": "accs",
}
CASES = ("nomn", "gent", "datv", "accs", "ablt", "loct")
CASE_ALIAS = {"gen2": "gent", "loc2": "loct", "acc2": "accs", "voct": "nomn"}

# Сокращения после числа -> существительное (форма подбирается по числу и падежу).
UNITS = [
    ("км/ч", "километр", " в час"), ("м/с", "метр", " в секунду"), ("°C", "градус", " Цельсия"),
    ("°С", "градус", " Цельсия"), ("°", "градус", ""), ("%", "процент", ""), ("₽", "рубль", ""),
    ("руб.", "рубль", ""), ("руб", "рубль", ""), ("$", "доллар", ""), ("€", "евро", ""),
    ("ТБ", "терабайт", ""), ("ГБ", "гигабайт", ""), ("МБ", "мегабайт", ""), ("КБ", "килобайт", ""),
    ("ГГц", "гигагерц", ""), ("МГц", "мегагерц", ""), ("Гц", "герц", ""), ("Вт", "ватт", ""),
    ("км", "километр", ""), ("кг", "килограмм", ""), ("мс", "миллисекунда", ""), ("см", "сантиметр", ""),
    ("мм", "миллиметр", ""), ("м", "метр", ""), ("г.", "год", ""), ("ч", "час", ""), ("мин", "минута", ""),
    ("сек", "секунда", ""),("fps", "кадр", " в секунду"), ("FPS", "кадр", " в секунду"),
]
# Знак валюты перед числом: «$5» -> «5 долларов».
CURRENCY_BEFORE = {"$": "$", "€": "€", "₽": "₽"}
SUBUNIT = {"рубль": "копейка", "доллар": "цент", "евро": "цент"}
NOUN = "\x01"                 # маркер: «\x01километр» — существительное, форму подберём

_morph = None


def morph():
    global _morph
    if _morph is None:
        try:
            import pymorphy3
            _morph = pymorphy3.MorphAnalyzer()
        except Exception:
            _morph = False
    return _morph or None


def form(n, forms):
    n = abs(int(n))
    return forms[2] if 10 < n % 100 < 20 else forms[0] if n % 10 == 1 else forms[1] if n % 10 in (2, 3, 4) else forms[2]


def plural_class(n):
    n = abs(int(n))
    if 10 < n % 100 < 20:
        return "many"
    return "one" if n % 10 == 1 else "few" if n % 10 in (2, 3, 4) else "many"


# ------------------------------------------------------------------ склонение слов

def _inflect(word, grams, pos=None):
    m = morph()
    if not m:
        return word
    for p in m.parse(word):
        if pos and p.tag.POS not in pos:
            continue
        r = p.inflect(set(grams))
        if r:
            return r.word
    return word


def _noun(lemma, n, case):
    """Форма существительного после числа n в падеже case: «пять минут», «о пяти минутах»."""
    if lemma == "евро" or not morph():
        return lemma if lemma == "евро" else {"one": lemma}.get(plural_class(n), lemma)
    cls = plural_class(n)
    if case in ("nomn", "accs"):
        if cls == "one":
            return _inflect(lemma, {"sing", case}, {"NOUN"})
        return _inflect(lemma, {"sing" if cls == "few" else "plur", "gent"}, {"NOUN"})
    return _inflect(lemma, {"sing" if cls == "one" else "plur", case}, {"NOUN"})


def _gender(lemma):
    m = morph()
    if not m or lemma == "евро":
        return "masc"
    for p in m.parse(lemma):
        if p.tag.POS == "NOUN":
            return p.tag.gender or "masc"
    return "masc"


# ------------------------------------------------------------------ числительные

def _hundreds_words(n, gender="masc"):
    words = []
    if n >= 100:
        words.append(HUNDREDS[n // 100])
        n %= 100
    if n >= 20:
        words.append(TENS[n // 10])
        n %= 10
    if n >= 10:
        words.append(TEENS[n - 10])
    elif n:
        words.append({"femn": {1: "одна", 2: "две"}, "neut": {1: "одно"}}.get(gender, {}).get(n, ONES[n]))
    return words


def _case_word(word, case, gender):
    """Одно слово количественного числительного в падеже."""
    if case == "nomn":
        return word
    if word == "сто":
        return "сто" if case == "accs" else "ста"
    if word in ("один", "одна", "одно"):
        if case == "accs":
            return {"одна": "одну"}.get(word, word)
        return _inflect("один", {case, gender if gender in ("masc", "femn", "neut") else "masc"}, {"ADJF"})
    if case == "accs":
        return word
    return _inflect(word, {case}, {"NUMR"})


def integer(n, feminine=False, case="nomn", gender=None):
    """Количественное число словами: integer(21, case="gent") -> «двадцати одного»."""
    n = int(n)
    gender = gender or ("femn" if feminine else "masc")
    if n < 0:
        return "минус " + integer(-n, case=case, gender=gender)
    if n == 0:
        return ONES[0] if case == "nomn" else _inflect("ноль", {case}, {"NOUN"})
    if n >= 10**12:
        return " ".join(ONES[int(c)] for c in str(n))
    parts = []
    for divisor, scale, female in SCALES:
        count, n = divmod(n, divisor)
        if count:
            if not (count == 1 and scale == "тысяча"):        # «тысяча ночей», не «одна тысяча»
                parts += [_case_word(w, case, "femn" if female else "masc")
                          for w in _hundreds_words(count, "femn" if female else "masc")]
            parts.append(_noun(scale, count, case) if morph() else
                         form(count, {"тысяча": ("тысяча", "тысячи", "тысяч"),
                                      "миллион": ("миллион", "миллиона", "миллионов"),
                                      "миллиард": ("миллиард", "миллиарда", "миллиардов")}[scale]))
    parts += [_case_word(w, case, gender) for w in _hundreds_words(n, gender)]
    return " ".join(parts)


def _ordinal_base(n):
    """Порядковое в мужском именительном: 2026 -> «две тысячи двадцать шестой»."""
    n = int(n)
    head = []
    for divisor, scale, female in SCALES:
        count, rest = divmod(n, divisor)
        if count and rest == 0:
            # «двухтысячный», «трёхмиллионный»: число тысяч сливается с порядковым.
            if count == 1:
                stem = ""
            elif count in GENITIVE_STEMS and count < 100:
                stem = GENITIVE_STEMS[count]
            else:
                stem = integer(count, case="gent").replace(" ", "")
            head.append(stem + {"тысяча": "тысячный", "миллион": "миллионный", "миллиард": "миллиардный"}[scale])
            return " ".join(head)
        if count:
            if not (count == 1 and scale == "тысяча"):
                head += _hundreds_words(count, "femn" if female else "masc")
            head.append(form(count, {"тысяча": ("тысяча", "тысячи", "тысяч"),
                                     "миллион": ("миллион", "миллиона", "миллионов"),
                                     "миллиард": ("миллиард", "миллиарда", "миллиардов")}[scale]))
            n = rest
    if n >= 100:
        if n % 100 == 0:
            return " ".join(head + [ORD_HUNDREDS[n // 100]])
        head.append(HUNDREDS[n // 100])
        n %= 100
    if n >= 20:
        if n % 10 == 0:
            return " ".join(head + [ORD_TENS[n // 10]])
        head.append(TENS[n // 10])
        n %= 10
    if 10 <= n < 20:
        return " ".join(head + [ORD_TEENS[n - 10]])
    if n == 0:
        return " ".join(head + ["нулевой"])
    return " ".join(head + [ORD_ONES[n]])


def ordinal(n, case="nomn", gender="masc", number="sing"):
    """Порядковое: ordinal(1, "gent", "neut") -> «первого»; меняется только последнее слово."""
    words = _ordinal_base(n).split()
    grams = {case, number} if number == "plur" else {case, gender}
    if (case, gender, number) != ("nomn", "masc", "sing"):
        words[-1] = _inflect(words[-1], grams, {"ADJF"})
    return " ".join(words)


def number(text):
    """Дробное число словами (именительный): «6.5» -> «шесть целых пять десятых»."""
    text = text.replace(",", ".")
    if "." not in text:
        return integer(text)
    whole, fraction = text.split(".", 1)
    denominators = {1: "десятых", 2: "сотых", 3: "тысячных", 4: "десятитысячных", 5: "стотысячных", 6: "миллионных"}
    if len(fraction) in denominators:
        negative = whole.startswith("-")
        count = abs(int(whole))
        return ("минус " if negative else "") + integer(count, True) + " " + form(count, ("целая", "целых", "целых")) \
            + " " + integer(int(fraction), True) + " " + denominators[len(fraction)]
    return integer(whole) + " запятая " + " ".join(ONES[int(c)] for c in fraction)


# ------------------------------------------------------------------ разбор контекста

WORD = re.compile(r"[а-яёА-ЯЁa-zA-Z\x01]+")


def _prev_word(text, start):
    m = re.search(r"([а-яёА-ЯЁ]+)[^\w\x01]*$", text[:start])
    if not m:
        return ""
    word = m.group(1).lower()
    return "" if word == "минус" else word


def _next_word(text, end):
    m = re.match(r"\s*(\x01?[а-яёА-ЯЁ]+)", text[end:])
    return (m.group(1), end + m.end()) if m else ("", end)


def _parses(word):
    m = morph()
    if not m or not word:
        return []
    return [p for p in m.parse(word.lower()) if p.tag.POS in ("NOUN", "ADJF", "PRTF")]


def _noun_cases(word, n):
    """Какой падеж у числа по форме существительного после него: [(падеж, род, парс)]."""
    cls = plural_class(n)
    out = []
    for p in _parses(word):
        if p.tag.POS != "NOUN":
            continue
        case = CASE_ALIAS.get(p.tag.case, p.tag.case)
        num = p.tag.number
        gender = p.tag.gender or "masc"
        if cls == "one" and num == "sing":
            out.append((case, gender, p))
        elif cls == "few" and num == "sing" and case == "gent":
            out.append(("nomn", gender, p))
        elif cls == "many" and num == "plur" and case == "gent":
            out.append(("nomn", gender, p))
        if cls != "one" and num == "plur" and case in ("gent", "datv", "ablt", "loct"):
            out.append((case, gender, p))
    return out


def _choose(candidates, preposition):
    if not candidates:
        return None
    wanted = PREPOSITIONS.get(preposition)
    for case, gender, p in candidates:
        if case == wanted or (wanted == "accs" and case == "nomn"):
            return case if case != "nomn" or wanted != "accs" else "accs", gender, p
    for preferred in ("nomn", "accs", "loct", "datv", "ablt", "gent"):
        for case, gender, p in candidates:
            if case == preferred:
                return case, gender, p
    return candidates[0]


def _is_lemma(word, lemmas):
    return any(p.normal_form in lemmas for p in _parses(word))


SUFFIX = {"й": ("nomn", "masc"), "ый": ("nomn", "masc"), "ий": ("nomn", "masc"), "ой": ("nomn", "masc"),
          "я": ("nomn", "femn"), "ая": ("nomn", "femn"), "е": ("nomn", "neut"), "ое": ("nomn", "neut"),
          "го": ("gent", "masc"), "му": ("datv", "masc"), "м": ("loct", "masc"), "ю": ("accs", "femn"),
          "х": ("gent", "plur"), "ые": ("nomn", "plur"), "ых": ("gent", "plur")}


def _say_integer(text, match):
    """Целое число в контексте -> слова (и форма маркера-существительного после него)."""
    raw, suffix = match.group(1), (match.group(2) or "").lower()
    n = int(re.sub(r"\D", "", raw))
    negative = text[max(0, match.start() - 1):match.start()] == "-" and not re.match(
        r"\w", text[max(0, match.start() - 2):max(0, match.start() - 1)] or " ")
    prep = _prev_word(text, match.start() - (1 if negative else 0))
    nxt, nxt_end = _next_word(text, match.end())
    sign = "минус " if negative else ""
    start = match.start() - (1 if negative else 0)

    if not morph():
        return start, match.end(), sign + integer(n)

    # Порядковое: «1-й», «3-я», «1990-х».
    if suffix:
        case, gender = SUFFIX.get(suffix, ("nomn", "masc"))
        number_ = "plur" if gender == "plur" else "sing"
        if gender == "plur":
            gender = "masc"
        if nxt and not nxt.startswith(NOUN):
            # Окончание задаёт падеж; существительное уточняет род, а у «-х», «-м», «-е»
            # (разные падежи) — и падеж: «в 1990-х годах», «на 5-м этаже».
            loose = suffix in ("х", "ых", "м", "е", "ые")
            for p in _parses(nxt):
                p_case = CASE_ALIAS.get(p.tag.case, p.tag.case)
                if loose and (number_ != "plur" or p.tag.number == "plur"):
                    case = p_case or case
                    number_ = p.tag.number or number_
                elif p_case != case:
                    continue
                gender = p.tag.gender or gender
                break
        return start, match.end(), sign + ordinal(n, case, gender, number_)

    # Дата: «1 декабря» -> «первое декабря», «до 1 декабря» -> «до первого декабря».
    if nxt and not nxt.startswith(NOUN) and 1 <= n <= 31 and _is_lemma(nxt, MONTH_LEMMAS):
        case = PREPOSITIONS.get(prep, "nomn")
        return start, match.end(), ordinal(n, case, "neut")

    # Год: «2026 год», «в 2026 году», «с 2020 года», «2026 г.».
    year_word = nxt[1:] if nxt.startswith(NOUN) else nxt
    if year_word and _is_lemma(year_word, {"год"}) and (n >= 1000 or prep in ("в", "с", "до", "к", "от")):
        if nxt.startswith(NOUN):
            case = {"в": "loct", "во": "loct"}.get(prep, PREPOSITIONS.get(prep, "nomn"))
            word = _inflect("год", {case if case != "accs" else "nomn", "sing"}, {"NOUN"})
            if case == "loct":
                word = "году"
            return start, nxt_end, f"{sign}{ordinal(n, case)} {word}"
        p = _parses(year_word)[0]
        case = CASE_ALIAS.get(p.tag.case, p.tag.case) or "nomn"
        if case == "datv" and prep in ("в", "во"):
            case = "loct"
        return start, match.end(), sign + ordinal(n, case, "masc", p.tag.number or "sing")

    # Сокращение-единица: падеж — от предлога, форма — от числа.
    if nxt.startswith(NOUN):
        lemma = nxt[1:]
        case = PREPOSITIONS.get(prep, "nomn")
        gender = _gender(lemma)
        words = integer(n, case=case, gender=gender)
        return start, nxt_end, f"{sign}{words} {_noun(lemma, n, case)}"

    # Обычное существительное после числа: падеж и род — по его форме.
    chosen = _choose(_noun_cases(nxt, n), prep)
    if chosen:
        case, gender, _p = chosen
        return start, match.end(), sign + integer(n, case=case, gender=gender)
    # Форма существительного не подходит количественному — значит, порядковое:
    # «2 серию» -> «вторую серию», «5 этаж» -> «пятый этаж».
    singular = [p for p in _parses(nxt) if p.tag.POS == "NOUN" and p.tag.number == "sing"]
    if singular and not negative:
        p = singular[0]
        return start, match.end(), ordinal(n, CASE_ALIAS.get(p.tag.case, p.tag.case) or "nomn", p.tag.gender or "masc")
    case = PREPOSITIONS.get(prep, "nomn")
    return start, match.end(), sign + integer(n, case=case if case != "accs" else "nomn")


# ------------------------------------------------------------------ подготовка

def _calendar(match):
    day, month, year = map(int, match.groups())
    try:
        date(year, month, day)
    except ValueError:
        return match[0]
    return f"{day} {MONTHS[month]} {year} года"


def _money(match):
    """«92,45 ₽» -> «92 \x01рубль 45 \x01копейка»; «$3.50» — так же."""
    sign_before, whole, cents, sign_after = match.groups()
    unit = dict((u, lemma) for u, lemma, _ in UNITS)[sign_before or sign_after]
    out = f"{whole} {NOUN}{unit}"
    if cents and int(cents):
        cents = cents.ljust(2, "0")[:2]
        out += f" {int(cents)} {NOUN}{SUBUNIT[unit]}"
    return out


def _decimal_with_unit(match):
    """«6.5 ГБ» -> «шесть целых пять десятых гигабайта» (после дроби — родительный ед. ч.)."""
    value, unit = match.group(1), match.group(2)
    lemma, tail = next((lemma, tail) for u, lemma, tail in UNITS if u == unit)
    noun = _inflect(lemma, {"sing", "gent"}, {"NOUN"}) if morph() else lemma
    return f"{number(value)} {noun}{tail}"


def prepare_for_speech(text):
    text = str(text)
    for word, spoken in PRONUNCIATIONS.items():
        text = re.sub(r"(?<!\w)" + re.escape(word) + r"(?!\w)", lambda m: spoken, text, flags=re.I)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[`*_#]", "", text)
    text = text.replace(" ", " ").replace("−", "-").replace(" ", " ")
    # Знак ударения (U+0301) клон голоса читает как лишний звук («зама йок») — убрать.
    text = text.replace("́", "")
    # 1 000 000 -> 1000000
    text = re.sub(r"(?<![\d.,])(\d{1,3})((?: \d{3})+)(?![\d.,])", lambda m: m[1] + m[2].replace(" ", ""), text)
    text = re.sub(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", _calendar, text)
    # Версии — идентификаторы, а не дроби.
    text = re.sub(r"\b(v|[Вв]ерсия\s+)(\d+(?:\.\d+)+)",
                  lambda m: ("версия " if m[1].lower() == "v" else m[1]) + " точка ".join(integer(p) for p in m[2].split(".")), text)
    # Телефоны — по цифрам.
    text = re.sub(r"\+\d[\d ()-]{8,}\d", lambda m: "плюс " + " ".join(
        ONES[int(c)] for c in m[0] if c.isdigit()), text)
    # Время 18:30 -> «18 часов 30 минут»; счёт 2:1 -> «2 — 1».
    def clock(m):
        hours, minutes = int(m[1]), int(m[2])
        return f"{hours} {NOUN}час" + (f" {minutes} {NOUN}минута" if minutes else "")
    text = re.sub(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", clock, text)
    text = re.sub(r"\b(\d+):(\d+)\b", r"\1 — \2", text)
    # Деньги с копейками/центами.
    text = re.sub(r"(?:([$€₽])\s?)?(?<![\d.,])(\d+)[.,](\d{1,2})(?:\s?(₽|руб\.?|\$|€))?(?![\w\d])",
                  lambda m: _money(m) if (m[1] or m[4]) else m[0], text)
    text = re.sub(r"([$€₽])\s?(\d+)(?!\d|[.,]\d)", lambda m: f"{m[2]} {NOUN}" + dict(
        (u, lemma) for u, lemma, _ in UNITS)[m[1]], text)
    # «+5» о погоде — «плюс пять».
    text = re.sub(r"(?<![\w\d])\+(\d)", r"плюс \1", text)
    # Дробь с единицей.
    units = "|".join(re.escape(u) for u, _, _ in UNITS)
    text = re.sub(r"(-?\d+[.,]\d+)\s?(" + units + r")(?![\w/])", _decimal_with_unit, text)
    # Целое с единицей -> маркер существительного (+ хвост «в секунду»).
    tails = {u: (lemma, tail) for u, lemma, tail in UNITS}

    def unit(m):
        lemma, tail = tails[m[2]]
        return f"{m[1]} {NOUN}{lemma}{NOUN}{tail}" if tail else f"{m[1]} {NOUN}{lemma}"
    text = re.sub(r"(\d+)\s?(" + units + r")(?![\wа-яё/])", unit, text)
    # Оставшиеся дроби — в именительном.
    text = re.sub(r"(?<![\w.,])-?\d+[.,]\d+(?![\w.,]*\d)", lambda m: number(m[0]), text)
    # Целые (и порядковые «1-й») — по одному, с учётом соседей.
    pattern = re.compile(r"(?<![\w.,])(\d+)(?:-(й|ый|ий|ой|я|ая|е|ое|го|му|м|ю|х|ые|ых))?(?![\w])")
    while True:
        m = pattern.search(text)
        if not m:
            break
        start, end, words = _say_integer(text, m)
        text = text[:start] + words + text[end:]
    text = text.replace(NOUN, "")
    return re.sub(r"\s+", " ", text).strip()


def split_for_speech(text, limit=450):
    text = prepare_for_speech(text)
    while len(text) > limit:
        cut = max(text.rfind(mark, 0, limit) for mark in (". ", "! ", "? ", "; ", ", ", " "))
        cut = cut + 1 if cut > 0 else limit
        yield text[:cut].strip()
        text = text[cut:].strip()
    if text:
        yield text
