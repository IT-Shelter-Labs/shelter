<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  import { onMount, onDestroy } from "svelte";
  import { Download } from "@lucide/svelte";
  import Setting from "../components/Setting.svelte";
  import Toggle from "../components/Toggle.svelte";
  import Segmented from "../components/Segmented.svelte";
  import ModelConnections from '../components/ModelConnections.svelte';
  import CloudMedia from "../components/CloudMedia.svelte";
  import { app, get, set, toast, toastError } from "../lib/store.svelte";
  import { api, on, type SetupEvent } from "../lib/api";

  let models = $state<string[]>([]);
  let ollama = $state<{ ok: boolean; running: boolean } | null>(null);
  let pulling = $state<{ name: string; pct: number } | null>(null);
  let modelStatusKnown = $state(false);
  let unlisten: (() => void) | undefined;
  let destroyed = false;

  const suggested = ["qwen3.5:4b", "qwen3.5:9b"];
  const defaultsOpen = !Object.keys(get('llm.connections',{}) ?? {}).length;

  onMount(async () => {
    const check = await api.setupCheck().catch(() => ({}) as any);
    ollama = check.ollama ?? null;
    models = check.ollama?.models ?? [];
    const unsubscribe = await on<SetupEvent>("setup:event", (e) => {
      if (!pulling) return;
      if (e.component === "ollama" && e.status === "error") { toastError(e.message); pulling = null; return; }
      if (e.status === "finished") { pulling = null; return; }
      if (e.component !== `model:${pulling.name}`) return;
      if (e.stage === "download" && e.total) pulling.pct = Math.round(((e.done ?? 0) / e.total) * 100);
      if (e.status === "ok") {
        toast(`Модель ${pulling.name} скачана`, "success");
        models = [...models, pulling.name];
        pulling = null;
      } else if (e.status === "error") {
        toastError(e.message);
        pulling = null;
      }
    });
    if (destroyed) { unsubscribe(); return; }
    unlisten = unsubscribe;
    modelStatusKnown = true;
  });
  onDestroy(() => { destroyed = true; unlisten?.(); });

  function pull(name: string) {
    if (pulling) return;
    pulling = { name, pct: 0 };
    api.setupInstall([...(ollama?.ok ? [] : ["ollama"]), `model:${name}`]).catch(error => { pulling = null; toastError(error); });
  }

  const tools = [
    { id: "app", title: "Программы, игры и сайты", hint: "«Открой Firefox», «запусти ведьмака», «открой ютуб»" },
    { id: "pc", title: "Управление компьютером", hint: "Окна, громкость, настройки Windows, выключение, Discord, буфер обмена" },
    { id: "weather", title: "Погода", hint: "«Какая погода», «нужен ли завтра зонт в Питере»" },
    { id: "search", title: "Поиск в интернете", hint: "Новости, курсы, цены, счёт матчей — с ответом по найденному" },
    { id: "timer", title: "Таймеры и напоминания", hint: "В том числе повторяющиеся и утренняя сводка" },
    { id: "memory", title: "Память", hint: "«Запомни…», «что ты обо мне знаешь», «забудь…»" },
    { id: "media", title: "Что играет", hint: "Трек или видео в любом плеере" },
    { id: "screen", title: "Что на экране", hint: "«Прочитай», «переведи», «что за ошибка», «что это за игра» — смотрит на активное окно" },
    { id: "obs", title: "OBS", hint: "«Сохрани момент», «начни запись»" },
    { id: "home", title: "Умный дом", hint: "Настраивается в «Возможностях»" },
  ];
  const enabled = $derived(get<string[]>("llm.tools", []) ?? []);
  function toggleTool(id: string, on: boolean) {
    set("llm.tools", on ? [...new Set([...enabled, id])] : enabled.filter((t) => t !== id));
  }
  function numberSetting(input:HTMLInputElement,path:string,min:number,max:number) {
    const value=input.valueAsNumber;
    if(!Number.isFinite(value)||value<min||value>max){toastError(`Введите число от ${min} до ${max}`);return;}
    set(path,Math.round(value));
  }
</script>

<h1>{uiText("Разум")}</h1>
<p class="lead">{uiText("Как Джарвис понимает просьбы и выполняет задачи. Быстрые команды работают без нейросети; для сложных можно выбрать локальную модель или свой сервер.")}</p>

<ModelConnections {models} {pulling} {modelStatusKnown} {pull} />
<CloudMedia mode="image" />

