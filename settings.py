"""Окно настроек Джарвиса: правит config.yaml, сохраняя комментарии.

python settings.py
"""

import argparse
import io
import os
import re
import tempfile
import tkinter as tk

import yaml
from ruamel.yaml import YAML

CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")

BG = "#04090f"
PANEL = "#071219"
PANEL_HI = "#0b202c"
LINE = "#164e63"
DIM = "#1f6f8c"
MID = "#37b3d8"
BRIGHT = "#7fe6ff"
WHITE = "#dff8ff"
AMBER = "#ffb648"
GREEN = "#5ef2a0"
MONO = "Consolas"

GENERAL_HELP = {
    ("companion", "enabled"): (
        "Мобильный пульт",
        "Разрешает управлять командами и профилями Jarvis с телефона в вашей локальной сети. "
        "Если пульт не используется, оставьте выключенным — фоновый веб-сервер запускаться не будет."),
    ("llm", "enabled"): (
        "Режим ИИ",
        "Позволяет задавать свободные вопросы после обращения «Джарвис», если фраза не совпала с обычной командой. "
        "Для работы нужен настроенный локальный или облачный провайдер."),
    ("llm", "provider"): (
        "Провайдер нейросети",
        "local — модель работает через локальный совместимый сервер и не отправляет речь в облако. "
        "anthropic — используется облачный сервис; потребуются интернет и ключ API."),
    ("llm", "model"): (
        "Модель нейросети",
        "Точное системное имя модели у выбранного провайдера, например llama3.1. Если имя неверное или модель не установлена, "
        "ответы ИИ работать не будут, но обычные команды сохранятся."),
    ("detector", "requires_wake"): (
        "Защита звукового триггера",
        "Если включено, открытие банки запускает сценарий только после обращения «Джарвис» и пока открыт режим ожидания команды. "
        "Если выключить, детектор сможет запускать сценарий постоянно в фоновом режиме — случайный похожий звук тоже может активировать его."),
    ("detector", "threshold"): (
        "Порог детектора банки",
        "Минимальная уверенность классификатора от 0.30 до 0.99. Выше — меньше ложных срабатываний, но тихое открытие можно пропустить. "
        "Ниже — детектор чувствительнее, однако чаще ошибается. Текущее рабочее значение обычно лучше менять небольшими шагами."),
    ("detector", "onset_factor"): (
        "Чувствительность звукового гейта",
        "Во сколько раз резкий высокочастотный звук должен быть громче фонового шума, прежде чем включится классификатор. "
        "Увеличьте при ложных срабатываниях; уменьшите, если открытие банки не замечается."),
    ("detector", "cooldown"): (
        "Пауза после срабатывания",
        "Количество секунд, в течение которых повторные открытия игнорируются. Защищает от нескольких запусков одного режима из-за эха "
        "или нескольких щелчков одного звука. Значение 0 отключает защитную паузу."),
    ("wake", "follow_up"): (
        "Ожидание команды",
        "Сколько секунд Jarvis продолжает слушать после отдельного обращения по имени. Если команда не прозвучит, интерфейс закроется. "
        "Значение 0 означает ожидание без ограничения времени."),
    ("tts", "speaker"): (
        "Голос Silero",
        "Голос, которым синтезируются фразы без готового WAV-файла. Изменение не влияет на заранее записанные реплики. "
        "Новый голос начнёт использоваться после перезапуска ассистента."),
    ("ui", "layout"): (
        "Вид окна",
        "auto — большое окно, а во время полноэкранной игры, видео или презентации — компактно. "
        "full — всегда большое окно, orb — всегда маленький анимированный круг в углу экрана."),
    ("ui", "busy"): (
        "Когда вы заняты",
        "orb — круг в углу поверх игры. monitor — большое окно на другом мониторе, "
        "если он подключён (иначе всё равно круг)."),
    ("location", "city"): (
        "Ваш город",
        "Для вопросов вроде «какая погода» без названия города. auto — определить по IP-адресу; "
        "с VPN это будет город сервера, поэтому лучше вписать свой."),
    ("smarthome", "enabled"): (
        "Умный дом",
        "Управление светом, розетками и техникой голосом через Home Assistant, Яндекс, Tuya или "
        "веб-адреса. Подключение и список устройств — в разделе smarthome файла config.yaml."),
    ("ui", "mode"): (
        "Интерфейс ассистента",
        "hud — стандартное окно Jarvis со статусом системы. vtube_studio — управление Live2D-моделью через VTube Studio. "
        "Для второго варианта дополнительно заполните раздел «Аватар»."),
}

NAV_HELP = {
    "general": "Основные параметры речи, нейросети, детектора звука и интерфейса.",
    "commands": "Голосовые фразы и цепочки действий, которые Jarvis выполняет в ответ.",
    "profiles": "Переиспользуемые наборы действий, которые можно запускать одной командой.",
    "avatar": "Выбор HUD или Live2D-модели и подключение к VTube Studio.",
}

