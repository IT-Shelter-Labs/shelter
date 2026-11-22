//! HUD-окно Джарвиса: реактор и живая телеметрия машины.
//!
//! Замена overlay.py с теми же аргументами и теми же файлами связи
//! (logs/overlay.json, logs/speaking.flag). Рисует видеокарта через OpenGL,
//! телеметрия опрашивается в отдельных потоках — кадр никогда не ждёт опроса.
//!
//!     jarvis-hud --seconds 8 --label "SYSTEM READY" --root <проект>

#![windows_subsystem = "windows"]

use std::collections::VecDeque;
use std::f32::consts::PI;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant, SystemTime};

use eframe::egui::{
    self, pos2, vec2, Align2, Color32, FontData, FontDefinitions, FontFamily,
    FontId, Pos2, Shape, Stroke, ViewportCommand,
};

mod screen;

const W: f32 = 960.0;
const H: f32 = 600.0;
// Кругляш: тот же реактор, уменьшенный, и строка состояния под ним.
const ORB_W: f32 = 236.0;
const ORB_H: f32 = 270.0;
const ORB_R: f32 = 108.0;
const FADE_IN: f32 = 0.25;
const FADE_OUT: f32 = 0.5;

const HEAD_H: f32 = 64.0;
const FOOT_H: f32 = 46.0;
const PY0: f32 = 78.0;
const PY1: f32 = H - FOOT_H - 12.0;
const LEFT: (f32, f32, f32, f32) = (18.0, PY0, 262.0, PY1);
const RIGHT: (f32, f32, f32, f32) = (W - 262.0, PY0, W - 18.0, PY1);
const RCX: f32 = 480.0;
const RCY: f32 = 322.0;
const RR: f32 = 188.0;
const HIST: usize = 26;

const TABS: [&str; 4] = ["OVERVIEW", "SYSTEM", "PROTOCOLS", "LOGS"];
const COINS: [(&str, &str); 6] = [
    ("BTC", "bitcoin"),
    ("ETH", "ethereum"),
    ("SOL", "solana"),
    ("TON", "the-open-network"),
    ("XRP", "ripple"),
    ("DOGE", "dogecoin"),
];

const fn hex(v: u32) -> Color32 {
    Color32::from_rgb((v >> 16) as u8, (v >> 8) as u8, v as u8)
}

const BG: Color32 = hex(0x04090f);
const PANEL: Color32 = hex(0x071219);
const PANEL_HI: Color32 = hex(0x0b202c);
const GRID: Color32 = hex(0x0a141c);
const LINE: Color32 = hex(0x164e63);
const DIM: Color32 = hex(0x1f6f8c);
const MID: Color32 = hex(0x37b3d8);
const BRIGHT: Color32 = hex(0x7fe6ff);
const WHITE: Color32 = hex(0xdff8ff);
const AMBER: Color32 = hex(0xffb648);
const GREEN: Color32 = hex(0x5ef2a0);
const RED: Color32 = hex(0xff6b6b);
const OFF_C: Color32 = hex(0x0a1c25);
const OFF_B: Color32 = hex(0x0d2833);
const OFF_A: Color32 = hex(0x2a1c0c);
const GLOW: [Color32; 5] = [hex(0x0a2b38), hex(0x0f4a5f), hex(0x177a99), hex(0x2ba8cd), hex(0x5fd4f2)];
const GLOW_HOT: [Color32; 5] = [hex(0x134e63), hex(0x1c7c9c), hex(0x39b6db), hex(0x8febff), hex(0xffffff)];

/// Линейная смесь двух цветов — переход между обычным режимом и речью.
fn mix(a: Color32, b: Color32, t: f32) -> Color32 {
    let t = t.clamp(0.0, 1.0);
    let ch = |x: u8, y: u8| (x as f32 + (y as f32 - x as f32) * t) as u8;
    Color32::from_rgb(ch(a.r(), b.r()), ch(a.g(), b.g()), ch(a.b(), b.b()))
}

fn pol(r: f32, deg: f32) -> Pos2 {
    pol_at(RCX, RCY, r, deg)
}

fn pol_at(cx: f32, cy: f32, r: f32, deg: f32) -> Pos2 {
    let a = deg.to_radians();
    pos2(cx + r * a.cos(), cy - r * a.sin())
}

// ------------------------------------------------------------ аргументы

struct Args {
    seconds: f32,
    pos: String,
    label: String,
    speaking: bool,
    root: PathBuf,
    fps: f32,
    /// auto — большое окно, а когда человек занят — компактно; full; orb.
    layout: String,
    /// Что значит «компактно»: orb — кругляш в углу; monitor — большое окно
    /// на другом мониторе (если он есть, иначе всё равно кругляш).
    busy: String,
    /// Угол для кругляша.
    corner: String,
    busy_apps: Vec<String>,
    /// Монитор по номеру (1 — основной, дальше слева направо); 0 — где человек.
    monitor: usize,
    /// Записать в файл, какой режим выбран и почему (для проверки).
    explain: Option<PathBuf>,
}

fn parse_args() -> Args {
    let mut args = Args {
        seconds: 8.0,
        pos: String::new(),
        label: "STANDING BY".into(),
        speaking: false,
        root: std::env::current_dir().unwrap_or_default(),
        fps: 30.0,
        layout: "auto".into(),
        busy: "orb".into(),
        corner: "bottom-right".into(),
        busy_apps: Vec::new(),
        monitor: 0,
        explain: None,
    };
    let mut it = std::env::args().skip(1);
    while let Some(key) = it.next() {
        match key.as_str() {
            "--seconds" => args.seconds = it.next().and_then(|v| v.parse().ok()).unwrap_or(8.0),
            "--pos" => args.pos = it.next().unwrap_or_default(),
            "--label" => args.label = it.next().unwrap_or_default(),
            "--root" => args.root = it.next().map(PathBuf::from).unwrap_or_default(),
            "--fps" => args.fps = it.next().and_then(|v| v.parse().ok()).unwrap_or(30.0),
            "--speaking" => args.speaking = true,
            "--layout" => args.layout = it.next().unwrap_or_default().to_lowercase(),
            "--busy" => args.busy = it.next().unwrap_or_default().to_lowercase(),
            "--corner" => args.corner = it.next().unwrap_or_default().to_lowercase(),
            "--busy-apps" => {
                args.busy_apps = it.next().unwrap_or_default().split(',')
                    .map(|s| s.trim().to_lowercase()).filter(|s| !s.is_empty()).collect()
            }
            "--explain" => args.explain = it.next().map(PathBuf::from),
            "--monitor" => args.monitor = it.next().and_then(|v| v.parse().ok()).unwrap_or(0),
            _ => {}
        }
    }
    args
}

// --------------------------------------------------------------- режим

/// Как показаться: большим окном или кругляшом, на каком мониторе и где.
struct Plan {
    orb: bool,
    monitor: Option<screen::Monitor>,
    corner: String,
    reason: String,
}