<div class="card">
  <div class="caps">{uiText("Нагрузка и задачи")}</div>
  <Setting title={uiText("Режим работы")} hint={uiText("Меняет распознавание и число шагов. Выбранный голос сохраняется. Размер контекста задаётся отдельно у каждого подключения; модели не скачиваются автоматически.")}>
    <Segmented value={get("performance.profile", "balanced")} options={[{value:"light",label:"Лёгкий"},{value:"balanced",label:"Баланс"},{value:"quality",label:"Качество"}]} onchange={v=>{set("performance.profile",v);set("asr.engine",v==="light"?"vosk":"gigaam");set("llm.agent.max_steps",v==="light"?3:6);}}/>
  </Setting>
  <Setting title={uiText("Выполнение составных просьб")} hint={uiText("Авто использует структурированные вызовы инструментов, если сервер их поддерживает. Совместимый режим сохраняет прежнюю маршрутизацию для небольших моделей.")}>
    <select value={get("llm.agent.protocol","auto")} onchange={e=>set("llm.agent.protocol",e.currentTarget.value)}><option value="auto">{uiText("Автоматически")}</option><option value="native">{uiText("Структурированные инструменты")}</option><option value="tags">{uiText("Совместимый режим")}</option></select>
  </Setting>
  {#if !Object.keys(get('llm.connections',{}) ?? {}).length}<Setting title={uiText("Модель для сложных задач")} hint={uiText("Необязательно. Используется для длинных просьб и работы с прикреплёнными материалами на том же сервере. Пусто — основная модель.")}>
    <input placeholder={uiText("Например, установленная модель Ollama")} value={get("llm.agent.model","")} onchange={e=>set("llm.agent.model",e.currentTarget.value.trim())}/>
  </Setting>{/if}
  <Setting title={uiText("Максимум шагов")} hint={uiText("Ограничивает число обращений модели к инструментам в одной задаче; повтор одинакового изменения блокируется.")}>
    <input type="number" min="1" max="12" value={get("llm.agent.max_steps",6)} onchange={e=>numberSetting(e.currentTarget,"llm.agent.max_steps",1,12)}/>
  </Setting>
  <Setting title={uiText("Недавние обмены репликами")} hint={uiText("Сколько последних пар «вопрос — ответ» стараться сохранить целиком. Более старая переписка ищется по теме. При нехватке места ближайшая длинная пара сокращается с пометкой; оригинал остаётся в истории.")}><input type="number" min="2" max="20" value={get("llm.memory.recent_turns",8)} onchange={e=>numberSetting(e.currentTarget,"llm.memory.recent_turns",2,20)}/></Setting>
</div>

<div class="card">
  <div class="caps">{uiText(Object.keys(get('llm.connections',{}) ?? {}).length ? 'Резервные настройки и характер' : 'Основная модель')}</div>
  <details open={defaultsOpen}><summary>{uiText("Основная модель без назначения подключений")}</summary>
  <Setting title={uiText("Где работает модель")} hint={uiText("Ollama — на этом компьютере или домашнем сервере. Совместимый сервер — LM Studio, llama.cpp или выбранный вами API.")}>
    <select value={get("llm.provider","ollama")} onchange={e=>set("llm.provider",e.currentTarget.value)}><option value="ollama">Ollama</option><option value="openai">{uiText("Совместимый сервер")}</option><option value="anthropic">{uiText("Anthropic (совместимый режим)")}</option></select>
  </Setting>
  <Setting title={uiText("Контекст модели")} hint={uiText("Рабочий лимит. Большое окно требует больше памяти; начните с 8192.")}><input type="number" min="2048" max="262144" step="1024" value={get("llm.context",8192)} onchange={e=>numberSetting(e.currentTarget,"llm.context",2048,262144)}/></Setting>
  <Setting title={uiText("Адрес сервера")} hint={uiText("Для Ollama обычно http://127.0.0.1:11434; для совместимого сервера нужен полный адрес /v1/chat/completions.")}>
    <input style="width:310px" value={get("llm.url", "http://127.0.0.1:11434")} onchange={e=>set("llm.url",e.currentTarget.value.trim())}/>
  </Setting>
  {#if get("llm.provider","ollama")!=="ollama"}<Setting title={uiText("Переменная окружения с ключом")} hint={uiText("Введите имя переменной, а не сам секретный ключ.")}><input value={get("llm.api_key_env","")} onchange={e=>set("llm.api_key_env",e.currentTarget.value.trim())}/></Setting>{/if}
  <Setting title={uiText("Модель")} hint={uiText(get("llm.provider","ollama")!=="ollama" ? "Точное имя модели на выбранном сервере" : ollama?.ok ? (ollama.running ? "Ollama работает" : "Ollama установлена, Джарвис запустит её сам") : "Ollama не установлена — скачается вместе с моделью")}>
    {#if get("llm.provider","ollama")!=="ollama"}<input aria-label={uiText("Имя модели сервера")} value={get("llm.model","")} onchange={e=>set("llm.model",e.currentTarget.value.trim())}/>{:else}
    <select style="width:220px" value={get("llm.model", "gemma4:e4b")} onchange={(e) => set("llm.model", (e.target as HTMLSelectElement).value)}>
      {#each [...new Set([get("llm.model", "gemma4:e4b"), ...models])] as m}<option value={m}>{uiText(m)}{uiText(models.includes(m) ? "" : " (не скачана)")}</option>{/each}
    </select>
    {/if}
  </Setting>
  </details>
  <Setting title={uiText("Свободные ответы")} hint={uiText("Выключите, если нужны только заранее настроенные команды.")}><Toggle checked={get('llm.enabled',true)} onchange={v=>set('llm.enabled',v)}/></Setting>
  {#if pulling}
    <div class="pull mono">{uiText("Скачиваю ")}{pulling.name}… {uiText(pulling.pct)}%<div class="bar"><div style="width:{pulling.pct}%"></div></div></div>
  {:else}
    <div class="suggest">
      {#each suggested.filter((m) => !models.includes(m)) as m}
        <button class="btn" onclick={() => pull(m)}><Download size={14} />{uiText(" Скачать ")}{uiText(m)}</button>
      {/each}
    </div>
  {/if}
  <Setting title={uiText("Характер")} hint={uiText("Пусто — классический Джарвис: дворецкий с лёгкой иронией, обращается «сэр»")} wide>
    <textarea rows="3" placeholder={uiText("Например: «Ты Юки, дружелюбная героиня аниме. Отвечай кратко, обращайся на ты и иногда шути»")} value={get("llm.system", "") ?? ""} onchange={(e) => set("llm.system", (e.target as HTMLTextAreaElement).value || null)}></textarea>
  </Setting>
</div>

<div class="card">
  <div class="caps">{uiText("Что Джарвис умеет делать сам")}</div>
  {#each tools.filter(t => t.id !== 'screen' || app.info?.platform === 'windows') as t}
    <Setting title={uiText(t.title)} hint={uiText(t.hint)}>
      <Toggle checked={enabled.includes(t.id)} onchange={(v) => toggleTool(t.id, v)} />
    </Setting>
  {/each}
</div>

<div class="card">
  <div class="caps">{uiText("Мир вокруг")}</div>
  <Setting title={uiText("Ваш город")} hint={uiText("Для «какая погода» без города. Можно сказать голосом: «Запомни, я живу в Казани»")}>
    <input type="text" style="width:220px" placeholder={uiText("Например, Москва")} value={get("location.city", "auto") === "auto" ? "" : get("location.city")} onchange={(e) => set("location.city", (e.target as HTMLInputElement).value.trim() || "auto")} />
  </Setting>
  <Setting title={uiText("Поиск в интернете")} hint={uiText("DuckDuckGo работает без ключа; Brave точнее, нужен бесплатный ключ с brave.com/search/api")}>
    <Segmented value={get("search.provider", "duckduckgo")} options={[{ value: "duckduckgo", label: "DuckDuckGo" }, { value: "brave", label: "Brave" }]} onchange={(v) => set("search.provider", v)} />
  </Setting>
  {#if get("search.provider") === "brave"}
    <Setting title={uiText("Ключ Brave Search")}>
      <input type="password" style="width:300px" value={get("search.api_key", "")} onchange={(e) => set("search.api_key", (e.target as HTMLInputElement).value.trim())} />
    </Setting>
  {/if}
</div>

<style>
  .suggest {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    padding: 4px 0 12px;
    border-bottom: 1px solid var(--line);
  }
  .pull {
    padding: 4px 0 12px;
    color: var(--accent-2);
    font-size: 12.5px;
  }
  .bar {
    margin-top: 6px;
    height: 6px;
    border-radius: 3px;
    background: #061219;
    overflow: hidden;
  }
  .bar div {
    height: 100%;
    background: var(--accent-2);
    transition: width 300ms;
  }
  textarea {
    width: 100%;
  }
</style>
