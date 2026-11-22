<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  import type { Snippet } from "svelte";
  import { getCurrentWindow } from "@tauri-apps/api/window";
  import { Minus, Square, X } from "@lucide/svelte";

  let {
    children,
    right,
    onclose,
    maximizable = true,
    height = 44,
  }: { children?: Snippet; right?: Snippet; onclose?: () => void; maximizable?: boolean; height?: number } = $props();

  const win = getCurrentWindow();
</script>

<header class="titlebar" style="height:{height}px" data-tauri-drag-region>
  <div class="left" data-tauri-drag-region>
    {@render children?.()}
  </div>
  <div class="right">
    {@render right?.()}
    <div class="controls">
      <button class="wbtn" title={uiText("Свернуть")} onclick={() => win.minimize()}><Minus size={15} /></button>
      {#if maximizable}
        <button class="wbtn" title={uiText("Развернуть")} onclick={() => win.toggleMaximize()}><Square size={12} /></button>
      {/if}
      <button class="wbtn close" title={uiText("Закрыть")} onclick={() => (onclose ? onclose() : win.close())}><X size={16} /></button>
    </div>
  </div>
</header>

<style>
  .titlebar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex: none;
    padding-left: 14px;
    user-select: none;
  }
  .left {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
    flex: 1;
    height: 100%;
  }
  .right {
    display: flex;
    align-items: center;
    gap: 4px;
    height: 100%;
  }
  .controls {
    display: flex;
    height: 100%;
  }
  .wbtn {
    width: 44px;
    height: 100%;
    border: none;
    background: transparent;
    color: var(--text-2);
    display: grid;
    place-items: center;
    cursor: pointer;
    transition: background var(--fast), color var(--fast);
  }
  .wbtn:hover {
    background: var(--hover);
    color: var(--text);
  }
  .wbtn.close:hover {
    background: #e5484d;
    color: #fff;
  }
</style>
