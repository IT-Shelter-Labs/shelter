<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  import { onMount, onDestroy } from "svelte";
  import { enable, disable, isEnabled } from "@tauri-apps/plugin-autostart";
  import { FileText, FolderOpen, Settings, Wand2 } from "@lucide/svelte";
  import Setting from "../components/Setting.svelte";
  import Toggle from "../components/Toggle.svelte";
  import Diagnostics from "../components/Diagnostics.svelte";
  import { app, set, saveNow, toast, toastError } from "../lib/store.svelte";
  import { api, on, type SetupEvent } from "../lib/api";

  let autostart = $state(false);
  let check = $state<Record<string, any>>({});
  let busy = $state<string | null>(null);
  let progress = $state("");
  let unlisten: (() => void) | undefined;

  const components = [
    { id: "python", title: "Среда Python", hint: "Основа ядра Джарвиса" },
    { id: "packages", title: "Библиотеки", hint: "Распознавание, звук, управление Windows (~150 МБ)" },
    { id: "vosk", title: "Распознавание vosk", hint: "Быстрая модель речи, 45 МБ" },
    { id: "kws", title: "Слово «Джарвис»", hint: "Лёгкий поиск имени, 22 МБ" },
    { id: "aec", title: "Подавление эха", hint: "Для колонок, ~15 МБ — включается в «Слухе»" },
    { id: "gigaam", title: "Точный слух GigaAM", hint: "Распознавание команд от Сбера, 170 МБ" },
    { id: "vad", title: "Фильтр шума Silero", hint: "1 МБ" },
    { id: "piper", install: "piper:ruslan", title: "Лёгкий голос", hint: "Голос без видеокарты, 64 МБ" },
    { id: "ollama", title: "Ollama", hint: "Движок для локальных моделей" },
  ];

  async function refresh() {
    check = await api.setupCheck().catch(() => ({}));
  }

  onMount(async () => {
    autostart = await isEnabled().catch(() => false);
    await refresh();
    unlisten = await on<SetupEvent>("setup:event", (e) => {
      if (e.stage === "download" && e.total) progress = `${e.component}: ${Math.round(((e.done ?? 0) / e.total) * 100)}%`;
      else if (e.stage) progress = `${e.component}: ${e.text ?? e.stage}`;
      if (e.status === "error") toastError(`${e.component}: ${e.message}`);
      if (e.status === "finished") {
        busy = null;
        progress = "";
        refresh();
        if (e.ok) toast("Готово", "success");
      }
    });
  });
  onDestroy(() => unlisten?.());

  async function toggleAutostart(v: boolean) {
    try {
      if (v) await enable();
      else await disable();
      autostart = v;
    } catch (e) {
      toastError(e);
    }
  }

  function install(ids: string[]) {
    busy = ids.join(",");
    api.setupInstall(ids).catch((e) => {
      busy = null;
      toastError(e);
    });
  }

  async function rerunWizard() {
    set("onboarded", false, false);
    await saveNow();
  }
  const ok = (id: string) => !!check[id]?.ok;
</script>

<h1>{uiText("Система и диагностика")}</h1>
<p class="lead">{uiText("Запуск, состояние модулей, компоненты и обслуживание.")}</p>

<Diagnostics />

<div class="card">
  <div class="caps">{uiText("Запуск")}</div>
  <Setting title={uiText("Запускать вместе с Windows")} hint={uiText("Джарвис стартует свёрнутым в трей и сразу слушает")}>
    <Toggle checked={autostart} onchange={toggleAutostart} />
  </Setting>
</div>

<div class="card">
  <div class="caps">{uiText("Компоненты")}</div>
  {#each components as c}
    <Setting title={uiText(c.title)} hint={uiText(c.hint)}>
      {#if ok(c.id)}
        <span class="chip ok"><span class="dot"></span>{uiText(" установлено")}</span>
      {:else}
        <button class="btn" disabled={!!busy} onclick={() => install([c.install ?? c.id])}>{uiText("Установить")}</button>
      {/if}
    </Setting>
  {/each}
  <Setting title={uiText("Фирменный голос (видеокарта)")} hint={uiText("Клонированный голос по образцу. Устанавливается в «Слух и голос» (≈5 ГБ, NVIDIA от 8 ГБ)")}>
    {#if ok("clone")}<span class="chip ok"><span class="dot"></span>{uiText(" установлено")}</span>{:else}<span class="chip">{uiText("не установлен")}</span>{/if}
  </Setting>
  {#if busy}<div class="progress mono">{uiText(progress || "Устанавливаю…")}</div>{/if}
</div>

<div class="card">
  <div class="caps">{uiText("Обслуживание")}</div>
  <Setting title={uiText("Журнал")} hint={uiText("Всё, что Джарвис слышал и делал — пригодится, если что-то не работает")}>
    <button class="btn" onclick={() => api.open("logs").catch(toastError)}><FileText size={14} />{uiText(" Открыть")}</button>
  </Setting>
  <Setting title={uiText("Папка Джарвиса")} hint={uiText("Модели, настройки, записи")}>
    <button class="btn" onclick={() => api.open("folder").catch(toastError)}><FolderOpen size={14} />{uiText(" Открыть")}</button>
  </Setting>
  <Setting title={uiText("Расширенные настройки")} hint={uiText("config.yaml с комментариями — для опытных. Команды удобнее создавать в разделе «Команды»")}>
    <button class="btn" onclick={() => api.open("config").catch(toastError)}><Settings size={14} />{uiText(" Открыть")}</button>
  </Setting>
  <Setting title={uiText("Мастер настройки")} hint={uiText("Пройти первоначальную настройку заново")}>
    <button class="btn" onclick={rerunWizard}><Wand2 size={14} />{uiText(" Запустить")}</button>
  </Setting>
</div>

<p class="dim mono about">{uiText("Джарвис ")}{uiText(app.info?.version)}{uiText(" · ядро: ")}{uiText(app.core?.root)}</p>

<style>
  .progress {
    padding-top: 10px;
    color: var(--accent-2);
    font-size: 12.5px;
  }
  .about {
    font-size: 11.5px;
    margin-top: 8px;
  }
</style>
