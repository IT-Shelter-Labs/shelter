<script lang="ts">
  import { t as uiText } from "../../lib/i18n.svelte";

  // Выполнение по шагам: текущий шаг, проверенный результат, ожидание и понятная ошибка.
  import { CircleCheck, CircleAlert, LoaderCircle, CircleSlash, Square, Hourglass } from "@lucide/svelte";
  import { app, toastError } from "../../lib/store.svelte";
  import { api } from "../../lib/api";

  let { run }: { run: string } = $props();
  type Line = { step: string; label: string; state: string; detail: string };
  const view = $derived.by(() => {
    const events = app.feed.filter((e: any) => e.kind === "scenario" && e.run === run) as any[];
    const lines = new Map<string, Line>();
    let status = "queued", error = "", name = "";
    for (const e of events) {
      name = e.name || name;
      if (e.step) lines.set(e.step, { step: e.step, label: e.label, state: e.state, detail: e.detail ?? "" });
      else { status = e.status; error = e.error ?? error; }
    }
    return { lines: [...lines.values()], status, error, name };
  });
  const labels: Record<string, string> = { queued: "В очереди", running: "Выполняется", done: "Готово", partial: "Готово, но были ошибки", failed: "Не выполнено", cancelled: "Остановлено", skipped: "Не запущено: условие не выполнено" };
  async function stop() {
    try { await api.scenarioOp({ op: "cancel", run }); } catch (e) { toastError(e); }
  }
</script>

<div class="run notice {view.status === 'done' ? 'ok' : view.status === 'failed' ? 'bad' : view.status === 'running' || view.status === 'queued' ? '' : 'warn'}" aria-live="polite">
  <div class="body">
    <div class="top">
      <b>{uiText(labels[view.status] ?? view.status)}</b>
      {#if view.status === "running" || view.status === "queued"}<button class="btn stop sm" onclick={stop}><Square size={12} />{uiText(" Стоп")}</button>{/if}
    </div>
    <ol>
      {#each view.lines as l (l.step)}
        <li>
          {#if l.state === "done"}<CircleCheck size={14} color="var(--ok)" />{:else if l.state === "failed"}<CircleAlert size={14} color="var(--bad)" />{:else if l.state === "running"}{#if /дожд|пауза/i.test(l.label)}<Hourglass size={14} />{:else}<LoaderCircle size={14} class="spin" />{/if}{:else}<CircleSlash size={14} />{/if}
          <span>{uiText(l.label)}</span>{#if l.detail}<small class="dim"> — {uiText(l.detail)}</small>{/if}
        </li>
      {:else}
        <li class="dim">{uiText("Ждёт своей очереди…")}</li>
      {/each}
    </ol>
    {#if view.error}<p class="err">{uiText(view.error)}</p>{/if}
    {#if view.status === "cancelled"}<p class="dim small">{uiText("Уже выполненные шаги не откатываются: открытые программы остаются открытыми.")}</p>{/if}
  </div>
</div>

<style>
  .run {
    margin-top: 10px;
  }
  .body {
    flex: 1;
    min-width: 0;
  }
  .top {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
  }
  ol {
    list-style: none;
    margin: 6px 0 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  li {
    display: flex;
    gap: 7px;
    align-items: baseline;
    font-size: 13px;
  }
  li :global(svg) {
    flex: none;
    position: relative;
    top: 2px;
  }
  .err {
    margin-top: 6px;
    color: var(--bad);
  }
  .small {
    font-size: 12px;
  }
</style>