ACTION_HELP = {
    "say": ("Произнести фразу", "Jarvis озвучит указанный текст.", "Введите текст, например: Добрый вечер, сэр."),
    "url": ("Открыть ссылку", "Откроет сайт или зарегистрированный адрес приложения в системе.",
            "Введите адрес, например: https://example.com или spotify:playlist:ID."),
    "launch": ("Запустить программу", "Запустит обычный исполняемый файл или ярлык.",
               r"Введите полный путь, например: C:\Program Files\App\app.exe."),
    "overlay": ("Показать HUD", "Покажет интерфейс Jarvis с указанной надписью примерно на 6 секунд.",
                "Введите короткий заголовок, например: GAMING MODE."),
    "media": ("Управлять медиаплеером", "Отправит системную мультимедийную команду.",
              "Введите play, pause, next, previous, volup или voldown."),
    "profile": ("Запустить профиль", "Выполнит все действия из выбранного профиля по порядку.",
                "Введите внутреннее имя профиля из раздела «Профили»."),
    "plugin": ("Запустить плагин", "Вызовет разрешённый пользовательский плагин из папки plugins.",
               "Введите имя файла без .py. Плагины должны быть разрешены в разделе security конфигурации."),
    "close": ("Закрыть HUD", "Закроет интерфейс Jarvis. Дополнительное значение для этого действия не требуется.",
              "Оставьте поле значения пустым."),
}

ROUNDTRIP_YAML = YAML()
ROUNDTRIP_YAML.preserve_quotes = True
ROUNDTRIP_YAML.width = 120

# (раздел, ключ, подпись, тип, варианты)
FIELDS = [
    ("companion", "enabled", "Мобильный пульт", "bool", None),
    ("llm", "enabled", "Режим ИИ", "bool", None),
    ("llm", "provider", "Провайдер", "choice", ["ollama", "openai", "anthropic"]),
    ("llm", "model", "Модель", "text", None),
    ("detector", "requires_wake", "Детектор только после «Джарвис»", "bool", None),
    ("detector", "threshold", "Порог детектора", "float", (0.3, 0.99)),
    ("detector", "onset_factor", "Чувствительность гейта", "float", (2.0, 20.0)),
    ("detector", "cooldown", "Пауза после срабатывания, с", "float", (0.0, 60.0)),
    ("wake", "follow_up", "Лимит ожидания, с (0 — нет)", "float", (0.0, 120.0)),
    ("tts", "engine", "Синтез речи", "choice", ["files", "clone", "silero"]),
    ("ui", "hud", "Окно HUD", "choice", ["rust", "python"]),
    ("ui", "fps", "Кадров в секунду окна", "float", (15.0, 60.0)),
    ("ui", "layout", "Вид окна", "choice", ["auto", "full", "orb"]),
    ("ui", "busy", "Когда вы заняты", "choice", ["orb", "monitor"]),
    ("location", "city", "Ваш город (погода)", "text", None),
    ("smarthome", "enabled", "Умный дом", "bool", None),
    ("tts", "speaker", "Голос silero", "choice",
     ["aidar", "baya", "kseniya", "xenia", "eugene"]),
    ("ui", "mode", "Интерфейс", "choice", ["hud", "vtube_studio"]),
]


def load_document():
    with open(CONFIG, encoding="utf-8") as file:
        return ROUNDTRIP_YAML.load(file) or {}


def dump_yaml_fragment(value):
    """Показать часть ruamel-документа в редакторе без потери совместимости."""
    stream = io.StringIO()
    ROUNDTRIP_YAML.dump(value, stream)
    return stream.getvalue()


def save_document(data):
    """Сохранить конфиг атомарно: сбой не оставит пустой config.yaml."""
    folder = os.path.dirname(CONFIG)
    handle, temporary = tempfile.mkstemp(prefix="config_", suffix=".yaml", dir=folder)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as file:
            ROUNDTRIP_YAML.dump(data, file)
        os.replace(temporary, CONFIG)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def read_value(text, section, key):
    """Значение ключа внутри раздела верхнего уровня."""
    block = re.search(rf"(?m)^{section}:\n((?:[ \t].*\n|\n)*)", text)
    if not block:
        return None
    found = re.search(rf"(?m)^\s+{key}:\s*(.*?)\s*(?:#.*)?$", block.group(1))
    return found.group(1).strip() if found else None


def write_value(text, section, key, value):
    """Заменить значение, не трогая отступы и комментарий в конце строки."""
    block = re.search(rf"(?m)^{section}:\n((?:[ \t].*\n|\n)*)", text)
    if not block:
        return text
    start, body = block.start(1), block.group(1)
    found = re.search(rf"(?m)^(\s+{key}:\s*)(.*?)(\s*(?:#.*)?)$", body)
    if not found:
        return text
    head, tail = found.group(1), found.group(3)
    line = f"{head}{value}{tail}"
    return text[:start + found.start()] + line + text[start + found.end():]


def parse_bool(raw):
    return str(raw).strip().lower() in ("true", "yes", "on", "1")


