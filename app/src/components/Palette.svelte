<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  // Поиск по разделам, настройкам и командам (Ctrl+K). Стрелки — выбор, Enter — перейти.
  import { onMount, tick } from "svelte";
  import { Search, Workflow, Settings2, CornerDownLeft } from "@lucide/svelte";
  import { navigate, app, type Page } from "../lib/store.svelte";
  import { api } from "../lib/api";
  import { SETTINGS_INDEX } from "../lib/settingsIndex";

  let { onclose }: { onclose: () => void } = $props();
  let query = $state("");
  let active = $state(0);
  let input: HTMLInputElement | undefined = $state();

  onMount(async () => {
    await tick();
    input?.focus();
    if (!app.scenarios && app.status) app.scenarios = await api.scenarios().catch(() => null);
  });

  type Hit = { title: string; hint: string; page: Page; sub: string; kind: "setting" | "command"; focus?: string };
  const norm = (s: string) => s.toLowerCase().replace(/ё/g, "е");
  const results = $derived.by<Hit[]>(() => {
    const q = norm(query.trim());
    const commands: Hit[] = (app.scenarios?.items ?? []).map((s: any) => ({
      title: s.name, hint: (s.phrases ?? []).map((p: string) => `«${p}»`).join(", ") || s.category,
      page: "commands" as Page, sub: "edit:" + s.id, kind: "command" as const }));
    const all: Hit[] = [...SETTINGS_INDEX.map((s) => ({ ...s, kind: "setting" as const })), ...commands];
    if (!q) return all.slice(0, 12);
    const words = q.split(/\s+/);
    return all
      .map((h) => ({ h, text: norm(h.title + " " + h.hint + " " + uiText(h.title) + " " + uiText(h.hint)) }))
      .filter(({ text }) => words.every((w) => text.includes(w)))
      .sort((a, b) => Number(!norm(a.h.title).startsWith(words[0])) - Number(!norm(b.h.title).startsWith(words[0])))
      .slice(0, 14)
      .map(({ h }) => h);
  });

  function go(hit: Hit | undefined) {
    if (!hit) return;
    onclose();
    navigate(hit.page, hit.sub);
    if (hit.focus) setTimeout(() => document.getElementById(hit.focus!)?.scrollIntoView({ block: "center" }), 120);
  }
  function keys(e: KeyboardEvent) {
    if (e.key === "Escape") onclose();
    else if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(results.length - 1, active + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(0, active - 1); }
    else if (e.key === "Enter") { e.preventDefault(); go(results[active]); }
  }
  $effect(() => { query; active = 0; });
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<div class="backdrop" role="presentation" onclick={onclose}>
  <div class="palette card" role="dialog" aria-modal="true" aria-label={uiText("Поиск")} tabindex="-1" onclick={(e) => e.stopPropagation()} onkeydown={keys}>
    <label class="query">
      <Search size={16} />
      <input bind:this={input} bind:value={query} placeholder={uiText("Например: микрофон, тема, громкость, музыка…")} aria-label={uiText("Что найти")} />
      <kbd>Esc</kbd>
    </label>
    <ul role="listbox" aria-label={uiText("Результаты")}>
      {#each results as hit, i}
        <li role="option" aria-selected={i === active}>
          <button class:active={i === active} onmouseenter={() => (active = i)} onclick={() => go(hit)}>
            {#if hit.kind === "command"}<Workflow size={15} />{:else}<Settings2 size={15} />{/if}
            <span class="text"><b>{uiText(hit.title)}</b><small>{uiText(hit.hint)}</small></span>
            {#if i === active}<CornerDownLeft size={14} />{/if}
          </button>
        </li>
      {:else}
        <li class="none dim">{uiText("Ничего не нашлось. Попробуйте другое слово.")}</li>
      {/each}
    </ul>
  </div>
</div>

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    z-index: 50;
    display: flex;
    justify-content: center;
    align-items: flex-start;
    padding-top: 12vh;
    background: rgba(0, 0, 0, 0.42);
  }
  .palette {
    width: min(620px, 92vw);
    padding: 8px;
    background: var(--surface-solid);
    box-shadow: var(--shadow);
  }
  .query {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 4px 10px;
    color: var(--text-3);
    border-bottom: 1px solid var(--line);
  }
  .query input {
    flex: 1;
    border: none;
    background: transparent;
    box-shadow: none;
    height: 42px;
    padding: 0;
    font-size: 15px;
  }
  ul {
    list-style: none;
    margin: 6px 0 0;
    padding: 0;
    max-height: 52vh;
    overflow-y: auto;
  }
  li button {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 10px;
    border: none;
    border-radius: 9px;
    background: transparent;
    color: var(--text-2);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  li button.active {
    background: var(--accent-soft);
    color: var(--text);
  }
  .text {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
  }
  .text b {
    font-weight: 600;
    color: var(--text);
  }
  .text small {
    font-size: 12px;
    color: var(--text-3);
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .none {
    padding: 16px;
    text-align: center;
  }
</style>
