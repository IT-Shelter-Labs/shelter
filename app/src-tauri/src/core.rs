//! Ядро Джарвиса (Python, main.py): запуск, присмотр, связь с ним.
//!
//! Ядро живёт в задании Windows: закрылось приложение (даже аварийно) —
//! закрылось и ядро. Упало ядро — поднимаем снова, до трёх раз за две минуты.
//! Остановка мягкая: просим ядро завершиться само (голосовой сервер, окно HUD),
//! через 10 секунд — принудительно.

use std::fs;
use std::io::BufRead;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Arc;
use std::time::{Duration, Instant};

use parking_lot::Mutex;
use serde::Serialize;
use serde_json::Value;
use tauri::{AppHandle, Emitter};

const CONTROL_PORT: u16 = 8770;
const STOP_GRACE: Duration = Duration::from_secs(10);
#[cfg(windows)]
const NO_WINDOW: u32 = 0x0800_0000;

#[derive(Clone, Copy, PartialEq)]
pub enum After {
    Nothing,
    Restart,
}

struct Inner {
    child: Option<Child>,
    paused: bool,
    crashes: Vec<Instant>,
    stopping: Option<(Instant, After)>,
    last_error: String,
    job: isize,
}

pub struct Core {
    pub root: PathBuf,
    inner: Mutex<Inner>,
    client: reqwest::blocking::Client,
    stream_client: reqwest::blocking::Client,
}

#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct CoreState {
    pub running: bool,
    pub paused: bool,
    pub stopping: bool,
    pub pid: Option<u32>,
    pub last_error: String,
    pub python: bool,
    pub root: String,
}

/// Explicit overrides win. A build inside this repository must share the
/// project's data and runtimes, rather than the public installer resources
/// Tauri stages beside target/release/Jarvis.exe.
pub fn find_root() -> PathBuf {
    if let Ok(dir) = std::env::var("JARVIS_CORE") {
        return PathBuf::from(dir);
    }
    let exe = std::env::current_exe().unwrap_or_default();
    root_from_exe(&exe)
}

fn root_from_exe(exe: &Path) -> PathBuf {
    if let Some(project) = exe.parent().into_iter().flat_map(Path::ancestors).find(|dir| {
        dir.join("main.py").is_file()
            && (dir.join("config.yaml").is_file() || dir.join("config.public.yaml").is_file())
            && dir.join("app/src-tauri/Cargo.toml").is_file()
            && dir.join("app/src-tauri/tauri.conf.json").is_file()
    }) {
        return project.to_path_buf();
    }
    if let Some(dir) = exe.parent() {
        if dir.join("core").join("main.py").exists() {
            return dir.join("core");
        }
    }
    exe.parent().into_iter().flat_map(Path::ancestors)
        .find(|dir| dir.join("main.py").exists())
        .map(Path::to_path_buf)
        .unwrap_or_else(|| exe.parent().map(Path::to_path_buf).unwrap_or_default().join("core"))
}

#[cfg(test)]
mod root_tests {
    use super::root_from_exe;
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::sync::atomic::{AtomicU64, Ordering};
    static NEXT: AtomicU64 = AtomicU64::new(0);

    struct Tree(PathBuf);
    impl Tree {
        fn new() -> Self {
            let path = std::env::temp_dir().join(format!("jarvis-root-{}-{}", std::process::id(), NEXT.fetch_add(1, Ordering::Relaxed)));
            fs::create_dir_all(&path).unwrap();
            Self(path)
        }
        fn file(&self, relative: &str) {
            let path = self.0.join(relative);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(path, "").unwrap();
        }
        fn project(&self) {
            for name in ["main.py", "config.yaml", "app/src-tauri/Cargo.toml", "app/src-tauri/tauri.conf.json"] { self.file(name); }
        }
        fn resolve(&self, exe: &str) -> PathBuf { root_from_exe(&self.0.join(exe)) }
    }
    impl Drop for Tree { fn drop(&mut self) { let _ = fs::remove_dir_all(&self.0); } }