class TooltipManager:
    """Одна переиспользуемая подсказка без отдельного окна в панели задач."""

    def __init__(self, root, delay=420):
        self.root = root
        self.delay = delay
        self.pending = None
        self.anchor = None
        self.title_source = ""
        self.text_source = ""
        self.window = None
        self.title_label = None
        self.text_label = None

    def attach(self, widget, title, text):
        widget.bind("<Enter>", lambda _event, item=widget: self.schedule(item, title, text), add="+")
        widget.bind("<Leave>", lambda _event: self.hide(), add="+")
        widget.bind("<ButtonPress>", lambda _event: self.hide(), add="+")
        widget.bind("<FocusIn>", lambda _event, item=widget: self.schedule(item, title, text), add="+")
        widget.bind("<FocusOut>", lambda _event: self.hide(), add="+")

    def attach_many(self, widgets, title, text):
        for widget in widgets:
            self.attach(widget, title, text)

    @staticmethod
    def _resolve(source):
        return str(source() if callable(source) else source)

    def schedule(self, widget, title, text):
        self.hide()
        self.anchor = widget
        self.title_source = title
        self.text_source = text
        self.pending = self.root.after(self.delay, self.show)

    def _create(self):
        self.window = tk.Toplevel(self.root, bg=LINE, bd=0)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.transient(self.root)
        try:
            self.window.attributes("-topmost", True)
        except tk.TclError:
            pass
        card = tk.Frame(self.window, bg="#091821", highlightbackground=BRIGHT,
                        highlightthickness=1, padx=14, pady=11)
        card.pack(fill="both", expand=True, padx=1, pady=1)
        self.title_label = tk.Label(card, bg="#091821", fg=AMBER,
                                    font=(MONO, 9, "bold"), anchor="w")
        self.title_label.pack(fill="x")
        tk.Frame(card, bg=LINE, height=1).pack(fill="x", pady=(7, 8))
        self.text_label = tk.Label(card, bg="#091821", fg=WHITE, font=(MONO, 9),
                                   justify="left", anchor="w", wraplength=390)
        self.text_label.pack(fill="x")

    def show(self):
        self.pending = None
        if self.anchor is None or not self.anchor.winfo_exists():
            return
        if self.window is None or not self.window.winfo_exists():
            self._create()
        self.title_label.configure(text=self._resolve(self.title_source).upper())
        self.text_label.configure(text=self._resolve(self.text_source))
        self.window.update_idletasks()

        x = self.root.winfo_pointerx() + 18
        y = self.root.winfo_pointery() + 20
        width = self.window.winfo_reqwidth()
        height = self.window.winfo_reqheight()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        if x + width > screen_w - 10:
            x = max(10, self.root.winfo_pointerx() - width - 14)
        if y + height > screen_h - 10:
            y = max(10, self.root.winfo_pointery() - height - 14)
        self.window.geometry(f"+{x}+{y}")
        self.window.deiconify()
        self.window.lift()

    def hide(self):
        if self.pending is not None:
            try:
                self.root.after_cancel(self.pending)
            except tk.TclError:
                pass
            self.pending = None
        self.anchor = None
        if self.window is not None and self.window.winfo_exists():
            self.window.withdraw()


