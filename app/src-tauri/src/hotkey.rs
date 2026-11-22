//! Кнопка «говорить» (push-to-talk): глобальная горячая клавиша вместо слова
//! «Джарвис» — удобно в шумной игре или когда не хочется говорить имя.
//! Нажатие = «Джарвис»: сигнал, окно, игра приглушается, слушаю команду.

use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, Mutex};

use tauri::{AppHandle, Emitter, Manager};

use crate::core::Core;

pub const DEFAULT: &str = "Ctrl+Alt+J";

static COMBO: Mutex<String> = Mutex::new(String::new());
static THREAD: AtomicU32 = AtomicU32::new(0);

fn key_code(part: &str) -> Option<u32> {
    match part {
        "space" | "пробел" => Some(0x20),
        p if p.len() == 1 && p.chars().all(|c| c.is_ascii_alphanumeric()) => Some(p.to_ascii_uppercase().as_bytes()[0] as u32),
        p => p.strip_prefix('f')?.parse::<u32>().ok().filter(|n| (1..=24).contains(n)).map(|n| 0x6F + n),
    }
}

/// «Ctrl+Alt+J», «Shift+F9», «Alt+Space» -> (модификаторы Win32, виртуальная клавиша).
pub fn parse(combo: &str) -> Option<(u32, u32)> {
    let (mut mods, mut key) = (0u32, None);
    for part in combo.split('+').map(|p| p.trim().to_lowercase()).filter(|p| !p.is_empty()) {
        match part.as_str() {
            "ctrl" | "control" | "ctl" => mods |= 0x0002,
            "alt" => mods |= 0x0001,
            "shift" => mods |= 0x0004,
            "win" | "super" | "meta" => mods |= 0x0008,
            p => if key.replace(key_code(p)?).is_some() { return None; },
        }
    }
    let key = key?;
    // Без модификатора — только F-клавиши: иначе обычная буква перестала бы печататься.
    if mods == 0 && !(0x70..=0x87).contains(&key) {
        return None;
    }
    Some((mods, key))
}

#[cfg(windows)]
pub fn start(app: AppHandle, core: Arc<Core>, combo: String) {
    *COMBO.lock().unwrap() = combo;
    std::thread::spawn(move || unsafe {
        use windows::Win32::System::Threading::GetCurrentThreadId;
        use windows::Win32::UI::Input::KeyboardAndMouse::{RegisterHotKey, UnregisterHotKey, HOT_KEY_MODIFIERS, MOD_NOREPEAT};
        use windows::Win32::UI::WindowsAndMessaging::{GetMessageW, MSG, WM_APP, WM_HOTKEY};
        const ID: i32 = 0x4a57;
        THREAD.store(GetCurrentThreadId(), Ordering::SeqCst);
        let register = |app: &AppHandle| {
            let combo = COMBO.lock().unwrap().clone();
            if combo.trim().is_empty() {
                return;
            }
            match parse(&combo) {
                Some((mods, key)) => {
                    if RegisterHotKey(None, ID, HOT_KEY_MODIFIERS(mods) | MOD_NOREPEAT, key).is_err() {
                        let _ = app.emit("hotkey:error", format!("{combo} занята другой программой — выберите другую"));
                    }
                }
                None => {
                    let _ = app.emit("hotkey:error", format!("Не понимаю сочетание «{combo}»"));
                }
            }
        };
        register(&app);
        // Ctrl+Alt+T — быстрые действия с выделенным текстом: ядро берёт выделение
        // из активной программы, потом окно Джарвиса показывает панель.
        if RegisterHotKey(None, ID + 2, HOT_KEY_MODIFIERS(0x0003) | MOD_NOREPEAT, b'T' as u32).is_err() {
            let _ = app.emit("hotkey:error", "Ctrl+Alt+T занята: быстрые действия с текстом доступны голосом и на главной.");
        }
        if RegisterHotKey(None, ID + 1, HOT_KEY_MODIFIERS(0x0003) | MOD_NOREPEAT, b'M' as u32).is_err() {
            let _ = app.emit("hotkey:error", "Ctrl+Alt+M занята: меню персонажа доступно по правому клику.");
        }
        let mut message = MSG::default();
        while GetMessageW(&mut message, None, 0, 0).0 > 0 {
            if message.message == WM_HOTKEY && message.wParam.0 == (ID + 2) as usize {
                let core = core.clone();
                let app = app.clone();
                std::thread::spawn(move || {
                    let captured = core.post("/api/textops", serde_json::json!({"op": "selection"}));
                    let _ = app.emit("textops:open", captured.is_ok());
                    if let Some(window) = app.get_webview_window("main") {
                        let _ = window.show();
                        let _ = window.unminimize();
                        let _ = window.set_focus();
                    }
                });
                continue;
            }
            if message.message == WM_HOTKEY && message.wParam.0 == (ID + 1) as usize {
                crate::avatar::open_menu(&app);
                continue;
            }
            if message.message == WM_HOTKEY && message.wParam.0 == ID as usize {
                let core = core.clone();
                std::thread::spawn(move || {
                    let _ = core.post("/api/listen", serde_json::json!({}));
                });
            } else if message.message == WM_APP + 7 {
                let _ = UnregisterHotKey(None, ID);
                register(&app);
            }
        }
        let _ = UnregisterHotKey(None, ID);
        let _ = UnregisterHotKey(None, ID + 1);
        let _ = UnregisterHotKey(None, ID + 2);
    });
}

