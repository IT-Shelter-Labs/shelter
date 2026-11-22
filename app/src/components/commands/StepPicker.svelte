<script lang="ts">
  import { t as uiText } from "../../lib/i18n.svelte";

  // «Добавить шаг»: действия по разделам с поиском. Продвинутые — только в продвинутом режиме.
  import { tick, onMount } from "svelte";
  import { Search, X } from "@lucide/svelte";
  import { app } from "../../lib/store.svelte";

  let { advanced = false, nested = false, onpick, onclose }: { advanced?: boolean; nested?: boolean; onpick: (type: string) => void; onclose: () => void } = $props();
  let query = $state("");
  let input: HTMLInputElement | undefined = $state();
  onMount(() => tick().then(() => input?.focus()));

  const platform = $derived(app.scenarios?.platform ?? "windows");
  const groups = $derived.by(() => {
    const q = query.toLowerCase().trim();
    const out = new Map<string, [string, any][]>();
    for (const [id, spec] of Object.entries(app.scenarios?.actions ?? {})) {
      if (spec.advanced && !advanced) continue;
      if (q && !(spec.label.toLowerCase().includes(q) || (spec.group ?? "").toLowerCase().includes(q))) continue;
      const list = out.get(spec.group ?? "Другое") ?? [];
      list.push([id, spec]);
      out.set(spec.group ?? "Другое", list);
    }
    return [...out.entries()];
  });
</script>

<div class="picker card fade-in" role="dialog" aria-label={uiText("Выберите действие")} tabindex="-1" onkeydown={(e) => e.key === "Escape" && onclose()}>
  <div class="top">
    <label class="search"><Search size={14} /><input bind:this={input} bind:value={query} placeholder={uiText("Что сделать? Например: окно, громкость, сайт")} aria-label={uiText("Поиск действия")} /></label>
    <button class="btn ghost icon sm" aria-label={uiText("Закрыть")} onclick={onclose}><X size={15} /></button>
  </div>
  <div class="groups">
    {#each groups as [group, list]}
      <div class="group">
        <span class="caps">{uiText(group)}</span>
        {#each list as [id, spec]}
          {@const unsupported = !!spec.platforms && !spec.platforms.includes(platform)}
          <button class="item" disabled={unsupported} title={uiText(unsupported ? "Недоступно на этой системе" : spec.hint ?? "")} onclick={() => onpick(id)}>
            {uiText(spec.label)}{#if unsupported}<small>{uiText(" — недоступно здесь")}</small>{/if}
          </button>
        {/each}
      </div>
    {:else}
      <p class="dim">{uiText("Ничего не нашлось")}{uiText(advanced ? "" : ". Включите «Продвинутый режим», чтобы увидеть все действия")}.</p>
    {/each}
  </div>
  {#if !advanced}<p class="dim note">{uiText("Ещё: команды Windows, плагины, профили — в продвинутом режиме.")}</p>{/if}
</div>

<style>
  .picker {
    padding: 12px;
    margin: 4px 0 8px;
    background: var(--surface-solid);
    border-color: var(--accent);
  }
  .top {
    display: flex;
    gap: 6px;
    align-items: center;
    margin-bottom: 10px;
  }
  .search {
    flex: 1;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 10px;
    border-radius: 10px;
    border: 1px solid var(--line-2);
    background: var(--field);
    color: var(--text-3);
  }
  .search input {
    flex: 1;
    border: none;
    background: transparent;
    box-shadow: none;
    padding: 0;
  }
  .groups {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 10px 16px;
  }
  .group {
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .item {
    text-align: left;
    border: none;
    background: none;
    color: var(--text);
    font: inherit;
    font-size: 13px;
    padding: 5px 8px;
    margin: 0 -8px;
    border-radius: 7px;
    cursor: pointer;
  }
  .item:hover:not(:disabled) {
    background: var(--accent-soft);
  }
  .item:disabled {
    color: var(--text-3);
    cursor: default;
  }
  .note {
    margin-top: 10px;
    font-size: 12px;
  }
</style>