class Settings:
    def __init__(self, root):
        self.root = root
        self.text = io.open(CONFIG, encoding="utf-8").read()
        self.vars = {}
        self.tooltips = TooltipManager(root)
        self.build()

    def build(self):
        root = self.root
        root.configure(bg=BG)
        root.title("JARVIS SETTINGS")
        root.geometry("1120x720")
        root.minsize(920, 620)

        head = tk.Frame(root, bg=PANEL_HI, highlightthickness=0)
        head.pack(fill="x")
        tk.Label(head, text="J . A . R . V . I . S", bg=PANEL_HI, fg=WHITE,
                 font=(MONO, 16, "bold")).pack(side="left", padx=22, pady=14)
        self.page_title = tk.Label(head, text="GENERAL", bg=PANEL_HI, fg=AMBER,
                                   font=(MONO, 10, "bold"))
        self.page_title.pack(side="left")

        shell = tk.Frame(root, bg=BG)
        shell.pack(fill="both", expand=True)
        sidebar = tk.Frame(shell, width=190, bg="#061017",
                           highlightbackground=LINE, highlightthickness=1)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        self.page_host = tk.Frame(shell, bg=BG)
        self.page_host.pack(side="left", fill="both", expand=True)

        self.pages = {}
        general = tk.Frame(self.page_host, bg=BG)
        self._build_general(general)
        self.pages["general"] = general
        self.pages["commands"] = StructuredEditor(self, "commands")
        self.pages["profiles"] = StructuredEditor(self, "profiles")
        self.pages["avatar"] = AvatarEditor(self)

        self.nav_buttons = {}
        for key, label in (("general", "ОБЩИЕ"), ("commands", "КОМАНДЫ"),
                           ("profiles", "ПРОФИЛИ"), ("avatar", "АВАТАР")):
            button = tk.Button(
                sidebar, text=label, command=lambda page=key: self.show_page(page),
                bg="#061017", fg=DIM, activebackground=PANEL_HI,
                activeforeground=WHITE, relief="flat", bd=0, anchor="w",
                padx=20, pady=13, font=(MONO, 10, "bold"), cursor="hand2")
            button.pack(fill="x", padx=8, pady=3)
            self.nav_buttons[key] = button
            self.tooltips.attach(button, label, NAV_HELP[key])

        tk.Frame(sidebar, bg=LINE, height=1).pack(fill="x", padx=16, pady=12)
        storage_note = tk.Label(sidebar, text="ⓘ  Наведите на любой\nпараметр для справки\n\nВсе изменения хранятся\nлокально в config.yaml",
                                bg="#061017", fg=DIM, justify="left",
                                font=(MONO, 8))
        storage_note.pack(anchor="w", padx=20)
        self.tooltips.attach(
            storage_note, "Локальная конфигурация",
            "Настройки записываются только в config.yaml в папке Jarvis. Они не отправляются в интернет. "
            "Большинство изменений применяется после перезапуска ассистента.")

        foot = tk.Frame(root, bg=PANEL_HI)
        foot.pack(fill="x")
        self.note = tk.Label(foot, text="изменения применятся после перезапуска ассистента",
                             bg=PANEL_HI, fg=DIM, font=(MONO, 8))
        self.note.pack(side="left", padx=18, pady=13)
        save_button = tk.Button(foot, text="СОХРАНИТЬ ОБЩИЕ", command=self.save, bg=MID, fg=BG,
                                relief="flat", font=(MONO, 9, "bold"), padx=16,
                                activebackground=BRIGHT, cursor="hand2")
        save_button.pack(side="right", padx=12, pady=8)
        close_button = tk.Button(foot, text="ЗАКРЫТЬ", command=self.root.destroy, bg=PANEL,
                                 fg=DIM, relief="flat", font=(MONO, 9), padx=16,
                                 activebackground=LINE, cursor="hand2")
        close_button.pack(side="right", pady=8)
        self.tooltips.attach(
            save_button, "Сохранить общие настройки",
            "Записывает параметры раздела «Общие» в config.yaml. Перезапустите Jarvis, чтобы работающие модули перечитали значения.")
        self.tooltips.attach(
            close_button, "Закрыть настройки",
            "Закрывает это окно. Несохранённые изменения в текущем разделе будут потеряны.")
        self.show_page("general")

    def _build_general(self, body):
        intro = tk.Frame(body, bg=BG)
        intro.pack(fill="x", padx=24, pady=(22, 12))
        tk.Label(intro, text="ОБЩИЕ НАСТРОЙКИ", bg=BG, fg=WHITE,
                 font=(MONO, 15, "bold")).pack(anchor="w")
        tk.Label(intro, text="Речь, детектор, интерфейс и мобильный пульт",
                 bg=BG, fg=DIM, font=(MONO, 9)).pack(anchor="w", pady=(3, 0))

        grid = tk.Frame(body, bg=BG)
        grid.pack(fill="both", expand=True, padx=24, pady=(0, 20))

        for index, (section, key, label, kind, extra) in enumerate(FIELDS):
            raw = read_value(self.text, section, key)
            if raw is None:
                continue
            row = tk.Frame(grid, bg=PANEL, highlightbackground=LINE,
                           highlightthickness=1)
            column, line = index % 2, index // 2
            row.grid(row=line, column=column, sticky="nsew", padx=5, pady=5)
            grid.grid_columnconfigure(column, weight=1, uniform="settings")
            label_widget = tk.Label(row, text=label.upper(), bg=PANEL, fg=DIM, anchor="w",
                                    font=(MONO, 9))
            label_widget.pack(side="left", padx=(10, 5), pady=6)
            help_widget = tk.Label(row, text="?", bg=PANEL_HI, fg=BRIGHT,
                                   font=(MONO, 8, "bold"), padx=5, pady=1,
                                   cursor="question_arrow")
            help_widget.pack(side="left", padx=(0, 4))

            if kind == "bool":
                var = tk.BooleanVar(value=parse_bool(raw))
                widget = tk.Checkbutton(
                    row, variable=var, bg=PANEL, fg=GREEN, activebackground=PANEL,
                    selectcolor=BG, highlightthickness=0, text="ВКЛ / ВЫКЛ",
                    font=(MONO, 9), anchor="w")
            elif kind == "choice":
                var = tk.StringVar(value=raw.strip('"'))
                widget = tk.OptionMenu(row, var, *extra)
                widget.configure(bg=PANEL_HI, fg=WHITE, highlightthickness=0,
                                 activebackground=MID, font=(MONO, 9), width=12)
                widget["menu"].configure(bg=PANEL_HI, fg=WHITE, font=(MONO, 9))
            elif kind == "float":
                var = tk.DoubleVar(value=float(raw))
                widget = tk.Scale(row, variable=var, from_=extra[0], to=extra[1],
                                  resolution=0.01 if extra[1] <= 1 else 0.1,
                                  orient="horizontal", length=260, bg=PANEL,
                                  fg=WHITE, troughcolor=BG, highlightthickness=0,
                                  font=(MONO, 8), sliderrelief="flat")
            else:
                var = tk.StringVar(value=raw.strip('"'))
                widget = tk.Entry(row, textvariable=var, bg=BG, fg=WHITE,
                                  insertbackground=BRIGHT, relief="flat",
                                  font=(MONO, 9), width=26)
            widget.pack(side="right", padx=10, pady=4)
            self.vars[(section, key, kind)] = var
            title, description = GENERAL_HELP.get((section, key), (label, ""))
            def parameter_help(variable=var, value_kind=kind, details=description):
                value = variable.get()
                if value_kind == "bool":
                    value = "включено" if value else "выключено"
                return f"{details}\n\nТекущее значение: {value}."
            self.tooltips.attach_many((label_widget, help_widget, widget), title, parameter_help)

    def show_page(self, name):
        self.tooltips.hide()
        for page in self.pages.values():
            page.pack_forget()
        self.pages[name].pack(fill="both", expand=True)
        titles = {"general": "ОБЩИЕ", "commands": "КОМАНДЫ",
                  "profiles": "ПРОФИЛИ", "avatar": "АВАТАР"}
        self.page_title.configure(text=titles[name])
        for key, button in self.nav_buttons.items():
            selected = key == name
            button.configure(bg=PANEL_HI if selected else "#061017",
                             fg=WHITE if selected else DIM)

    def save(self):
        text = self.text
        for (section, key, kind), var in self.vars.items():
            value = var.get()
            if kind == "bool":
                value = "true" if value else "false"
            elif kind == "float":
                value = f"{float(value):g}"
            else:
                value = f'"{value}"'
            text = write_value(text, section, key, value)
        folder = os.path.dirname(CONFIG)
        handle, temporary = tempfile.mkstemp(prefix="config_", suffix=".yaml", dir=folder)
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="") as file:
                file.write(text)
            os.replace(temporary, CONFIG)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        self.text = text
        self.note.configure(text="сохранено — перезапустите ассистента", fg=GREEN)


