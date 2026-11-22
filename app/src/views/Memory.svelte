<script lang="ts">
  import { t as uiText, locale } from "../lib/i18n.svelte";

  import { onMount } from "svelte";
  import { open, save as saveDialog } from "../lib/fileDialogs";
  import { app, get, set, refreshAssistant, toast, toastError } from "../lib/store.svelte";
  import { api, on, type SetupEvent } from "../lib/api";
  import Setting from "../components/Setting.svelte";
  import Toggle from '../components/Toggle.svelte';
  let query = $state("");
  let text = $state("");
  let editId = $state<string | null>(null);
  let scope = $state("");
  let name = $state("");
  let instructions = $state("");
  let projectEdit = $state<string | null>(null);
  let busy = $state(false);
  let indexing = $state(false);
  let indexResult = $state('');
  let downloading = $state(false);
  let downloadNote = $state("");
  let downloadProgress = $state(0);
  const diagnostic = $derived(app.assistant?.context_diagnostic);
  const sourceKinds:Record<string,string>={memory:'Факт памяти',attachment:'Прикреплённый материал',tool:'Результат действия',document:'Документ',episode:'Выдержка переписки'};
  const sourceNames:Record<string,string>={user:'По вашей просьбе',settings:'Из настроек','execution ledger':'Журнал действий','current conversation':'Этот разговор'};
  const visible = $derived(app.assistant?.memories ?? []);
  let searchTimer: ReturnType<typeof setTimeout> | undefined;
  onMount(() => {
    refreshAssistant().catch(toastError);
    let disposed=false;let unlisten:(()=>void)|undefined;
    on<SetupEvent>('setup:event',e=>{
      if (!downloading) return;
      if (e.status === "finished" && !e.ok) {
        downloading = false;
        if (!downloadNote) downloadNote = "Не удалось установить модель поиска. Попробуйте ещё раз.";
      }
      if(e.component!=='model:embeddinggemma' && !(e.component === "ollama" && e.status === "error"))return;
      if(e.total){downloadNote="";downloadProgress=Math.round(100*(e.done??0)/e.total);}
      if(e.stage==='retry')downloadNote=e.text??"";
      if(e.status==='ok'){downloading=false;downloadNote="";toast('Модель поиска готова. Обновите смысловой индекс.','success');}
      if(e.status==='error'){downloading=false;downloadNote=e.message??"";toastError(e.message);}
    }).then(f=>{if(disposed)f();else unlisten=f;}).catch(toastError);
    return ()=>{disposed=true;unlisten?.();clearTimeout(searchTimer);};
  });
  function search() {
    clearTimeout(searchTimer); const requested=query;
    searchTimer=setTimeout(async()=>{try{const result=await api.assistant(requested);if(query===requested)app.assistant=result;}catch(e){toastError(e);}},300);
  }
  async function act(op: string, data: Record<string, unknown> = {}) {
    busy = true;
    try { await api.assistantAction({op, ...data}); await refreshAssistant(); return true; }
    catch(e) { toastError(e); return false; }
    finally { busy = false; }
  }
  async function pick(instructions = false) {
    const path = await open({multiple: false, filters: [{name: instructions ? "JARVIS.md" : "Материалы проекта", extensions: instructions ? ["md"] : ["md", "txt", "csv", "json", "yaml", "py", "rs", "js", "ts"]}]});
    if (typeof path === "string" && await act("context.import", {path, project_id: app.assistant?.project_id, instructions})) toast("Файл добавлен", "success");
  }
  async function indexMemory() {
    indexing=true;
    try {
      const r=await api.assistantAction<{ok:boolean;indexed?:number;error?:string;status?:string}>({op:'memory.index'});
      indexResult=r.ok ? (r.status==='already_running' ? 'Индексация уже идёт.' : `Обновлено записей: ${r.indexed ?? 0}`) : r.error ?? 'Не удалось обновить индекс';
      await refreshAssistant();
    }catch(e){toastError(e);}finally{indexing=false;}
  }
  async function downloadSearchModel() {
    downloading=true;downloadProgress=0;downloadNote="";
    try {
      const installed=await api.setupCheck();
      await api.setupInstall([...(installed.ollama?.ok ? [] : ['ollama']),'model:embeddinggemma']);
    }catch(e){downloading=false;toastError(e);}
  }
  async function exportMemory() {
    const path = await saveDialog({ defaultPath: "память-джарвиса.json", filters: [{ name: "Память Джарвиса", extensions: ["json"] }] });
    if (!path) return;
    try {
      const r = await api.assistantAction<{ count: number }>({ op: "memory.export", path });
      toast(`Сохранено фактов: ${r.count}. Переписка и ключи в файл не входят`, "success");
    } catch (e) { toastError(e); }
  }
</script>