fn plan(args: &Args) -> Plan {
    let s = screen::situation(&args.busy_apps);
    // Выбранный голосом монитор («перейди на второй монитор») важнее того, где человек.
    let mut ordered = s.monitors.clone();
    ordered.sort_by_key(|m| (!m.primary, m.full.left, m.full.top));
    let chosen = (args.monitor > 0).then(|| ordered.get(args.monitor - 1).copied()).flatten();
    let active = chosen
        .or_else(|| s.monitors.iter().find(|m| Some(m.id) == s.active).copied())
        .or_else(|| s.monitors.iter().find(|m| m.primary).copied());
    let full_corner = if args.pos.is_empty() { "center".to_string() } else { args.pos.clone() };
    let orb_corner = if args.pos.is_empty() { args.corner.clone() } else { args.pos.clone() };
    let orb = |reason: String| Plan { orb: true, monitor: active, corner: orb_corner.clone(), reason };
    match args.layout.as_str() {
        "orb" => orb("layout=orb".into()),
        "full" => Plan { orb: false, monitor: active, corner: full_corner, reason: "layout=full".into() },
        _ => match s.busy {
            None => Plan { orb: false, monitor: active, corner: full_corner, reason: "free".into() },
            Some(why) => {
                // Занят: на свободный монитор, если просили и он есть, иначе кругляш.
                // Из свободных — основной, иначе самый большой.
                let other = s.monitors.iter().filter(|m| Some(m.id) != s.active)
                    .max_by_key(|m| (m.primary, m.full.width() as i64 * m.full.height() as i64))
                    .copied();
                match (args.busy.as_str(), other) {
                    ("monitor", Some(m)) => Plan {
                        orb: false,
                        monitor: Some(m),
                        corner: "center".into(),
                        reason: format!("busy: {why} -> second monitor"),
                    },
                    _ => orb(format!("busy: {why} -> orb")),
                }
            }
        },
    }
}

// ----------------------------------------------------------- телеметрия

#[derive(Clone, Default)]
struct Stats {
    cpu: f32,
    mem: f32,
    mem_used: f32,
    gpu: f32,
    gpu_temp: f32,
    disk: f32,
    net: f32,
    net_max: f32,
    freq: f32,
    cores: Vec<f32>,
    nproc: usize,
    uptime: String,
    cpu_hist: VecDeque<f32>,
    net_hist: VecDeque<f32>,
    coins: Vec<(String, f64, f64)>,
}

impl Stats {
    fn new() -> Self {
        Stats {
            net_max: 64.0,
            cpu_hist: VecDeque::from(vec![0.0; HIST]),
            net_hist: VecDeque::from(vec![0.0; HIST]),
            ..Default::default()
        }
    }
}

type Shared = Arc<Mutex<Stats>>;

fn push(hist: &mut VecDeque<f32>, value: f32) {
    hist.push_back(value);
    while hist.len() > HIST {
        hist.pop_front();
    }
}

/// Процессор, память, сеть — раз в секунду; диск, частота, процессы — реже.
fn collect_system(shared: Shared) {
    use sysinfo::{Disks, MemoryRefreshKind, Networks, ProcessRefreshKind, ProcessesToUpdate, System};
    let mut sys = System::new();
    let mut networks = Networks::new_with_refreshed_list();
    let mut disks = Disks::new_with_refreshed_list();
    sys.refresh_cpu_usage();
    let mut last = Instant::now();
    let mut tick: u64 = 0;
    loop {
        thread::sleep(Duration::from_secs(1));
        sys.refresh_cpu_usage();
        // Только оперативная память: полный refresh_memory опрашивает ещё и
        // файл подкачки и стоит 75–90 мс процессора — раз в секунду это 8% ядра.
        sys.refresh_memory_specifics(MemoryRefreshKind::nothing().with_ram());
        networks.refresh(true);
        let span = last.elapsed().as_secs_f32().max(1e-3);
        last = Instant::now();
        let bytes: u64 = networks
            .iter()
            .map(|(_, data)| data.received() + data.transmitted())
            .sum();

        let cores: Vec<f32> = sys.cpus().iter().map(|c| c.cpu_usage()).collect();
        let cpu = if cores.is_empty() { 0.0 } else { cores.iter().sum::<f32>() / cores.len() as f32 };
        let total = sys.total_memory().max(1) as f32;
        let up = System::uptime();

        let mut slow_disk = None;
        let mut slow_freq = None;
        let mut slow_procs = None;
        if tick % 4 == 0 {
            disks.refresh(true);
            slow_disk = disks
                .iter()
                .find(|d| {
                    let m = d.mount_point().to_string_lossy();
                    m.starts_with("C:") || m == "/"
                })
                .map(|d| 100.0 * (1.0 - d.available_space() as f32 / d.total_space().max(1) as f32));
        }
        if tick % 4 == 1 {
            sys.refresh_cpu_frequency();
            slow_freq = sys.cpus().first().map(|c| c.frequency() as f32 / 1000.0);
        }
        if tick % 30 == 2 {
            // Нужно только число процессов: без чтения памяти, путей и
            // командных строк каждого из трёх сотен.
            sys.refresh_processes_specifics(ProcessesToUpdate::All, true, ProcessRefreshKind::nothing());
            slow_procs = Some(sys.processes().len());
        }

        let mut s = shared.lock().unwrap();
        s.cores = cores;
        s.cpu = cpu;
        push(&mut s.cpu_hist, cpu);
        s.mem = 100.0 * sys.used_memory() as f32 / total;
        s.mem_used = sys.used_memory() as f32 / 1_073_741_824.0;
        s.net = bytes as f32 / span / 1024.0;
        let net = s.net;
        push(&mut s.net_hist, net);
        s.net_max = s.net_hist.iter().cloned().fold(64.0, f32::max);
        s.uptime = format!("{:02}:{:02}:{:02}", up / 3600, up % 3600 / 60, up % 60);
        if let Some(v) = slow_disk {
            s.disk = v;
        }
        if let Some(v) = slow_freq {
            s.freq = v;
        }
        if let Some(v) = slow_procs {
            s.nproc = v;
        }
        drop(s);
        tick += 1;
    }
}

/// Видеокарта через NVML напрямую: без запуска nvidia-smi раз в пару секунд.
fn collect_gpu(shared: Shared) {
    use nvml_wrapper::enum_wrappers::device::TemperatureSensor;
    use nvml_wrapper::Nvml;
    let Ok(nvml) = Nvml::init() else { return };
    let Ok(device) = nvml.device_by_index(0) else { return };
    loop {
        let load = device.utilization_rates().map(|u| u.gpu as f32).ok();
        let temp = device.temperature(TemperatureSensor::Gpu).map(|t| t as f32).ok();
        {
            let mut s = shared.lock().unwrap();
            if let Some(v) = load {
                s.gpu = v;
            }
            if let Some(v) = temp {
                s.gpu_temp = v;
            }
        }
        thread::sleep(Duration::from_secs(2));
    }
}

