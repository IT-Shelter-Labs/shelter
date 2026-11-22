<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  import { onMount } from "svelte";
  import { open } from "../lib/fileDialogs";
  import { Paperclip, Square, Plus, X, Clipboard, RotateCcw } from "@lucide/svelte";
  import { app, refreshAssistant, toastError } from "../lib/store.svelte";
  import { api, type RunDetail } from "../lib/api";
  let title = $state("");
  let content = $state("");
  let busy = $state(false);
  let detail = $state<RunDetail | null>(null);
  const labels: Record<string, string> = {queued: "В очереди", running: "Выполняю", done: "Завершено", failed: "Ошибка", cancelled: "Остановлено", interrupted: "Прервано при перезапуске"};
  const active = $derived(app.assistant?.runs.find(r => r.status === "running" || r.status === "queued"));
  const progress = $derived([...app.feed].reverse().find(e=>e.kind==="progress" && e.session_id===app.assistant?.session_id && e.time>(active?.created ?? Infinity))?.text);
  onMount(() => {
    refreshAssistant().catch(toastError);
    const timer = setInterval(() => refreshAssistant().catch(() => {}), 3000);
    return () => clearInterval(timer);
  });
  async function act(op: string, fields: Record<string, unknown> = {}) {
    busy = true;
    try { await api.assistantAction({op, ...fields}); await refreshAssistant(); }
    catch (e) { toastError(e); }
    finally { busy = false; }
  }
  async function attachFile() {
    const path = await open({multiple: false, filters: [{name: "Текст и исходный код", extensions: ["txt", "md", "csv", "json", "yaml", "yml", "py", "rs", "js", "ts", "html"]}]});
    if (typeof path === "string") await act("context.import", {path});
  }
</script>

