import { defineConfig, type Plugin } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import http from "node:http";

const host = process.env.TAURI_DEV_HOST;
// npm run dev:bridge — окно в обычном браузере на данных тестового стенда ядра
// (tools/dev_core.py). Только разработка: в сборку приложения мост не попадает.
const CORE = Number(process.env.JARVIS_BRIDGE_PORT ?? 8771);

function core(method: string, path: string, body?: unknown, port = CORE): Promise<{ status: number; data: any }> {
  const token = readFileSync(process.env.JARVIS_BRIDGE_TOKEN_FILE || resolve(import.meta.dirname, "../data/control.token"), "utf-8").trim();
  return new Promise((done, fail) => {
    const payload = body === undefined ? undefined : Buffer.from(JSON.stringify(body));
    const request = http.request({ host: "127.0.0.1", port, path, method,
      headers: { "X-Jarvis-Token": token, "Content-Type": "application/json", ...(payload ? { "Content-Length": payload.length } : {}) } },
      (response) => {
        const chunks: Buffer[] = [];
        response.on("data", (c) => chunks.push(c));
        response.on("end", () => {
          const text = Buffer.concat(chunks).toString("utf-8");
          try { done({ status: response.statusCode ?? 500, data: text ? JSON.parse(text) : {} }); }
          catch { done({ status: response.statusCode ?? 500, data: { error: text } }); }
        });
      });
    request.on("error", fail);
    if (payload) request.write(payload);
    request.end();
  });
}

function devBridge(): Plugin {
  return {
    name: "jarvis-dev-bridge",
    configureServer(server) {
      server.middlewares.use("/__bridge/invoke", async (req, res) => {
        const chunks: Buffer[] = [];
        for await (const c of req) chunks.push(c as Buffer);
        const { command, args } = JSON.parse(Buffer.concat(chunks).toString("utf-8") || "{}");
        const reply = (status: number, data: unknown) => { res.statusCode = status; res.setHeader("Content-Type", "application/json"); res.end(JSON.stringify(data)); };
        try {
          if (command === "app_info") return reply(200, { version: "0.1.0-alpha.2-dev", root: resolve(import.meta.dirname, ".."), onboarded: true, minimized: false, platform: "windows" });
          if (command === "avatar_portrait") {
            const preview = resolve(import.meta.dirname, "../personas/anime/preview.png");
            if (typeof args.path !== "string" || resolve(args.path) !== preview) return reply(404, { error: "Portrait unavailable" });
            res.writeHead(200, { "Content-Type": "image/png" });
            return res.end(readFileSync(preview));
          }
          if (command === "core_state") {
            const alive = await core("GET", "/api/status").then(() => true, () => false);
            return reply(200, { running: alive, paused: false, stopping: false, pid: null, lastError: alive ? "" : "стенд ядра не запущен (tools/dev_core.py)", python: true, root: "" });
          }
          if (command === "core_get") { const r = await core("GET", args.path); return reply(r.status < 400 ? 200 : 400, r.status < 400 ? r.data : { error: r.data.error }); }
          if (command === "core_post") { const r = await core("POST", args.path, args.body ?? {}); return reply(r.status < 400 ? 200 : 400, r.status < 400 ? r.data : { error: r.data.error }); }
          if (command === "settings_get") return reply(200, (await core("GET", "/", undefined, CORE + 1)).data);
          if (command === "settings_save") return reply(200, (await core("POST", "/", { user: args.user }, CORE + 1)).data);
          if (command === "setup_check") return reply(200, {});
          return reply(200, {});
        } catch (error) {
          return reply(400, { error: String(error) });
        }
      });
      server.middlewares.use("/__bridge/events", (_req, res) => {
        res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", Connection: "keep-alive" });
        const token = readFileSync(process.env.JARVIS_BRIDGE_TOKEN_FILE || resolve(import.meta.dirname, "../data/control.token"), "utf-8").trim();
        const upstream = http.get({ host: "127.0.0.1", port: CORE, path: "/api/events", headers: { "X-Jarvis-Token": token } }, (stream) => {
          let buffer = "";
          stream.on("data", (chunk) => {
            buffer += chunk.toString("utf-8");
            const lines = buffer.split("\n");
            buffer = lines.pop() ?? "";
            for (const line of lines) if (line.trim()) res.write(`data: ${line}\n\n`);
          });
        });
        upstream.on("error", () => res.end());
        res.on("close", () => upstream.destroy());
      });
    },
  };
}

export default defineConfig(({ mode }) => {
  const bridge = mode === "bridge" || process.env.JARVIS_BRIDGE === "1";
  return {
  plugins: [svelte(), ...(bridge ? [devBridge()] : [])],
  clearScreen: false,
  resolve: bridge
    ? {
        alias: [
          { find: "@tauri-apps/api/core", replacement: resolve(import.meta.dirname, "src/dev/tauri-core.ts") },
          { find: "@tauri-apps/api/event", replacement: resolve(import.meta.dirname, "src/dev/tauri-event.ts") },
          { find: /^@tauri-apps\/api\/(window|webviewWindow)$/, replacement: resolve(import.meta.dirname, "src/dev/tauri-misc.ts") },
          { find: /^@tauri-apps\/plugin-(dialog|autostart|opener)$/, replacement: resolve(import.meta.dirname, "src/dev/tauri-misc.ts") },
        ],
      }
    : undefined,
  server: {
    port: bridge ? 1430 : 1420,
    strictPort: true,
    host: host || false,
    hmr: host ? { protocol: "ws", host, port: 1421 } : undefined,
    watch: { ignored: ["**/src-tauri/**", "**/.devenv/**"] },
    // Режим моста: окно персонажа в браузере берёт VRM-модели из папок проекта.
    fs: bridge ? { allow: [resolve(import.meta.dirname, "..")] } : undefined,
  },
  build: {
    target: "es2022",
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      // Второе окно — персонаж (VRM): отдельная лёгкая страница без Svelte.
      input: { main: "index.html", avatar: "avatar.html" },
    },
  },
};
});