    #[test]
    fn release_build_reuses_project_even_with_staged_installer_core() {
        let tree = Tree::new(); tree.project();
        tree.file("data/settings.json");
        tree.file("app/src-tauri/target/release/core/main.py");
        tree.file("app/src-tauri/target/release/core/data/settings.json");
        assert_eq!(tree.resolve("app/src-tauri/target/release/Jarvis.exe"), tree.0);
    }
    #[test]
    fn debug_build_and_bin_entry_point_share_the_same_project() {
        let tree = Tree::new(); tree.project();
        assert_eq!(tree.resolve("app/src-tauri/target/debug/Jarvis.exe"), tree.0);
        assert_eq!(tree.resolve("bin/jarvis.exe"), tree.0);
    }
    #[test]
    fn fresh_public_checkout_works_without_a_private_config() {
        let tree = Tree::new();
        for name in ["main.py", "config.public.yaml", "app/src-tauri/Cargo.toml", "app/src-tauri/tauri.conf.json", "app/src-tauri/target/release/core/main.py"] { tree.file(name); }
        assert_eq!(tree.resolve("app/src-tauri/target/release/Jarvis.exe"), tree.0);
    }
    #[test]
    fn installed_app_uses_bundled_core_even_with_unrelated_parent_script() {
        let tree = Tree::new();
        tree.file("main.py");
        tree.file("Programs/Jarvis/core/main.py");
        assert_eq!(tree.resolve("Programs/Jarvis/Jarvis.exe"), tree.0.join("Programs/Jarvis/core"));
    }
    #[test]
    fn portable_legacy_layout_still_works() {
        let tree = Tree::new(); tree.file("main.py");
        assert_eq!(tree.resolve("bin/jarvis.exe"), tree.0);
    }
    #[test]
    fn empty_install_defaults_to_adjacent_core() {
        let tree = Tree::new();
        assert_eq!(tree.resolve("Programs/Jarvis/Jarvis.exe"), tree.0.join("Programs/Jarvis/core"));
        assert_eq!(root_from_exe(Path::new("Jarvis.exe")), PathBuf::from("core"));
    }
}

impl Core {
    pub fn new(root: PathBuf) -> Arc<Self> {
        // Только локальный адрес — и мимо системного прокси (VPN-клиенты
        // ставят прокси без исключений, и запросы к 127.0.0.1 ломались).
        let client = reqwest::blocking::Client::builder()
            .no_proxy()
            .timeout(Duration::from_secs(8))
            .build()
            .expect("http client");
        let stream_client = reqwest::blocking::Client::builder()
            .no_proxy()
            .connect_timeout(Duration::from_secs(2))
            .timeout(None)
            .build()
            .expect("http client");
        Arc::new(Core {
            root,
            inner: Mutex::new(Inner {
                child: None,
                paused: false,
                crashes: Vec::new(),
                stopping: None,
                last_error: String::new(),
                job: job_object(),
            }),
            client,
            stream_client,
        })
    }

    pub fn python(&self) -> Option<PathBuf> {
        [self.root.join("runtime").join(if cfg!(windows) { "python.exe" } else { "bin/python3" }),
         self.root.join(if cfg!(windows) { ".venv" } else { ".venv-linux" }).join(if cfg!(windows) { "Scripts/python.exe" } else { "bin/python" }),
         self.root.join(".venv").join(if cfg!(windows) { "Scripts/python.exe" } else { "bin/python" })]
            .into_iter()
            .find(|p| p.exists())
    }

    fn token(&self) -> Option<String> {
        fs::read_to_string(self.root.join("data").join("control.token")).ok().map(|t| t.trim().to_string())
    }

    fn url(path: &str) -> String {
        format!("http://127.0.0.1:{CONTROL_PORT}{path}")
    }

    pub fn state(&self) -> CoreState {
        let inner = self.inner.lock();
        CoreState {
            running: inner.child.is_some(),
            paused: inner.paused,
            stopping: inner.stopping.is_some(),
            pid: inner.child.as_ref().map(|c| c.id()),
            last_error: inner.last_error.clone(),
            python: self.python().is_some(),
            root: self.root.display().to_string(),
        }
    }