/// Курсы раз в минуту: чаще не нужно и упрёмся в лимит CoinGecko.
fn collect_coins(shared: Shared) {
    let ids: Vec<&str> = COINS.iter().map(|(_, id)| *id).collect();
    let url = format!(
        "https://api.coingecko.com/api/v3/simple/price?ids={}&vs_currencies=usd&include_24hr_change=true",
        ids.join(",")
    );
    loop {
        let reply = ureq::get(&url)
            .set("User-Agent", "jarvis/1.0")
            .timeout(Duration::from_secs(8))
            .call()
            .ok()
            .and_then(|r| r.into_json::<serde_json::Value>().ok());
        if let Some(data) = reply {
            let rows: Vec<(String, f64, f64)> = COINS
                .iter()
                .filter_map(|(ticker, id)| {
                    let item = data.get(*id)?;
                    Some((
                        ticker.to_string(),
                        item.get("usd")?.as_f64()?,
                        item.get("usd_24h_change").and_then(|v| v.as_f64()).unwrap_or(0.0),
                    ))
                })
                .collect();
            if !rows.is_empty() {
                shared.lock().unwrap().coins = rows;
            }
        }
        thread::sleep(Duration::from_secs(60));
    }
}

// ------------------------------------------------------------ рисование

/// Обёртка над Painter: все цвета проходят через прозрачность окна (fade).
struct Pen<'a> {
    p: &'a egui::Painter,
    a: f32,
    /// Масштаб сцены и куда переносится центр реактора — для кругляша.
    /// У большого окна 1.0 и (RCX, RCY): координаты как есть.
    s: f32,
    o: Pos2,
}

impl<'a> Pen<'a> {
    fn new(p: &'a egui::Painter, a: f32) -> Self {
        Pen { p, a, s: 1.0, o: pos2(RCX, RCY) }
    }
    fn m(&self, p: Pos2) -> Pos2 {
        if self.s == 1.0 && self.o == pos2(RCX, RCY) {
            return p;
        }
        pos2(self.o.x + (p.x - RCX) * self.s, self.o.y + (p.y - RCY) * self.s)
    }
    fn c(&self, c: Color32) -> Color32 {
        c.gamma_multiply(self.a)
    }
    fn stroke(&self, w: f32, c: Color32) -> Stroke {
        Stroke::new(w * self.s, self.c(c))
    }
    fn line(&self, a: Pos2, b: Pos2, w: f32, c: Color32) {
        self.p.line_segment([self.m(a), self.m(b)], self.stroke(w, c));
    }
    fn hline(&self, x0: f32, x1: f32, y: f32, w: f32, c: Color32) {
        self.line(pos2(x0, y), pos2(x1, y), w, c);
    }
    fn vline(&self, x: f32, y0: f32, y1: f32, w: f32, c: Color32) {
        self.line(pos2(x, y0), pos2(x, y1), w, c);
    }
    fn map(&self, pts: Vec<Pos2>) -> Vec<Pos2> {
        pts.into_iter().map(|p| self.m(p)).collect()
    }
    fn polyline(&self, pts: Vec<Pos2>, w: f32, c: Color32) {
        self.p.add(Shape::line(self.map(pts), self.stroke(w, c)));
    }
    fn closed(&self, pts: Vec<Pos2>, w: f32, c: Color32) {
        self.p.add(Shape::closed_line(self.map(pts), self.stroke(w, c)));
    }
    fn poly(&self, pts: Vec<Pos2>, fill: Color32, w: f32, outline: Color32) {
        let stroke = if w > 0.0 { self.stroke(w, outline) } else { Stroke::NONE };
        self.p.add(Shape::convex_polygon(self.map(pts), self.c(fill), stroke));
    }
    fn rect(&self, x0: f32, y0: f32, x1: f32, y1: f32, fill: Color32) {
        let r = egui::Rect::from_min_max(self.m(pos2(x0, y0)), self.m(pos2(x1.max(x0), y1.max(y0))));
        self.p.rect_filled(r, 0.0, self.c(fill));
    }
    fn frame(&self, x0: f32, y0: f32, x1: f32, y1: f32, w: f32, c: Color32) {
        self.closed(vec![pos2(x0, y0), pos2(x1, y0), pos2(x1, y1), pos2(x0, y1)], w, c);
    }
    fn disc(&self, cx: f32, cy: f32, r: f32, fill: Color32) {
        self.p.circle_filled(self.m(pos2(cx, cy)), r.max(0.0) * self.s, self.c(fill));
    }
    fn ring(&self, cx: f32, cy: f32, r: f32, w: f32, c: Color32) {
        self.p.circle_stroke(self.m(pos2(cx, cy)), r.max(0.0) * self.s, self.stroke(w, c));
    }
    /// Дуга в градусах, как в Tk: против часовой стрелки от оси X.
    fn arc(&self, r: f32, start: f32, extent: f32, w: f32, c: Color32) {
        let n = ((extent.abs() / 3.0) as usize).max(2);
        let pts = (0..=n).map(|i| pol(r, start + extent * i as f32 / n as f32)).collect();
        self.polyline(pts, w, c);
    }
    fn pie(&self, r: f32, start: f32, extent: f32, c: Color32) {
        let n = ((extent.abs() / 3.0) as usize).max(2);
        let mut pts = vec![pos2(RCX, RCY)];
        pts.extend((0..=n).map(|i| pol(r, start + extent * i as f32 / n as f32)));
        self.poly(pts, c, 0.0, c);
    }
    fn spoke(&self, cx: f32, cy: f32, r1: f32, r2: f32, deg: f32, w: f32, c: Color32) {
        self.line(pol_at(cx, cy, r1, deg), pol_at(cx, cy, r2, deg), w, c);
    }
    fn text(&self, x: f32, y: f32, align: Align2, text: &str, size: f32, bold: bool, c: Color32) {
        // Размеры в пунктах Tk: 1 pt = 4/3 px.
        let family = if bold { FontFamily::Name("bold".into()) } else { FontFamily::Monospace };
        self.p.text(self.m(pos2(x, y)), align, text, FontId::new(size * 4.0 / 3.0 * self.s, family), self.c(c));
    }
}

fn price(value: f64) -> String {
    fn grouped(int_part: u64) -> String {
        let s = int_part.to_string();
        let mut out = String::new();
        for (i, ch) in s.chars().enumerate() {
            if i > 0 && (s.len() - i) % 3 == 0 {
                out.push(' ');
            }
            out.push(ch);
        }
        out
    }
    if value >= 1000.0 {
        grouped(value.round() as u64)
    } else if value >= 1.0 {
        let cents = (value * 100.0).round() as u64;
        format!("{}.{:02}", grouped(cents / 100), cents % 100)
    } else {
        format!("{value:.4}")
    }
}

struct Hud {
    args: Args,
    plan: Plan,
    place_tries: u32,
    shared: Shared,
    stats: Stats,
    started: Instant,
    last_frame: Instant,
    expires: Option<Instant>,
    label: String,
    phase: f32,
    pulse: f32,
    act: f32,
    speaking: bool,
    state_seen: Option<SystemTime>,
    last_poll: Instant,
    placed: bool,
    // Замер для отладки: JARVIS_HUD_STATS=<файл> — FPS и время кадра.
    stats_file: Option<PathBuf>,
    frames: u32,
    busy: Duration,
    window_start: Instant,
}

