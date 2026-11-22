//! «Джарвис» — окно управления: мастер настройки, лента разговора, настройки,
//! значок в трее. Само ядро (распознавание, модель, голос) — Python, см. core.rs.

mod avatar;
mod core;
mod routes;
mod appearance;
mod hardware;
mod hotkey;
mod settings;
mod setup;

use std::sync::Arc;
use std::time::Duration;

use serde_json::{json, Value};
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Listener, Manager, State, WindowEvent};

use crate::core::{After, Core, CoreState};

type CoreRef<'a> = State<'a, Arc<Core>>;

#[tauri::command]
fn app_info(core: CoreRef) -> Value {
    json!({
        "version": env!("CARGO_PKG_VERSION"),
        "root": core.root.display().to_string(),
        "onboarded": settings::user(&core.root).get("onboarded").and_then(|v| v.as_bool()).unwrap_or(false),
        "minimized": std::env::args().any(|a| a == "--minimized"),
        "platform": std::env::consts::OS,
        "contextRequested": std::env::args().any(|a| a == "--context"),
    })
}

#[tauri::command]
fn core_state(core: CoreRef) -> CoreState {
    core.state()
}

#[tauri::command]
fn core_start(app: AppHandle, core: CoreRef) -> Result<CoreState, String> {
    core.start()?;
    let state = core.state();
    let _ = app.emit("core:state", state.clone());
    Ok(state)
}

#[tauri::command]
async fn core_stop(app: AppHandle, core: CoreRef<'_>) -> Result<CoreState, String> {
    core.pause();
    let _ = app.emit("core:state", core.state());
    Ok(core.state())
}

#[tauri::command]
async fn core_restart(core: CoreRef<'_>) -> Result<(), String> {
    core.stop(After::Restart);
    Ok(())
}

#[tauri::command]
async fn core_get(core: CoreRef<'_>, path: String) -> Result<Value, String> {
    if !path.starts_with("/api/") {
        return Err("неверный адрес".into());
    }
    let core = core.inner().clone();
    tauri::async_runtime::spawn_blocking(move || core.get(&path)).await.map_err(|e| e.to_string())?
}

/// Модель персонажа (.vrm) для окна аватара — сырые байты, без JSON.
#[tauri::command]
async fn avatar_model(core: CoreRef<'_>, path: String) -> Result<tauri::ipc::Response, String> {
    let root = core.root.clone();
    let bytes = tauri::async_runtime::spawn_blocking(move || avatar::model_bytes(&root, &path))
        .await
        .map_err(|e| e.to_string())??;
    Ok(tauri::ipc::Response::new(bytes))
}

#[tauri::command]
async fn avatar_animation(core: CoreRef<'_>, path: String) -> Result<tauri::ipc::Response, String> {
    let root = core.root.clone();
    let bytes = tauri::async_runtime::spawn_blocking(move || avatar::asset_bytes(&root, &path, "vrma", 32))
        .await.map_err(|e| e.to_string())??;
    Ok(tauri::ipc::Response::new(bytes))
}

#[tauri::command]
fn avatar_snapshot() -> Value { avatar::snapshot() }

#[tauri::command]
fn avatar_layout(app: AppHandle) -> Result<Value,String> { avatar::layout(&app) }
#[tauri::command]
fn avatar_pointer(app: AppHandle, interactive: bool) -> Result<Value,String> { avatar::pointer(&app,interactive) }
#[tauri::command]
fn avatar_anchor(app: AppHandle, x: f64, y: f64) -> Result<(),String> { avatar::anchor(&app,x,y) }

#[tauri::command]
fn avatar_surfaces(app: AppHandle) -> Result<Value,String> { avatar::surfaces(&app) }
#[tauri::command]
fn avatar_menu_state(active: bool) { avatar::menu_state(active); }
#[tauri::command]
fn avatar_report(state: String) { avatar::report(state.chars().take(300).collect()); }
#[tauri::command]
fn avatar_runtime() -> Value { avatar::runtime() }
#[tauri::command]
fn avatar_menu_open(app: AppHandle) { avatar::open_menu(&app); }
#[tauri::command]
fn avatar_settings(app: AppHandle) {
    if let Some(w) = app.get_webview_window("main") { let _ = w.show(); let _ = w.set_focus(); }
    let _ = app.emit("avatar:settings", json!({}));
}
#[tauri::command]
async fn avatar_accessory(core: CoreRef<'_>, path: String) -> Result<tauri::ipc::Response, String> {
    let root = core.root.clone();
    let bytes = tauri::async_runtime::spawn_blocking(move || avatar::asset_bytes(&root, &path, "glb", 16)).await.map_err(|e| e.to_string())??;
    Ok(tauri::ipc::Response::new(bytes))
}