<h1>{uiText("Память и проекты")}</h1>
<p class="muted">{uiText("Джарвис запоминает по вашей просьбе. Здесь можно проверить, исправить и удалить факты, задать рабочие инструкции и выбрать материалы.")}</p>
{#if !app.status}<div class="card muted">{uiText("Включите ядро, чтобы управлять памятью.")}</div>{:else}
<section class="card">
  <div class="caps">{uiText("Как используется контекст")}</div>
  <Setting title={uiText("Поиск фактов по смыслу")} hint={uiText("Использует небольшую локальную модель EmbeddingGemma через Ollama на процессоре. В облако ничего не отправляется при адресе по умолчанию. Если модель недоступна, остаётся поиск по словам.")}><Toggle checked={get('llm.memory.semantic',false)} onchange={v=>set('llm.memory.semantic',v)}/></Setting>
  <div class="buttons"><button class="btn" disabled={indexing} onclick={indexMemory}>{uiText(indexing ? 'Обновляю…' : 'Обновить смысловой индекс')}</button><button class="btn ghost" disabled={downloading} onclick={downloadSearchModel}>{uiText(downloading ? `Загрузка модели · ${downloadProgress}%` : 'Скачать модель поиска · 622 МБ')}</button><span class="dim">{uiText("Записей в индексе: ")}{uiText(app.assistant?.indexed_memories ?? 0)}</span></div>
  {#if downloadNote}<p class="dim" role="status">{uiText(downloadNote)}</p>{/if}
  {#if indexResult}<p class="dim" role="status">{uiText(indexResult)}</p>{/if}
  <p class="dim">{uiText("Удаление факта удаляет и его поисковый вектор. Исходная переписка сохраняется отдельно: чтобы убрать сведения из неё, удалите соответствующий разговор.")}</p>
  {#if diagnostic}
    <details class="diagnostic"><summary>{uiText("Что использовано в последнем запросе")}</summary>
      <div class="stats"><span><b>{uiText(diagnostic.model)}</b><small>{uiText("Модель · ")}{uiText(diagnostic.route==='task' ? 'сложная задача' : 'разговор')}</small></span>
        <span><b>{uiText(diagnostic.actual_prompt_tokens ?? diagnostic.input_tokens_estimate)} / {uiText(diagnostic.context_limit)}</b><small>{uiText(diagnostic.actual_prompt_tokens===undefined ? 'Оценка токенов входа' : 'Токены входа по данным сервера')}</small></span>
        <span><b>{uiText(diagnostic.recent_messages)} / {uiText(diagnostic.available_messages)}</b><small>{uiText("Сообщений истории в запросе")}</small></span></div>
      {#if diagnostic.shortened_exchanges||diagnostic.materials_shortened}<p class="dim">{uiText("Часть материала сокращена под окно модели. Оригиналы сохранены.")}</p>{/if}
      {#if !diagnostic.share_context}<p class="dim">{uiText("Память и материалы выключены для этого подключения.")}</p>{/if}
      {#each diagnostic.sources as source}<div class="source"><b>{uiText(source.title)}</b><small class="dim">{uiText(sourceKinds[source.kind]??source.kind)} · {uiText(sourceNames[source.source]??source.source)} · #{uiText(source.id)}{uiText(source.shortened ? ' · сокращено' : '')}</small></div>{:else}<p class="dim">{uiText("Дополнительные источники не использованы.")}</p>{/each}
    </details>
  {:else}<p class="dim">{uiText("После следующего ответа здесь появится состав запроса: история, источники и размер контекста.")}</p>{/if}
</section>
<section class="card">
  <div class="caps">{uiText("Постоянная память")}</div>
  <Setting title={uiText("Что Джарвис помнит")} hint={uiText("Личные факты доступны во всех проектах. Факты проекта учитываются только внутри него.")} wide>
    <input type="text" aria-label={uiText("Поиск в памяти")} placeholder={uiText("Найти воспоминание…")} bind:value={query} oninput={search}/>
  </Setting>
  <p class="dim">{uiText("Показано ")}{uiText(visible.length)}{uiText(" из ")}{uiText(app.assistant?.memory_total ?? 0)} · <button class="link" onclick={exportMemory}>{uiText("Экспорт в файл")}</button></p>
  {#each visible as m}
    <article class="memory">
      <div><p>{m.text}</p><small class="dim">{uiText(m.project_id ? "Проект" : "Обо мне")} · {uiText(m.source)} · {uiText(new Date(m.updated * 1000).toLocaleDateString((locale.language === "ru" ? "ru-RU" : "en-US")))}</small></div>
      <button class="btn ghost" disabled={busy} onclick={() => { text = m.text; editId = m.id; scope = m.project_id; }}>{uiText("Изменить")}</button>
      <button class="btn ghost" disabled={busy} onclick={() => act("memory.delete", {id:m.id})}>{uiText("Забыть")}</button>
    </article>
  {:else}<p class="dim">{uiText("Пока ничего не найдено. Скажите: «Джарвис, запомни…».")}</p>{/each}
  <div class="editor">
    <textarea aria-label={uiText("Текст воспоминания")} rows="2" maxlength="2000" placeholder={uiText("Например: я предпочитаю короткие ответы")} bind:value={text}></textarea>
    <div class="buttons">
      <select aria-label={uiText("Область памяти")} bind:value={scope}><option value="">{uiText("Обо мне, для всех проектов")}</option>{#if app.assistant?.project_id}<option value={app.assistant.project_id}>{uiText("Только текущий проект")}</option>{/if}</select>
      <button class="btn primary" disabled={busy || !text.trim()} onclick={async () => { if(await act("memory.save", {id:editId, text, project_id:scope})) { text=""; editId=null; } }}>{uiText(editId ? "Сохранить" : "Запомнить")}</button>
      {#if editId}<button class="btn ghost" onclick={() => { editId=null; text=""; }}>{uiText("Отмена")}</button>{/if}
    </div>
  </div>
</section>
<section class="card">
  <div class="caps">{uiText("Рабочий контекст")}</div>
  <Setting title={uiText("Текущий проект")} hint={uiText("Голосовые запросы и новые разговоры относятся к выбранному проекту. Общий режим не использует материалы других проектов.")}>
    <select aria-label={uiText("Текущий проект")} value={app.assistant?.project_id ?? ""} onchange={e => act("project.activate", {id:e.currentTarget.value})}><option value="">{uiText("Общий режим")}</option>{#each app.assistant?.projects ?? [] as p}<option value={p.id}>{p.name}</option>{/each}</select>
  </Setting>
  <div class="buttons">
    <button class="btn" onclick={() => { name=""; instructions=""; projectEdit=null; }}>{uiText("Новый проект")}</button>
    {#if app.assistant?.project_id}<button class="btn" onclick={() => { const p=app.assistant?.projects.find(p => p.id===app.assistant?.project_id); if(p) {name=p.name;instructions=p.instructions;projectEdit=p.id;} }}>{uiText("Изменить текущий")}</button><button class="btn ghost" onclick={()=>{if(confirm(uiText("Удалить проект, его разговоры, задачи и память? Личные факты и исходные файлы сохранятся.")))act("project.delete",{id:app.assistant?.project_id});}}>{uiText("Удалить проект")}</button>{/if}
  </div>
  <div class="editor">
    <input type="text" aria-label={uiText("Название проекта")} placeholder={uiText("Название проекта")} maxlength="120" bind:value={name}/>
    <textarea aria-label={uiText("Инструкции проекта")} rows="4" maxlength="8000" placeholder={uiText("Как помогать в этом проекте: цели, предпочтения, ограничения…")} bind:value={instructions}></textarea>
    <button class="btn primary" disabled={busy || !name.trim()} onclick={async () => {if(await act("project.save", {id:projectEdit,name,instructions})) {name="";instructions="";projectEdit=null;toast("Проект сохранён", "success");}}}>{uiText("Сохранить проект")}</button>
  </div>
  {#if app.assistant?.project_id}
    <Setting title={uiText("Материалы проекта")} hint={uiText("Выберите конкретные текстовые файлы. Джарвис найдёт подходящие фрагменты; весь диск автоматически не индексируется.")} wide>
      <div class="buttons"><button class="btn" onclick={() => pick()}>{uiText("Добавить файл")}</button><button class="btn" onclick={() => pick(true)}>{uiText("Загрузить инструкции JARVIS.md")}</button></div>
    </Setting>
    {#each app.assistant.documents as d}<div class="memory"><div><b>{uiText(d.title)}</b><small class="dim">{uiText(d.source)}</small></div><button class="btn ghost" onclick={() => act("document.delete", {id:d.id})}>{uiText("Убрать")}</button></div>{/each}
  {/if}
</section>
{/if}

<style>
  .card { margin:16px 0; }
  .memory { display:flex; align-items:center; gap:8px; padding:12px 0; border-bottom:1px solid var(--line); }
  .memory>div { flex:1; min-width:0; }
  .memory p { margin:0 0 4px; white-space:pre-wrap; overflow-wrap:anywhere; }
  small { display:block; overflow-wrap:anywhere; }
  .editor { display:flex; flex-direction:column; gap:10px; margin-top:16px; }
  .editor input,.editor textarea { width:100%; }
  .buttons { display:flex; flex-wrap:wrap; align-items:center; gap:8px; }
  .diagnostic {margin-top:16px;border:1px solid var(--line);border-radius:12px;padding:14px;}
  summary {cursor:pointer;font-weight:600;}
  .stats {display:flex;gap:24px;flex-wrap:wrap;padding:16px 0;}
  .stats small {margin-top:5px;color:var(--muted);}
  .source {padding:10px 0;border-top:1px solid var(--line);overflow-wrap:anywhere;}
</style>
