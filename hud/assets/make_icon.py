"""Иконка Джарвиса (реактор) для exe, трея и ярлыков: python make_icon.py -> jarvis.ico.

Нужен Pillow. Рисуется в 1024 px и уменьшается — края получаются гладкими.
"""
import math
import os

from PIL import Image, ImageDraw, ImageFilter

S = 1024
C = S / 2


def ring(draw, r, width, color, start=0, end=360):
    box = (C - r, C - r, C + r, C + r)
    draw.arc(box, start, end, fill=color, width=width)


def make():
    base = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(base)
    d.ellipse((24, 24, S - 24, S - 24), fill=(4, 12, 20, 255))
    d.ellipse((24, 24, S - 24, S - 24), outline=(31, 111, 140, 255), width=22)

    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    for i in range(4):                       # внешние дуги
        start = i * 90 + 12
        ring(g, 400, 46, (55, 179, 216, 255), start, start + 62)
    for i in range(3):                       # средние дуги
        start = i * 120 + 40
        ring(g, 318, 34, (127, 230, 255, 255), start, start + 84)
    for i in range(36):                      # засечки
        a = math.radians(i * 10)
        r1, r2 = 238, 262 if i % 3 == 0 else 252
        g.line((C + r1 * math.cos(a), C + r1 * math.sin(a), C + r2 * math.cos(a), C + r2 * math.sin(a)),
               fill=(55, 179, 216, 255), width=12 if i % 3 == 0 else 7)
    for k, (r, col) in enumerate([(200, (15, 74, 95)), (165, (23, 122, 153)), (130, (43, 168, 205)),
                                  (95, (95, 212, 242)), (60, (223, 248, 255))]):
        g.ellipse((C - r, C - r, C + r, C + r), fill=col + (255,))
    blurred = glow.filter(ImageFilter.GaussianBlur(18))
    base = Image.alpha_composite(base, blurred)
    base = Image.alpha_composite(base, glow)
    return base


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    image = make()
    image.save(os.path.join(here, "jarvis.ico"),
               sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)])
    image.resize((256, 256), Image.LANCZOS).save(os.path.join(here, "jarvis.png"))
    print("ok")
