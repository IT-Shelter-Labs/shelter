//! Прозрачный слой всего рабочего стола. Координаты персонажа независимы от окна.
use serde_json::{json, Value};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use tauri::{
    AppHandle, Emitter, Manager, PhysicalPosition, PhysicalSize, WebviewUrl, WebviewWindowBuilder,
};

const LABEL: &str = "avatar";
static SNAPSHOT: Mutex<Option<Value>> = Mutex::new(None);
static GEOMETRY: Mutex<Option<(PathBuf, Value)>> = Mutex::new(None);
static INTERACTIVE: Mutex<Option<bool>> = Mutex::new(None);
static MENU_OPEN: Mutex<bool> = Mutex::new(false);
static RENDER_STATE: Mutex<String> = Mutex::new(String::new());
pub fn report(state: String) { *RENDER_STATE.lock().unwrap() = state; }
pub fn runtime() -> Value { json!({"renderer":RENDER_STATE.lock().unwrap().clone(),"menu":*MENU_OPEN.lock().unwrap()}) }

pub fn snapshot() -> Value {
    SNAPSHOT.lock().unwrap().clone().unwrap_or(json!({}))
}

pub fn handle(app: &AppHandle, event: &Value) {
    *SNAPSHOT.lock().unwrap() = Some(event.clone());
    let event = event.clone();
    let app = app.clone();
    let handle = app.clone();
    let _ = handle.run_on_main_thread(move || {
        if event["state"] == "hide" {
            if let Some(w) = app.get_webview_window(LABEL) {
                let _ = w.hide();
            }
        } else if event["state"] != "idle" {
            show(&app, event["model"].as_str().unwrap_or(""));
        }
    });
}

