//! Вшивает иконку (assets/jarvis.ico) в оба exe: в проводнике, на панели задач
//! и в трее у лаунчера будет реактор. Нужен rc.exe из Windows SDK — он ставится
//! вместе с инструментами сборки Rust (MSVC). Нет его — exe собирается без иконки.

use std::env;
use std::path::PathBuf;
use std::process::Command;

fn find_rc() -> Option<PathBuf> {
    if let Ok(rc) = env::var("RC") {
        return Some(PathBuf::from(rc));
    }
    let kits = PathBuf::from(r"C:\Program Files (x86)\Windows Kits\10\bin");
    let mut versions: Vec<PathBuf> = std::fs::read_dir(&kits).ok()?
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.join("x64").join("rc.exe").exists())
        .collect();
    versions.sort();
    versions.pop().map(|v| v.join("x64").join("rc.exe"))
}

fn main() {
    println!("cargo:rerun-if-changed=assets/jarvis.rc");
    println!("cargo:rerun-if-changed=assets/jarvis.ico");
    if env::var("CARGO_CFG_TARGET_OS").as_deref() != Ok("windows") {
        return;
    }
    let Some(rc) = find_rc() else {
        println!("cargo:warning=rc.exe не найден — exe будут без иконки");
        return;
    };
    let out = PathBuf::from(env::var("OUT_DIR").unwrap()).join("jarvis.res");
    let ok = Command::new(rc)
        .args(["/nologo", "/fo"])
        .arg(&out)
        .arg("jarvis.rc")
        .current_dir("assets")
        .status()
        .map(|s| s.success())
        .unwrap_or(false);
    if ok {
        println!("cargo:rustc-link-arg-bins={}", out.display());
    } else {
        println!("cargo:warning=rc.exe не собрал ресурсы — exe будут без иконки");
    }
}