impl Hud {
    fn new(cc: &eframe::CreationContext<'_>, args: Args, plan: Plan) -> Self {
        install_fonts(&cc.egui_ctx);
        // Сглаживание краёв делает видеокарта (MSAA), а не процессор: программное
        // сглаживание удваивало геометрию каждой из тысячи линий сцены.
        if msaa() > 0 {
            cc.egui_ctx.tessellation_options_mut(|o| o.feathering = false);
        }
        let shared: Shared = Arc::new(Mutex::new(Stats::new()));
        // JARVIS_HUD_OFF=system,gpu,coins — отключить опрос (для замеров).
        let off = std::env::var("JARVIS_HUD_OFF").unwrap_or_default();
        for (name, job) in [("system", collect_system as fn(Shared)), ("gpu", collect_gpu), ("coins", collect_coins)] {
            // Кругляшу нужна только загрузка процессора — видеокарту и биржу не трогаем.
            if off.split(',').any(|o| o == name) || (plan.orb && name != "system")
                || (name == "coins" && std::env::var("JARVIS_MARKETS").as_deref() != Ok("1")) {
                continue;
            }
            let s = shared.clone();
            thread::spawn(move || job(s));
        }
        // Темп кадров держит свой таймер. В egui request_repaint() всегда даёт
        // два кадра подряд, а request_repaint_after вычитает из задержки оценку
        // кадра (1/60 с) — короткая задержка превращается в ноль, и окно гнало
        // тысячи кадров в секунду. Ненулевая микрозадержка даёт ровно один кадр.
        let ctx = cc.egui_ctx.clone();
        let period = Duration::from_secs_f32(1.0 / args.fps.clamp(1.0, 240.0));
        thread::spawn(move || {
            let mut next = Instant::now();
            loop {
                next += period;
                let now = Instant::now();
                if next > now {
                    thread::sleep(next - now);
                } else {
                    next = now; // отстали — не догоняем пачкой кадров
                }
                ctx.request_repaint_after(Duration::from_nanos(1));
            }
        });
        let now = Instant::now();
        let state_path = args.root.join("logs").join("overlay.json");
        Hud {
            expires: (args.seconds > 0.0).then(|| now + Duration::from_secs_f32(args.seconds)),
            label: args.label.clone(),
            state_seen: std::fs::metadata(&state_path).and_then(|m| m.modified()).ok(),
            stats: Stats::new(),
            shared,
            started: now,
            last_frame: now,
            phase: 0.0,
            pulse: 0.0,
            act: 0.0,
            speaking: args.speaking,
            last_poll: now,
            placed: false,
            stats_file: std::env::var_os("JARVIS_HUD_STATS").map(PathBuf::from),
            frames: 0,
            busy: Duration::ZERO,
            window_start: now,
            args,
            plan,
            place_tries: 0,
        }
    }

    /// Поставить окно на нужный монитор в физических пикселях. Окно может
    /// поменять размер при переезде на монитор с другим масштабом, поэтому
    /// проверяем ещё несколько кадров, пока оно не встанет на место.
    fn place(&mut self, ctx: &egui::Context) {
        if self.placed {
            return;
        }
        self.place_tries += 1;
        if let (Some(hwnd), Some(monitor)) = (screen::own_window(), self.plan.monitor) {
            if self.place_tries == 1 {
                screen::mark_tool_window(hwnd);
            }
            if let Some(r) = screen::window_rect(hwnd) {
                let margin = if self.plan.orb { 24 } else { 30 };
                let (x, y) = screen::anchor(monitor.work, r.width(), r.height(), &self.plan.corner, margin);
                if (r.left, r.top) != (x, y) {
                    screen::move_to(hwnd, x, y);
                } else if self.place_tries > 3 {
                    self.placed = true;
                }
                if self.place_tries > 12 {
                    self.placed = true;
                }
                if self.placed && self.plan.orb {
                    // Окно встало и больше не меняет размер — обрезаем по форме.
                    let k = r.width() as f32 / ORB_W;
                    let px = |v: f32| (v * k).round() as i32;
                    let (cx, cy) = (ORB_W / 2.0, ORB_R + 6.0);
                    let circle = screen::Rect {
                        left: px(cx - ORB_R - 2.0), top: px(cy - ORB_R - 2.0),
                        right: px(cx + ORB_R + 3.0), bottom: px(cy + ORB_R + 3.0),
                    };
                    let y = ORB_H - 20.0;
                    let bar = screen::Rect {
                        left: px(14.0), top: px(y - 12.0), right: px(ORB_W - 13.0), bottom: px(y + 13.0),
                    };
                    screen::shape_orb(hwnd, circle, bar, px(6.0));
                }
                return;
            }
        }
        // Запасной путь без Win32: логические координаты основного монитора.
        if let Some(screen) = ctx.input(|i| i.viewport().monitor_size) {
            let (w, h) = if self.plan.orb { (ORB_W, ORB_H) } else { (W, H) };
            let (x, y) = match self.plan.corner.as_str() {
                "top-right" => (screen.x - w - 30.0, 30.0),
                "bottom-right" => (screen.x - w - 30.0, screen.y - h - 90.0),
                _ => ((screen.x - w) / 2.0, (screen.y - h) / 2.0),
            };
            ctx.send_viewport_cmd(ViewportCommand::OuterPosition(pos2(x, y)));
            self.placed = true;
        }
    }

    /// Новый заголовок и срок от ассистента — без перезапуска окна.
    fn poll_files(&mut self) {
        if self.last_poll.elapsed() < Duration::from_millis(100) {
            return;
        }
        self.last_poll = Instant::now();
        let logs = self.args.root.join("logs");
        self.speaking = self.args.speaking || logs.join("speaking.flag").exists();
        let state = logs.join("overlay.json");
        let Ok(mtime) = std::fs::metadata(&state).and_then(|m| m.modified()) else { return };
        if Some(mtime) == self.state_seen {
            return;
        }
        self.state_seen = Some(mtime);
        let Ok(text) = std::fs::read_to_string(&state) else { return };
        let Ok(data) = serde_json::from_str::<serde_json::Value>(&text) else { return };
        if let Some(label) = data.get("label").and_then(|v| v.as_str()) {
            self.label = label.to_string();
        }
        // «Перейди на второй монитор»: переставить живое окно без перезапуска.
        if let Some(place) = data.get("place") {
            let monitor = place.get("monitor").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
            let corner = place.get("corner").and_then(|v| v.as_str()).unwrap_or("").to_string();
            if monitor != self.args.monitor || corner != self.args.pos {
                self.args.monitor = monitor;
                self.args.pos = corner;
                self.plan = plan(&self.args);
                self.placed = false;
                self.place_tries = 0;
            }
        }
        let seconds = data.get("seconds").and_then(|v| v.as_f64()).unwrap_or(0.0) as f32;
        self.expires = (seconds > 0.0).then(|| Instant::now() + Duration::from_secs_f32(seconds));
    }

