<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  import { Ear, Brain, Palette, Cpu } from "@lucide/svelte";
  import { nav, navigate } from "../lib/store.svelte";
  import Hearing from "./Hearing.svelte";
  import Mind from "./Mind.svelte";
  import Look from "./Look.svelte";
  import System from "./System.svelte";

  const sections = [
    { id: "voice", title: "Голос и слух", icon: Ear, view: Hearing },
    { id: "models", title: "Модели и разум", icon: Brain, view: Mind },
    { id: "look", title: "Оформление", icon: Palette, view: Look },
    { id: "system", title: "Система и диагностика", icon: Cpu, view: System },
  ] as const;
  const current = $derived(sections.find((s) => s.id === nav.sub) ?? sections[0]);
</script>

<div class="tabs" role="tablist" aria-label={uiText("Разделы настроек")}>
  {#each sections as s}
    <button role="tab" aria-selected={current.id === s.id} class:active={current.id === s.id} onclick={() => navigate("settings", s.id)}>
      <s.icon size={16} /> {uiText(s.title)}
    </button>
  {/each}
</div>

{#key current.id}
  <div class="fade-in"><current.view /></div>
{/key}

<style>
  .tabs {
    position: sticky;
    top: -18px;
    z-index: 5;
    display: flex;
    gap: 4px;
    margin: -4px 0 18px;
    padding: 6px;
    border-radius: 12px;
    border: 1px solid var(--line);
    background: var(--surface-solid);
    overflow-x: auto;
  }
  button {
    display: flex;
    align-items: center;
    gap: 8px;
    height: 34px;
    padding: 0 14px;
    border: none;
    border-radius: 8px;
    background: transparent;
    color: var(--text-2);
    font: inherit;
    font-weight: 560;
    white-space: nowrap;
    cursor: pointer;
  }
  button:hover {
    background: var(--hover);
    color: var(--text);
  }
  button.active {
    background: var(--accent-soft);
    color: var(--accent-2);
  }
</style>
