// Общее состояние окна: ядро, лента разговора, настройки, уведомления.
import { api, on, errorText, type CoreState, type CoreStatus, type FeedEvent, type AssistantSnapshot } from "./api";
import { goBack } from "./navigation";
import { setLanguage } from "./i18n.svelte";

export const app = $state({
  info: null as { version: string; root: string; onboarded: boolean; minimized: boolean; platform: string; contextRequested?: boolean } | null,
  core: null as CoreState | null,
  status: null as CoreStatus | null,
  connected: false,
  connectionError: "",
  feed: [] as FeedEvent[],
  assistant: null as AssistantSnapshot | null,
  contextOpen: false,
  defaults: {} as Record<string, any>,
  user: {} as Record<string, any>,
  dirty: false, // настройки сохранены, но ядро ещё работает со старыми
  dirtyReasons: [] as string[], // что именно ждёт перезапуска
  scenarios: null as (import("./api").ScenarioSnapshot & { choices?: any }) | null,
  toasts: [] as { id: number; kind: "info" | "success" | "error"; text: string }[],
});

let toastId = 0;
export function toast(text: string, kind: "info" | "success" | "error" = "info") {
  const id = ++toastId;
  app.toasts.push({ id, kind, text });
  setTimeout(() => {
    const i = app.toasts.findIndex((t) => t.id === id);
    if (i >= 0) app.toasts.splice(i, 1);
  }, kind === "error" ? 7000 : 3200);
}
export const toastError = (e: unknown) => toast(errorText(e), "error");

// ------------------------------------------------------------ настройки

function dig(obj: any, path: string[]) {
  return path.reduce((o, k) => (o && typeof o === "object" ? o[k] : undefined), obj);
}

/** Действующее значение: то, что выставил человек, иначе — из config.yaml. */
export function get<T = any>(path: string, fallback?: T): T {
  const keys = path.split(".");
  const own = dig(app.user, keys);
  if (own !== undefined) return own as T;
  const base = dig(app.defaults, keys);
  return (base !== undefined ? base : fallback) as T;
}

let saveTimer: ReturnType<typeof setTimeout> | undefined;
let saveChain: Promise<void> = Promise.resolve();
function persist() {
  const snapshot = $state.snapshot(app.user);
  saveChain = saveChain.catch(() => {}).then(() => api.saveSettings(snapshot));
  return saveChain;
}

// Что окно применяет само (оформление), что ядро перечитывает на ходу, что требует перезапуска.
const APP_ONLY = ["ui.language", "ui.theme", "ui.glass", "ui.accent", "ui.motion", "ui.text_scale", "ui.home", "ui.nav", "ui.nav_collapsed"];
const LIVE = ["ui.", "plugins.", "gaming.", "factorio.", "confirm.", "discord.", "obs.", "location.", "search.", "wake.earcon", "wake.duck",
  "wake.close_after_action", "tts.reply_sentences", "tts.pronunciations", "llm.tools", "llm.system", "llm.action_plans"];
const RESTART_REASONS: [string, string][] = [
  ["audio.", "микрофон и звук"], ["asr.", "распознавание речи"], ["wake.", "слово-обращение и слушание"],
  ["tts.", "голос озвучки"], ["llm.", "нейросеть"], ["integrations.", "подключения MCP"], ["smarthome.", "умный дом"],
  ["companion.", "связь с телефоном"], ["telegram.", "Telegram-бот"], ["performance.", "режим нагрузки"], ["detector.", "звуковой триггер"],
];
let liveTimer: ReturnType<typeof setTimeout> | undefined;
let themeHook: (() => void) | undefined;
export function onThemeChange(hook: (() => void) | undefined) { themeHook = hook; }

/** Изменить настройку. Сохраняется сразу; применяется сразу, если это возможно без перезапуска. */
export function set(path: string, value: unknown, apply = true) {
  if (APP_ONLY.some((p) => path === p || path.startsWith(p + "."))) apply = false;
  const keys = path.split(".");
  let node = app.user;
  for (const k of keys.slice(0, -1)) {
    if (typeof node[k] !== "object" || node[k] === null || Array.isArray(node[k])) node[k] = {};
    node = node[k];
  }
  node[keys[keys.length - 1]] = value;
  if(path==='ui.language')setLanguage(value);
  if (path.startsWith("ui.")) themeHook?.();
  const live = LIVE.some((p) => path.startsWith(p));
  if (apply && !live) {
    app.dirty = true;
    const reason = RESTART_REASONS.find(([p]) => path.startsWith(p))?.[1] ?? "основные настройки";
    if (!app.dirtyReasons.includes(reason)) app.dirtyReasons.push(reason);
  }
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    persist().then(() => { if (apply && live && app.core?.running) applyLive(); }).catch(toastError);
  }, 250);
}