    /// Телеметрия меняется раз в секунду, а на экране цифры плывут плавно.
    fn smooth(&mut self, dt: f32) {
        let target = self.shared.lock().unwrap().clone();
        let k = 1.0 - 0.82f32.powf(dt * 24.0);
        let s = &mut self.stats;
        for (v, t) in [
            (&mut s.cpu, target.cpu),
            (&mut s.mem, target.mem),
            (&mut s.gpu, target.gpu),
            (&mut s.gpu_temp, target.gpu_temp),
            (&mut s.disk, target.disk),
            (&mut s.net, target.net),
            (&mut s.net_max, target.net_max),
            (&mut s.freq, target.freq),
            (&mut s.mem_used, target.mem_used),
        ] {
            *v += (t - *v) * k;
        }
        if s.cores.len() != target.cores.len() {
            s.cores = target.cores.clone();
        } else {
            for (v, t) in s.cores.iter_mut().zip(&target.cores) {
                *v += (t - *v) * k;
            }
        }
        s.nproc = target.nproc;
        s.uptime = target.uptime;
        s.coins = target.coins;
        s.cpu_hist = target.cpu_hist;
        s.net_hist = target.net_hist;
    }
}

fn install_fonts(ctx: &egui::Context) {
    let mut fonts = FontDefinitions::default();
    let dir = PathBuf::from(std::env::var("WINDIR").unwrap_or_else(|_| "C:\\Windows".into())).join("Fonts");
    if let Ok(bytes) = std::fs::read(dir.join("consola.ttf")) {
        fonts.font_data.insert("consolas".into(), Arc::new(FontData::from_owned(bytes)));
        fonts.families.entry(FontFamily::Monospace).or_default().insert(0, "consolas".into());
    }
    let mut bold = Vec::new();
    if let Ok(bytes) = std::fs::read(dir.join("consolab.ttf")) {
        fonts.font_data.insert("consolas-bold".into(), Arc::new(FontData::from_owned(bytes)));
        bold.push("consolas-bold".to_string());
    }
    bold.extend(fonts.families.get(&FontFamily::Monospace).cloned().unwrap_or_default());
    fonts.families.insert(FontFamily::Name("bold".into()), bold);
    ctx.set_fonts(fonts);
}

impl eframe::App for Hud {
    fn clear_color(&self, _visuals: &egui::Visuals) -> [f32; 4] {
        [0.0, 0.0, 0.0, 0.0]
    }

    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        let now = Instant::now();
        let dt = (now - self.last_frame).as_secs_f32().min(0.1);
        self.last_frame = now;
        self.poll_files();

        self.place(ctx);

        let closing = ctx.input(|i| i.key_pressed(egui::Key::Escape) || i.pointer.any_click());
        if closing || self.expires.is_some_and(|e| now >= e) {
            ctx.send_viewport_cmd(ViewportCommand::Close);
            return;
        }

        let elapsed = (now - self.started).as_secs_f32();
        let alpha = if elapsed < FADE_IN {
            elapsed / FADE_IN
        } else if let Some(left) = self.expires.map(|e| (e - now).as_secs_f32()).filter(|l| *l < FADE_OUT) {
            (left / FADE_OUT).max(0.0)
        } else {
            1.0
        };

        let target = if self.speaking { 1.0 } else { 0.0 };
        self.act += (target - self.act) * (1.0 - 0.84f32.powf(dt * 24.0));
        // Фазы копятся сами: смена скорости при речи не даёт рывка.
        self.phase += 48.0 * (1.0 + 0.8 * self.act) * dt;
        self.pulse += 84.0 * (1.0 + 1.8 * self.act) * dt;
        self.smooth(dt);

        let f = elapsed * 48.0; // счётчик кадров оригинала: f = кадр * 2 при 24 fps
        if self.plan.orb {
            orb(ctx, alpha, elapsed, self.phase, self.pulse, self.act, self.stats.cpu, &self.label, f);
            self.write_stats(now);
            return;
        }
        let painter = ctx.layer_painter(egui::LayerId::background());
        let pen = Pen::new(&painter, alpha);
        draw_static(&pen);
        tabs(&pen, f);
        reactor(&pen, self.phase, self.pulse, self.act, self.stats.cpu);
        gauges(&pen, &self.stats);
        net_graph(&pen, &self.stats);
        net_bar(&pen, &self.stats);
        machine(&pen, &self.stats);
        cores(&pen, &self.stats);
        cpu_graph(&pen, &self.stats);
        markets(&pen, &self.stats);
        header(&pen, &self.stats, &self.label, self.act);
        footer(&pen, f, self.act);
        self.write_stats(now);
    }
}

impl Hud {
    fn write_stats(&mut self, now: Instant) {
        if let Some(path) = &self.stats_file {
            self.frames += 1;
            self.busy += now.elapsed();
            let span = self.window_start.elapsed();
            if span >= Duration::from_secs(3) {
                let line = format!(
                    "fps {:.1}  кадр {:.2} мс (update)  смен кадров {}
",
                    self.frames as f32 / span.as_secs_f32(),
                    self.busy.as_secs_f32() * 1000.0 / self.frames.max(1) as f32,
                    self.frames
                );
                let _ = std::fs::OpenOptions::new().create(true).append(true).open(path)
                    .and_then(|mut f| std::io::Write::write_all(&mut f, line.as_bytes()));
                self.frames = 0;
                self.busy = Duration::ZERO;
                self.window_start = Instant::now();
            }
        }
    }
}

// --------------------------------------------------------------- сцена

fn cut_panel(pen: &Pen, (x0, y0, x1, y1): (f32, f32, f32, f32), title: &str) {
    let cut = 14.0;
    pen.poly(
        vec![
            pos2(x0 + cut, y0),
            pos2(x1, y0),
            pos2(x1, y1 - cut),
            pos2(x1 - cut, y1),
            pos2(x0, y1),
            pos2(x0, y0 + cut),
        ],
        PANEL,
        1.0,
        LINE,
    );
    pen.rect(x0 + cut + 4.0, y0 + 6.0, x1 - 8.0, y0 + 26.0, PANEL_HI);
    pen.text(x0 + cut + 12.0, y0 + 16.0, Align2::LEFT_CENTER, title, 9.0, true, AMBER);
    pen.hline(x0 + 6.0, x1 - 6.0, y0 + 32.0, 1.0, LINE);
}

fn sub(pen: &Pen, x: f32, y: f32, x1: f32, text: &str) {
    pen.hline(x - 8.0, x1, y - 14.0, 1.0, LINE);
    pen.text(x, y, Align2::LEFT_CENTER, text, 9.0, true, DIM);
}

