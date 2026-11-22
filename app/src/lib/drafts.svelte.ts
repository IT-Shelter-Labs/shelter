// Черновики редактора команд живут здесь, а не в компоненте: уход на другую
// страницу и обратно не теряет введённое. Плюс копия в localStorage на случай
// закрытия окна (если хранилище браузера доступно).
import type { Scenario } from "./api";

const KEY = "jarvis.scenario.draft";

export const drafts = $state({
  current: null as Scenario | null,      // что сейчас в редакторе
  original: "" as string,                // как было до правок (для «несохранено»)
  history: [] as string[],               // для «отменить»
  future: [] as string[],                // для «повторить»
  fromTask: null as { draft: Scenario; skipped: string[] } | null,
});

export function remember() {
  try {
    if (drafts.current) localStorage.setItem(KEY, JSON.stringify({ current: drafts.current, original: drafts.original }));
    else localStorage.removeItem(KEY);
  } catch {
    /* хранилище недоступно — черновик живёт до закрытия окна */
  }
}

export function restore(): { current: Scenario; original: string } | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function forget() {
  drafts.current = null;
  drafts.original = "";
  drafts.history = [];
  drafts.future = [];
  remember();
}

export const isDirty = () => !!drafts.current && JSON.stringify(drafts.current) !== drafts.original;
