<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { t } from "../lib/i18n.svelte";
  import { get, set, app, navigate } from "../lib/store.svelte";
  import Setting from "./Setting.svelte";

  let { kind }: { kind: "stt" | "tts" } = $props();
  type Provider = { id: string; name: string };
  let providers = $state<Provider[]>([]);
  let loadState = $state<"offline" | "loading" | "ready" | "error">("offline");
  let request = 0;
  const online = $derived(!!app.status);
  const section = $derived(kind === "stt" ? "asr" : "tts");
  const enabled = $derived(get(section + ".engine") === "plugin");
  const selected = $derived(get<string>(section + ".plugin.id", ""));
  const title = $derived(kind === "stt" ? "Распознавание через дополнение" : "Голос из дополнения");

  async function load() {
    const current = ++request;
    if (!online) { providers = []; loadState = "offline"; return; }
    loadState = "loading";
    try {
      const result = await invoke<Record<"stt" | "tts", Provider[]>>("core_post", { path: "/api/plugins", body: { op: "extensions" } });
      if (current === request) { providers = result[kind]; loadState = "ready"; }
    } catch {
      if (current === request) { providers = []; loadState = "error"; }
    }
  }
  $effect(() => { void load(); return () => { request++; }; });

  function choose(id: string) {
    if (!providers.some(item => item.id === id)) return;
    set(section + ".plugin.id", id);
    set(section + ".engine", "plugin");
  }
</script>

<Setting title={t(title)} hint={t(kind === "stt"
  ? "Дополнение превращает речь в текст вместо GigaAM или Vosk. В списке — установленные и разрешённые движки."
  : "Используйте установленный и разрешённый движок озвучки.")} wide>
  <div class="speech-options">
  {#if loadState === "loading"}
    <p class="dim" role="status">{t("Проверяю установленные дополнения…")}</p>
  {:else if loadState === "offline"}
    <p class="dim">{t("Запустите Джарвиса, чтобы увидеть доступные дополнения.")}</p>
  {:else if loadState === "error"}
    <p class="dim" role="status">{t("Не удалось получить список дополнений.")}</p>
  {:else}
    {#if enabled && (!selected || !providers.some(item => item.id === selected))}
      <p class="notice" role="status">{t("Сохранённое дополнение сейчас недоступно. Установите и разрешите его или смените движок.")}</p>
    {/if}
    {#if providers.length}
      <select aria-label={t(title)} value={enabled && providers.some(item => item.id === selected) ? selected : ""}
        onchange={(e) => choose(e.currentTarget.value)}>
        <option value="" disabled>{t("Выберите дополнение")}</option>
        {#each providers as item (item.id)}<option value={item.id}>{item.name}</option>{/each}
      </select>
      <p class="dim">{t("После выбора нажмите «Применить».")}</p>
    {:else}
      <p class="dim">{t(kind === "stt" ? "Нет доступных дополнений для распознавания. Можно выбрать GigaAM или Vosk выше."
        : "Нет доступных дополнений для озвучки. Выберите другой голос или установите дополнение.")}</p>
    {/if}
  {/if}
  <div class="buttons">
    <button class="btn sm" onclick={() => navigate("connections", "plugins")}>{t("Открыть дополнения")}</button>
    <button class="btn sm ghost" onclick={load} disabled={!online || loadState === "loading"}>{t("Обновить")}</button>
  </div>
  </div>
</Setting>

<style>
  .speech-options { min-width: 0; width: 100%; }
  .speech-options p { margin: 0 0 8px; }
  .speech-options select { margin: 0 0 8px; max-width: 100%; }
  .buttons { flex-wrap: wrap; }
</style>