fn draw_static(pen: &Pen) {
    pen.rect(0.0, 0.0, W, H, BG);
    let mut x = 0.0;
    while x < W {
        pen.vline(x, 0.0, H, 1.0, GRID);
        x += 32.0;
    }
    let mut y = 0.0;
    while y < H {
        pen.hline(0.0, W, y, 1.0, GRID);
        y += 32.0;
    }
    pen.frame(2.0, 2.0, W - 2.0, H - 2.0, 2.0, DIM);
    pen.frame(6.0, 6.0, W - 6.0, H - 6.0, 1.0, LINE);
    for (sx, sy) in [(1.0, 1.0), (-1.0, 1.0), (1.0, -1.0), (-1.0, -1.0)] {
        let x = if sx > 0.0 { 6.0 } else { W - 6.0 };
        let y = if sy > 0.0 { 6.0 } else { H - 6.0 };
        pen.hline(x, x + sx * 46.0, y, 3.0, BRIGHT);
        pen.vline(x, y, y + sy * 34.0, 3.0, BRIGHT);
    }
    pen.rect(6.0, 6.0, W - 6.0, HEAD_H, PANEL_HI);
    pen.hline(6.0, W - 6.0, HEAD_H, 2.0, MID);
    pen.text(26.0, 26.0, Align2::LEFT_CENTER, "J . A . R . V . I . S", 16.0, true, WHITE);
    pen.rect(6.0, H - FOOT_H, W - 6.0, H - 6.0, PANEL_HI);
    pen.hline(6.0, W - 6.0, H - FOOT_H, 2.0, MID);

    cut_panel(pen, LEFT, "SYSTEM STATUS");
    cut_panel(pen, RIGHT, "PROCESSOR");
    let (x0, y0, x1, _) = LEFT;
    sub(pen, x0 + 18.0, y0 + 176.0, x1 - 6.0, "NETWORK  KB/S");
    sub(pen, x0 + 18.0, y0 + 302.0, x1 - 6.0, "MACHINE");
    let (rx0, ry0, rx1, _) = RIGHT;
    sub(pen, rx0 + 18.0, ry0 + 226.0, rx1 - 6.0, "CPU LOAD HISTORY");
    sub(pen, rx0 + 18.0, ry0 + 352.0, rx1 - 6.0, "MARKETS  USD");

    pen.disc(RCX, RCY, RR, PANEL);
    pen.ring(RCX, RCY, RR, 1.0, LINE);
    pen.ring(RCX, RCY, RR - 4.0, 1.0, DIM);
    for r in [150.0, 116.0, 96.0] {
        pen.ring(RCX, RCY, r, 1.0, hex(0x0d2a35));
    }
    for deg in [0.0, 90.0, 180.0, 270.0] {
        pen.spoke(RCX, RCY, 20.0, RR - 8.0, deg, 1.0, hex(0x0d2430));
    }
    for i in 0..90 {
        let long = i % 5 == 0;
        let r2 = if long { RR - 6.0 } else { RR - 11.0 };
        pen.spoke(RCX, RCY, RR - 16.0, r2, i as f32 * 4.0, 1.0, if long { MID } else { DIM });
    }
    pen.text(282.0, 116.0, Align2::LEFT_CENTER, "ARC REACTOR  //  STABLE", 8.0, false, DIM);
    pen.text(282.0, 526.0, Align2::LEFT_CENTER, "SYNC LOCKED", 8.0, false, DIM);
    for (deg, name) in [(90.0, "000"), (0.0, "090"), (270.0, "180"), (180.0, "270")] {
        let p = pol(RR + 16.0, deg);
        pen.text(p.x, p.y, Align2::CENTER_CENTER, name, 8.0, false, DIM);
        pen.spoke(RCX, RCY, RR + 2.0, RR + 8.0, deg, 2.0, MID);
    }
}

fn tabs(pen: &Pen, f: f32) {
    let sel = (f / 40.0) as usize % TABS.len();
    let (mut x, y) = (282.0, PY0);
    for (i, name) in TABS.iter().enumerate() {
        let on = i == sel;
        pen.poly(
            vec![pos2(x + 8.0, y), pos2(x + 96.0, y), pos2(x + 88.0, y + 24.0), pos2(x, y + 24.0)],
            if on { PANEL_HI } else { PANEL },
            1.0,
            if on { BRIGHT } else { LINE },
        );
        pen.text(x + 48.0, y + 12.0, Align2::CENTER_CENTER, name, 8.0, true, if on { WHITE } else { DIM });
        x += 102.0;
    }
}

fn reactor(pen: &Pen, p: f32, pp: f32, act: f32, cpu: f32) {
    let hot = mix(MID, hex(0xbff3ff), act);
    let hot_dim = mix(DIM, MID, act);

    for i in 0..4 {
        let s = p * 0.4 + i as f32 * 90.0;
        pen.arc(160.0, s, 62.0, 10.0, mix(GLOW[1], GLOW_HOT[1], act));
        pen.arc(160.0, s, 62.0, 3.0, hot);
        let e = pol(160.0, s + 62.0);
        pen.disc(e.x, e.y, 4.0 + 2.0 * act, BRIGHT);
    }
    for i in 0..3 {
        let s = -p * 0.85 + i as f32 * 120.0;
        pen.arc(138.0, s, 84.0, 14.0, mix(GLOW[0], GLOW_HOT[0], act));
        pen.arc(138.0, s, 84.0, 4.0, BRIGHT);
    }
    for i in 0..60 {
        pen.arc(122.0, p * 1.5 + i as f32 * 6.0, 3.0, 3.0, if i % 2 == 1 { hot_dim } else { hot });
    }
    for i in 0..36 {
        let deg = -p * 0.7 + i as f32 * 10.0;
        let major = i % 3 == 0;
        pen.spoke(RCX, RCY, 104.0, if major { 118.0 } else { 114.0 }, deg,
                  if major { 2.0 } else { 1.0 }, if major { hot } else { hot_dim });
    }

    let head = p * 2.0;
    for (ext, color) in [(-46.0, GLOW[0]), (-30.0, GLOW[1]), (-14.0, GLOW[2])] {
        pen.pie(112.0, head, ext, color);
    }
    let tip = pol(112.0, head);
    pen.line(pos2(RCX, RCY), tip, 2.0, BRIGHT);
    pen.disc(tip.x, tip.y, 4.0, BRIGHT);

    pen.disc(RCX, RCY, 78.0, mix(hex(0x081d27), hex(0x0d2f3e), act));
    pen.ring(RCX, RCY, 78.0, 1.0, hex(0x12384a));

    // Режим речи: от ядра расходятся волны.
    if act > 0.02 {
        for i in 0..3 {
            let r = 40.0 + (p * 2.4 + i as f32 * 38.0).rem_euclid(114.0);
            let fade = (1.0 - (r - 40.0) / 114.0).max(0.0).powf(0.6) * act;
            pen.ring(RCX, RCY, r, 3.0, mix(hex(0x081d27), BRIGHT, fade));
        }
    }

    for i in 0..6 {
        let c = pol(100.0, -p * 0.5 + i as f32 * 60.0);
        pen.poly(
            vec![pos2(c.x, c.y - 8.0), pos2(c.x + 8.0, c.y), pos2(c.x, c.y + 8.0), pos2(c.x - 8.0, c.y)],
            PANEL_HI,
            2.0,
            if i % 2 == 1 { AMBER } else { hot },
        );
    }
    for (sign, color, r) in [(1.0, hot_dim, 84.0), (-1.0, hot, 68.0)] {
        let pts = (0..3).map(|i| pol(r, sign * p + i as f32 * 120.0 + 90.0)).collect();
        pen.closed(pts, 2.0, color);
    }

    let pulse = (4.0 + 9.0 * act) * (pp * PI / 180.0).sin();
    pen.arc(60.0 + pulse, p * 2.6, 300.0, 2.0 + (act * 2.0).floor(), BRIGHT);
    for i in 0..12 {
        pen.spoke(RCX, RCY, 64.0, 70.0 + 4.0 * act, p * 1.4 + i as f32 * 30.0, 2.0, hot);
    }
    for k in 0..GLOW.len() {
        pen.disc(RCX, RCY, 46.0 + pulse - k as f32 * 8.0 + 4.0 * act, mix(GLOW[k], GLOW_HOT[k], act));
    }
    pen.disc(RCX, RCY, 9.0 + pulse * 0.3 + 3.0 * act, WHITE);

    // Загрузка CPU кольцом вокруг ядра — реактор дышит вместе с машиной.
    let load = cpu.clamp(0.0, 100.0);
    if load > 1.0 {
        pen.arc(92.0, 90.0, -3.6 * load, 3.0, if load > 80.0 { AMBER } else { BRIGHT });
    }
}

