<script lang="ts">
  import { t as uiText } from "../../lib/i18n.svelte";

  // Задачи помощника: что выполняется, итог и «Сохранить как сценарий» для удачных.
  import { onMount } from "svelte";
  import { Save, Square, CircleCheck, CircleAlert, LoaderCircle, CircleSlash } from "@lucide/svelte";
  import { app, navigate, refreshAssistant, toastError } from "../../lib/store.svelte";
  import { api } from "../../lib/api";
  import { poll } from "../../lib/poll";
  import { drafts } from "../../lib/drafts.svelte";

  onMount(() => poll(() => refreshAssistant(), 4000));
  const runs = $derived((app.assistant?.runs ?? []).slice(0, 5));
  const labels: Record<string, string> = { queued: "в очереди", running: "выполняю", done: "готово", failed: "ошибка", cancelled: "остановлено", interrupted: "прервано" };

  async function save(id: string) {
    try {
      const r = await api.scenarioOp<{ draft: any; skipped: string[] }>({ op: "from_run", run: id });
      drafts.fromTask = { draft: r.draft, skipped: r.skipped.map((x) => "Не перенесено: " + x) };
      navigate("commands", "task");
    } catch (e) {
      toastError(e);
    }
  }
</script>

{#if !runs.length}
  <p class="line dim">{uiText("Задач пока не было. Попросите, например: «открой телеграм и сделай громкость 30».")}</p>
{:else}
  <ul>
    {#each runs as r (r.id)}
      <li>
        {#if r.status === "done"}<CircleCheck size={14} color="var(--ok)" />{:else if r.status === "failed"}<CircleAlert size={14} color="var(--bad)" />{:else if r.status === "running" || r.status === "queued"}<LoaderCircle size={14} class="spin" />{:else}<CircleSlash size={14} />{/if}
        <span class="q" title={r.error || r.question}>{r.question}</span>
        <span class="st dim">{uiText(labels[r.status] ?? r.status)}</span>
        {#if r.status === "running"}
          <button class="btn ghost icon sm" aria-label={uiText("Остановить задачу")} title={uiText("Остановить")} onclick={() => api.assistantAction({ op: "task.stop", id: r.id }).catch(toastError)}><Square size={13} /></button>
        {:else if r.status === "done"}
          <button class="btn ghost icon sm" aria-label={uiText("Сохранить как сценарий")} title={uiText("Сохранить как сценарий — повторять без нейросети")} onclick={() => save(r.id)}><Save size={13} /></button>
        {/if}
      </li>
    {/each}
  </ul>
{/if}

<style>
  ul { list-style: none; margin: 4px 0 0; padding: 0; }
  li { display: flex; align-items: center; gap: 8px; padding: 4px 0; }
  .q { flex: 1; min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  .st { font-size: 12px; }
  .line { font-size: 13px; }
</style>
