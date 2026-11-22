//! Установка компонентов для мастера: свой Python (встраиваемая сборка с
//! python.org), затем пакеты, модели и Ollama — через setup_tool.py ядра.
//! Прогресс — событиями «setup:event» в окно.

use std::fs;
use std::io::{BufRead, Read, Write};
use std::path::Path;
use std::process::{Command, Stdio};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

use serde_json::{json, Value};
use tauri::{AppHandle, Emitter};

use crate::core::Core;

const PYTHON_ZIP: &str = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip";
const GET_PIP: &str = "https://bootstrap.pypa.io/get-pip.py";
static INSTALLING: AtomicBool = AtomicBool::new(false);
struct InstallGuard;
impl Drop for InstallGuard {
    fn drop(&mut self) { INSTALLING.store(false, Ordering::Release); }
}
#[cfg(windows)]
const NO_WINDOW: u32 = 0x0800_0000;

fn emit(app: &AppHandle, event: Value) {
    let _ = app.emit("setup:event", event);
}

fn hide(command: &mut Command) -> &mut Command {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(NO_WINDOW);
    }
    command
}

/// Что установлено. Без Python — только это и сообщаем.
pub fn check(core: &Core) -> Value {
    let Some(python) = core.python() else {
        return json!({ "python": { "ok": false } });
    };
    let output = hide(Command::new(python).args(["setup_tool.py", "check"]).current_dir(&core.root))
        .env("PYTHONIOENCODING", "utf-8")
        .output();
    let mut report = output
        .ok()
        .and_then(|o| serde_json::from_slice::<Value>(&o.stdout).ok())
        .unwrap_or_else(|| json!({}));
    report["python"] = json!({ "ok": true });
    report
}

/// Скачать файл с прогрессом (через системный прокси — как браузер).
fn download(app: &AppHandle, component: &str, url: &str, path: &Path) -> Result<(), String> {
    let client = reqwest::blocking::Client::builder()
        .timeout(None)
        .connect_timeout(Duration::from_secs(20))
        .user_agent("Jarvis-Setup/2.0")
        .build()
        .map_err(|e| e.to_string())?;
    let mut last_error = String::new();
    for attempt in 1..=4 {
        match (|| -> Result<(), String> {
            let mut response = client.get(url).send().and_then(|r| r.error_for_status()).map_err(|e| e.to_string())?;
            let total = response.content_length().unwrap_or(0);
            let part = path.with_extension("part");
            let mut out = fs::File::create(&part).map_err(|e| e.to_string())?;
            let mut buf = vec![0u8; 1 << 16];
            let (mut done, mut last) = (0u64, Instant::now());
            loop {
                let n = response.read(&mut buf).map_err(|e| e.to_string())?;
                if n == 0 {
                    break;
                }
                out.write_all(&buf[..n]).map_err(|e| e.to_string())?;
                done += n as u64;
                if last.elapsed() > Duration::from_millis(250) {
                    emit(app, json!({"component": component, "stage": "download", "done": done, "total": total}));
                    last = Instant::now();
                }
            }
            drop(out);
            fs::rename(&part, path).map_err(|e| e.to_string())?;
            Ok(())
        })() {
            Ok(()) => return Ok(()),
            Err(error) => {
                last_error = error;
                emit(app, json!({"component": component, "stage": "retry", "text": format!("обрыв связи, попытка {}", attempt + 1)}));
                std::thread::sleep(Duration::from_secs(2 * attempt));
            }
        }
    }
    Err(format!("не удалось скачать {url}: {last_error}"))
}