fn gauges(pen: &Pen, s: &Stats) {
    let (x0, y0, x1, _) = LEFT;
    for (i, (name, value)) in [("CPU", s.cpu), ("MEM", s.mem), ("GPU", s.gpu), ("DISK", s.disk)]
        .into_iter()
        .enumerate()
    {
        let y = y0 + 56.0 + i as f32 * 28.0;
        pen.text(x0 + 18.0, y, Align2::LEFT_CENTER, name, 9.0, false, DIM);
        let (bx0, bx1) = (x0 + 62.0, x1 - 52.0);
        pen.rect(bx0, y - 6.0, bx1, y + 6.0, BG);
        pen.frame(bx0, y - 6.0, bx1, y + 6.0, 1.0, LINE);
        let v = value.clamp(0.0, 100.0);
        pen.rect(bx0, y - 6.0, bx0 + (bx1 - bx0) * v / 100.0, y + 6.0, if v < 85.0 { MID } else { AMBER });
        let mut gx = bx0 + 6.0;
        while gx < bx1 {
            pen.vline(gx, y - 6.0, y + 6.0, 1.0, BG);
            gx += 7.0;
        }
        pen.text(x1 - 14.0, y, Align2::RIGHT_CENTER, &format!("{:3.0}%", v), 9.0, false, WHITE);
    }
}

fn net_graph(pen: &Pen, s: &Stats) {
    let (x0, y0, x1, _) = LEFT;
    let (bx0, bx1, by0, by1) = (x0 + 18.0, x1 - 18.0, y0 + 190.0, y0 + 252.0);
    pen.rect(bx0, by0, bx1, by1, BG);
    pen.frame(bx0, by0, bx1, by1, 1.0, LINE);
    for gy in 1..3 {
        pen.hline(bx0, bx1, by0 + (by1 - by0) * gy as f32 / 3.0, 1.0, hex(0x0b2029));
    }
    let top = s.net_max.max(1.0);
    let n = s.net_hist.len().max(2);
    let pts = s
        .net_hist
        .iter()
        .enumerate()
        .map(|(i, v)| {
            pos2(bx0 + (bx1 - bx0) * i as f32 / (n - 1) as f32,
                 by1 - 4.0 - (by1 - by0 - 8.0) * (v / top).min(1.0))
        })
        .collect();
    pen.polyline(pts, 2.0, BRIGHT);
    pen.text(bx0 + 6.0, by0 + 10.0, Align2::LEFT_CENTER, &format!("{:.0} KB/S", s.net), 9.0, true, MID);
    pen.text(bx1 - 6.0, by0 + 10.0, Align2::RIGHT_CENTER, &format!("peak {top:.0}"), 8.0, false, DIM);
}

fn net_bar(pen: &Pen, s: &Stats) {
    let (x0, y0, x1, _) = LEFT;
    let (bx0, bx1, y) = (x0 + 18.0, x1 - 18.0, y0 + 262.0);
    let n = 26;
    let step = (bx1 - bx0) / n as f32;
    let level = (s.net / s.net_max.max(1.0)).min(1.0);
    for i in 0..n {
        let on = (i as f32 / n as f32) < level;
        let color = if i as f32 > n as f32 * 0.86 {
            if on { AMBER } else { OFF_A }
        } else if i as f32 > n as f32 * 0.66 {
            if on { BRIGHT } else { OFF_B }
        } else if on {
            MID
        } else {
            OFF_C
        };
        let x = bx0 + i as f32 * step;
        pen.rect(x, y, x + step - 2.0, y + 11.0, color);
    }
}

fn machine(pen: &Pen, s: &Stats) {
    let (x0, y0, x1, _) = LEFT;
    let rows = [
        ("UPTIME", if s.uptime.is_empty() { "--:--:--".to_string() } else { s.uptime.clone() }),
        ("PROCESSES", s.nproc.to_string()),
        ("CPU CLOCK", if s.freq > 0.0 { format!("{:.2} GHz", s.freq) } else { "--".into() }),
        ("GPU TEMP", if s.gpu_temp > 0.0 { format!("{:.0} C", s.gpu_temp) } else { "--".into() }),
        ("MEM USED", format!("{:.1} GB", s.mem_used)),
    ];
    for (i, (name, value)) in rows.iter().enumerate() {
        let y = y0 + 322.0 + i as f32 * 22.0;
        pen.text(x0 + 20.0, y, Align2::LEFT_CENTER, name, 9.0, false, DIM);
        pen.text(x1 - 16.0, y, Align2::RIGHT_CENTER, value, 9.0, false, WHITE);
    }
}

fn chart_frame(pen: &Pen, x0: f32, y0: f32, x1: f32, y1: f32) {
    pen.rect(x0, y0, x1, y1, BG);
    pen.frame(x0, y0, x1, y1, 1.0, LINE);
    for part in [0.25, 0.5, 0.75] {
        let y = y1 - (y1 - y0) * part;
        pen.hline(x0 + 1.0, x1 - 1.0, y, 1.0, hex(0x0b2029));
        pen.text(x0 + 4.0, y - 6.0, Align2::LEFT_CENTER, &format!("{}", (part * 100.0) as i32), 7.0, false, hex(0x14455a));
    }
}

fn bars(pen: &Pen, values: &[f32], x0: f32, top: f32, width: f32, height: f32) {
    let step = width / values.len().max(1) as f32;
    for (i, v) in values.iter().enumerate() {
        let v = v.clamp(0.0, 100.0);
        let h = 3.0 + (height - 6.0) * v / 100.0;
        let x = x0 + i as f32 * step;
        pen.rect(x, top + height - h, x + step - 3.0, top + height - 1.0, if v > 85.0 { AMBER } else { MID });
    }
}

fn cores(pen: &Pen, s: &Stats) {
    let (x0, y0, x1, _) = RIGHT;
    let values: Vec<f32> = if s.cores.is_empty() { vec![0.0] } else { s.cores.clone() };
    let (top, height) = (y0 + 46.0, 140.0);
    chart_frame(pen, x0 + 18.0, top, x1 - 18.0, top + height);
    bars(pen, &values, x0 + 18.0, top, x1 - x0 - 36.0, height);
    let peak = values.iter().cloned().fold(0.0, f32::max);
    pen.text(x0 + 18.0, top + height + 16.0, Align2::LEFT_CENTER,
             &format!("{} LOGICAL CORES", values.len()), 8.0, false, DIM);
    pen.text(x1 - 16.0, top + height + 16.0, Align2::RIGHT_CENTER, &format!("MAX {peak:.0}%"), 8.0, false, DIM);
}

