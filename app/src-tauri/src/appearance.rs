//! Native desktop transparency, with an opaque fallback on unsupported systems.
use tauri::WebviewWindow;

#[tauri::command]
pub fn window_material(window: WebviewWindow, glass: bool, light: bool, opacity: u8) -> Result<bool, String> {
    if window.label() != "main" { return Err("Материал доступен только главному окну".into()); }
    #[cfg(windows)]
    {
        use tauri::window::{Color, Effect, EffectsBuilder};
        if glass {
            window.set_background_color(Some(Color(0, 0, 0, 0))).map_err(|e| e.to_string())?;
            let alpha = opacity.clamp(15, 85).saturating_mul(2);
            let tint = if light { Color(238, 245, 255, alpha) } else { Color(12, 21, 35, alpha) };
            // Blur is supported by Windows 10 and avoids Acrylic's drag lag on 19045.
            if window.set_effects(EffectsBuilder::new().effect(Effect::Blur).color(tint).build()).is_ok() { return Ok(true); }
        }
        let _ = window.set_effects(None);
        window.set_background_color(Some(if light { Color(234, 240, 246, 255) } else { Color(5, 9, 15, 255) })).map_err(|e| e.to_string())?;
    }
    Ok(false)
}