fn show(app: &AppHandle, model: &str) {
    if let Some(w) = app.get_webview_window(LABEL) {
        let _ = w.show();
        return;
    }
    let url = format!("avatar.html?model={}", encode(model));
    let Ok(w) = WebviewWindowBuilder::new(app, LABEL, WebviewUrl::App(url.into()))
        .title("Персонаж")
        .decorations(false)
        .transparent(true)
        .shadow(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .resizable(false)
        .focused(false)
        .visible(false)
        .background_color(tauri::utils::config::Color(0, 0, 0, 0))
        .build()
    else {
        return;
    };
    if let Ok(monitors) = w.available_monitors() {
        let rects: Vec<(i32, i32, u32, u32)> = monitors
            .iter()
            .map(|m| {
                let a = m.work_area();
                (a.position.x, a.position.y, a.size.width, a.size.height)
            })
            .collect();
        if let Some((x, y, width, height)) = union(&rects) {
            let _ = w.set_position(PhysicalPosition::new(x, y));
            let _ = w.set_size(PhysicalSize::new(width, height));
        }
    }
    let _ = w.set_ignore_cursor_events(true);
    *INTERACTIVE.lock().unwrap() = Some(false);
    let _ = w.show();
}

fn union(rects: &[(i32, i32, u32, u32)]) -> Option<(i32, i32, u32, u32)> {
    if rects.is_empty() {
        return None;
    }
    let x = rects.iter().map(|r| r.0).min()?;
    let y = rects.iter().map(|r| r.1).min()?;
    let right = rects.iter().map(|r| r.0 as i64 + r.2 as i64).max()?;
    let bottom = rects.iter().map(|r| r.1 as i64 + r.3 as i64).max()?;
    Some((x, y, (right - x as i64) as u32, (bottom - y as i64) as u32))
}

pub fn layout(app: &AppHandle) -> Result<Value, String> {
    let w = app
        .get_webview_window(LABEL)
        .ok_or("окно персонажа не открыто")?;
    if let Ok(monitors) = w.available_monitors() {
        let rects: Vec<_> = monitors
            .iter()
            .map(|m| {
                let a = m.work_area();
                (a.position.x, a.position.y, a.size.width, a.size.height)
            })
            .collect();
        if let Some((x, y, width, height)) = union(&rects) {
            if w.outer_size()
                .map(|s| s.width != width || s.height != height)
                .unwrap_or(true)
                || w.outer_position()
                    .map(|p| p.x != x || p.y != y)
                    .unwrap_or(true)
            {
                let _ = w.set_position(PhysicalPosition::new(x, y));
                let _ = w.set_size(PhysicalSize::new(width, height));
            }
        }
    }
    let origin = w.outer_position().map_err(|e| e.to_string())?;
    let scale = w.scale_factor().map_err(|e| e.to_string())?;
    let mut monitors = w.available_monitors().map_err(|e| e.to_string())?;
    let primary = w.primary_monitor().ok().flatten();
    monitors.sort_by_key(|m| {
        (
            if primary
                .as_ref()
                .map(|p| p.position() == m.position())
                .unwrap_or(false)
            {
                0
            } else {
                1
            },
            m.position().x,
            m.position().y,
        )
    });
    let screens: Vec<Value> = monitors.iter().enumerate().map(|(i,m)| {
        let a=m.work_area();
        json!({"monitor":i+1,"x":(a.position.x-origin.x) as f64/scale,"y":(a.position.y-origin.y) as f64/scale,
               "width":a.size.width as f64/scale,"height":a.size.height as f64/scale})
    }).collect();
    let core = app.state::<std::sync::Arc<crate::core::Core>>();
    let saved = std::fs::read(core.root.join("data/avatar-placement.json"))
        .ok()
        .and_then(|b| serde_json::from_slice::<Value>(&b).ok());
    let anchor = saved.and_then(|v| {
        let x = v["x"].as_f64()?;
        let y = v["y"].as_f64()?;
        if !x.is_finite() || !y.is_finite() {
            return None;
        }
        if monitors.iter().any(|m| {
            let a = m.work_area();
            x >= a.position.x as f64
                && x < a.position.x as f64 + a.size.width as f64
                && y >= a.position.y as f64
                && y <= a.position.y as f64 + a.size.height as f64
        }) {
            Some(json!({"x":(x-origin.x as f64)/scale,"y":(y-origin.y as f64)/scale}))
        } else {
            None
        }
    });
    Ok(json!({"screens":screens,"anchor":anchor}))
}

pub fn pointer(app: &AppHandle, interactive: bool) -> Result<Value, String> {
    let w = app
        .get_webview_window(LABEL)
        .ok_or("окно персонажа не открыто")?;
    let forced = snapshot()
        .pointer("/options/click_through")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let interactive = *MENU_OPEN.lock().unwrap() || (interactive && !forced);
    let mut previous = INTERACTIVE.lock().unwrap();
    if *previous != Some(interactive) {
        w.set_ignore_cursor_events(!interactive)
            .map_err(|e| e.to_string())?;
        *previous = Some(interactive);
    }
    let p = w.cursor_position().map_err(|e| e.to_string())?;
    let o = w.outer_position().map_err(|e| e.to_string())?;
    let s = w.scale_factor().map_err(|e| e.to_string())?;
    Ok(json!({"x":(p.x-o.x as f64)/s,"y":(p.y-o.y as f64)/s}))
}

pub fn menu_state(active: bool) { *MENU_OPEN.lock().unwrap() = active; }

pub fn open_menu(app: &AppHandle) {
    if snapshot()["state"] == "hide" { return; }
    if let Some(w) = app.get_webview_window(LABEL) {
        let _ = w.set_focus();
        let _ = w.emit("avatar:menu", json!({}));
    }
}

/// Only geometry and opaque IDs; no window text or screenshots are collected.
pub fn surfaces(app: &AppHandle) -> Result<Value, String> {
    let w = app.get_webview_window(LABEL).ok_or("окно персонажа не открыто")?;
    let origin = w.outer_position().map_err(|e| e.to_string())?;
    let scale = w.scale_factor().map_err(|e| e.to_string())?;
    let mut result = Vec::new();
    #[cfg(windows)]
    unsafe {
        use windows::core::BOOL;
        use windows::Win32::Foundation::{HWND, LPARAM, RECT};
        use windows::Win32::UI::WindowsAndMessaging::*;
        use windows::Win32::Graphics::Dwm::{DwmGetWindowAttribute, DWMWA_EXTENDED_FRAME_BOUNDS, DWMWA_CLOAKED};
        unsafe extern "system" fn collect(hwnd: HWND, param: LPARAM) -> BOOL {
            let output = &mut *(param.0 as *mut Vec<(usize, RECT)>);
            let mut pid = 0;
            GetWindowThreadProcessId(hwnd, Some(&mut pid));
            if pid == std::process::id() || !IsWindowVisible(hwnd).as_bool() || IsIconic(hwnd).as_bool() { return BOOL(1); }
            let mut cloaked: u32 = 0;
            let _ = DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, &mut cloaked as *mut _ as _, 4);
            let style = GetWindowLongW(hwnd, GWL_STYLE) as u32;
            let ex = GetWindowLongW(hwnd, GWL_EXSTYLE) as u32;
            if cloaked != 0 || style & WS_CAPTION.0 == 0 || ex & WS_EX_TOOLWINDOW.0 != 0 { return BOOL(1); }
            let mut rect = RECT::default();
            if DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, &mut rect as *mut _ as _, std::mem::size_of::<RECT>() as u32).is_ok() && rect.right - rect.left > 120 && rect.bottom - rect.top > 80 {
                output.push((hwnd.0 as usize, rect));
            }
            BOOL(1)
        }
        let mut windows: Vec<(usize, RECT)> = Vec::new();
        let _ = EnumWindows(Some(collect), LPARAM(&mut windows as *mut _ as isize));
        // EnumWindows is front-to-back. Reject edges occluded by nearer windows.
        for (index, (id, r)) in windows.iter().enumerate() {
            if IsZoomed(HWND(*id as *mut _)).as_bool() { continue; }
            let mut intervals = vec![(r.left,r.right)];
            for (_, near) in &windows[..index] {
                if r.top < near.top || r.top >= near.bottom { continue; }
                intervals = intervals.into_iter().flat_map(|(left,right)| {
                    let mut remaining=Vec::new();
                    if near.right <= left || near.left >= right { remaining.push((left,right)); }
                    else { if near.left>left { remaining.push((left,near.left)); } if near.right<right { remaining.push((near.right,right)); } }
                    remaining
                }).collect();
            }
            for (segment,(left,right)) in intervals.into_iter().enumerate() {
                if right-left < 120 { continue; }
                result.push(json!({"id":format!("w{id}:{segment}"),"kind":"window", "x":(left-origin.x) as f64/scale,"y":(r.top-origin.y) as f64/scale,"width":(right-left) as f64/scale,"height":(r.bottom-r.top) as f64/scale}));
            }
        }
    }
    for (i, m) in w.available_monitors().map_err(|e| e.to_string())?.iter().enumerate() {
        let a = m.work_area();
        result.push(json!({"id":format!("taskbar{i}"),"kind":"taskbar","x":(a.position.x-origin.x) as f64/scale,"y":(a.position.y-origin.y) as f64/scale+a.size.height as f64/scale-1.,"width":a.size.width as f64/scale,"height":1}));
    }
    Ok(json!({"surfaces":result,"windows_supported":cfg!(windows)}))
}

