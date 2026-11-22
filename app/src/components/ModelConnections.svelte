<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  import { onMount } from 'svelte';
  import { api } from '../lib/api';
  import { get, set, toast, toastError } from '../lib/store.svelte';
  import Setting from './Setting.svelte';
  import Toggle from './Toggle.svelte';
  import builtinModels from '../lib/builtinModels.json';

  type Connection = {name:string; provider:string; url:string; model:string; context:number;
    api_key?:string; api_key_env?:string; share_context?:boolean; think?:boolean; preset?:string; workspace_id?:string; max_tokens?:number};
  type Preset = {name:string;provider:string;url:string;local:boolean};
  let { models, pulling, modelStatusKnown, pull }: {
    models: string[]; pulling: { name: string; pct: number } | null; modelStatusKnown: boolean; pull: (name: string) => void;
  } = $props();
  let presets = $state<Record<string,Preset>>({});
  let selected = $state("");
  let editing = $state<string | null>(null);
  let draft = $state<Connection>({name:'',provider:'ollama',url:'',model:'',context:8192});
  let modelList = $state<string[]>([]);
  let checking = $state(false);
  let result = $state('');
  const connections = $derived(get<Record<string,Connection>>('llm.connections',{}) ?? {});
  const selectable = $derived({ ...connections, ...builtinModels });
  const routes = $derived(get<Record<string,string>>('llm.routes',{}) ?? {});
  const roles = [{id:'conversation',name:'Разговор и повседневные просьбы',hint:'Быстрая модель для голосового общения.'},
    {id:'task',name:'Сложные задачи и материалы',hint:'Подробные разборы, длинные запросы и прикреплённые файлы.'},
    {id:'vision',name:'Зрение и снимки экрана',hint:'Модель с поддержкой изображений. Получает только запрошенный снимок и текущий вопрос, без памяти и файлов проекта. Облачное подключение будет получать эти снимки.'}];

  onMount(()=>{api.assistantAction<{presets:Record<string,Preset>}>({op:'llm.catalog'})
    .then(r=>presets=r.presets).catch(()=>{});});
  function start(preset:string) {
    const p=presets[preset]; if(!p)return;
    editing='';modelList=[];result='';
    draft={name:p.name,provider:p.provider,url:p.url,model:'',context:8192,share_context:p.local,preset};
  }
  function edit(id:string) {draft={...connections[id]};editing=id;modelList=[];result='';}
  function credentialMismatch() {
    const saved = editing ? connections[editing] : undefined;
    if (!saved) return false;
    try {
      return new URL(saved.url).origin !== new URL(draft.url).origin &&
        (!!saved.api_key && draft.api_key === saved.api_key || !!saved.api_key_env && draft.api_key_env === saved.api_key_env);
    } catch { return false; }
  }
  function save() {
    if(!draft.name.trim()||!draft.model.trim()||!/^https?:\/\//.test(draft.url)||!Number.isInteger(draft.context)||draft.context<2048||draft.context>262144) {
      toastError('Укажите название, адрес HTTP/HTTPS, модель и контекст от 2048 до 262144.');return;
    }
    try {const u=new URL(draft.url);if(u.username||u.password||u.search||u.hash)throw Error();}
    catch {toastError('Адрес сервера должен быть без ключа, пароля и параметров в URL.');return;}
    if (credentialMismatch()) { toastError("Для нового сервера укажите отдельный ключ API."); return; }
    if(draft.max_tokens!==undefined&&(!Number.isInteger(draft.max_tokens)||draft.max_tokens<1||draft.max_tokens>Math.min(16384,draft.context-512))) {toastError('Уменьшите лимит ответа: он должен оставлять место для запроса.');return;}
    const id=editing || 'model_'+crypto.randomUUID().slice(0,8);
    set('llm.connections',{...connections,[id]:{...draft,name:draft.name.trim(),model:draft.model.trim(),url:draft.url.trim()}});
    if(!Object.keys(routes).length)set('llm.routes',{conversation:id,task:id});
    editing=null;toast('Подключение сохранено. Примените настройки для ядра.','success');
  }
  function remove(id:string) {
    if (Object.hasOwn(builtinModels, id)) return;
    const next={...connections};delete next[id];
    // Clear routes first: no saved route may reference a deleted connection.
    set('llm.routes',Object.fromEntries(Object.entries(routes).filter(([,value])=>value!==id)));
    set('llm.connections',next);
  }
  async function probe() {
    if (credentialMismatch()) { toastError("Для нового сервера укажите отдельный ключ API."); return; }
    checking=true;result='';
    try {
      const r=await api.assistantAction<{ok:boolean;models:string[];error?:string}>({op:'llm.probe',connection:{...draft}});
      modelList=r.models;result=r.ok ? `Сервер доступен · моделей: ${r.models.length}. Генерация пока не проверялась.` : r.error ?? 'Сервер недоступен';
    }catch(e){result=String(e);}finally{checking=false;}
  }
  function importCurrent() {
    draft={name:'Моя текущая модель',provider:get('llm.provider','ollama'),url:get('llm.url','http://127.0.0.1:11434'),
      model:get('llm.model','gemma4:e4b'),context:get('llm.context',8192),api_key_env:get('llm.api_key_env',''),share_context:true};
    editing='';modelList=[];result='';
  }