/** Ядро перечитывает безопасные разделы без перезапуска — «применено». */
function applyLive() {
  clearTimeout(liveTimer);
  liveTimer = setTimeout(async () => {
    try {
      const r = await api.reloadSettings();
      if (r.applied.length) toast("Применено без перезапуска", "success");
    } catch {
      // Старое ядро без этого адреса — тогда как раньше, через перезапуск.
      app.dirty = true;
      if (!app.dirtyReasons.includes("основные настройки")) app.dirtyReasons.push("основные настройки");
    }
  }, 300);
}

export async function saveNow() {
  clearTimeout(saveTimer);
  await persist();
}

/** Применить сохранённые настройки: ядро перезапускается (~10 с). */
export async function applySettings() {
  await saveNow();
  if (app.core?.running) {
    await api.coreRestart();
    toast("Применяю настройки — Джарвис перезапускается", "info");
  }
  app.dirty = false;
  app.dirtyReasons = [];
}

// ---------------------------------------------------------- навигация

export type Page = "home" | "commands" | "connections" | "memory" | "persona" | "settings" | "games";
export const nav = $state({ page: "home" as Page, sub: "", history: [] as { page: Page; sub: string }[], palette: false });
/** Редактор с несохранёнными правками ставит сюда вопрос «сохранить/отбросить». */
let guard: (() => Promise<boolean>) | null = null;
export function setGuard(fn: (() => Promise<boolean>) | null) { guard = fn; }

export async function navigate(page: Page, sub = "", remember = true) {
  if (page === nav.page && sub === nav.sub) return true;
  if (guard && !(await guard())) return false;
  if (remember) nav.history.push({ page: nav.page, sub: nav.sub });
  if (nav.history.length > 30) nav.history.shift();
  nav.page = page;
  nav.sub = sub;
  document.querySelector("#shell-content")?.scrollTo({ top: 0, behavior: "instant" });
  return true;
}
export async function back() {
  await goBack(nav.history, previous => navigate(previous.page, previous.sub, false));
}

// ------------------------------------------------------------- запуск

let statusTimer: ReturnType<typeof setInterval> | undefined;
let refreshing = false;
let eventError = "";

let assistantRefreshing = false;
export async function refreshAssistant() {
  if (assistantRefreshing || !app.status) return;
  assistantRefreshing = true;
  try { app.assistant = await api.assistant(); }
  finally { assistantRefreshing = false; }
}

export async function init() {
  app.info = await api.appInfo();
  const s = await api.settings();
  app.defaults = s.defaults;
  app.user = s.user;
  setLanguage(get('ui.language','ru'));
  if (app.user._secret_error) toast(String(app.user._secret_error), "error");
  app.core = await api.coreState();
  // Polling must work even when an optional event subscription fails.
  statusTimer = setInterval(refreshStatus, 1500);
  await refreshStatus();
  const subscriptions = await Promise.allSettled([
  on<CoreState>("core:state", (state) => (app.core = state)),
  on<boolean>("core:connected", (c) => (app.connected = c)),
  on<FeedEvent>("core:event", (event) => {
    // Голосом поменяли вид окна («работай без окна») — ядро уже сохранило, показываем.
    const changed = (event as any).kind === "settings" ? (event as any).ui : null;
    if (changed && typeof changed === "object") {
      app.user.ui = { ...(app.user.ui ?? {}), ...changed };
      return;
    }
    // Сценарии поменялись (сохранили голосом, с телефона, в другом окне) — обновить список.
    if (event.kind === "scenarios") {
      api.scenarios().then((s) => (app.scenarios = s)).catch(() => {});
      return;
    }
    // История при переподключении приходит повторно. Сравниваем событие целиком: на Windows у
    // соседних событий (последний шаг и итог сценария) бывает одинаковая метка времени.
    const same = JSON.stringify(event);
    if (app.feed.some((e) => e.time === event.time && e.kind === event.kind && JSON.stringify(e) === same)) return;
    app.feed.push(event);
    if (app.feed.length > 200) app.feed.splice(0, app.feed.length - 200);
  })]);
  const errors = subscriptions.filter((r): r is PromiseRejectedResult => r.status === 'rejected');
  eventError = errors.map(r => errorText(r.reason)).join('; ');
  if (eventError) app.connectionError = eventError;
}

export async function refreshStatus() {
  // Окно свёрнуто в трей — не опрашивать ядро зря (события всё равно приходят).
  if (refreshing || (document.visibilityState !== "visible" && app.status)) return;
  refreshing = true;
  try {
    app.core = await api.coreState();
    app.status = app.core.running ? await api.status() : null;
    app.connectionError = eventError;
  } catch (error) {
    app.status = null;
    app.connectionError = errorText(error);
  } finally {
    refreshing = false;
  }
}

export function stopPolling() {
  clearInterval(statusTimer);
}
