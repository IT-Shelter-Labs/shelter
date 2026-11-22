<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  // Ползунок со значением справа.
  let { value, min, max, step = 1, format = (v: number) => String(v), onchange }: { value: number; min: number; max: number; step?: number; format?: (v: number) => string; onchange: (v: number) => void } = $props();
</script>

<div class="range">
  <input type="range" {min} {max} {step} value={value} oninput={(e) => onchange(Number((e.target as HTMLInputElement).value))} />
  <span class="mono">{uiText(format(value))}</span>
</div>

<style>
  .range {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  input {
    width: 200px;
    accent-color: var(--accent);
  }
  span {
    min-width: 56px;
    text-align: right;
    color: var(--accent-2);
    font-size: 12.5px;
  }
</style>