class StructuredEditor(tk.Frame):
    """Редактор последовательностей действий для команд и профилей."""

    def __init__(self, owner, section):
        super().__init__(owner.page_host, bg=BG)
        self.owner = owner
        self.section = section
        self.data = load_document()
        self.items = self.data.get(section) or ({} if section == "profiles" else [])
        self.current = None
        title = "КОМАНДЫ" if section == "commands" else "ПРОФИЛИ"
        self.build(title)
        self.refresh(0)

    def build(self, title):
        header = tk.Frame(self, bg=PANEL_HI)
        header.pack(fill="x")
        tk.Label(header, text=title, bg=PANEL_HI, fg=WHITE,
                 font=(MONO, 15, "bold")).pack(side="left", padx=18, pady=12)
        hint = "Одна команда — любая цепочка действий" if self.section == "commands" \
            else "Профиль можно вызвать действием type: profile"
        tk.Label(header, text=hint, bg=PANEL_HI, fg=AMBER,
                 font=(MONO, 8)).pack(side="left", padx=10)

        body = tk.PanedWindow(self, bg=BG, sashwidth=5, sashrelief="flat")
        body.pack(fill="both", expand=True, padx=14, pady=12)
        left = tk.Frame(body, bg=PANEL)
        right = tk.Frame(body, bg=BG)
        body.add(left, minsize=230)
        body.add(right, minsize=440)

        self.listbox = tk.Listbox(left, bg=PANEL, fg=WHITE, selectbackground=MID,
                                  selectforeground=BG, borderwidth=0,
                                  font=(MONO, 10), activestyle="none")
        self.listbox.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        self.listbox.bind("<<ListboxSelect>>", self.select)
        list_text = ("Список всех голосовых команд. Выберите строку, чтобы изменить ключевые слова и действия."
                     if self.section == "commands" else
                     "Список профилей — готовых цепочек действий. Выберите профиль, чтобы изменить его параметры.")
        self.owner.tooltips.attach(self.listbox, f"Список: {title.lower()}", list_text)
        buttons = tk.Frame(left, bg=PANEL)
        buttons.pack(fill="x", padx=8, pady=(0, 8))
        add_button = tk.Button(buttons, text="+ НОВЫЙ", command=self.add, bg=MID, fg=BG,
                               relief="flat", font=(MONO, 8, "bold"), cursor="hand2")
        add_button.pack(side="left")
        delete_button = tk.Button(buttons, text="УДАЛИТЬ", command=self.delete,
                                  bg="#40202a", fg=WHITE, relief="flat",
                                  font=(MONO, 8), cursor="hand2")
        delete_button.pack(side="right")
        self.owner.tooltips.attach(
            add_button, "Создать",
            "Добавляет новую команду с безопасным примером действия." if self.section == "commands"
            else "Добавляет новый профиль с примером действия. После этого задайте ему понятное имя.")
        self.owner.tooltips.attach(
            delete_button, "Удалить выбранное",
            "Удаляет выбранную команду из списка. Изменение попадёт в config.yaml только после нажатия «Сохранить»."
            if self.section == "commands" else
            "Удаляет выбранный профиль. Команды, которые ссылаются на него, после сохранения перестанут работать.")

        self.name_var = tk.StringVar()
        self.label_var = tk.StringVar()
        self.keep_listening_var = tk.BooleanVar(value=False)
        if self.section == "commands":
            keyword_widgets = self._field(right, "Ключевые слова через запятую", self.label_var)
            self.owner.tooltips.attach_many(
                keyword_widgets, "Ключевые слова",
                "Фразы, по которым распознаётся эта команда. Разделяйте варианты запятыми. Звёздочка в конце задаёт начало слова: "
                "например, «музык*» распознает «музыка», «музыкальный» и похожие формы.")
            keep_box = tk.Checkbutton(
                right, text="ПРОДОЛЖАТЬ СЛУШАТЬ ПОСЛЕ ВЫПОЛНЕНИЯ",
                variable=self.keep_listening_var, bg=BG, fg=DIM,
                selectcolor=PANEL, activebackground=BG, activeforeground=WHITE,
                font=(MONO, 8, "bold"), cursor="hand2")
            keep_box.pack(anchor="w", pady=(7, 1))
            self.owner.tooltips.attach(
                keep_box, "Продолжать слушать",
                "Если включено, HUD останется открытым и после выполнения команды Jarvis будет ждать следующую фразу без повторного обращения по имени. "
                "Удобно для приветствия и начала диалога. Если выключено, обычная команда завершит текущий сеанс.")
        else:
            name_widgets = self._field(right, "Внутреннее имя", self.name_var)
            label_widgets = self._field(right, "Подпись профиля", self.label_var)
            self.owner.tooltips.attach_many(
                name_widgets, "Внутреннее имя профиля",
                "Короткий уникальный идентификатор без пробелов, например gaming или focus. Именно это имя указывается в действии type: profile.")
            self.owner.tooltips.attach_many(
                label_widgets, "Подпись профиля",
                "Понятное человеку название, которое показывается в интерфейсе. Оно не используется для запуска профиля.")
        actions_label = tk.Label(right, text="ДЕЙСТВИЯ (YAML-СПИСОК)", bg=BG, fg=DIM,
                                 font=(MONO, 8, "bold"))
        actions_label.pack(anchor="w", pady=(10, 4))
        quick = tk.Frame(right, bg=BG)
        quick.pack(fill="x", pady=(0, 5))
        self.quick_type = tk.StringVar(value="say")
        self.quick_value = tk.StringVar()
        type_menu = tk.OptionMenu(quick, self.quick_type, "say", "url", "launch", "overlay",
                                  "media", "profile", "plugin", "close")
        type_menu.configure(bg=PANEL_HI, fg=WHITE, activebackground=MID,
                            highlightthickness=0, font=(MONO, 9), cursor="hand2")
        type_menu["menu"].configure(bg=PANEL_HI, fg=WHITE, font=(MONO, 9))
        type_menu.pack(side="left")
        value_entry = tk.Entry(quick, textvariable=self.quick_value, bg=PANEL, fg=WHITE,
                               insertbackground=BRIGHT, relief="flat", font=(MONO, 9))
        value_entry.pack(side="left", fill="x", expand=True, padx=5, ipady=4)
        action_button = tk.Button(quick, text="+ ДЕЙСТВИЕ", command=self.append_action, bg=LINE,
                                  fg=BRIGHT, relief="flat", font=(MONO, 8, "bold"), cursor="hand2")
        action_button.pack(side="right")
        action_title = lambda: ACTION_HELP[self.quick_type.get()][0]
        action_description = lambda: ACTION_HELP[self.quick_type.get()][1]
        value_description = lambda: ACTION_HELP[self.quick_type.get()][2]
        self.owner.tooltips.attach(type_menu, action_title, action_description)
        self.owner.tooltips.attach(value_entry, "Значение действия", value_description)
        self.owner.tooltips.attach(
            action_button, "Добавить действие",
            "Создаёт действие выбранного типа и добавляет его в конец YAML-списка ниже. Действия выполняются сверху вниз.")
        self.actions = tk.Text(right, height=18, bg=PANEL, fg=WHITE,
                               insertbackground=BRIGHT, relief="flat",
                               font=(MONO, 10), padx=10, pady=8,
                               wrap="none")
        self.actions.pack(fill="both", expand=True)
        self.owner.tooltips.attach_many(
            (actions_label, self.actions), "Цепочка действий",
            "Расширенный редактор последовательности. Каждая строка с «- type:» начинает новое действие; строки ниже задают его параметры. "
            "Порядок важен: Jarvis выполняет список сверху вниз. Если не знаете YAML, используйте конструктор над этим полем.")
        example = ("- type: say\n  text: Привет\n- type: url\n  url: https://example.com")
        self.actions.insert("1.0", example)

        footer = tk.Frame(self, bg=PANEL_HI)
        footer.pack(fill="x")
        self.status = tk.Label(footer, text="", bg=PANEL_HI, fg=DIM, font=(MONO, 8))
        self.status.pack(side="left", padx=14, pady=10)
        save_button = tk.Button(footer, text="СОХРАНИТЬ", command=self.save, bg=GREEN,
                                fg=BG, relief="flat", font=(MONO, 9, "bold"),
                                padx=14, cursor="hand2")
        save_button.pack(side="right", padx=12, pady=8)
        self.owner.tooltips.attach(
            save_button, "Сохранить изменения",
            "Проверяет поля и YAML, затем атомарно записывает весь раздел в config.yaml. Для применения перезапустите Jarvis.")

    @staticmethod
    def _field(parent, label, variable):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=3)
        label_widget = tk.Label(row, text=label.upper(), bg=BG, fg=DIM,
                                font=(MONO, 8, "bold"))
        label_widget.pack(anchor="w")
        entry = tk.Entry(row, textvariable=variable, bg=PANEL, fg=WHITE,
                         insertbackground=BRIGHT, relief="flat", font=(MONO, 10))
        entry.pack(fill="x", ipady=5, pady=(2, 0))
        return label_widget, entry

    def names(self):
        if self.section == "commands":
            return [", ".join(item.get("keywords") or ["без ключа"])
                    for item in self.items]
        return list(self.items)

    def refresh(self, select=None):
        self.listbox.delete(0, "end")
        for name in self.names():
            self.listbox.insert("end", name)
        if select is not None and self.names():
            select = min(select, len(self.names()) - 1)
            self.listbox.selection_set(select)
            self.select()

    def select(self, _event=None):
        picked = self.listbox.curselection()
        if not picked:
            return
        self.commit_current(silent=True)
        self.current = picked[0]
        item = self.items[self.current] if self.section == "commands" \
            else self.items[list(self.items)[self.current]]
        self.name_var.set("" if self.section == "commands" else list(self.items)[self.current])
        self.label_var.set(", ".join(item.get("keywords") or []) if self.section == "commands"
                           else item.get("label", ""))
        self.keep_listening_var.set(
            bool(item.get("keep_listening")) if self.section == "commands" else False)
        self.actions.delete("1.0", "end")
        self.actions.insert("1.0", dump_yaml_fragment(item.get("actions") or []))

    def parse_actions(self):
        value = yaml.safe_load(self.actions.get("1.0", "end")) or []
        if not isinstance(value, list) or not all(isinstance(action, dict) for action in value):
            raise ValueError("действия должны быть YAML-списком словарей")
        if any(not action.get("type") for action in value):
            raise ValueError("у каждого действия должно быть поле type")
        return value

    def append_action(self):
        """Быстрый конструктор покрывает частые действия без знания YAML."""
        try:
            actions = self.parse_actions()
        except (ValueError, yaml.YAMLError) as error:
            self.status.configure(text=f"Сначала исправьте YAML: {error}", fg="#ff7182")
            return
        kind = self.quick_type.get()
        value = self.quick_value.get().strip()
        if kind == "say":
            action = {"type": kind, "text": value or "Новая фраза"}
        elif kind in ("url", "launch"):
            if not value:
                self.status.configure(text="Укажите ссылку или путь", fg="#ff7182")
                return
            action = {"type": kind, "url" if kind == "url" else "path": value}
        elif kind == "overlay":
            action = {"type": kind, "seconds": 6, "text": value or "JARVIS"}
        elif kind == "media":
            action = {"type": kind, "key": value or "play"}
        elif kind == "profile":
            if not value:
                self.status.configure(text="Введите внутреннее имя профиля", fg="#ff7182")
                return
            action = {"type": kind, "name": value}
        elif kind == "plugin":
            if not value:
                self.status.configure(text="Введите имя файла плагина без .py", fg="#ff7182")
                return
            action = {"type": kind, "name": value, "params": {}}
        else:
            action = {"type": "close"}
        actions.append(action)
        self.actions.delete("1.0", "end")
        self.actions.insert("1.0", dump_yaml_fragment(actions))
        self.quick_value.set("")
        self.status.configure(text="Действие добавлено", fg=GREEN)

    def commit_current(self, silent=False):
        if self.current is None:
            return True
        try:
            actions = self.parse_actions()
            if self.section == "commands":
                keywords = [word.strip().lower() for word in self.label_var.get().split(",") if word.strip()]
                if not keywords:
                    raise ValueError("нужно хотя бы одно ключевое слово")
                command = self.items[self.current]
                command["keywords"] = keywords
                command["actions"] = actions
                if self.keep_listening_var.get():
                    command["keep_listening"] = True
                else:
                    command.pop("keep_listening", None)
            else:
                old_name = list(self.items)[self.current]
                name = self.name_var.get().strip()
                if not name:
                    raise ValueError("укажите внутреннее имя профиля")
                if name != old_name and name in self.items:
                    raise ValueError("профиль с таким именем уже есть")
                profile = self.items[old_name]
                profile["label"] = self.label_var.get().strip() or name
                profile["actions"] = actions
                if name != old_name:
                    ordered = list(self.items.items())
                    ordered[self.current] = (name, profile)
                    self.items = dict(ordered)
                else:
                    self.items[name] = profile
            return True
        except (ValueError, yaml.YAMLError) as error:
            if not silent:
                self.status.configure(text=f"Ошибка: {error}", fg="#ff7182")
            return False

    def add(self):
        if not self.commit_current():
            return
        default = {"actions": [{"type": "overlay", "seconds": 4, "text": "NEW COMMAND"}]}
        if self.section == "commands":
            default["keywords"] = ["новая команда"]
            self.items.append(default)
        else:
            number = 1
            name = "new_profile"
            while name in self.items:
                number += 1
                name = f"new_profile_{number}"
            self.items[name] = {"label": "Новый профиль", **default}
        self.current = None
        self.refresh(len(self.names()) - 1)

    def delete(self):
        if self.current is None:
            return
        if self.section == "commands":
            self.items.pop(self.current)
        else:
            self.items.pop(list(self.items)[self.current])
        self.current = None
        self.refresh(max(0, self.current or 0))

    def save(self):
        if not self.commit_current():
            return
        self.data[self.section] = self.items
        try:
            save_document(self.data)
        except OSError as error:
            self.status.configure(text=f"Не удалось сохранить: {error}", fg="#ff7182")
            return
        self.owner.text = io.open(CONFIG, encoding="utf-8").read()
        self.owner.note.configure(text="команды/профили сохранены — перезапустите ассистента", fg=GREEN)
        self.status.configure(text="Сохранено", fg=GREEN)


