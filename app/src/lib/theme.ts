// Оформление окна: тема, акцент, движение, облегчённый режим.
// Хранится в настройках (ui.theme…); ядро это не перезапускает — применяется сразу.
import { get } from "./store.svelte";
import { invoke } from "@tauri-apps/api/core";
let nativeMaterial = "";
let nativeVersion = 0;

export const ACCENTS = [
  { id: "cyan", label: "Бирюзовый", hue: 194 },
  { id: "blue", label: "Синий", hue: 214 },
  { id: "violet", label: "Фиолетовый", hue: 262 },
  { id: "green", label: "Зелёный", hue: 152 },
  { id: "amber", label: "Янтарный", hue: 36 },
  { id: "rose", label: "Розовый", hue: 338 },
] as const;

let media: MediaQueryList | undefined;
let motionMedia: MediaQueryList | undefined;
let transparencyMedia: MediaQueryList | undefined;
let contrastMedia: MediaQueryList | undefined;

export const THEMES = [
  { id: "dark", label: "Глубокая ночь", description: "Тёмный, спокойный, собранный" },
  { id: "light", label: "Светлый день", description: "Воздух, мягкие тени и чистые линии" },
  { id: "glass", label: "Liquid Glass", description: "Жидкое стекло и цветная атмосфера" },
  { id: "system", label: "Как в системе", description: "Следует за светлой и тёмной темой" },
] as const;

function preferences() {
  media ??= window.matchMedia("(prefers-color-scheme: light)");
  motionMedia ??= window.matchMedia("(prefers-reduced-motion: reduce)");
  transparencyMedia ??= window.matchMedia("(prefers-reduced-transparency: reduce)");
  contrastMedia ??= window.matchMedia("(forced-colors: active)");
}

function bounded(value: unknown, fallback: number, min: number, max: number) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(min, Math.min(max, number)) : fallback;
}

/** Прочитать настройки и выставить атрибуты <html>. Вызывается при любом изменении. */
export function applyTheme() {
  const root = document.documentElement;
  const theme = get<string>("ui.theme", "dark");
  preferences();
  const glass = theme === "glass";
  const tint = get<string>("ui.glass.tint", "dark");
  root.dataset.theme = theme === "system" || (glass && tint === "system")
    ? (media!.matches ? "light" : "dark") : theme === "light" || (glass && tint === "light") ? "light" : "dark";
  root.dataset.material = glass ? "glass" : "solid";
  const accent = ACCENTS.find((a) => a.id === get<string>("ui.accent", "cyan")) ?? ACCENTS[0];
  root.style.setProperty("--accent-h", String(accent.hue));
  const motion = get<string>("ui.motion", "auto");
  const reduce = motion === "reduce" || (motion === "auto" && motionMedia!.matches) || get<boolean>("ui.lite", false);
  if (reduce) root.dataset.motion = "reduce";
  else delete root.dataset.motion;
  if (get<boolean>("ui.lite", false)) root.dataset.lite = "";
  else delete root.dataset.lite;
  if (transparencyMedia!.matches || contrastMedia!.matches || get<boolean>("ui.glass.opaque", false)) root.dataset.opaque = "";
  else delete root.dataset.opaque;
  const opacity = bounded(get("ui.glass.opacity", 30), 30, 15, 85);
  root.style.setProperty("--glass-opacity", String(opacity / 100));
  root.style.setProperty("--glass-blur", `${bounded(get("ui.glass.blur", 8), 8, 0, 24)}px`);
  const desktop = glass && get<boolean>("ui.glass.desktop", true) && !root.hasAttribute("data-opaque") && !get<boolean>("ui.lite", false);
  const material = JSON.stringify([desktop, root.dataset.theme, opacity]);
  if ("__TAURI_INTERNALS__" in window && material !== nativeMaterial) {
    nativeMaterial = material;
    const version = ++nativeVersion;
    void invoke<boolean>("window_material", {glass: desktop, light: root.dataset.theme === "light", opacity}).then(enabled => {
      if (version === nativeVersion) root.dataset.desktopGlass = enabled ? "on" : "off";
    }).catch(() => { if (version === nativeVersion) { root.dataset.desktopGlass = "off"; nativeMaterial = ""; } });
  }
  root.dataset.atmosphere = !glass || get<boolean>("ui.lite", false) || contrastMedia!.matches ? "off"
    : reduce || !get<boolean>("ui.glass.animate", true) ? "still" : "flow";
  root.style.setProperty("--mist-strength", String(bounded(get("ui.glass.intensity", 55), 55, 10, 90) / 100));
  root.style.setProperty("--mist-duration", `${bounded(get("ui.glass.speed", 36), 36, 20, 80)}s`);
  const scale = bounded(get("ui.text_scale", 100), 100, 85, 150);
  root.style.fontSize = "";
  document.body.style.zoom = scale === 100 ? "" : String(scale / 100);
}

/** Системная тема и «уменьшить движение» Windows — следить и применять сразу. */
export function watchSystemTheme() {
  preferences();
  const queries = [media!, motionMedia!, transparencyMedia!, contrastMedia!];
  queries.forEach(query => query.addEventListener("change", applyTheme));
  const activity = () => document.documentElement.toggleAttribute("data-background", document.hidden || !document.hasFocus());
  document.addEventListener("visibilitychange", activity);
  window.addEventListener("focus", activity);
  window.addEventListener("blur", activity);
  activity();
  return () => {
    queries.forEach(query => query.removeEventListener("change", applyTheme));
    document.removeEventListener("visibilitychange", activity);
    window.removeEventListener("focus", activity);
    window.removeEventListener("blur", activity);
  };
}

/** Лёгкий режим: окно не рисует эффекты, персонаж реже, реактор без анимации. */
export function lite() {
  return get<boolean>("ui.lite", false);
}
