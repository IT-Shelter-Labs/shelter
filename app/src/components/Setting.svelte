<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  import type { Snippet } from "svelte";
  // Строка настройки: название и пояснение слева, элемент управления справа.
  let { title, hint = "", children, wide = false }: { title: string; hint?: string; children: Snippet; wide?: boolean } = $props();
</script>

<div class="row" class:wide>
  <div class="label">
    <b>{uiText(title)}</b>
    {#if hint}<span>{uiText(hint)}</span>{/if}
  </div>
  <div class="control">{@render children()}</div>
</div>

<style>
  .control {
    flex: none;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .wide {
    flex-direction: column;
    align-items: stretch;
  }
  .wide .control {
    flex: 1;
  }
  .label {
    max-width: 560px;
  }
</style>
