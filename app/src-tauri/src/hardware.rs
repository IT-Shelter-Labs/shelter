//! Железо компьютера и что под него рекомендовать (основа — из Zorko).

use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Gpu {
    pub name: String,
    /// nvidia | amd | intel | other
    pub vendor: String,
    pub vram_gb: f64,
    pub integrated: bool,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct HardwareInfo {
    pub os: String,
    pub cpu: String,
    pub cpu_threads: usize,
    pub ram_total_gb: f64,
    pub gpus: Vec<Gpu>,
    pub disk_free_gb: Option<f64>,
    pub recommendation: Recommendation,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Recommendation {
    /// Модель Ollama или пусто, если локально не потянет.
    pub model: String,
    pub model_reason: String,
    /// clone — голос Джарвиса на видеокарте; piper — лёгкий голос на процессоре.
    pub voice: String,
    pub voice_reason: String,
}

pub fn detect(root: &std::path::Path) -> HardwareInfo {
    use sysinfo::{Disks, System};
    let mut sys = System::new();
    sys.refresh_memory();
    sys.refresh_cpu_all();
    let cpu = sys.cpus().first().map(|c| c.brand().trim().to_string()).unwrap_or_default();
    let disks = Disks::new_with_refreshed_list();
    let disk_free_gb = disks
        .list()
        .iter()
        .filter(|d| root.starts_with(d.mount_point()))
        .max_by_key(|d| d.mount_point().as_os_str().len())
        .map(|d| d.available_space() as f64 / 1_073_741_824.0);
    let gpus = gpus();
    let ram_total_gb = sys.total_memory() as f64 / 1_073_741_824.0;
    let recommendation = recommend(&gpus, ram_total_gb);
    HardwareInfo {
        os: format!("{} {}", System::name().unwrap_or_default(), System::os_version().unwrap_or_default()),
        cpu,
        cpu_threads: sys.cpus().len(),
        ram_total_gb,
        gpus,
        disk_free_gb,
        recommendation,
    }
}

fn recommend(gpus: &[Gpu], ram: f64) -> Recommendation {
    let best = gpus
        .iter()
        .filter(|g| !g.integrated && (g.vendor == "nvidia" || g.vendor == "amd"))
        .max_by(|a, b| a.vram_gb.partial_cmp(&b.vram_gb).unwrap_or(std::cmp::Ordering::Equal));
    let vram = best.map(|g| g.vram_gb).unwrap_or(0.0);
    let name = best.map(|g| g.name.clone()).unwrap_or_default();
    let nvidia = best.is_some_and(|g| g.vendor == "nvidia");

    let (model, model_reason) = if vram >= 7.5 {
        ("gemma4:e4b", format!("{name} ({vram:.0} ГБ) — умная модель целиком в видеопамяти, ответ за доли секунды."))
    } else if vram >= 3.5 {
        ("gemma4:e2b", format!("{name} ({vram:.0} ГБ) — лёгкая модель на видеокарте, отвечает быстро."))
    } else if ram >= 15.0 {
        ("gemma4:e2b", format!("Подходящей видеокарты нет: модель будет думать на процессоре ({ram:.0} ГБ ОЗУ), по несколько секунд."))
    } else {
        ("", "Памяти мало для локальной модели — Джарвис будет выполнять команды, но без свободного разговора.".to_string())
    };
    // Клон голоса — модель 0.6B на CUDA: ~2 ГБ видеопамяти рядом с моделью разговора.
    let (voice, voice_reason) = if nvidia && vram >= 7.5 {
        ("clone", format!("{name} потянет фирменный голос Джарвиса (нужно ~4 ГБ загрузки)."))
    } else if nvidia && vram >= 5.5 {
        ("piper", "Видеопамяти впритык — голос Джарвиса можно включить, но лёгкий голос надёжнее.".to_string())
    } else {
        ("piper", "Фирменный голос требует видеокарту NVIDIA — будет лёгкий голос на процессоре.".to_string())
    };
    Recommendation { model: model.into(), model_reason, voice: voice.into(), voice_reason }
}

#[cfg(windows)]
fn gpus() -> Vec<Gpu> {
    use windows::Win32::Graphics::Dxgi::{CreateDXGIFactory1, IDXGIFactory1, DXGI_ADAPTER_FLAG_SOFTWARE};
    let mut out = Vec::new();
    unsafe {
        let Ok(factory) = CreateDXGIFactory1::<IDXGIFactory1>() else { return out };
        let mut i = 0;
        while let Ok(adapter) = factory.EnumAdapters1(i) {
            i += 1;
            let Ok(desc) = adapter.GetDesc1() else { continue };
            if (desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE.0 as u32) != 0 {
                continue;
            }
            let name = String::from_utf16_lossy(&desc.Description).trim_end_matches('\0').trim().to_string();
            if name.contains("Microsoft Basic") || out.iter().any(|g: &Gpu| g.name == name) {
                continue;
            }
            let vendor = match desc.VendorId {
                0x10DE => "nvidia",
                0x1002 | 0x1022 => "amd",
                0x8086 => "intel",
                _ => "other",
            };
            let vram_gb = desc.DedicatedVideoMemory as f64 / 1_073_741_824.0;
            let integrated = vendor == "intel" && !name.to_lowercase().contains("arc")
                || (vendor == "amd" && vram_gb < 1.5)
                || vram_gb < 0.6;
            out.push(Gpu { name, vendor: vendor.into(), vram_gb, integrated });
        }
    }
    out
}

#[cfg(not(windows))]
fn gpus() -> Vec<Gpu> {
    Vec::new()
}
