//! Где показать окно: мониторы, «занят ли человек» и точная расстановка.
//!
//! Занятость — это полноэкранная игра или презентация (так считает сама
//! Windows), окно без рамки на весь монитор (так работают почти все
//! современные игры и видео) или программа из списка --busy-apps.
//! Всё это несколько системных вызовов — микросекунды, без опроса в фоне.

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Rect {
    pub left: i32,
    pub top: i32,
    pub right: i32,
    pub bottom: i32,
}

impl Rect {
    pub fn width(&self) -> i32 {
        self.right - self.left
    }
    pub fn height(&self) -> i32 {
        self.bottom - self.top
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Monitor {
    pub id: isize,
    pub full: Rect,
    /// Без панели задач: сюда ставим окно, чтобы оно её не перекрывало.
    pub work: Rect,
    pub primary: bool,
}

/// Что сейчас на экране у человека.
pub struct Situation {
    pub monitors: Vec<Monitor>,
    /// Монитор, на котором окно в фокусе (там человек и смотрит).
    pub active: Option<isize>,
    /// Почему человек занят; None — свободен.
    pub busy: Option<String>,
}

#[cfg(windows)]
mod imp {
    use super::{Monitor, Rect, Situation};
    use std::ptr::null_mut;
    use windows_sys::Win32::Foundation::{CloseHandle, BOOL, HWND, LPARAM, RECT};
    use windows_sys::Win32::Graphics::Gdi::{
        EnumDisplayMonitors, GetMonitorInfoW, MonitorFromWindow, HDC, HMONITOR, MONITORINFO,
        MONITOR_DEFAULTTONEAREST,
    };
    use windows_sys::Win32::System::Threading::{
        GetCurrentThreadId, OpenProcess, QueryFullProcessImageNameW, PROCESS_QUERY_LIMITED_INFORMATION,
    };
    use windows_sys::Win32::UI::Shell::{
        SHQueryUserNotificationState, QUNS_BUSY, QUNS_PRESENTATION_MODE, QUNS_RUNNING_D3D_FULL_SCREEN,
    };
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        EnumThreadWindows, GetClassNameW, GetForegroundWindow, GetShellWindow, GetWindowLongW,
        GetWindowRect, GetWindowThreadProcessId, SetWindowPos, GWL_STYLE, HWND_TOPMOST,
        SWP_NOACTIVATE, SWP_NOSIZE, WS_CAPTION, WS_THICKFRAME,
    };

    fn rect(r: RECT) -> Rect {
        Rect { left: r.left, top: r.top, right: r.right, bottom: r.bottom }
    }

    unsafe extern "system" fn collect(handle: HMONITOR, _: HDC, _: *mut RECT, data: LPARAM) -> BOOL {
        let list = &mut *(data as *mut Vec<Monitor>);
        let mut info: MONITORINFO = std::mem::zeroed();
        info.cbSize = std::mem::size_of::<MONITORINFO>() as u32;
        if GetMonitorInfoW(handle, &mut info) != 0 {
            list.push(Monitor {
                id: handle as isize,
                full: rect(info.rcMonitor),
                work: rect(info.rcWork),
                primary: info.dwFlags & 1 != 0, // MONITORINFOF_PRIMARY
            });
        }
        1
    }

    pub fn monitors() -> Vec<Monitor> {
        let mut list: Vec<Monitor> = Vec::new();
        unsafe {
            EnumDisplayMonitors(null_mut(), std::ptr::null(), Some(collect), &mut list as *mut _ as LPARAM);
        }
        list
    }

    fn class_name(hwnd: HWND) -> String {
        let mut buf = [0u16; 128];
        let n = unsafe { GetClassNameW(hwnd, buf.as_mut_ptr(), buf.len() as i32) };
        String::from_utf16_lossy(&buf[..n.max(0) as usize])
    }

    fn process_name(hwnd: HWND) -> String {
        unsafe {
            let mut pid = 0u32;
            GetWindowThreadProcessId(hwnd, &mut pid);
            let process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
            if process.is_null() {
                return String::new();
            }
            let mut buf = [0u16; 512];
            let mut len = buf.len() as u32;
            let ok = QueryFullProcessImageNameW(process, 0, buf.as_mut_ptr(), &mut len);
            CloseHandle(process);
            if ok == 0 {
                return String::new();
            }
            let path = String::from_utf16_lossy(&buf[..len as usize]);
            path.rsplit(['\\', '/']).next().unwrap_or_default().to_lowercase()
        }
    }

    pub fn situation(busy_apps: &[String]) -> Situation {
        let monitors = monitors();
        unsafe {
            let fg = GetForegroundWindow();
            let active = (!fg.is_null()).then(|| MonitorFromWindow(fg, MONITOR_DEFAULTTONEAREST) as isize);

            let mut state = 0;
            let quns = if SHQueryUserNotificationState(&mut state) == 0 { state } else { 0 };
            let mut busy = match quns {
                QUNS_RUNNING_D3D_FULL_SCREEN => Some("fullscreen 3D".to_string()),
                QUNS_PRESENTATION_MODE => Some("presentation".to_string()),
                QUNS_BUSY => Some("fullscreen app".to_string()),
                _ => None,
            };

            // Безрамочное окно на весь монитор — игра или видео на весь экран.
            // Рабочий стол и панель задач тоже «на весь экран», их не считаем.
            if busy.is_none() && !fg.is_null() && fg != GetShellWindow() {
                let class = class_name(fg);
                let shell = ["Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"];
                // Обычное развёрнутое окно сохраняет рамку и заголовок — это не полный экран,
                // даже если на мониторе без панели задач оно занимает его целиком.
                let style = GetWindowLongW(fg, GWL_STYLE) as u32;
                let framed = style & WS_CAPTION == WS_CAPTION && style & WS_THICKFRAME != 0;
                let mut r: RECT = std::mem::zeroed();
                if !framed && !shell.contains(&class.as_str()) && GetWindowRect(fg, &mut r) != 0 {
                    let r = rect(r);
                    if let Some(m) = monitors.iter().find(|m| Some(m.id) == active) {
                        if r.left <= m.full.left && r.top <= m.full.top
                            && r.right >= m.full.right && r.bottom >= m.full.bottom
                        {
                            busy = Some(format!("fullscreen window ({class})"));
                        }
                    }
                }
            }

            if busy.is_none() && !busy_apps.is_empty() && !fg.is_null() {
                let name = process_name(fg);
                if !name.is_empty() && busy_apps.iter().any(|a| a.eq_ignore_ascii_case(&name)) {
                    busy = Some(name);
                }
            }
            Situation { monitors, active, busy }
        }
    }

    unsafe extern "system" fn first(hwnd: HWND, data: LPARAM) -> BOOL {
        // У потока есть и служебные окна winit и IME; окно сцены — класса «Window Class».
        if class_name(hwnd) == "Window Class" {
            *(data as *mut isize) = hwnd as isize;
            return 0;
        }
        1
    }

    /// Окно этого процесса: его создаёт главный поток, на нём же и update().
    pub fn own_window() -> Option<isize> {
        let mut found: isize = 0;
        unsafe {
            EnumThreadWindows(GetCurrentThreadId(), Some(first), &mut found as *mut _ as LPARAM);
        }
        (found != 0).then_some(found)
    }

    pub fn window_rect(hwnd: isize) -> Option<Rect> {
        let mut r: RECT = unsafe { std::mem::zeroed() };
        (unsafe { GetWindowRect(hwnd as HWND, &mut r) } != 0).then(|| rect(r))
    }

    /// Обрезать окно по форме кругляша: круг и плашка состояния. Всё вне формы
    /// не рисуется и пропускает клики мыши в игру под окном.
    pub fn shape_orb(hwnd: isize, circle: Rect, bar: Rect, radius: i32) {
        use windows_sys::Win32::Graphics::Gdi::{
            CombineRgn, CreateEllipticRgn, CreateRoundRectRgn, DeleteObject, SetWindowRgn, RGN_OR,
        };
        unsafe {
            let shape = CreateEllipticRgn(circle.left, circle.top, circle.right, circle.bottom);
            let label = CreateRoundRectRgn(bar.left, bar.top, bar.right, bar.bottom, radius, radius);
            CombineRgn(shape, shape, label, RGN_OR);
            DeleteObject(label);
            // Регион теперь принадлежит системе — удалять его нельзя.
            SetWindowRgn(hwnd as HWND, shape, 1);
        }
    }

    /// Пометить окно служебным: его не трогают утилиты вроде DisplayFusion,
    /// которые вешают свои кнопки на заголовки обычных окон.
    pub fn mark_tool_window(hwnd: isize) {
        use windows_sys::Win32::UI::WindowsAndMessaging::{
            SetWindowLongW, GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW,
        };
        unsafe {
            let ex = GetWindowLongW(hwnd as HWND, GWL_EXSTYLE) as u32;
            SetWindowLongW(hwnd as HWND, GWL_EXSTYLE, (ex | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE) as i32);
        }
    }

    /// Поставить окно в точку экрана в физических пикселях, не отнимая фокус.
    pub fn move_to(hwnd: isize, x: i32, y: i32) {
        unsafe {
            SetWindowPos(hwnd as HWND, HWND_TOPMOST, x, y, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE);
        }
    }
}

#[cfg(not(windows))]
mod imp {
    use super::{Monitor, Rect, Situation};
    pub fn situation(_: &[String]) -> Situation {
        Situation { monitors: Vec::<Monitor>::new(), active: None, busy: None }
    }
    pub fn own_window() -> Option<isize> {
        None
    }
    pub fn window_rect(_: isize) -> Option<Rect> {
        None
    }
    pub fn move_to(_: isize, _: i32, _: i32) {}
    pub fn shape_orb(_: isize, _: Rect, _: Rect, _: i32) {}
    pub fn mark_tool_window(_: isize) {}
}

pub use imp::{mark_tool_window, move_to, own_window, shape_orb, situation, window_rect};

/// Точка левого верхнего угла окна размера (w, h) в углу или по центру области.
pub fn anchor(area: Rect, w: i32, h: i32, corner: &str, margin: i32) -> (i32, i32) {
    let left = area.left + margin;
    let right = area.right - w - margin;
    let top = area.top + margin;
    let bottom = area.bottom - h - margin;
    let cx = area.left + (area.width() - w) / 2;
    let cy = area.top + (area.height() - h) / 2;
    match corner {
        "top-right" => (right, top),
        "bottom-right" => (right, bottom),
        "top-left" => (left, top),
        "bottom-left" => (left, bottom),
        "right" => (right, cy),
        "left" => (left, cy),
        _ => (cx, cy),
    }
}
