<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  import { tick } from "svelte";
  import { dialog, answer } from "../lib/dialog.svelte";
  let box: HTMLDivElement | undefined = $state();
  $effect(() => {
    if (dialog.current) tick().then(() => box?.querySelector<HTMLButtonElement>("button.primary, button.danger")?.focus());
  });
  function keys(e: KeyboardEvent) {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); answer("cancel"); }
    if (e.key === "Tab" && box) {
      const buttons = Array.from(box.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'));
      const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
      if (index < 0 || (!e.shiftKey && index === buttons.length - 1) || (e.shiftKey && index === 0)) {
        e.preventDefault(); buttons[e.shiftKey ? buttons.length - 1 : 0]?.focus();
      }
    }
  }
</script>

{#if dialog.current}
  <div class="backdrop" role="presentation">
    <div class="dialog card fade-in" bind:this={box} role="alertdialog" aria-modal="true" aria-labelledby="dialog-title" aria-describedby="dialog-text" tabindex="-1" onkeydown={keys}>
      <h2 id="dialog-title">{uiText(dialog.current.title)}</h2>
      <p id="dialog-text">{uiText(dialog.current.text)}</p>
      <div class="buttons">
        <button class="btn ghost" onclick={() => answer("cancel")}>{uiText(dialog.current.cancel ?? "Отмена")}</button>
        {#if dialog.current.extra}<button class="btn" onclick={() => answer("extra")}>{uiText(dialog.current.extra)}</button>{/if}
        <button class="btn {dialog.current.danger ? 'danger' : 'primary'}" onclick={() => answer("ok")}>{uiText(dialog.current.ok)}</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    z-index: 60;
    display: grid;
    place-items: center;
    padding: 16px;
    background: rgba(0, 0, 0, 0.45);
  }
  .dialog {
    width: min(460px, 100%);
    background: var(--surface-solid);
    box-shadow: var(--shadow);
  }
  p {
    margin: 8px 0 18px;
    color: var(--text-2);
    white-space: pre-line;
  }
  .buttons {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    flex-wrap: wrap;
  }
</style>
