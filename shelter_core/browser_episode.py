"""Intent for the foreground browser player's native Next control."""
import re


def matches(text):
    phrase = " ".join(re.sub(r"[,.?!;:]+", " ", text.lower().replace("ё", "е")).split())
    return bool(re.fullmatch(
        r"(?:(?:пожалуйста|давай|можешь) )?(?:(?:включи|вруби|включить|поставь|открой|запусти|переключи(?:сь)?(?: на)?|перейди на|на) )?"
        r"следующ(?:ая|ую|ий) (?:серию|серия|эпизод)(?: аниме)?(?: пожалуйста)?|(?:play )?next episode", phrase))
