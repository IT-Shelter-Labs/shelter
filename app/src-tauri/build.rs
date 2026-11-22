fn main() {
    if std::env::var("PROFILE").as_deref() == Ok("release") && tauri_build::is_dev() {
        panic!("Release build has no embedded frontend. Run npm run desktop:build from app/ (or enable --features custom-protocol).");
    }
    tauri_build::build()
}
