#[cfg(windows)]
mod platform {
    use windows::Media::Control::{GlobalSystemMediaTransportControlsSessionManager as Manager, GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status};
    use windows::Media::MediaPlaybackType;
    use windows::Win32::System::WinRT::{RoInitialize, RoUninitialize, RO_INIT_MULTITHREADED};
    struct Apartment(bool);
    impl Apartment { fn new() -> Self { Self(unsafe{RoInitialize(RO_INIT_MULTITHREADED)}.is_ok()) } }
    impl Drop for Apartment { fn drop(&mut self) { if self.0 { unsafe{RoUninitialize()} } } }
    pub fn snapshot() -> windows::core::Result<serde_json::Value> {
        let _apartment = Apartment::new();
        let manager = Manager::RequestAsync()?.join()?;
        let current = manager.GetCurrentSession().and_then(|s|s.SourceAppUserModelId()).map(|s|s.to_string()).unwrap_or_default();
        let mut result = Vec::new();
        for session in manager.GetSessions()? {
            // One broken browser session must not hide a working music player.
            let item = (|| -> windows::core::Result<serde_json::Value> {
                let source = session.SourceAppUserModelId()?.to_string();
                let info = session.GetPlaybackInfo()?;
                let props = session.TryGetMediaPropertiesAsync()?.join()?;
                let controls = info.Controls()?;
                let kind = match props.PlaybackType().and_then(|v|v.Value()) {
                    Ok(MediaPlaybackType::Music) => "music", Ok(MediaPlaybackType::Video) => "video", _ => "unknown"
                };
                Ok(serde_json::json!({"source":source,"title":props.Title()?.to_string(),"artist":props.Artist()?.to_string(),
                    "playing":info.PlaybackStatus()? == Status::Playing,"kind":kind,"current":source == current,
                    "next_enabled": controls.IsNextEnabled().unwrap_or(false),
                    "previous_enabled": controls.IsPreviousEnabled().unwrap_or(false)}))
            })();
            if let Ok(item) = item { result.push(item); }
        }
        Ok(serde_json::Value::Array(result))
    }
    pub fn control(action: u32, source: &str) -> windows::core::Result<bool> {
        let _apartment = Apartment::new();
        let manager = Manager::RequestAsync()?.join()?;
        for session in manager.GetSessions()? {
            if session.SourceAppUserModelId()?.to_string() != source { continue; }
            let op = match action {
                0 => session.TryPauseAsync()?, 1 => session.TryPlayAsync()?, 2 => session.TryTogglePlayPauseAsync()?,
                3 => session.TrySkipNextAsync()?, 4 => session.TrySkipPreviousAsync()?, 5 => session.TryStopAsync()?, _ => return Ok(false)
            };
            return op.join();
        }
        Ok(false)
    }
}
#[cfg(windows)]
pub use platform::*;
#[cfg(not(windows))]
pub fn snapshot() -> Result<serde_json::Value, ()> { Err(()) }
#[cfg(not(windows))]
pub fn control(_:u32,_:&str) -> Result<bool, ()> { Err(()) }