#[tauri::command]
async fn avatar_portrait(core: CoreRef<'_>, path: String) -> Result<tauri::ipc::Response, String> {
    let root = core.root.clone();
    let bytes = tauri::async_runtime::spawn_blocking(move || avatar::asset_bytes(&root, &path, "png", 4))
        .await.map_err(|e| e.to_string())??;
    Ok(tauri::ipc::Response::new(bytes))
}

#[tauri::command]
async fn core_post(core: CoreRef<'_>, path: String, body: Value) -> Result<Value, String> {
    if !routes::post_allowed(&path) {
        return Err(format!("Приложение не поддерживает запрос {path}"));
    }
    let core = core.inner().clone();
    // Запись образца голоса длится до 20 секунд — обычного таймаута мало.
    let long = routes::long_request(&path);
    tauri::async_runtime::spawn_blocking(move || core.post_with(&path, body, long)).await.map_err(|e| e.to_string())?
}

#[tauri::command]
fn settings_get(core: CoreRef) -> Value {
    json!({ "defaults": settings::defaults(&core.root), "user": settings::user(&core.root) })
}

#[tauri::command]
fn settings_save(app: AppHandle, core: CoreRef, user: Value) -> Result<(), String> {
    settings::save(&core.root, &user)?;
    let _=app.emit("ui:language",settings::ui_language(&core.root, &user));
    Ok(())
}

/// Горячая клавиша «говорить» — применяется сразу, без перезапуска.
#[tauri::command]
fn set_hotkey(combo: String) -> Result<(), String> {
    hotkey::change(&combo)
}

fn configured_hotkey(core: &Core) -> String {
    let pick = |v: Value| v.pointer("/wake/hotkey").and_then(|h| h.as_str()).map(str::to_string);
    pick(settings::user(&core.root))
        .or_else(|| pick(settings::defaults(&core.root)))
        .unwrap_or_else(|| hotkey::DEFAULT.to_string())
}