/// Встраиваемый Python 3.11 в core\runtime + pip. Без установщиков и без прав администратора.
fn install_python(app: &AppHandle, root: &Path) -> Result<(), String> {
    if !cfg!(windows) {
        return Err("На Linux установите Python 3.11+ и создайте .venv в папке ядра (см. docs/LINUX.md).".into());
    }
    let runtime = root.join("runtime");
    if runtime.join("python.exe").exists() && hide(Command::new(runtime.join("python.exe")).args(["-m", "pip", "--version"]))
        .stdout(Stdio::null()).stderr(Stdio::null()).status().is_ok_and(|s| s.success()) {
        return Ok(());
    }
    let downloads = root.join("models").join("_download");
    fs::create_dir_all(&downloads).map_err(|e| e.to_string())?;
    let archive = downloads.join("python-embed.zip");
    download(app, "python", PYTHON_ZIP, &archive)?;
    emit(app, json!({"component": "python", "stage": "extract"}));
    let file = fs::File::open(&archive).map_err(|e| e.to_string())?;
    let mut zip = zip::ZipArchive::new(file).map_err(|e| e.to_string())?;
    zip.extract(&runtime).map_err(|e| e.to_string())?;
    let _ = fs::remove_file(&archive);
    // ._pth управляет путями встраиваемого Python: включить site (для pip) и
    // добавить папку ядра, чтобы импортировались его модули.
    if let Some(pth) = fs::read_dir(&runtime).ok().and_then(|d| {
        d.filter_map(|e| e.ok()).map(|e| e.path()).find(|p| p.extension().is_some_and(|x| x == "_pth"))
    }) {
        let text = fs::read_to_string(&pth).unwrap_or_default();
        let mut lines: Vec<String> = text.lines().filter(|l| *l != ".." && *l != "Lib\\site-packages")
            .map(|l| l.replace("#import site", "import site")).collect();
        lines.insert(0, "..".into());
        lines.insert(1, "Lib\\site-packages".into());
        fs::write(&pth, lines.join("\r\n")).map_err(|e| e.to_string())?;
    }
    let get_pip = runtime.join("get-pip.py");
    download(app, "python", GET_PIP, &get_pip)?;
    emit(app, json!({"component": "python", "stage": "pip"}));
    let status = hide(Command::new(runtime.join("python.exe")).arg(&get_pip).args(["--no-warn-script-location"]))
        .current_dir(&runtime)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map_err(|e| e.to_string())?;
    let _ = fs::remove_file(&get_pip);
    if !status.success() {
        return Err("не удалось установить pip".into());
    }
    Ok(())
}

/// Установить список компонентов в фоне; итог — событие {status: "finished"}.
pub fn install(app: AppHandle, core: Arc<Core>, components: Vec<String>) -> Result<(), String> {
    if INSTALLING.compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire).is_err() {
        return Err("Установка уже идёт. Дождитесь её завершения.".into());
    }
    std::thread::spawn(move || {
        let _guard = InstallGuard;
        let mut failed = 0;
        let rest: Vec<String> = components.iter().filter(|c| c.as_str() != "python").cloned().collect();
        if components.iter().any(|c| c == "python") || core.python().is_none() {
            emit(&app, json!({"component": "python", "status": "start"}));
            match install_python(&app, &core.root) {
                Ok(()) => emit(&app, json!({"component": "python", "status": "ok"})),
                Err(error) => {
                    failed += 1;
                    emit(&app, json!({"component": "python", "status": "error", "message": error}));
                }
            }
        }
        if !rest.is_empty() {
            if let Some(python) = core.python() {
                let child = hide(Command::new(python).arg("setup_tool.py").arg("install").args(&rest))
                    .current_dir(&core.root)
                    .env("PYTHONIOENCODING", "utf-8")
                    .env("PYTHONUTF8", "1")
                    .stdout(Stdio::piped())
                    .stderr(Stdio::null())
                    .spawn();
                match child {
                    Ok(mut child) => {
                        if let Some(stdout) = child.stdout.take() {
                            for line in std::io::BufReader::new(stdout).lines().map_while(Result::ok) {
                                if let Ok(event) = serde_json::from_str::<Value>(&line) {
                                    if event.get("status").and_then(|s| s.as_str()) == Some("error") {
                                        failed += 1;
                                    }
                                    emit(&app, event);
                                }
                            }
                        }
                        if !child.wait().is_ok_and(|status| status.success()) {
                            failed += 1;
                            emit(&app, json!({"component": "setup", "status": "error", "message": "Установка завершилась аварийно. Повторите установку."}));
                        }
                    }
                    Err(error) => {
                        failed += 1;
                        emit(&app, json!({"component": "setup", "status": "error", "message": error.to_string()}));
                    }
                }
            } else {
                failed += 1;
            }
        }
        emit(&app, json!({"status": "finished", "ok": failed == 0}));
    });
    Ok(())
}