    pub fn start(&self) -> Result<(), String> {
        let mut inner = self.inner.lock();
        if inner.child.is_some() {
            return Ok(());
        }
        let python = self.python().ok_or("Компоненты ещё не установлены — пройдите мастер настройки.")?;
        let logs = self.root.join("logs");
        let _ = fs::create_dir_all(&logs);
        let log = logs.join("jarvis.log");
        let _ = fs::rename(&log, logs.join("jarvis.prev.log"));
        let out = fs::File::create(&log).map_err(|e| format!("журнал: {e}"))?;
        let err = out.try_clone().map_err(|e| format!("журнал: {e}"))?;
        let mut command = Command::new(&python);
        command
            .args(["-u", "main.py"])
            .current_dir(&self.root)
            .env("PYTHONIOENCODING", "utf-8")
            .env("PYTHONUTF8", "1")
            .env("JARVIS_APP", "1")
            // «Джарвис, настройки» — ядро откроет окно этого приложения.
            .env("JARVIS_APP_EXE", std::env::current_exe().unwrap_or_default())
            .stdin(Stdio::null())
            .stdout(out)
            .stderr(err);
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(NO_WINDOW);
        }
        let child = command.spawn().map_err(|e| format!("не удалось запустить ядро: {e}"))?;
        assign_to_job(inner.job, &child);
        inner.child = Some(child);
        inner.paused = false;
        inner.last_error.clear();
        Ok(())
    }

    /// Попросить ядро завершиться самому; через STOP_GRACE — принудительно.
    pub fn stop(&self, after: After) {
        let running = self.inner.lock().child.is_some();
        if !running {
            if after == After::Restart {
                let _ = self.start();
            }
            return;
        }
        // Отметку — до запроса: ядро может завершиться раньше, чем придёт ответ,
        // и присмотр не должен принять это за обычный выход.
        self.inner.lock().stopping = Some((Instant::now(), after));
        if self.post("/api/stop", serde_json::json!({})).is_err() {
            let _ = fs::write(self.root.join("logs").join("stop.request"), b"stop");
        }
    }

    pub fn pause(&self) {
        self.inner.lock().paused = true;
        self.stop(After::Nothing);
    }

    /// Раз в полсекунды: не завершилось ли ядро, не пора ли добить или поднять.
    pub fn tick(&self, app: &AppHandle) {
        let mut restart = false;
        let mut changed = false;
        {
            let mut inner = self.inner.lock();
            let Some(child) = inner.child.as_mut() else { return };
            match child.try_wait() {
                Ok(None) => {
                    if let Some((since, _)) = inner.stopping {
                        if since.elapsed() > STOP_GRACE {
                            let _ = inner.child.as_mut().map(|c| c.kill());
                        }
                    }
                }
                Ok(Some(status)) => {
                    inner.child = None;
                    changed = true;
                    close_hud();
                    if let Some((_, after)) = inner.stopping.take() {
                        restart = after == After::Restart;
                    } else if !status.success() {
                        let now = Instant::now();
                        inner.crashes.retain(|t| now.duration_since(*t) < Duration::from_secs(120));
                        inner.crashes.push(now);
                        if inner.crashes.len() <= 3 {
                            inner.last_error = format!("Ядро завершилось с ошибкой (код {}), перезапускаю.",
                                                       status.code().unwrap_or(-1));
                            restart = true;
                        } else {
                            inner.paused = true;
                            inner.last_error = "Ядро падает снова и снова — остановлено. Подробности в журнале.".into();
                        }
                    }
                }
                Err(_) => {}
            }
        }
        if restart {
            if let Err(error) = self.start() {
                self.inner.lock().last_error = error;
            }
        }
        if changed || restart {
            let _ = app.emit("core:state", self.state());
        }
    }

    pub fn get(&self, path: &str) -> Result<Value, String> {
        let token = self.token().ok_or("ядро ещё не запущено")?;
        self.client
            .get(Self::url(path))
            .header("X-Jarvis-Token", token)
            .send()
            .and_then(|r| r.error_for_status())
            .and_then(|r| r.json::<Value>())
            .map_err(|e| format!("ядро не отвечает: {e}"))
    }

    pub fn post(&self, path: &str, body: Value) -> Result<Value, String> {
        self.post_with(path, body, false)
    }

    /// long — без короткого таймаута (запись образца голоса).
    pub fn post_with(&self, path: &str, body: Value, long: bool) -> Result<Value, String> {
        let token = self.token().ok_or("ядро ещё не запущено")?;
        let client = if long { &self.stream_client } else { &self.client };
        let response = client
            .post(Self::url(path))
            .timeout(Duration::from_secs(if long { 120 } else { 8 }))
            .header("X-Jarvis-Token", token)
            .json(&body)
            .send()
            .map_err(|e| format!("ядро не отвечает: {e}"))?;
        let ok = response.status().is_success();
        let value = response.json::<Value>().map_err(|e| format!("ядро не отвечает: {e}"))?;
        if ok {
            Ok(value)
        } else {
            Err(value.get("error").and_then(|e| e.as_str()).unwrap_or("ошибка ядра").to_string())
        }
    }

    /// Лента событий ядра -> событие «core:event» в окне. Переподключается сама.
    pub fn pump_events(self: &Arc<Self>, app: AppHandle) {
        let core = self.clone();
        std::thread::spawn(move || loop {
            let running = core.inner.lock().child.is_some();
            if running {
                if let Some(token) = core.token() {
                    if let Ok(response) =
                        core.stream_client.get(Self::url("/api/events")).header("X-Jarvis-Token", token).send()
                    {
                        if response.status().is_success() {
                            let _ = app.emit("core:connected", true);
                            for line in std::io::BufReader::new(response).lines() {
                                let Ok(line) = line else { break };
                                if let Ok(event) = serde_json::from_str::<Value>(&line) {
                                    let kind = event.get("kind").and_then(|k| k.as_str()).unwrap_or("");
                                    if kind == "avatar" {
                                        crate::avatar::handle(&app, &event);
                                    }
                                    if kind == "avatar_move" { crate::avatar::move_actor(&app, &event); }
                                    if kind != "ping" {
                                        let _ = app.emit("core:event", event);
                                    }
                                }
                            }
                            let _ = app.emit("core:connected", false);
                        }
                    }
                }
            }
            std::thread::sleep(Duration::from_millis(800));
        });
    }

    /// Закрытие приложения: ядро завершается само, иначе через 10 с.
    pub fn shutdown(&self) {
        self.stop(After::Nothing);
        let deadline = Instant::now() + STOP_GRACE;
        while Instant::now() < deadline {
            let mut inner = self.inner.lock();
            match inner.child.as_mut().map(|c| c.try_wait()) {
                Some(Ok(None)) => {}
                _ => return,
            }
            drop(inner);
            std::thread::sleep(Duration::from_millis(150));
        }
        if let Some(child) = self.inner.lock().child.as_mut() {
            let _ = child.kill();
        }
        close_hud();
    }
}