pub fn anchor(app: &AppHandle, x: f64, y: f64) -> Result<(), String> {
    if !x.is_finite() || !y.is_finite() {
        return Err("неверные координаты".into());
    }
    let w = app
        .get_webview_window(LABEL)
        .ok_or("окно персонажа не открыто")?;
    let p = w.outer_position().map_err(|e| e.to_string())?;
    let s = w.scale_factor().map_err(|e| e.to_string())?;
    let core = app.state::<std::sync::Arc<crate::core::Core>>();
    *GEOMETRY.lock().unwrap() = Some((
        core.root.join("data/avatar-placement.json"),
        json!({"x":p.x as f64+x*s,"y":p.y as f64+y*s}),
    ));
    Ok(())
}

pub fn move_actor(app: &AppHandle, event: &Value) {
    let app = app.clone();
    let event = event.clone();
    let handle = app.clone();
    let _ = handle.run_on_main_thread(move || move_on_main(&app, &event));
}

fn move_on_main(app: &AppHandle, event: &Value) {
    match layout(app) {
        Ok(value) => {
            let screens = value["screens"].as_array().cloned().unwrap_or_default();
            let requested = event["monitor"].as_u64().unwrap_or(0);
            let selected = if requested == 0 {
                None
            } else {
                screens.iter().find(|s| s["monitor"] == requested).cloned()
            };
            if requested > 0 && selected.is_none() {
                let _=app.emit("core:event",json!({"kind":"avatar_notice","text":"Такой монитор не подключён.","motion_id":event["motion_id"]}));
                return;
            }
            let placement = json!({"kind":"avatar_place","rect":selected,"screens":screens,"position":event["position"],"motion_id":event["motion_id"]});
            if let Some(ref mut snapshot) = *SNAPSHOT.lock().unwrap() {
                snapshot["placement"] = placement.clone();
            }
            let _ = app.emit("core:event", placement);
        }
        Err(error) => {
            let _ = app.emit(
                "core:event",
                json!({"kind":"avatar_notice","text":error,"motion_id":event["motion_id"]}),
            );
        }
    }
}

