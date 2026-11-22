<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  let { checked = false, disabled = false, onchange, label = "" }: { checked?: boolean; disabled?: boolean; onchange?: (v: boolean) => void; label?: string } = $props();
</script>

<button
  type="button"
  role="switch"
  aria-checked={checked}
  aria-label={uiText(label)}
  class="toggle"
  class:on={checked}
  {disabled}
  onclick={() => onchange?.(!checked)}
>
  <span class="knob"></span>
</button>

<style>
  .toggle {
    position: relative;
    width: 40px;
    height: 23px;
    flex: none;
    border-radius: 999px;
    border: 1px solid var(--line-2);
    background: var(--surface-3);
    cursor: pointer;
    transition: background var(--mid) var(--ease), border-color var(--mid);
    outline: none;
    padding: 0;
  }
  .toggle:focus-visible {
    box-shadow: 0 0 0 3px var(--focus);
  }
  .toggle.on {
    background: var(--accent);
    border-color: transparent;
  }
  .toggle:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .knob {
    position: absolute;
    top: 2px;
    left: 2px;
    width: 17px;
    height: 17px;
    border-radius: 50%;
    background: #fff;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
    transition: transform var(--mid) var(--ease);
  }
  .toggle.on .knob {
    transform: translateX(17px);
  }
</style>
