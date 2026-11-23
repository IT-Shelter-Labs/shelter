<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  import { onMount, onDestroy } from "svelte";
  import { enable as enableAutostart } from "@tauri-apps/plugin-autostart";
  import { Check, LoaderCircle, CircleAlert, Cpu, MemoryStick, MonitorCog, HardDrive, Volume2, ArrowLeft, ArrowRight } from "@lucide/svelte";
  import TitleBar from "../components/TitleBar.svelte";
  import Reactor from "../components/Reactor.svelte";
  import MicMeter from "../components/MicMeter.svelte";
  import Toggle from "../components/Toggle.svelte";
  import VoiceClone from "../components/VoiceClone.svelte";
  import { app, get, set, saveNow, toastError, refreshStatus } from "../lib/store.svelte";
  import { api, on, type Hardware, type SetupEvent } from "../lib/api";

  const steps = ["Знакомство", "Компьютер", "Установка", "Микрофон", "Голос", "О вас", "Готово"];
  let step = $state(0);
  let navigating = $state(false);
  let voiceVisited = $state(false);
  let stage: HTMLDivElement;
  let unlockNavigation: ReturnType<typeof setTimeout>;
  let hw = $state<Hardware | null>(null);
  let check = $state<Record<string, any>>({});
  let plan = $state<{ id: string; title: string; state: "wait" | "run" | "ok" | "error"; note: string }[]>([]);
  let installing = $state(false);
  let installed = $state(false);
  let devices = $state<{ index: number; name: string; default: boolean }[]>([]);
  let heardWake = $state(false);
  let micStepStarted = 0;
  let restarting = $state(false);
  let autostart = $state(true);
  let preciseRecognition = $state(true);
  let modelMode = $state<"local" | "later">("local");
  let city = $state("");
  let unlisten: (() => void) | undefined;
  const navigationDisabled = $derived(navigating || installing || restarting);

  const titles: Record<string, string> = {
    python: "Среда Python",
    packages: "Библиотеки распознавания и звука",
    vosk: "Распознавание речи vosk",
    kws: "Распознавание имени персонажа",
    gigaam: "Точный слух GigaAM",
    vad: "Фильтр шума Silero",
    "piper:ruslan": "Лёгкий голос",
    "piper:irina": "Голос для Пиппы",
    ollama: "Движок нейросети Ollama",
  };

  onMount(async () => {
    hw = await api.hardware().catch(() => null);
    if (get("llm.provider", "ollama") !== "ollama" || Object.keys(get("llm.connections", {}) ?? {}).length) modelMode = "later";
    unlisten = await on<SetupEvent>("setup:event", onSetup);
    city = get("location.city", "auto") === "auto" ? "" : get("location.city");
  });
  onDestroy(() => {
    clearTimeout(unlockNavigation);
    unlisten?.();
  });

  async function buildPlan() {
    check = await api.setupCheck().catch(() => ({}));
    const need: string[] = [];
    if (!check.python?.ok) need.push("python");
    if (!check.packages?.ok) need.push("packages");
    for (const id of ["vosk", "kws", "vad", ...(preciseRecognition ? ["gigaam"] : [])]) if (!check[id]?.ok) need.push(id);
    if (!check.piper?.ok) need.push("piper:ruslan");
    if (!(check.piper?.voices ?? []).includes("irina")) need.push("piper:irina");
    const model = modelMode === "local" ? hw?.recommendation.model : null;
    if (model) {
      if (!check.ollama?.ok) need.push("ollama");
      if (!(check.ollama?.models ?? []).includes(model)) need.push(`model:${model}`);
    }
    plan = need.map((id) => ({ id, title: titles[id] ?? (id.startsWith("model:") ? `Нейросеть ${id.slice(6)}` : id), state: "wait", note: "" }));
    installed = need.length === 0;
  }

  function onSetup(e: SetupEvent) {
    if (!installing) return;
    if (e.status === "finished") {
      installing = false;
      installed = !!e.ok && plan.every((p) => p.state === "ok");
      return;
    }
    const item = plan.find((p) => p.id === e.component);
    if (!item) return;
    if (e.status === "start") item.state = "run";
    else if (e.status === "ok") (item.state = "ok"), (item.note = "");
    else if (e.status === "error") (item.state = "error"), (item.note = e.message ?? "ошибка");
    else if (e.stage === "download" && e.total) item.note = `${(e.done! / 1048576).toFixed(0)} из ${(e.total / 1048576).toFixed(0)} МБ`;
    else if (e.stage === "extract") item.note = "распаковка…";
    else if (e.stage === "install") item.note = "установка…";
    else if (e.stage === "pip" && e.text) item.note = e.text.slice(0, 70);
    else if (e.stage === "retry") item.note = e.text ?? "повтор";
  }

  function install() {
    if (navigationDisabled) return;
    installing = true;
    api.setupInstall(plan.filter((p) => p.state !== "ok").map((p) => p.id)).catch((e) => {
      installing = false;
      toastError(e);
    });
  }

  async function waitConnected(timeout = 60000) {
    const end = Date.now() + timeout;
    while (Date.now() < end) {
      await refreshStatus();
      if (app.status) return true;
      await new Promise((r) => setTimeout(r, 700));
    }
    return false;
  }

  async function startMicStep() {
    restarting = true;
    try {
      if (!app.core?.running) await api.coreStart();
      await waitConnected();
      devices = (await api.devices()).devices;
    } catch (e) {
      toastError(e);
    }
    restarting = false;
    micStepStarted = Date.now() / 1000;
    heardWake = false;
  }

  async function restartCore(resetWake = false) {
    restarting = true;
    try {
      await saveNow();
      await api.coreRestart();
      await new Promise((r) => setTimeout(r, 1500));
      await waitConnected();
      if (resetWake) {
        micStepStarted = Date.now() / 1000;
        heardWake = false;
      }
    } catch (e) {
      toastError(e);
    } finally {
      restarting = false;
    }
  }

  $effect(() => {
    if (step === 3 && !restarting && app.feed.some((e) => e.kind === "wake" && e.time >= micStepStarted)) heardWake = true;
  });

  function beginNavigation(event: MouseEvent) {
    if (navigationDisabled || event.detail > 1) return false;
    navigating = true;
    return true;
  }

  function showStep(target: number) {
    step = target;
    if (target === 4) voiceVisited = true;
    stage.scrollTop = 0;
    // The second click can land on a different button after the DOM changes.
    unlockNavigation = setTimeout(() => { navigating = false; }, 500);
  }

  function previous(event: MouseEvent) {
    if (step > 0 && beginNavigation(event)) showStep(step - 1);
  }

  async function next(event: MouseEvent) {
    if (step >= steps.length - 1 || !beginNavigation(event)) return;
    try {
      if (step === 1) await buildPlan();
      if (step === 2) {
        const model = modelMode === "local" ? hw?.recommendation.model : null;
        if (model) {
          set("llm.provider", "ollama", false);
          set("llm.model", model, false);
          set("llm.enabled", true, false);
        } else if (!Object.keys(get("llm.connections", {}) ?? {}).length && get("llm.provider", "ollama") === "ollama") {
          set("llm.enabled", false, false);
        }
        set("asr.engine", preciseRecognition ? "gigaam" : "vosk", false);
        await saveNow();
        await startMicStep();
      }
      showStep(step + 1);
    } catch (e) {
      navigating = false;
      toastError(e);
    }
  }

  async function finish(event: MouseEvent) {
    if (!beginNavigation(event)) return;
    set("location.city", city.trim() || "auto", false);
    if (autostart) await enableAutostart().catch(() => {});
    set("onboarded", true, false);
    await saveNow();
    // Ядро подхватывает все выбранные в мастере настройки.
    await api.coreRestart().catch(() => {});
    app.dirty = false;
  }

  async function chooseVoice(engine: string, voice?: string) {
    if (navigationDisabled) return;
    set("tts.engine", engine, false);
    if (voice) set("tts.piper.voice", voice, false);
    await restartCore();
  }

  const vram = $derived(Math.max(0, ...(hw?.gpus.filter((g) => !g.integrated).map((g) => g.vramGb) ?? [0])));