/// HUD-окно — отдельный процесс ядра; если ядро упало или было убито, окно
/// осталось бы висеть на экране.
fn close_hud() {
    if !cfg!(windows) { return; }
    let mut command = Command::new("taskkill");
    command.args(["/IM", "jarvis-hud.exe", "/F"]).stdout(Stdio::null()).stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(NO_WINDOW);
    }
    let _ = command.status();
}

#[cfg(windows)]
fn job_object() -> isize {
    use windows::Win32::System::JobObjects::*;
    unsafe {
        let Ok(job) = CreateJobObjectW(None, None) else { return 0 };
        let mut info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
        // Закрылось приложение — закрылось ядро. Программы, которые ядро запускает
        // по просьбе пользователя (игры, браузер), в задание не попадают.
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK;
        let _ = SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            &info as *const _ as *const std::ffi::c_void,
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        );
        job.0 as isize
    }
}

#[cfg(windows)]
fn assign_to_job(job: isize, child: &Child) {
    use std::os::windows::io::AsRawHandle;
    use windows::Win32::Foundation::HANDLE;
    use windows::Win32::System::JobObjects::AssignProcessToJobObject;
    if job != 0 {
        unsafe {
            let _ = AssignProcessToJobObject(HANDLE(job as *mut _), HANDLE(child.as_raw_handle()));
        }
    }
}

#[cfg(not(windows))]
fn job_object() -> isize {
    0
}

#[cfg(not(windows))]
fn assign_to_job(_: isize, _: &Child) {}