</script>

<section class="card connections">
  <div class="caps">{uiText("Подключения моделей")}</div>
  <p class="muted intro">{uiText("Несколько локальных и облачных моделей — с отдельным назначением. При сбое Джарвис не отправляет разговор другому провайдеру автоматически.")}</p>
  <Setting title={uiText("Разбирать команды ввода до ответа")} hint={uiText("Если короткое правило не сработало, выбранная разговорная модель сначала проверит смысл просьбы к мыши, клавиатуре или полю ввода. Это дополнительный короткий запрос; облако может брать за него плату. При отключении действие выбирает основной диалог.")}>
    <Toggle checked={get('llm.semantic_input',true)} onchange={v=>set('llm.semantic_input',v)}/>
  </Setting>
  <Setting title={uiText("Собирать цепочки по смыслу")} hint={uiText("Модель разбирает незнакомые формулировки в просьбах к программам, окнам, звуку и таймерам. Она получает только текущие фразы, без истории и экрана. Простые цепочки работают и без модели.")}>
    <Toggle checked={get('llm.action_plans',true)} onchange={v=>set('llm.action_plans',v)}/>
  </Setting>
  <div class="connection-list">
    {#each Object.entries(builtinModels) as [id,c] (id)}
      <article class="connection">
        <div><b>{c.name}</b><span class="mono dim">{c.model}</span>
          <small class="dim">{uiText("Встроенный локальный вариант")} · {uiText(models.includes(c.model) ? "Скачана" : modelStatusKnown ? "Нужно скачать" : "Проверяю наличие")}</small>
        </div>
        {#if pulling?.name === c.model}
          <span role="status">{uiText("Скачиваю")} · {pulling.pct}%</span>
        {:else if !models.includes(c.model)}
          <button class="btn" disabled={!!pulling || !modelStatusKnown} onclick={() => pull(c.model)}>{uiText("Скачать модель")}</button>
        {:else if routes.conversation !== id}
          <button class="btn" onclick={() => set('llm.routes', {...routes, conversation: id})}>{uiText("Выбрать для разговора")}</button>
        {/if}
      </article>
    {/each}
    {#each Object.entries(connections).filter(([id]) => !Object.hasOwn(builtinModels, id)) as [id,c] (id)}
      <article class="connection">
        <div><b>{c.name}</b><span class="mono dim">{uiText(c.model)}</span><small class="dim">{uiText(c.share_context ? 'С памятью и материалами' : 'Только текущий разговор')}</small></div>
        <button class="btn" onclick={()=>edit(id)} aria-label={uiText(`Изменить подключение ${c.name}`)}>{uiText("Настроить")}</button>
        <button class="btn ghost" onclick={()=>remove(id)} aria-label={uiText(`Удалить подключение ${c.name}`)}>{uiText("Убрать")}</button>
      </article>
    {:else}<button class="btn" onclick={importCurrent}>{uiText("Сохранить текущее подключение")}</button>{/each}
  </div>
    {#each roles as role}
      <Setting title={uiText(role.name)} hint={uiText(role.hint)}>
        <select aria-label={uiText(role.name)} value={routes[role.id] ?? ''} onchange={e=>set('llm.routes',{...routes,[role.id]:e.currentTarget.value})}>
          <option value="">{uiText(role.id==='vision' ? 'Текущая модель разговора или задачи' : role.id==='task' ? 'Как для разговора' : 'Основная модель из настроек ниже')}</option>
          {#each Object.entries(selectable) as [id,c]}<option value={id}>{c.name} · {c.model}</option>{/each}
        </select>
      </Setting>
    {/each}
  {#if Object.keys(presets).length}
    <Setting title={uiText("Добавить провайдера")} hint={uiText("Выберите сервис. Джарвис подставит адрес и протокол. Затем введите ключ и выберите модель.")}>
      <div class="providers">
        <select aria-label={uiText("Провайдер модели")} bind:value={selected} disabled={checking || editing !== null}>
          <option value="">{uiText("Выберите провайдера")}</option>
          <optgroup label={uiText("Облачные сервисы")}>
            {#each Object.entries(presets).filter(([id, p]) => !p.local && id !== "custom") as [id,p]}
              <option value={id}>{p.name}</option>
            {/each}
          </optgroup>
          <optgroup label={uiText("Локальные серверы")}>
            {#each Object.entries(presets).filter(([, p]) => p.local) as [id,p]}
              <option value={id}>{p.name}</option>
            {/each}
          </optgroup>
          {#if presets.custom}<option value="custom">{uiText("Свой сервер с OpenAI-совместимым API")}</option>{/if}
        </select>
        <button class="btn" disabled={!selected || editing !== null || checking} onclick={() => { start(selected); selected = ""; }}>{uiText("Добавить")}</button>
      </div>
    </Setting>
  {:else}
    <p class="dim">{uiText("Запустите ядро, чтобы добавить провайдера.")}</p>
  {/if}
  {#if editing!==null}
    <div class="connection-editor">
      <h3>{uiText(editing ? 'Настройка подключения' : 'Новое подключение')}</h3>
      {#if draft.preset === "alibaba"}
        <p class="dim">{uiText("По умолчанию выбран Сингапур. Используйте адрес и ключ из одной рабочей области Alibaba. Для Qwen Audio TTS нужен адрес вашей рабочей области.")}</p>
      {/if}
      <Setting title={uiText("Название")} hint={uiText("Любое понятное название: например, «Быстрая локальная» или «Облако для работы».")}><input type="text" aria-label={uiText("Название подключения")} bind:value={draft.name}/></Setting>
      <Setting title={uiText("Протокол")} hint={uiText("Ollama — локальный сервер. Совместимый API — OpenAI, OpenRouter, DeepSeek, LM Studio и llama.cpp. Anthropic использует свой формат.")}>
        <select aria-label={uiText("Протокол подключения")} bind:value={draft.provider}><option value="ollama">Ollama</option><option value="openai">{uiText("Совместимый API")}</option><option value="anthropic">Anthropic</option></select>
      </Setting>
      <Setting title={uiText("Адрес сервера")} hint={uiText("Базовый адрес API. Для облака используйте HTTPS. Можно также вставить полный адрес chat/completions.")}><input type="text" aria-label={uiText("Адрес подключения")} bind:value={draft.url}/></Setting>
      {#if draft.provider!=='ollama'}
        <Setting title={uiText("Ключ API")} hint={uiText("Ключ хранится на устройстве. В Windows он защищается средствами учётной записи; в запросы к другим подключениям не передаётся.")}><input type="password" autocomplete="new-password" aria-label={uiText("Ключ API подключения")} bind:value={draft.api_key}/></Setting>
        <Setting title={uiText("Или переменная с ключом")} hint={uiText("Необязательно: имя переменной окружения вместо хранения ключа в настройках. Введённый выше ключ имеет приоритет.")}><input type="text" aria-label={uiText("Переменная с ключом")} bind:value={draft.api_key_env}/></Setting>
        {#if draft.provider==='anthropic'}<Setting title={uiText("Рабочее пространство Anthropic")} hint={uiText("Необязательно для ключа одного пространства. Для общего ключа укажите workspace ID из консоли Anthropic.")}><input type="text" aria-label={uiText("Рабочее пространство Anthropic")} bind:value={draft.workspace_id} placeholder="wrkspc_…"/></Setting>{/if}
      {/if}
      <div class="buttons"><button class="btn" disabled={checking||!draft.url.trim()} onclick={probe}>{uiText(checking ? 'Проверяю…' : 'Проверить и получить модели')}</button><small class="dim">{uiText("Без отправки переписки и генерации ответа.")}</small></div>
      {#if result}<p class="probe-result" role="status">{uiText(result)}</p>{/if}
      <Setting title={uiText("Модель")} hint={uiText("Точное имя из списка сервера. Если список не загружается, имя можно ввести вручную.")}><input type="text" aria-label={uiText("Модель подключения")} list="connection-models" bind:value={draft.model}/><datalist id="connection-models">{#each modelList as model}<option value={model}></option>{/each}</datalist></Setting>
      <Setting title={uiText("Окно контекста")} hint={uiText("Рабочий лимит входа и ответа. Значение должно поддерживаться моделью и сервером. Большое окно требует больше памяти и дольше обрабатывается.")}><input aria-label={uiText("Контекст подключения")} type="number" min="2048" max="262144" step="1024" bind:value={draft.context}/></Setting>
      <Setting title={uiText("Лимит ответа")} hint={uiText("Максимум токенов генерации за один проход. В облачных моделях с размышлением сюда может входить и внутреннее рассуждение. Пусто — общий лимит; большой ответ занимает больше времени и может стоить дороже.")}><input aria-label={uiText("Лимит ответа подключения")} type="number" min="1" max={Math.min(16384,draft.context-512)} bind:value={draft.max_tokens} placeholder={uiText("Автоматически")}/></Setting>
      <Setting title={uiText("Память и материалы проекта")} hint={uiText("Передавать этому подключению сохранённые факты, инструкции проекта и файлы. Сам запрос и недавняя переписка отправляются всегда, когда выбрано это подключение.")}><Toggle checked={draft.share_context ?? false} onchange={v=>draft.share_context=v}/></Setting>
      <div class="buttons"><button class="btn primary" onclick={save}>{uiText("Сохранить подключение")}</button><button class="btn ghost" onclick={()=>editing=null}>{uiText("Отмена")}</button></div>
    </div>
  {/if}
</section>

<style>
  .intro {max-width:760px;line-height:1.6;margin:10px 0 18px;}
  .connection-list {display:grid;gap:10px;}
  .connection {display:flex;align-items:center;gap:8px;border:1px solid var(--line);border-radius:12px;padding:14px;flex-wrap:wrap;}
  .connection>div {flex:1;min-width:180px;overflow-wrap:anywhere;}
  .connection span,.connection small {display:block;margin-top:5px;}
  .providers,.buttons {display:flex;flex-wrap:wrap;align-items:center;gap:8px;}
  .buttons {margin:16px 0;}
  .providers select {width:min(255px, 100%);}
  .connection-editor {border:1px solid var(--line);border-radius:14px;padding:18px;margin-top:20px;}
  .connection-editor h3 {margin:0 0 10px;}
  input,select {max-width:100%;width:310px;}
  .probe-result {font-size:13px;overflow-wrap:anywhere;padding:10px;border-left:2px solid var(--accent);}
</style>
