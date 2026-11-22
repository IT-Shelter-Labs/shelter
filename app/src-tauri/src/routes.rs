//! IPC boundary: the production shell must expose the same actions as the UI.
pub const POST: &[&str] = &[
    "/api/ask", "/api/say", "/api/assistant", "/api/listen", "/api/cancel",
    "/api/voice/record", "/api/voice/import", "/api/speaker/enroll", "/api/speaker/test",
    "/api/speaker/forget", "/api/speaker/status", "/api/persona", "/api/persona/save",
    "/api/persona/delete", "/api/persona/export", "/api/persona/import", "/api/avatar/motion",
    "/api/avatar/options", "/api/avatar/finished", "/api/avatar/seated", "/api/avatar/resize",
    "/api/scenarios", "/api/settings/reload", "/api/schedule/cancel", "/api/audio/test",
    "/api/companion", "/api/textops", "/api/plugins", "/api/connections/test", "/api/media", "/api/minecraft",
    "/api/image/generate", "/api/factorio", "/api/minecraft/npc",
];

pub fn post_allowed(path: &str) -> bool { POST.contains(&path) }
pub fn long_request(path: &str) -> bool {
    path.starts_with("/api/voice/") || path.starts_with("/api/speaker/") || matches!(path,
        "/api/audio/test" | "/api/plugins" | "/api/connections/test" | "/api/persona/export" | "/api/persona/import" | "/api/textops" | "/api/scenarios" | "/api/image/generate")
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn interactive_routes_reach_core_and_unrelated_paths_stay_blocked() {
        for path in ["/api/scenarios", "/api/settings/reload", "/api/plugins", "/api/avatar/resize", "/api/avatar/seated", "/api/minecraft"] {
            assert!(post_allowed(path), "blocked: {path}");
        }
        for path in ["https://example.com", "/api/stop", "/api/../stop", "/api/plugins?op=install", "/api/browser-episode/agent"] { assert!(!post_allowed(path)); }
        assert!(long_request("/api/audio/test"));
        assert!(long_request("/api/plugins"));
    }
}