pub fn persist() {
    if let Some((path, value)) = GEOMETRY.lock().unwrap().take() {
        if let Some(dir) = path.parent() {
            let _ = std::fs::create_dir_all(dir);
        }
        if let Ok(b) = serde_json::to_vec(&value) {
            let _ = std::fs::write(path, b);
        }
    }
}

fn encode(text: &str) -> String {
    text.bytes()
        .map(|b| match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                (b as char).to_string()
            }
            _ => format!("%{b:02X}"),
        })
        .collect()
}

/// Файл модели для окна персонажа: только .vrm из папок моделей и персонажей ядра.
pub fn model_bytes(root: &Path, path: &str) -> Result<Vec<u8>, String> {
    asset_bytes(root, path, "vrm", 128)
}

pub fn asset_bytes(
    root: &Path,
    path: &str,
    extension: &str,
    limit_mb: u64,
) -> Result<Vec<u8>, String> {
    let input = PathBuf::from(path);
    let file = if input.is_absolute() {
        input
    } else {
        root.join(input)
    }
    .canonicalize()
    .map_err(|_| "файл персонажа не найден".to_string())?;
    let allowed = ["models", "personas", "data"]
        .iter()
        .filter_map(|dir| root.join(dir).canonicalize().ok())
        .any(|dir| file.starts_with(dir));
    let vrm = file
        .extension()
        .and_then(|e| e.to_str())
        .map(|e| e.eq_ignore_ascii_case(extension))
        .unwrap_or(false);
    if !allowed || !vrm {
        return Err(format!("нужен файл .{extension} в папке персонажа"));
    }
    if std::fs::metadata(&file).map_err(|e| e.to_string())?.len() > limit_mb * 1024 * 1024 {
        return Err(format!("файл больше {limit_mb} МБ"));
    }
    std::fs::read(&file).map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn encodes_windows_paths() {
        assert_eq!(encode("C:\\a b\\м.vrm"), "C%3A%5Ca%20b%5C%D0%BC.vrm");
    }

    #[test]
    fn desktop_union_includes_monitors_on_left_and_above() {
        assert_eq!(
            union(&[(-1920, 0, 1920, 1080), (0, -200, 2560, 1440)]),
            Some((-1920, -200, 4480, 1440))
        );
        assert_eq!(union(&[]), None);
    }

    #[test]
    fn refuses_files_outside_core() {
        let root = std::env::temp_dir().join("jarvis-avatar-test");
        std::fs::create_dir_all(root.join("models")).unwrap();
        let outside = std::env::temp_dir().join("jarvis-outside.vrm");
        std::fs::write(&outside, b"x").unwrap();
        assert!(model_bytes(&root, outside.to_str().unwrap()).is_err());
        let inside = root.join("models").join("ok.vrm");
        std::fs::write(&inside, b"vrm").unwrap();
        assert_eq!(
            model_bytes(&root, inside.to_str().unwrap()).unwrap(),
            b"vrm"
        );
        let text = root.join("models").join("secret.txt");
        std::fs::write(&text, b"t").unwrap();
        assert!(model_bytes(&root, text.to_str().unwrap()).is_err());
    }

    #[test]
    fn animation_boundary_checks_type_location_and_size() {
        let root =
            std::env::temp_dir().join(format!("jarvis-animation-test-{}", std::process::id()));
        std::fs::create_dir_all(root.join("data/personas/custom")).unwrap();
        let clip = root.join("data/personas/custom/wave.vrma");
        std::fs::write(&clip, b"animation").unwrap();
        assert_eq!(
            asset_bytes(&root, "data/personas/custom/wave.vrma", "vrma", 32).unwrap(),
            b"animation"
        );
        assert!(model_bytes(&root, clip.to_str().unwrap()).is_err());
        assert!(asset_bytes(&root, clip.to_str().unwrap(), "vrma", 0).is_err());
    }
}
