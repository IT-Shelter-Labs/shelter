<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  import { app } from "../lib/store.svelte";
  import { CircleCheck, CircleAlert, Info, X } from "@lucide/svelte";
  const dismissToast = (id: number) => {
    const i = app.toasts.findIndex((t) => t.id === id);
    if (i >= 0) app.toasts.splice(i, 1);
  };
</script>

<div class="toasts">
  {#each app.toasts as t (t.id)}
    <div class="toast {t.kind} fade-up" role="status">
      <span class="ic">
        {#if t.kind === "success"}<CircleCheck size={17} />{:else if t.kind === "error"}<CircleAlert size={17} />{:else}<Info size={17} />{/if}
      </span>
      <div class="body">
        <div>{uiText(t.text)}</div>
      </div>
      <button class="x" onclick={() => dismissToast(t.id)} aria-label={uiText("Закрыть")}><X size={14} /></button>
    </div>
  {/each}
</div>

<style>
  .toasts {
    position: fixed;
    right: 16px;
    bottom: 16px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    z-index: 100;
    max-width: 380px;
    pointer-events: none;
  }
  .toast {
    pointer-events: auto;
    display: flex;
    gap: 10px;
    align-items: flex-start;
    padding: 11px 12px;
    border-radius: var(--r-md);
    background: var(--surface);
    border: 1px solid var(--line-2);
    box-shadow: var(--shadow);
    font-size: 13px;
    background: #0a1a24;
    animation: fade-in 260ms var(--ease) both;
  }
  .ic {
    margin-top: 1px;
    color: var(--accent-2);
  }
  .toast.success .ic {
    color: var(--ok);
  }
  .toast.error .ic {
    color: var(--bad);
  }
  .body {
    flex: 1;
    min-width: 0;
  }
  .hint {
    color: var(--text-2);
    font-size: 12.5px;
    margin-top: 2px;
  }
  .x {
    border: none;
    background: transparent;
    color: var(--text-3);
    cursor: pointer;
    padding: 2px;
    border-radius: 5px;
  }
  .x:hover {
    color: var(--text);
    background: var(--hover);
  }
</style>
