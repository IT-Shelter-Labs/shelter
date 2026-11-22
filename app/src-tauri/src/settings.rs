//! Настройки: config.yaml — значения по умолчанию (с комментариями, для
//! продвинутых), data/settings.json — то, что человек выставил в приложении.
//! Ядро накладывает второе на первое при запуске (main.load_config).

use std::fs;
use std::path::Path;
use std::sync::Mutex;
static SAVE_LOCK: Mutex<()> = Mutex::new(());

use serde_json::{json, Value};

pub fn defaults(root: &Path) -> Value {
    fs::read_to_string(root.join("config.yaml"))
        .or_else(|_| fs::read_to_string(root.join("config.public.yaml")))
        .ok()
        .and_then(|text| serde_yaml::from_str::<Value>(&text).ok())
        .unwrap_or_else(|| json!({}))
}

pub fn user(root: &Path) -> Value {
    let mut value = fs::read_to_string(root.join("data").join("settings.json"))
        .ok()
        .and_then(|text| serde_json::from_str::<Value>(&text).ok())
        .filter(|v| v.is_object())
        .or_else(|| fs::read_to_string(root.join("data/settings.json.bak")).ok()
                 .and_then(|text| serde_json::from_str::<Value>(&text).ok()).filter(|v| v.is_object()))
        .unwrap_or_else(|| json!({}));
    if let Err(error) = transform_secrets(&mut value, false) {
        value["_secret_error"] = Value::String(error);
    }
    value
}

pub fn ui_language(root: &Path, user: &Value) -> &'static str {
    match user.pointer("/ui/language").cloned()
        .or_else(|| defaults(root).pointer("/ui/language").cloned())
        .and_then(|v| v.as_str().map(str::to_owned)).as_deref() {
        Some("en") => "en",
        _ => "ru",
    }
}

#[cfg(windows)]
fn crypt(bytes: &[u8], encrypt: bool) -> Result<Vec<u8>, String> {
    use windows::Win32::Security::Cryptography::*;
    use windows::Win32::Foundation::{LocalFree, HLOCAL};
    let input = CRYPT_INTEGER_BLOB { cbData: bytes.len() as u32, pbData: bytes.as_ptr() as *mut u8 };
    let mut output = CRYPT_INTEGER_BLOB::default();
    unsafe {
        if encrypt {
            CryptProtectData(&input, windows::core::PCWSTR::null(), None, None, None, 1, &mut output)
        } else {
            CryptUnprotectData(&input, None, None, None, None, 1, &mut output)
        }.map_err(|_| "Не удалось открыть защищённые секреты текущего пользователя Windows".to_string())?;
        let bytes = std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec();
        LocalFree(Some(HLOCAL(output.pbData as *mut _)));
        Ok(bytes)
    }
}