</script>

{#snippet backButton()}
  <button class="btn ghost back" disabled={navigationDisabled} onclick={previous}><ArrowLeft size={16} />{uiText("Назад")}</button>
{/snippet}

<div class="wizard">
  <TitleBar maximizable={false}>
    <span class="caps brand">{uiText("Настройка Shelter")}</span>
  </TitleBar>

  <div class="steps">
    {#each steps as s, i}
      <div class="dot" class:done={i < step} class:current={i === step} aria-current={i === step ? "step" : undefined}><span>{uiText(i < step ? "✓" : i + 1)}</span>{uiText(s)}</div>
    {/each}
  </div>

  <div class="stage" bind:this={stage}>
    {#key step}
      <div class="panel fade-in" hidden={step === 4}>
        {#if step === 0}
          <div class="center">
            <Reactor size={240} state="listening" />
            <h1>{uiText("Добрый день, сэр.")}</h1>
            <p class="muted">{uiText("Я Джарвис — голосовой ассистент, который живёт на вашем компьютере. Понимаю речь, отвечаю голосом,\r\n              управляю программами, играми и умным домом. Настроим всё за пару минут.")}</p>
            <button class="btn primary lg" disabled={navigationDisabled} onclick={next}>{uiText("Начать ")}<ArrowRight size={16} /></button>
          </div>
        {:else if step === 1}
          <h2>{uiText("Ваш компьютер")}</h2>
          <p class="muted">{uiText("Подберу настройки под железо, чтобы Джарвис работал быстро и не мешал играм.")}</p>
          {#if hw}
            <div class="hw">
              <div class="card"><Cpu size={18} /><b>{uiText(hw.cpu)}</b><span class="dim">{uiText(hw.cpuThreads)}{uiText(" потоков")}</span></div>
              <div class="card"><MemoryStick size={18} /><b>{uiText(hw.ramTotalGb.toFixed(0))}{uiText(" ГБ")}</b><span class="dim">{uiText("оперативной памяти")}</span></div>
              <div class="card"><MonitorCog size={18} /><b>{uiText(hw.gpus.find((g) => !g.integrated)?.name ?? "Встроенная графика")}</b><span class="dim">{uiText(vram ? vram.toFixed(0) + " ГБ видеопамяти" : "без отдельной видеокарты")}</span></div>
              <div class="card"><HardDrive size={18} /><b>{uiText(hw.diskFreeGb?.toFixed(0) ?? "?")}{uiText(" ГБ")}</b><span class="dim">{uiText("свободно на диске")}</span></div>
            </div>
            <div class="card rec">
              <div class="caps">{uiText("Рекомендую")}</div>
              <p><b>{uiText("Разум:")}</b> {uiText(hw.recommendation.model || "без локальной модели")} — {uiText(hw.recommendation.modelReason)}</p>
              <p><b>{uiText("Голос:")}</b> {uiText(hw.recommendation.voice === "clone" ? "фирменный голос Джарвиса" : "лёгкий голос")} — {uiText(hw.recommendation.voiceReason)}</p>
            </div>
            <div class="card">
              <label class="field"><span>{uiText("Модель для разговора")}</span>
                <select bind:value={modelMode}>
                  <option value="local" disabled={!hw.recommendation.model}>{uiText("Скачать рекомендованную модель")}</option>
                  <option value="later">{uiText("Пропустить скачивание · настроить модель позже")}</option>
                </select>
              </label>
              <div class="row"><div class="label"><b>{uiText("Точное распознавание GigaAM")}</b><span>{uiText("Скачает дополнительную модель для русской речи. Можно поставить позже.")}</span></div><Toggle checked={preciseRecognition} onchange={(value) => preciseRecognition = value} /></div>
            </div>
          {:else}
            <div class="center"><LoaderCircle class="spin" size={28} /></div>
          {/if}
          <div class="nav">{@render backButton()}<button class="btn primary lg" disabled={!hw || navigationDisabled} onclick={next}>{uiText("Дальше ")}<ArrowRight size={16} /></button></div>
        {:else if step === 2}
          <h2>{uiText("Установка")}</h2>
          <p class="muted">{uiText("Выбранные компоненты скачиваются с официальных сайтов. Если Ollama уже установлена, используется существующая копия.")}</p>
          {#if app.info?.root}
            <div class="card folder"><b>{uiText("Папка компонентов и данных")}</b><div class="mono dim">{app.info.root}</div></div>
          {/if}
          {#if plan.length}
            <div class="card plan">
              {#each plan as p}
                <div class="item {p.state}">
                  <span class="ic">{#if p.state === "ok"}<Check size={16} />{:else if p.state === "run"}<LoaderCircle class="spin" size={16} />{:else if p.state === "error"}<CircleAlert size={16} />{:else}·{/if}</span>
                  <span class="name">{uiText(p.title)}</span>
                  <span class="note mono">{uiText(p.note)}</span>
                </div>
              {/each}
            </div>
          {:else}
            <div class="card ok-all"><Check size={18} />{uiText(" Всё уже установлено.")}</div>
          {/if}
          <div class="nav">
            {@render backButton()}
            {#if !installed}
              <button class="btn primary lg" disabled={navigationDisabled} onclick={install}>{uiText(installing ? "Устанавливаю…" : plan.some((p) => p.state === "error") ? "Повторить" : "Установить")}</button>
            {:else}
              <button class="btn primary lg" disabled={navigationDisabled} onclick={next}>{uiText("Дальше ")}<ArrowRight size={16} /></button>
            {/if}
          </div>
        {:else if step === 3}
          <h2>{uiText("Микрофон")}</h2>
          <p class="muted">{uiText("Выберите микрофон и скажите обычным голосом: ")}<b class="accent">{uiText("«Джарвис»")}</b>.</p>
          <div class="card">
            <select style="width:100%" disabled={restarting} value={String(get("audio.device") ?? "")} onchange={async (e) => { const v = (e.target as HTMLSelectElement).value; set("audio.device", v === "" ? null : Number(v), false); set("audio.device_name", devices.find(d => String(d.index) === v)?.name ?? null, false); await restartCore(true); }}>
              <option value="">{uiText("По умолчанию Windows")}</option>
              {#each devices as d}<option value={String(d.index)}>{d.name}</option>{/each}
              {#if get("audio.device") != null && !devices.some((d) => d.index === get("audio.device"))}<option value={String(get("audio.device"))}>{uiText("Текущий микрофон (№")}{uiText(get("audio.device"))})</option>{/if}
            </select>
            <div class="meter"><MicMeter /></div>
            <div class="wake {heardWake ? 'heard' : ''}">
              {#if restarting}<LoaderCircle class="spin" size={18} />{uiText(" Подключаю микрофон…\r\n              ")}{:else if heardWake}<Check size={18} />{uiText(" Слышу вас отлично, сэр.\r\n              ")}{:else}<span class="pulse"></span>{uiText(" Жду «Джарвис»…")}{/if}
            </div>
          </div>
          <p class="dim hint">{uiText("Не срабатывает? Говорите ближе к микрофону, проверьте, что полоска прыгает, когда вы говорите, или выберите другой микрофон.")}</p>
          <div class="nav">
            {@render backButton()}
            <button class="btn ghost" disabled={navigationDisabled} onclick={next}>{uiText("Пропустить")}</button>
            <button class="btn primary lg" disabled={!heardWake || navigationDisabled} onclick={next}>{uiText("Дальше ")}<ArrowRight size={16} /></button>
          </div>
        {:else if step === 5}
          <h2>{uiText("О вас")}</h2>
          <p class="muted">{uiText("Пара мелочей, чтобы Джарвис был полезнее.")}</p>
          <div class="card">
            <label class="field"><span>{uiText("Ваш город — для погоды и утренней сводки")}</span><input type="text" placeholder={uiText("Например, Москва")} bind:value={city} /></label>
            <div class="row"><div class="label"><b>{uiText("Запускать вместе с Windows")}</b><span>{uiText("Джарвис будет в трее и сразу слушать")}</span></div><Toggle checked={autostart} onchange={(v) => (autostart = v)} /></div>
          </div>
          <div class="nav">{@render backButton()}<button class="btn primary lg" disabled={navigationDisabled} onclick={next}>{uiText("Дальше ")}<ArrowRight size={16} /></button></div>
        {:else if step === 6}
          <div class="center">
            <Reactor size={200} state="speaking" />
            <h1>{uiText("Готово, сэр.")}</h1>
            <p class="muted">{uiText("Скажите ")}<b class="accent">{uiText("«Джарвис»")}</b>{uiText(" — и просите что угодно: «открой браузер», «какая погода завтра», «таймер на пять минут»,\r\n              «выключи микрофон в дискорде», «что ты умеешь?». Окно можно закрыть — Джарвис останется в трее у часов.")}</p>
            <div class="nav">{@render backButton()}<button class="btn primary lg" disabled={navigationDisabled} onclick={finish}>{uiText("Начать работу")}</button></div>
          </div>
        {/if}
      </div>
    {/key}
    <!-- Keep the download and sample controls alive when revisiting Voice. -->
    {#if voiceVisited}
      <div class="panel fade-in" hidden={step !== 4}>
        <h2>{uiText("Голос")}</h2>
        <p class="muted">{uiText("Как будет звучать Джарвис. Выберите и нажмите «Прослушать».")}</p>
        {#if hw?.recommendation.voice === "clone" || check.clone?.ok}
          <div class="card">
            <div class="caps">{uiText("Фирменный голос — ваша видеокарта его потянет")}</div>
            <VoiceClone />
          </div>
          <div class="caps">{uiText("Или лёгкий голос")}</div>
        {/if}
        <div class="voices">
          {#each [["ruslan", "Руслан"], ["irina", "Ирина"], ["dmitri", "Дмитрий"], ["denis", "Денис"]] as [id, name]}
            {#if (check.piper?.voices ?? ["ruslan"]).includes(id)}
              <button class="card voice" class:sel={get("tts.engine") !== "clone" && get("tts.piper.voice", "ruslan") === id} disabled={navigationDisabled} onclick={() => chooseVoice("piper", id)}><b>{uiText(name)}</b><span class="dim">{uiText("лёгкий голос, процессор")}</span></button>
            {/if}
          {/each}
        </div>
        <div class="nav">
          {@render backButton()}
          <button class="btn" disabled={navigationDisabled || !app.status} onclick={() => api.say("Добрый день, сэр. Все системы в норме. Чем могу помочь?").catch(toastError)}>
            {#if restarting}<LoaderCircle class="spin" size={15} />{:else}<Volume2 size={15} />{/if}{uiText(" Прослушать\r\n            ")}</button>
          <button class="btn primary lg" disabled={navigationDisabled} onclick={next}>{uiText("Дальше ")}<ArrowRight size={16} /></button>
        </div>
      </div>
    {/if}
  </div>
</div>

<style>
  .wizard {
    display: flex;
    flex-direction: column;
    height: 100%;
  }
  .brand {
    color: var(--accent-2);
    letter-spacing: 0.25em;
  }
  .folder { overflow-wrap: anywhere; margin-bottom: 12px; }
  .steps {
    display: flex;
    justify-content: center;
    gap: 6px;
    padding: 6px 20px 0;
    flex-wrap: wrap;
  }
  .dot {
    display: flex;
    align-items: center;
    gap: 7px;
    font-size: 12.5px;
    color: var(--text-3);
    padding: 4px 10px;
    border-radius: 999px;
  }
  .dot span {
    width: 20px;
    height: 20px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    font-size: 11px;
    border: 1px solid var(--line-2);
  }
  .dot.current {
    color: var(--accent-2);
    background: rgba(55, 179, 216, 0.1);
  }
  .dot.current span {
    border-color: var(--accent-2);
    box-shadow: 0 0 8px var(--glow);
  }
  .dot.done {
    color: var(--text-2);
  }
  .dot.done span {
    background: var(--accent);
    color: #021018;
    border-color: transparent;
  }
  .stage {
    flex: 1;
    overflow-y: auto;
    display: flex;
    justify-content: center;
    padding: 20px 30px 30px;
  }
  .panel {
    width: min(760px, 100%);
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .center {
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
    gap: 16px;
    margin: auto;
    max-width: 600px;
  }
  .accent {
    color: var(--accent-2);
  }
  .nav {
    display: flex;
    justify-content: flex-end;
    flex-wrap: wrap;
    gap: 10px;
    margin-top: 6px;
  }
  .nav .back { margin-inline-end: auto; }
  .panel[hidden] { display: none; }
  .hw {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 10px;
  }
  .hw .card {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 14px;
    color: var(--accent-2);
  }
  .hw b {
    color: var(--text);
    font-size: 13px;
  }
  .hw span {
    font-size: 12px;
  }
  .rec p {
    margin-top: 8px;
    color: var(--text-2);
  }
  .rec b {
    color: var(--text);
  }
  .plan .item {
    display: grid;
    grid-template-columns: 24px 1fr auto;
    align-items: center;
    gap: 10px;
    padding: 9px 0;
    border-bottom: 1px solid var(--line);
  }
  .plan .item:last-child {
    border-bottom: none;
  }
  .item .ic {
    color: var(--text-3);
    display: grid;
    place-items: center;
  }
  .item.ok .ic {
    color: var(--ok);
  }
  .item.run .ic {
    color: var(--accent-2);
  }
  .item.error .ic,
  .item.error .note {
    color: var(--bad);
  }
  .note {
    font-size: 11.5px;
    color: var(--text-2);
    max-width: 360px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .ok-all {
    display: flex;
    gap: 10px;
    align-items: center;
    color: var(--ok);
  }
  .meter {
    margin: 14px 0;
  }
  .wake {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 15px;
    color: var(--text-2);
    padding: 12px 14px;
    border-radius: 12px;
    border: 1px dashed var(--line-2);
  }
  .wake.heard {
    color: var(--ok);
    border: 1px solid rgba(94, 242, 160, 0.4);
    background: rgba(94, 242, 160, 0.06);
  }
  .pulse {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--accent-2);
    animation: blink 1.2s infinite;
  }
  @keyframes blink {
    50% {
      opacity: 0.2;
    }
  }
  .hint {
    font-size: 12.5px;
  }
  .voices {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
    gap: 10px;
  }
  .voice {
    display: flex;
    flex-direction: column;
    gap: 4px;
    text-align: left;
    cursor: pointer;
    color: var(--text);
    font: inherit;
  }
  .voice.sel {
    border-color: var(--accent-2);
    box-shadow: 0 0 18px var(--glow);
  }
  .voice span {
    font-size: 12px;
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--line);
  }
  .field span {
    color: var(--text-2);
    font-size: 13px;
  }
  :global(.spin) {
    animation: spin 1s linear infinite;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
</style>
