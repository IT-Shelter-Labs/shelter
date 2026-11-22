<script lang="ts">
  import { t as uiText, locale } from "../lib/i18n.svelte";

  // Сопряжённые устройства: одноразовый код, список, отзыв доступа.
  import { onMount } from "svelte";
  import { KeyRound, Smartphone, Send, Ban } from "@lucide/svelte";
  import { invoke } from "@tauri-apps/api/core";
  import { app, toast, toastError } from "../lib/store.svelte";
  import { ask } from "../lib/dialog.svelte";

  let { kind = "phone" }: { kind?: "phone" | "telegram" } = $props();
  type Device = { id: string; name: string; kind: string; revoked: boolean; created: number; last_seen: number };
  let list = $state<Device[]>([]);
  let code = $state<{ code: string; until: number } | null>(null);
  let now = $state(Date.now());

  async function load() {
    if (!app.status) return;
    try { list = (await invoke<{ devices: Device[] }>("core_post", { path: "/api/companion", body: { op: "list" } })).devices; }
    catch (e) { toastError(e); }
  }
  onMount(() => {
    load();
    const t = setInterval(() => (now = Date.now()), 1000);
    return () => clearInterval(t);
  });
  async function newCode() {
    try {
      const r = await invoke<{ code: string; expires: number }>("core_post", { path: "/api/companion", body: { op: "code" } });
      code = { code: r.code, until: Date.now() + r.expires * 1000 };
    } catch (e) { toastError(e); }
  }
  async function revoke(d: Device) {
    if ((await ask({ title: "Отозвать доступ?", text: `«${d.name}» больше не сможет ничего выполнять. Вернуть — только новым сопряжением.`, ok: "Отозвать", danger: true })) !== "ok") return;
    try { await invoke("core_post", { path: "/api/companion", body: { op: "revoke", id: d.id } }); toast("Доступ отозван", "success"); load(); }
    catch (e) { toastError(e); }
  }
  const mine = $derived(list.filter((d) => (kind === "telegram" ? d.kind === "telegram" : d.kind !== "telegram")));
  const seen = (t: number) => (t ? new Date(t * 1000).toLocaleString((locale.language === "ru" ? "ru-RU" : "en-US"), { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—");
</script>

{#if !app.status}
  <p class="dim">{uiText("Включите Джарвиса, чтобы подключать устройства.")}</p>
{:else}
  <div class="pair">
    <button class="btn" onclick={newCode}><KeyRound size={14} />{uiText(" Получить код")}</button>
    {#if code && code.until > now}
      <span class="code mono" aria-label={uiText("Код сопряжения")}>{uiText(code.code.slice(0, 3))} {uiText(code.code.slice(3))}</span>
      <span class="dim small">{uiText("ещё ")}{uiText(Math.ceil((code.until - now) / 1000))}{uiText(" с · ")}{uiText(kind === "telegram" ? "отправьте боту «/start " + code.code + "»" : "введите на телефоне")}</span>
    {/if}
  </div>
  <ul>
    {#each mine as d (d.id)}
      <li class:revoked={d.revoked}>
        {#if d.kind === "telegram"}<Send size={14} />{:else}<Smartphone size={14} />{/if}
        <span class="name">{d.name}</span>
        <span class="dim small">{uiText(d.revoked ? "отозван" : `был на связи: ${seen(d.last_seen)}`)}</span>
        {#if !d.revoked}<button class="btn ghost sm danger" onclick={() => revoke(d)}><Ban size={13} />{uiText(" Отозвать")}</button>{/if}
      </li>
    {:else}
      <li class="dim">{uiText("Пока ничего не подключено.")}</li>
    {/each}
  </ul>
{/if}

<style>
  .pair { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin: 6px 0 10px; }
  .code { font-size: 24px; font-weight: 700; letter-spacing: 0.12em; color: var(--accent-2); }
  ul { list-style: none; padding: 0; margin: 0; }
  li { display: flex; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px solid var(--line); }
  li:last-child { border-bottom: none; }
  li.revoked { opacity: 0.55; }
  .name { flex: 1; font-weight: 600; }
  .small { font-size: 12.5px; }
</style>