fn transform_secrets(value: &mut Value, encrypt: bool) -> Result<(), String> {
    match value {
        Value::Object(map) => for (key, item) in map {
            let lower = key.to_lowercase();
            if ["token", "password", "api_key", "local_key", "key", "secret", "credential"].iter().any(|name| lower == *name || lower.ends_with(&format!("_{name}"))) {
                if let Some(text) = item.as_str() {
                    #[cfg(windows)]
                    if encrypt && !text.is_empty() && !text.starts_with("dpapi:") {
                        *item = Value::String("dpapi:".to_string() + &crypt(text.as_bytes(), true)?.iter().map(|b| format!("{b:02x}")).collect::<String>());
                    } else if !encrypt && text.starts_with("dpapi:") {
                        let hex = &text[6..];
                        if !hex.is_ascii() || hex.len() % 2 != 0 { return Err("Повреждён секрет".into()); }
                        let bytes: Result<Vec<u8>, _> = (0..hex.len()).step_by(2).map(|i| u8::from_str_radix(&hex[i..i+2], 16)).collect();
                        *item = Value::String(String::from_utf8(crypt(&bytes.map_err(|_| "Повреждён секрет")?, false)?).map_err(|_| "Повреждён секрет")?);
                    }
                    #[cfg(not(windows))]
                    if text.starts_with("dpapi:") { return Err("Этот секрет защищён учётной записью Windows; введите его заново на Linux".into()); }
                }
            } else {
                transform_secrets(item, encrypt)?;
            }
        },
        Value::Array(items) => for item in items { transform_secrets(item, encrypt)?; },
        _ => {}
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_invalid_settings_before_writing() {
        assert!(save(Path::new("unused"), &json!([])).is_err());
        assert!(save(Path::new("unused"), &json!({"ui":{"language":"invalid"}})).is_err());
    }

    #[test]
    fn language_uses_defaults_and_explicit_user_choice() {
        let root = std::env::temp_dir().join(format!("jarvis-language-test-{}", std::process::id()));
        fs::create_dir_all(&root).unwrap();
        fs::write(root.join("config.yaml"), "ui:\n  language: en\n").unwrap();
        assert_eq!(ui_language(&root, &json!({})), "en");
        assert_eq!(ui_language(&root, &json!({"ui":{"language":"ru"}})), "ru");
        fs::remove_dir_all(root).unwrap();
    }

    #[cfg(windows)]
    #[test]
    fn secrets_round_trip_including_nested_arrays() {
        let original = json!({"smarthome":{"token":"тестовый секрет"},"devices":[{"key":"test"}],"llm":{"model":"normal"}});
        let mut value = original.clone();
        transform_secrets(&mut value, true).unwrap();
        assert!(value["smarthome"]["token"].as_str().unwrap().starts_with("dpapi:"));
        assert_eq!(value["llm"]["model"], "normal");
        transform_secrets(&mut value, false).unwrap();
        assert_eq!(value, original);
        assert!(transform_secrets(&mut json!({"token":"dpapi:€a"}), false).is_err());
    }

    #[test]
    fn concurrent_saves_leave_valid_document_and_backup() {
        let unique = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos();
        let root = std::env::temp_dir().join(format!("jarvis-settings-test-{}-{unique}", std::process::id()));
        let workers: Vec<_> = (0..6).map(|i| {
            let root = root.clone();
            std::thread::spawn(move || save(&root, &json!({"llm":{"model": format!("model-{i}")}})).unwrap())
        }).collect();
        for worker in workers { worker.join().unwrap(); }
        assert!(user(&root).pointer("/llm/model").unwrap().as_str().unwrap().starts_with("model-"));
        assert!(root.join("data/settings.json.bak").is_file());
        fs::remove_dir_all(root).unwrap();
    }
}

pub fn save(root: &Path, value: &Value) -> Result<(), String> {
    let _guard = SAVE_LOCK.lock().map_err(|e| e.to_string())?;
    if !value.is_object() {
        return Err("Настройки должны быть JSON-объектом".into());
    }
    for section in ["audio", "wake", "tts", "llm", "ui", "smarthome", "security", "integrations", "performance"] {
        if value.get(section).is_some_and(|v| !v.is_object()) {
            return Err(format!("Раздел {section} должен быть объектом"));
        }
    }
    if let Some(words) = value.pointer("/wake/words") {
        if !words.as_array().is_some_and(|items| !items.is_empty() && items.iter().all(|w| w.as_str().is_some_and(|s| !s.trim().is_empty()))) {
            return Err("Нужно хотя бы одно непустое слово-обращение".into());
        }
    }
    if value.pointer("/ui/language").is_some_and(|v| !matches!(v.as_str(), Some("ru" | "en"))) {
        return Err("Язык интерфейса: ru или en".into());
    }
    let dir = root.join("data");
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let mut stored = value.clone();
    transform_secrets(&mut stored, true)?;
    let text = serde_json::to_string_pretty(&stored).map_err(|e| e.to_string())?;
    let temporary = dir.join("settings.json.tmp");
    fs::write(&temporary, text).map_err(|e| e.to_string())?;
    let destination = dir.join("settings.json");
    if let Some(mut old) = fs::read_to_string(&destination).ok()
        .and_then(|text| serde_json::from_str::<Value>(&text).ok()).filter(|v| v.is_object()) {
        transform_secrets(&mut old, true)?;
        fs::write(dir.join("settings.json.bak"), serde_json::to_string_pretty(&old).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
    }
    #[cfg(unix)] {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&temporary, fs::Permissions::from_mode(0o600)).map_err(|e| e.to_string())?;
        let backup = dir.join("settings.json.bak");
        if backup.exists() { fs::set_permissions(backup, fs::Permissions::from_mode(0o600)).map_err(|e| e.to_string())?; }
    }
    fs::rename(&temporary, dir.join("settings.json")).map_err(|e| e.to_string())
}