<section class="assistant-panel card" aria-label={uiText("Текущий контекст и задачи")}>
  <div class="toolbar">
    <select aria-label={uiText("Текущий проект")} value={app.assistant?.project_id ?? ""} disabled={busy || !app.status} onchange={e => act("project.activate", {id: e.currentTarget.value})} title={uiText("Общий режим или отдельный проект со своими инструкциями и материалами")}>
      <option value="">{uiText("Общий режим")}</option>
      {#each app.assistant?.projects ?? [] as p}<option value={p.id}>{p.name}</option>{/each}
    </select>
    <select aria-label={uiText("Текущий разговор")} value={app.assistant?.session_id ?? ""} disabled={busy || !app.status} onchange={e => act("session.activate", {id: e.currentTarget.value})} title={uiText("Продолжить предыдущий разговор; голосовые просьбы относятся к нему же")}>
      {#each app.assistant?.sessions ?? [] as s}<option value={s.id}>{uiText(s.title)}</option>{/each}
    </select>
    <button class="btn ghost" disabled={busy || !app.status} onclick={() => act("session.new")} title={uiText("Начать разговор с чистой историей; постоянная память сохранится")}><Plus size={15}/>{uiText(" Новый")}</button>
    <button class="btn ghost" disabled={busy || !app.assistant} title={uiText("Удалить историю и материалы текущего разговора; постоянная память останется")} onclick={()=>{if(confirm(uiText("Удалить этот разговор, его историю задач и прикреплённые материалы? Постоянная память останется.")))act("session.delete",{id:app.assistant?.session_id});}}>{uiText("Удалить разговор")}</button>
    <button class="btn" disabled={!app.status} onclick={() => app.contextOpen = !app.contextOpen} title={uiText("Прикрепить материалы, которые Джарвис будет учитывать в этом разговоре")}><Paperclip size={15}/>{uiText(" Контекст")}</button>
  </div>
  {#if app.assistant?.context.length}
    <div class="attachments">
      {#each app.assistant.context as c}<span class="attachment" title={c.content.slice(0, 1000)}>{c.title}<button aria-label={uiText("Убрать " + c.title)} onclick={() => act("context.delete", {id: c.id})}><X size={12}/></button></span>{/each}
    </div>
  {/if}
  {#if app.contextOpen}
    <div class="context-editor">
      <p class="muted">{uiText("Добавьте текст или файл. Материалы учитываются в этом разговоре, пока вы их не уберёте. Быстрый вызов в Windows: Ctrl+Shift+Space.")}</p>
      <input aria-label={uiText("Название материала")} placeholder={uiText("Название материала")} maxlength="160" bind:value={title}/>
      <textarea aria-label={uiText("Текст контекста")} placeholder={uiText("Выделенный текст, заметка или описание текущей задачи…")} rows="4" maxlength="24000" bind:value={content}></textarea>
      <div class="toolbar">
        <button class="btn primary" disabled={busy || !content.trim()} onclick={async () => { await act("context.add", {title: title || "Мой текст", text: content}); content = ""; title = ""; }}>{uiText("Прикрепить текст")}</button>
        <button class="btn" disabled={busy} onclick={attachFile}><Paperclip size={14}/>{uiText(" Файл")}</button>
        <button class="btn" disabled={busy} onclick={() => act("context.clipboard")}><Clipboard size={14}/>{uiText(" Из буфера")}</button>
      </div>
    </div>
  {/if}
  {#if active || app.status?.speaking || app.status?.thinking}
    <div class="task-line"><span class="dot"></span><span>{active ? `${uiText(progress || labels[active.status])}: ${active.question.slice(0, 120)}` : uiText(app.status?.speaking ? "Говорю" : "Выполняю задачу из другого разговора")}</span><button class="btn ghost" onclick={() => act("task.stop")}><Square size={13}/>{uiText(" Остановить")}</button></div>
  {/if}
  {#if app.assistant?.runs.length}
    <details class="journal">
      <summary>{uiText("Последние задачи · ")}{uiText(app.assistant.runs.length)}</summary>
      {#each app.assistant.runs.slice(0, 8) as r}
        <div class="task-line">
          <button class="task-title" onclick={async () => { try { detail = await api.assistantAction<RunDetail>({op: "task.detail", id: r.id}); } catch(e) { toastError(e); } }}>{r.question.slice(0, 130)}</button>
          <span class:failed={r.status === "failed"}>{uiText(labels[r.status] ?? r.status)}</span>
          {#if ["failed", "cancelled", "interrupted"].includes(r.status)}<button class="btn ghost" disabled={busy} onclick={() => act("task.resume", {id: r.id})} title={uiText("Передать Джарвису прежнюю просьбу и журнал шагов. Состояние нужно проверить перед повторением изменений")}><RotateCcw size={13}/>{uiText(" Продолжить")}</button>{/if}
        </div>
      {/each}
    </details>
  {/if}
  {#if detail}
    <div class="run-detail">
      <div class="toolbar"><b>{uiText(labels[detail.status] ?? detail.status)}</b><button class="btn ghost" onclick={() => detail = null}>{uiText("Закрыть")}</button></div>
      <p>{detail.question}</p>
      {#each detail.steps as s}<div class="step"><b>{s.name} · {uiText(s.outcome)}</b><p>{s.argument}</p><p class="muted">{s.result}</p></div>{/each}
      {#if detail.error}<p class="failed">{uiText(detail.error)}</p>{/if}
      {#if detail.result}<p>{detail.result}</p>{/if}
    </div>
  {/if}
</section>

<style>
  .assistant-panel { margin: 14px 0; padding: 14px 18px; }
  .toolbar,.attachments { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
  select { max-width:250px; min-width:140px; }
  .attachments { margin-top:10px; }
  .attachment { display:inline-flex; align-items:center; gap:6px; border:1px solid var(--line-2); padding:5px 8px; border-radius:8px; font-size:12px; }
  .attachment button { border:0; background:none; color:var(--text-2); cursor:pointer; }
  .context-editor,.journal,.run-detail { margin-top:12px; border-top:1px solid var(--line); padding-top:12px; }
  .context-editor input,.context-editor textarea { width:100%; margin-bottom:8px; }
  .task-line { display:flex; align-items:center; gap:10px; margin-top:10px; font-size:12px; }
  .task-line>span:nth-child(2),.task-title { flex:1; }
  .task-title { border:0; background:none; color:var(--text); text-align:left; cursor:pointer; font:inherit; }
  summary { cursor:pointer; color:var(--text-2); font-size:12px; }
  .step { padding:10px; margin:8px 0; border:1px solid var(--line); border-radius:8px; white-space:pre-wrap; overflow-wrap:anywhere; }
  .run-detail p { white-space:pre-wrap; overflow-wrap:anywhere; }
  .failed { color:var(--bad); }
</style>