class AvatarEditor(tk.Frame):
    """Настройки VTube Studio: модель выбирается в самом VTube Studio."""

    def __init__(self, owner):
        super().__init__(owner.page_host, bg=BG)
        self.owner = owner
        self.data = load_document()
        ui = self.data.get("ui") or {}
        vtube = ui.get("vtube_studio") or {}
        self.mode = tk.StringVar(value=ui.get("mode", "hud"))
        self.path = tk.StringVar(value=vtube.get("path", ""))
        self.url = tk.StringVar(value=vtube.get("url", "ws://127.0.0.1:8001"))
        self.autostart = tk.BooleanVar(value=bool(vtube.get("autostart")))
        reactions = vtube.get("reactions") or {}
        self.listening = tk.StringVar(value=reactions.get("listening", "jarvis_listening"))
        self.speaking = tk.StringVar(value=reactions.get("speaking", "jarvis_speaking"))
        self.idle = tk.StringVar(value=reactions.get("idle", "jarvis_idle"))
        self.build()

    def build(self):
        tk.Label(self, text="ИНТЕРФЕЙС АССИСТЕНТА", bg=PANEL_HI, fg=WHITE,
                 font=(MONO, 15, "bold"), anchor="w").pack(fill="x", padx=0, pady=0,
                                                            ipady=12)
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=20, pady=14)
        for text, value in (("HUD JARVIS", "hud"), ("VTube Studio / Live2D", "vtube_studio")):
            radio = tk.Radiobutton(body, text=text, variable=self.mode, value=value, bg=BG,
                                   fg=WHITE, selectcolor=PANEL_HI, activebackground=BG,
                                   activeforeground=BRIGHT, font=(MONO, 10, "bold"),
                                   cursor="hand2")
            radio.pack(anchor="w")
            description = (
                "Стандартный интерфейс Jarvis: окно со статусом прослушивания, речи и показателями компьютера. VTube Studio не требуется."
                if value == "hud" else
                "Вместо стандартного HUD Jarvis будет переключать эмоции и состояния выбранной Live2D-модели через Plugin API VTube Studio.")
            self.owner.tooltips.attach(radio, text, description)

        avatar_fields = (
            ("Путь к VTubeStudio.exe", self.path, "Путь к VTube Studio",
             r"Полный путь к VTubeStudio.exe. Нужен только при автозапуске, например C:\Program Files (x86)\Steam\steamapps\common\VTube Studio\VTube Studio.exe."),
            ("Адрес API", self.url, "Адрес Plugin API",
             "Локальный WebSocket-адрес VTube Studio. Стандартное значение — ws://127.0.0.1:8001. Меняйте его только если порт изменён в VTube Studio."),
            ("Hotkey: слушает", self.listening, "Hotkey: Jarvis слушает",
             "Точное имя горячей клавиши VTube Studio, которая включает позу или эмоцию ожидания команды. Создайте её в модели заранее."),
            ("Hotkey: говорит", self.speaking, "Hotkey: Jarvis говорит",
             "Точное имя горячей клавиши VTube Studio для состояния речи. Она вызывается, пока ассистент озвучивает ответ."),
            ("Hotkey: покой", self.idle, "Hotkey: состояние покоя",
             "Точное имя горячей клавиши, возвращающей модель в обычное состояние после прослушивания или речи."),
        )
        for label, var, title, description in avatar_fields:
            widgets = StructuredEditor._field(body, label, var)
            self.owner.tooltips.attach_many(widgets, title, description)
        autostart_box = tk.Checkbutton(
            body, text="Запускать VTube Studio вместе с Jarvis", variable=self.autostart,
            bg=BG, fg=BRIGHT, selectcolor=PANEL_HI, activebackground=BG,
            activeforeground=WHITE, font=(MONO, 9), cursor="hand2")
        autostart_box.pack(anchor="w", pady=8)
        self.owner.tooltips.attach(
            autostart_box, "Автозапуск VTube Studio",
            "Если включено и выбран режим VTube Studio, Jarvis попробует запустить программу по указанному пути. "
            "Если она уже открыта, второй экземпляр запускаться не должен.")
        self.status = tk.Label(body, text="Включите Plugin API в VTube Studio и разрешите Jarvis при первом запуске.",
                               bg=BG, fg=AMBER, font=(MONO, 8), wraplength=590, justify="left")
        self.status.pack(anchor="w")
        self.owner.tooltips.attach(
            self.status, "Первое подключение",
            "В VTube Studio откройте Settings → Plugins, включите Plugin API и оставьте программу запущенной. "
            "При первом соединении подтвердите запрос доступа от Jarvis.")
        footer = tk.Frame(self, bg=PANEL_HI)
        footer.pack(fill="x")
        save_button = tk.Button(footer, text="СОХРАНИТЬ", command=self.save, bg=GREEN, fg=BG,
                                relief="flat", font=(MONO, 9, "bold"), padx=16,
                                cursor="hand2")
        save_button.pack(side="right", padx=12, pady=10)
        self.owner.tooltips.attach(
            save_button, "Сохранить настройки аватара",
            "Записывает режим интерфейса, адрес API, горячие клавиши и автозапуск. Изменения применятся после перезапуска Jarvis.")

    def save(self):
        ui = self.data.setdefault("ui", {})
        ui["mode"] = self.mode.get()
        ui["vtube_studio"] = {
            "path": self.path.get().strip(), "autostart": bool(self.autostart.get()),
            "url": self.url.get().strip() or "ws://127.0.0.1:8001",
            "reactions": {"listening": self.listening.get().strip(),
                          "speaking": self.speaking.get().strip(),
                          "idle": self.idle.get().strip()},
        }
        save_document(self.data)
        self.owner.text = io.open(CONFIG, encoding="utf-8").read()
        self.owner.note.configure(text="настройки аватара сохранены — перезапустите ассистента", fg=GREEN)
        self.status.configure(text="Настройки аватара сохранены", fg=GREEN)


def main():
    parser = argparse.ArgumentParser(description="Настройки Джарвиса")
    parser.parse_args()
    root = tk.Tk()
    Settings(root)
    root.mainloop()


if __name__ == "__main__":
    main()
