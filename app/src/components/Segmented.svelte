<script lang="ts" generics="V extends string">
  import { t as uiText } from "../lib/i18n.svelte";

  let {
    options,
    value,
    onchange,
    size = "md",
  }: { options: { value: V; label: string; hint?: string }[]; value: V; onchange: (v: V) => void; size?: "sm" | "md" } = $props();
</script>

<div class="seg {size}" role="radiogroup">
  {#each options as o}
    <button
      type="button"
      role="radio"
      aria-checked={o.value === value}
      class:active={o.value === value}
      title={uiText(o.hint ?? "")}
      onclick={() => onchange(o.value)}
    >
      {uiText(o.label)}
    </button>
  {/each}
</div>

<style>
  .seg {
    display: inline-flex;
    padding: 3px;
    gap: 2px;
    border-radius: 10px;
    background: var(--surface-3);
    border: 1px solid var(--line);
  }
  button {
    height: 28px;
    padding: 0 12px;
    border: none;
    border-radius: 7px;
    background: transparent;
    color: var(--text-2);
    font: inherit;
    font-size: 13px;
    font-weight: 550;
    cursor: pointer;
    white-space: nowrap;
    transition: background var(--fast), color var(--fast), box-shadow var(--fast);
  }
  button:hover {
    color: var(--text);
  }
  button.active {
    background: var(--surface);
    color: var(--text);
    box-shadow: var(--shadow-sm), 0 0 0 1px var(--line);
  }
  .sm button {
    height: 24px;
    padding: 0 9px;
    font-size: 12px;
  }
</style>