/// Поменять клавишу на лету (пустая строка — выключить).
#[cfg(windows)]
pub fn change(combo: &str) -> Result<(), String> {
    use windows::Win32::Foundation::{LPARAM, WPARAM};
    use windows::Win32::UI::WindowsAndMessaging::{PostThreadMessageW, WM_APP};
    if !combo.trim().is_empty() && parse(combo).is_none() {
        return Err(format!("Не понимаю сочетание «{combo}». Пример: Ctrl+Alt+J или F9"));
    }
    *COMBO.lock().unwrap() = combo.to_string();
    let thread = THREAD.load(Ordering::SeqCst);
    if thread != 0 {
        unsafe {
            let _ = PostThreadMessageW(thread, WM_APP + 7, WPARAM(0), LPARAM(0));
        }
    }
    Ok(())
}

#[cfg(target_os = "linux")]
static LINUX_APP: Mutex<Option<AppHandle>> = Mutex::new(None);

#[cfg(target_os = "linux")]
pub fn start(app: AppHandle, core: Arc<Core>, combo: String) {
    use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};
    if std::env::var_os("WAYLAND_DISPLAY").is_some() || std::env::var("XDG_SESSION_TYPE").unwrap_or_default() == "wayland" {
        let _ = app.emit("hotkey:error", "В Wayland глобальные клавиши пока недоступны. Используйте кнопку «Говорить» или слово-обращение.");
        return;
    }
    let text: Shortcut = "Ctrl+Alt+T".parse().unwrap();
    let menu: Shortcut = "Ctrl+Alt+M".parse().unwrap();
    let plugin = tauri_plugin_global_shortcut::Builder::new().with_handler(move |app, shortcut, event| {
        if event.state() != ShortcutState::Pressed { return; }
        if shortcut == &menu { crate::avatar::open_menu(app); return; }
        let is_text = shortcut == &text;
        let current = COMBO.lock().unwrap().parse::<Shortcut>().ok();
        if !is_text && current.as_ref() != Some(shortcut) { return; }
        let core = core.clone();
        let app = app.clone();
        std::thread::spawn(move || {
            if is_text {
                let captured = core.post("/api/textops", serde_json::json!({"op": "selection"}));
                let _ = app.emit("textops:open", captured.is_ok());
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.show(); let _ = window.unminimize(); let _ = window.set_focus();
                }
            } else { let _ = core.post("/api/listen", serde_json::json!({})); }
        });
    }).build();
    if let Err(error) = app.plugin(plugin) {
        let _ = app.emit("hotkey:error", format!("Не удалось включить горячие клавиши: {error}")); return;
    }
    for shortcut in [text, menu] {
        if let Err(error) = app.global_shortcut().register(shortcut) { let _ = app.emit("hotkey:error", error.to_string()); }
    }
    *LINUX_APP.lock().unwrap() = Some(app.clone());
    if let Err(error) = change(&combo) { let _ = app.emit("hotkey:error", error); }
}

#[cfg(target_os = "linux")]
pub fn change(combo: &str) -> Result<(), String> {
    use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut};
    let guard = LINUX_APP.lock().unwrap();
    let app = guard.as_ref().ok_or("Глобальные клавиши доступны в графическом сеансе X11")?;
    let mut old = COMBO.lock().unwrap();
    if old.as_str() == combo { return Ok(()); }
    if !combo.trim().is_empty() {
        if parse(combo).is_none() { return Err("Некорректная комбинация. Пример: Ctrl+Alt+J".into()); }
        if ["ctrl+alt+t", "ctrl+alt+m"].contains(&combo.to_lowercase().replace(' ', "").as_str()) { return Err("Эта комбинация занята быстрым меню Джарвиса".into()); }
        let shortcut: Shortcut = combo.parse().map_err(|e| format!("Не понимаю сочетание: {e}"))?;
        app.global_shortcut().register(shortcut).map_err(|e| e.to_string())?;
    }
    if let Ok(shortcut) = old.parse::<Shortcut>() { let _ = app.global_shortcut().unregister(shortcut); }
    *old = combo.to_string();
    Ok(())
}

#[cfg(not(any(windows, target_os = "linux")))]
pub fn start(_: AppHandle, _: Arc<Core>, _: String) {}

#[cfg(not(any(windows, target_os = "linux")))]
pub fn change(_: &str) -> Result<(), String> { Err("Глобальные клавиши на этой ОС пока не поддерживаются".into()) }

#[cfg(test)]
mod tests {
    use super::parse;

    #[test]
    fn rejects_multiple_primary_keys() {
        assert_eq!(parse("Ctrl+J+K"), None);
        assert_eq!(parse("F9+F10"), None);
        assert_eq!(parse("Alt+Space+J"), None);
    }

    #[test]
    fn parses_common_combos() {
        assert_eq!(parse("Ctrl+Alt+J"), Some((0x0003, b'J' as u32)));
        assert_eq!(parse("F9"), Some((0, 0x78)));
        assert_eq!(parse("shift + space"), Some((0x0004, 0x20)));
        assert_eq!(parse("J"), None, "буква без модификатора сломала бы обычный ввод");
        assert_eq!(parse("Ctrl+Что"), None);
    }
}