#[tauri::command]
async fn hardware_info(core: CoreRef<'_>) -> Result<hardware::HardwareInfo, String> {
    let root = core.root.clone();
    tauri::async_runtime::spawn_blocking(move || hardware::detect(&root)).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn setup_check(core: CoreRef<'_>) -> Result<Value, String> {
    let core = core.inner().clone();
    tauri::async_runtime::spawn_blocking(move || setup::check(&core)).await.map_err(|e| e.to_string())
}

#[tauri::command]
fn setup_install(app: AppHandle, core: CoreRef, components: Vec<String>) -> Result<(), String> {
    setup::install(app, core.inner().clone(), components)
}

#[tauri::command]
fn open_in_system(core: CoreRef, what: String) -> Result<(), String> {
    let path = match what.as_str() {
        "logs" => core.root.join("logs").join("jarvis.log"),
        "folder" => core.root.clone(),
        "config" => core.root.join("config.yaml"),
        _ => return Err("неизвестно, что открыть".into()),
    };
    tauri_plugin_opener::open_path(path, None::<&str>).map_err(|e| e.to_string())
}

fn show_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

fn show_context(app: &AppHandle) {
    show_main(app);
    let _ = app.emit("assistant:context", true);
}

#[cfg(windows)]
fn context_shortcut(app: AppHandle) {
    std::thread::spawn(move || unsafe {
        use windows::Win32::UI::Input::KeyboardAndMouse::{RegisterHotKey, UnregisterHotKey, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT, VK_SPACE};
        use windows::Win32::UI::WindowsAndMessaging::{GetMessageW, MSG, WM_HOTKEY};
        if RegisterHotKey(None, 0x4a56, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_SPACE.0 as u32).is_err() {
            eprintln!("Контекст: Ctrl+Shift+Space занят другой программой; кнопка в окне остаётся доступной");
            return;
        }
        let mut message = MSG::default();
        while GetMessageW(&mut message, None, 0, 0).0 > 0 {
            if message.message == WM_HOTKEY {
                show_context(&app);
            }
        }
        let _ = UnregisterHotKey(None, 0x4a56);
    });
}

fn build_tray(app: &tauri::App, core: Arc<Core>) -> tauri::Result<()> {
    let en=settings::ui_language(&core.root, &settings::user(&core.root))=="en";
    let open = MenuItem::with_id(app, "open", if en {"Open Shelter"} else {"Открыть Shelter"}, true, None::<&str>)?;
    let pause = MenuItem::with_id(app, "pause", if en {"Pause / Start"} else {"Пауза / Запустить"}, true, None::<&str>)?;
    let restart = MenuItem::with_id(app, "restart", if en {"Restart"} else {"Перезапустить"}, true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", if en {"Quit"} else {"Выход"}, true, None::<&str>)?;
    let separator = PredefinedMenuItem::separator(app)?;
    let menu = Menu::with_items(app, &[&open, &pause, &restart, &separator, &quit])?;
    TrayIconBuilder::with_id("main")
        .icon(app.default_window_icon().cloned().expect("icon"))
        .tooltip("Shelter")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(move |app, event| match event.id.as_ref() {
            "open" => show_main(app),
            "pause" => {
                let state = core.state();
                if state.running {
                    core.pause();
                } else {
                    let _ = core.start();
                }
                let _ = app.emit("core:state", core.state());
            }
            "restart" => core.stop(After::Restart),
            "quit" => {
                core.shutdown();
                app.exit(0);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = event {
                show_main(tray.app_handle());
            }
        })
        .build(app)?;
    let handle=app.handle().clone();
    app.listen("ui:language",move |event|{
        let en=serde_json::from_str::<String>(event.payload()).ok().as_deref()==Some("en");
        for (item,ru,en_text) in [(&open,"Открыть Shelter","Open Shelter"),(&pause,"Пауза / Запустить","Pause / Start"),
            (&restart,"Перезапустить","Restart"),(&quit,"Выход","Quit")] {
            let _=item.set_text(if en {en_text} else {ru});
        }
        if let Some(tray)=handle.tray_by_id("main") {let _=tray.set_tooltip(Some("Shelter"));}
    });
    Ok(())
}

pub fn run() {
    let core = Core::new(core::find_root());
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, args, _cwd| {
            if args.iter().any(|a| a == "--context") { show_context(app); }
            else { show_main(app); }
        }))
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            Some(vec!["--minimized"]),
        ))
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(core.clone())
        .setup(move |app| {
            build_tray(app, core.clone())?;
            #[cfg(windows)]
            context_shortcut(app.handle().clone());
            hotkey::start(app.handle().clone(), core.clone(), configured_hotkey(&core));
            let handle = app.handle().clone();
            let monitor = core.clone();
            std::thread::spawn(move || loop {
                monitor.tick(&handle);
                avatar::persist();
                std::thread::sleep(Duration::from_millis(500));
            });
            core.pump_events(app.handle().clone());
            // Настроено — ядро работает сразу; первый запуск — сначала мастер.
            let onboarded = settings::user(&core.root).get("onboarded").and_then(|v| v.as_bool()).unwrap_or(false);
            if onboarded && core.python().is_some() {
                let _ = core.start();
            }
            let minimized = std::env::args().any(|a| a == "--minimized");
            if !minimized || !onboarded {
                show_main(app.handle());
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            // Крестик прячет окно в трей: ассистент продолжает слушать.
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .invoke_handler(tauri::generate_handler![
            app_info,
            core_state,
            core_start,
            core_stop,
            core_restart,
            core_get,
            avatar_model,
            avatar_animation,
            avatar_snapshot,
            avatar_layout,
            avatar_pointer,
            avatar_anchor,
            avatar_surfaces,
            avatar_menu_state,
            avatar_report,
            avatar_runtime,
            avatar_menu_open,
            avatar_settings,
            avatar_accessory,
            avatar_portrait,
            core_post,
            settings_get,
            settings_save,
            appearance::window_material,
            set_hotkey,
            hardware_info,
            setup_check,
            setup_install,
            open_in_system,
        ])
        .build(tauri::generate_context!())
        .expect("не удалось запустить приложение")
        .run(|app, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                if let Some(core) = app.try_state::<Arc<Core>>() {
                    core.shutdown();
                }
            }
        });
}
