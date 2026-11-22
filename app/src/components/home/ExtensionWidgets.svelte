<script lang="ts">
  import { t as uiText } from "../../lib/i18n.svelte";

  import { onMount } from "svelte";
  import { invoke } from "@tauri-apps/api/core";
  import { poll } from "../../lib/poll";
  import { app, navigate } from "../../lib/store.svelte";
  type Widget = { id: string; name: string; title?: string; text?: string; rows?: {label: string; value: string}[]; error?: string };
  let items = $state<Widget[]>([]);
  let error = $state("");
  onMount(() => poll(async () => {
    if (!app.status) return;
    try {
      const result = await invoke<{items: Widget[]}>("core_post", {path: "/api/plugins", body: {op: "widgets"}});
      items = result.items;
      error = "";
    } catch { error = "Не удалось обновить дополнения"; }
  }, 15000));
</script>

{#if error}<p class="dim small">{uiText(error)}</p>{/if}
{#each items as item (item.id)}
  <section class="extension-widget" aria-label={item.title || item.name}>
    <b>{item.title || item.name}</b>
    {#if item.error}<p class="bad-text">{uiText(item.error)}</p>{:else}
      {#if item.text}<p class="selectable">{item.text}</p>{/if}
      {#if item.rows?.length}<dl>{#each item.rows as row}<div><dt>{uiText(row.label)}</dt><dd>{uiText(row.value)}</dd></div>{/each}</dl>{/if}
    {/if}
  </section>
{:else}<p class="dim small">{uiText("Установите дополнение с виджетом в ")}<button class="link" onclick={() => navigate("connections")}>{uiText("«Подключениях»")}</button>.</p>{/each}

<style>
  .extension-widget + .extension-widget { margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--line); }
  p { white-space: pre-wrap; font-size: 13px; color: var(--text-2); margin: 5px 0; overflow-wrap: anywhere; }
  .bad-text { color: var(--bad); }
  dl { margin: 10px 0 0; font-size: 12px; } dl > div { display: flex; justify-content: space-between; gap: 14px; padding: 4px 0; }
  dt { color: var(--text-2); } dd { margin: 0; color: var(--text); text-align: right; overflow-wrap: anywhere; }
</style>
