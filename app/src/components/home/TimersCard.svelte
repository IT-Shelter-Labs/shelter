<script lang="ts">
  import { t as uiText, locale } from "../../lib/i18n.svelte";

  import { AlarmClock, X, Repeat } from "@lucide/svelte";
  import { onMount } from "svelte";
  import { invoke } from "@tauri-apps/api/core";
  import { app, toastError } from "../../lib/store.svelte";
  import { poll } from "../../lib/poll";

  type Item = { id: string; label: string; due: number; kind: string; repeat?: { time: string; days: number[] } | null };
  let items = $state<Item[]>([]);
  let now = $state(Date.now() / 1000);
  let offset = 0;
  onMount(() => poll(async () => {
    if (!app.status) return;
    const r = await invoke<{ items: Item[]; now: number }>("core_get", { path: "/api/schedule" });
    offset = r.now - Date.now() / 1000;
    items = r.items.sort((a, b) => a.due - b.due);
  }, 5000));
  onMount(() => {
    const t = setInterval(() => (now = Date.now() / 1000 + offset), 1000);
    return () => clearInterval(t);
  });

  function left(due: number) {
    const s = Math.max(0, Math.round(due - now));
    if (s >= 86400) return new Date(due * 1000).toLocaleString((locale.language === "ru" ? "ru-RU" : "en-US"), { weekday: "short", hour: "2-digit", minute: "2-digit" });
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    return h ? `${h} ч ${m} мин` : m ? `${m}:${String(sec).padStart(2, "0")}` : `${sec} с`;
  }
  async function cancel(id: string) {
    try {
      await invoke("core_post", { path: "/api/schedule/cancel", body: { id } });
      items = items.filter((i) => i.id !== id);
    } catch (e) {
      toastError(e);
    }
  }
</script>

{#if !items.length}
  <p class="line dim">{uiText("Пока ничего не запланировано. Скажите: «таймер на пять минут» или «напомни через час сделать перерыв».")}</p>
{:else}
  <ul>
    {#each items.slice(0, 5) as t (t.id)}
      <li>
        {#if t.repeat}<Repeat size={14} />{:else}<AlarmClock size={14} />{/if}
        <span class="label">{t.label || uiText(t.kind === "timer" ? "Таймер" : "Напоминание")}</span>
        <span class="left mono">{uiText(left(t.due))}</span>
        <button class="btn ghost icon sm" aria-label={uiText("Отменить «" + String(t.label || 'таймер') + "»")} title={uiText("Отменить")} onclick={() => cancel(t.id)}><X size={14} /></button>
      </li>
    {/each}
  </ul>
{/if}

<style>
  ul { list-style: none; margin: 4px 0 0; padding: 0; }
  li { display: flex; align-items: center; gap: 8px; padding: 4px 0; color: var(--text-2); }
  .label { flex: 1; min-width: 0; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .left { font-size: 12.5px; color: var(--accent-2); }
  .line { font-size: 13px; }
</style>
