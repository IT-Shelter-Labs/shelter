<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  import { invoke } from "@tauri-apps/api/core";
  import { get, set, toast, toastError } from "../lib/store.svelte";
  import { ask } from "../lib/dialog.svelte";
  type Package = {id: string; version: string; name: string; description: string; sha256: string};
  let source = $state(get<string>("ui.plugin_source", ""));
  let local = $state(false);
  let packages = $state<Package[]>([]);
  let loadedSource = $state("");
  let loadedLocal = $state(false);
  let busy = $state(false);
  let { onchange }: {onchange: () => void} = $props();
  const post = <T,>(body: object) => invoke<T>("core_post", {path: "/api/plugins", body});
  async function load() {
    busy = true;
    try {
      const index = await post<{packages: Package[]}>({op:"source", source: source.trim(), local});
      packages = index.packages; loadedSource = source.trim(); loadedLocal = local;
      set("ui.plugin_source", loadedSource);
    } catch (e) { packages = []; toastError(e); } finally { busy = false; }
  }
  async function install(p: Package) {
    busy = true;
    try {
      const info = await post<{ticket: string; manifest: {author: string; license: string}; permissions: string[]}>({op:"source_preview", source:loadedSource, local:loadedLocal, id:p.id, version:p.version, sha256:p.sha256});
      if (await ask({title: `Установить ${p.name} ${p.version}?`, text:`Источник: ${loadedSource}\nАвтор: ${info.manifest.author}\nЛицензия: ${info.manifest.license || "не указана"}\nПрава: ${info.permissions.join(", ") || "не заявлены"}\nSHA256: ${p.sha256}\n\nЭто код с правами вашей учётной записи. Контрольная сумма проверяет архив, но не гарантирует надёжность автора.`, ok:"Доверяю, установить"}) !== "ok") return;
      await post({op:"source_install", ticket: info.ticket}); toast(`«${p.name}» установлено`, "success"); onchange();
    } catch (e) { toastError(e); } finally { busy = false; }
  }
</script>
<details class="source">
  <summary>{uiText("Другой источник дополнений")}</summary>
  <p class="lead small">{uiText("Добавляйте только каталоги известных вам авторов. Проверка источника загружает список; установка требует отдельного подтверждения.")}</p>
  <label>{uiText("Адрес index.json ")}<input aria-label={uiText("Адрес источника дополнений")} type="url" bind:value={source} placeholder="https://example.org/jarvis/index.json" /></label>
  <label class="local"><input type="checkbox" bind:checked={local} />{uiText(" Локальная демонстрация на localhost (HTTP)")}</label>
  <button class="btn sm" disabled={busy || !source.trim()} onclick={load}>{uiText(busy ? "Проверяю…" : "Проверить источник")}</button>
  {#each packages as p (p.id + p.version)}<div class="package"><div><b>{p.name} · {uiText(p.version)}</b><p>{uiText(p.description)}</p></div><button class="btn sm" disabled={busy} onclick={() => install(p)}>{uiText("Просмотр и установка")}</button></div>{/each}
</details>
<style>
  .source { margin-top: 18px; border-top: 1px solid var(--line); padding-top: 16px; }
  summary { cursor: pointer; font-size: 13px; } label { display: flex; gap: 8px; flex-direction: column; font-size: 12px; color: var(--text-2); margin: 12px 0; }
  input[type="url"] { width: 100%; } .local { flex-direction: row; align-items: center; } .local input { width: auto; }
  .package { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin-top: 10px; padding: 12px; border: 1px solid var(--line); border-radius: 12px; }
  .package p { font-size: 12px; color: var(--text-2); margin: 4px 0; }
</style>