fn cpu_graph(pen: &Pen, s: &Stats) {
    let (x0, y0, x1, _) = RIGHT;
    let (top, height) = (y0 + 238.0, 74.0);
    chart_frame(pen, x0 + 18.0, top, x1 - 18.0, top + height);
    let hist: Vec<f32> = s.cpu_hist.iter().cloned().collect();
    bars(pen, &hist, x0 + 18.0, top, x1 - x0 - 36.0, height);
    let peak = hist.iter().cloned().fold(0.0, f32::max);
    pen.text(x0 + 18.0, y0 + 326.0, Align2::LEFT_CENTER, &format!("NOW {:.0}%", s.cpu), 8.0, false, DIM);
    pen.text(x1 - 16.0, y0 + 326.0, Align2::RIGHT_CENTER, &format!("PEAK {peak:.0}%"), 8.0, false, DIM);
}

fn markets(pen: &Pen, s: &Stats) {
    let (x0, y0, x1, _) = RIGHT;
    if s.coins.is_empty() {
        pen.text(x0 + 18.0, y0 + 372.0, Align2::LEFT_CENTER, "нет связи", 9.0, false, DIM);
        return;
    }
    for (i, (ticker, value, change)) in s.coins.iter().take(6).enumerate() {
        let y = y0 + 370.0 + i as f32 * 16.0;
        pen.text(x0 + 18.0, y, Align2::LEFT_CENTER, ticker, 9.0, true, WHITE);
        pen.text(x1 - 74.0, y, Align2::RIGHT_CENTER, &price(*value), 9.0, false, MID);
        pen.text(x1 - 16.0, y, Align2::RIGHT_CENTER, &format!("{change:+.2}%"), 9.0, false,
                 if *change >= 0.0 { GREEN } else { RED });
    }
}

fn header(pen: &Pen, s: &Stats, label: &str, act: f32) {
    let now = chrono::Local::now();
    pen.text(W - 28.0, 24.0, Align2::RIGHT_CENTER, &now.format("%H:%M:%S").to_string(), 15.0, true, WHITE);
    pen.text(W - 28.0, 46.0, Align2::RIGHT_CENTER,
             &now.format("%d.%m.%Y  %a").to_string().to_uppercase(), 8.0, false, DIM);
    pen.text(28.0, 47.0, Align2::LEFT_CENTER,
             &format!("UPTIME {}  //  {} PROC", s.uptime, s.nproc), 8.0, false, DIM);
    pen.text(W / 2.0, 32.0, Align2::CENTER_CENTER, label, 14.0, true, mix(AMBER, WHITE, act));
}

fn footer(pen: &Pen, f: f32, act: f32) {
    let y = H - FOOT_H / 2.0 - 3.0;
    let (text, color) = if act > 0.5 {
        (">> SPEAKING".to_string(), AMBER)
    } else {
        (format!("LISTENING{}", ".".repeat(1 + (f / 8.0) as usize % 3)), BRIGHT)
    };
    pen.text(28.0, y, Align2::LEFT_CENTER, &text, 10.0, true, color);
    let (bx0, bx1) = (210.0, W - 250.0);
    pen.rect(bx0, y - 6.0, bx1, y + 6.0, BG);
    pen.frame(bx0, y - 6.0, bx1, y + 6.0, 1.0, LINE);
    let p = (f * 1.6).rem_euclid(bx1 - bx0);
    pen.rect(bx0 + p, y - 6.0, bx0 + (p + 90.0).min(bx1 - bx0), y + 6.0, mix(MID, AMBER, act));
}

/// Компактный режим: тот же реактор в круге и строка состояния — в углу поверх игры.
#[allow(clippy::too_many_arguments)]
fn orb(ctx: &egui::Context, alpha: f32, elapsed: f32, p: f32, pp: f32, act: f32, cpu: f32, label: &str, f: f32) {
    // Появление: круг раскрывается из 70 % размера, без рывка.
    let t = (elapsed / 0.35).min(1.0);
    let grow = 0.7 + 0.3 * (1.0 - (1.0 - t).powi(3));
    let (cx, cy) = (ORB_W / 2.0, ORB_R + 6.0);
    // Реактор рисуется в своих координатах (центр RCX, RCY) — перо его сжимает
    // и переносит. Слои egui с трансформацией оставляли в прозрачном окне мусор.
    let painter = ctx.layer_painter(egui::LayerId::background());
    let pen = Pen { p: &painter, a: alpha, s: ORB_R / 172.0 * grow, o: pos2(cx, cy) };
    // Подложка — чтобы линии не сливались с картинкой игры под кругом.
    pen.disc(RCX, RCY, 172.0, Color32::from_rgba_unmultiplied(3, 8, 13, 230));
    pen.ring(RCX, RCY, 172.0, 3.0, mix(LINE, MID, act));
    reactor(&pen, p, pp, act, cpu);

    let pen = Pen::new(&painter, alpha);
    let y = ORB_H - 20.0;
    let status = if act > 0.5 { ">> SPEAKING".to_string() } else { label.chars().take(26).collect() };
    pen.p.rect_filled(
        egui::Rect::from_min_max(pos2(14.0, y - 11.0), pos2(ORB_W - 14.0, y + 11.0)),
        3.0,
        pen.c(Color32::from_rgba_unmultiplied(3, 8, 13, 225)),
    );
    pen.frame(14.0, y - 11.0, ORB_W - 14.0, y + 11.0, 1.0, LINE);
    // Бегущий штрих снизу — признак того, что ассистент слушает.
    let span = ORB_W - 40.0;
    let x = 20.0 + (f * 1.2).rem_euclid(span - 30.0);
    pen.hline(x, x + 30.0, y + 11.0, 2.0, mix(MID, AMBER, act));
    pen.text(ORB_W / 2.0, y, Align2::CENTER_CENTER, &status, 8.5, true, mix(BRIGHT, AMBER, act));
}

fn msaa() -> u16 {
    std::env::var("JARVIS_HUD_MSAA").ok().and_then(|v| v.parse().ok()).unwrap_or(4)
}

fn main() -> eframe::Result {
    let args = parse_args();
    let plan = plan(&args);
    if let Some(path) = &args.explain {
        let _ = std::fs::write(path, format!(
            "orb={} corner={} monitor={:?} reason={}\n",
            plan.orb, plan.corner, plan.monitor.map(|m| (m.full, m.primary)), plan.reason));
    }
    let size = if plan.orb { vec2(ORB_W, ORB_H) } else { vec2(W, H) };
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title("JARVIS")
            .with_inner_size(size)
            .with_decorations(false)
            .with_transparent(true)
            .with_always_on_top()
            .with_taskbar(false)
            .with_resizable(false)
            // Не отбирать фокус: окно всплывает поверх игры, а клавиатура остаётся у неё.
            .with_active(false),
        centered: true,
        // Без vsync: драйвер NVIDIA в OpenGL ждёт кадровую развёртку холостым
        // циклом и съедает ядро целиком. Темп кадров держим сами.
        vsync: false,
        multisampling: msaa(),
        ..Default::default()
    };
    eframe::run_native("JARVIS", options, Box::new(|cc| Ok(Box::new(Hud::new(cc, args, plan)))))
}
