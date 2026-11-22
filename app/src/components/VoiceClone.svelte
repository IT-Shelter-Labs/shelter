<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  import { onMount, onDestroy } from "svelte";
  import { open as openFile } from "../lib/fileDialogs";
  import { Download, Mic, FolderOpen, Volume2, LoaderCircle, Check, ShieldAlert } from "@lucide/svelte";
  import { app, get, set, saveNow, toast, toastError, refreshStatus } from "../lib/store.svelte";
  import { api, on, type SetupEvent } from "../lib/api";

  // Фирменный голос: установка (~5 ГБ) -> образец голоса -> прослушать.
  let { compact = false }: { compact?: boolean } = $props();

  let installed = $state<boolean | null>(null);
  let installing = $state(false);
  let progress = $state({ pct: 0, text: "" });
  let recording = $state(0); // секунд до конца записи
  let importing = $state(false);
  let applying = $state(false);
  let unlisten: (() => void) | undefined;

  const PHRASE = "Добрый вечер. Все системы работают в штатном режиме, погода сегодня отличная, а задачи на день уже готовы. Чем могу быть полезен?";
  const sample = $derived(get<string>("tts.clone.reference", ""));
  const sampleText = $derived(get<string>("tts.clone.reference_text", ""));

  onMount(async () => {
    installed = !!(await api.setupCheck().catch(() => ({}) as any)).clone?.ok;
    unlisten = await on<SetupEvent>("setup:event", (e) => {
      if (e.component !== "clone" && e.status !== "finished") return;
      if (e.stage === "download" && e.total) progress = { pct: Math.min(100, Math.round(((e.done ?? 0) / e.total) * 100)), text: `модель голоса: ${((e.done ?? 0) / 1073741824).toFixed(1)} из ${(e.total / 1073741824).toFixed(1)} ГБ` };
      else if (e.text) progress = { ...progress, text: e.text };
      else if (e.stage) progress = { ...progress, text: e.stage === "extract" ? "распаковка…" : e.stage };
      if (e.status === "error") toastError(e.message);
      if (e.status === "finished") {
        installing = false;
        api.setupCheck().then((c: any) => (installed = !!c.clone?.ok));
        if (e.ok) toast("Фирменный голос установлен", "success");
      }
    });
  });
  onDestroy(() => unlisten?.());

  function install() {
    installing = true;
    progress = { pct: 0, text: "готовлю…" };
    api.setupInstall(["clone"]).catch((e) => {
      installing = false;
      toastError(e);
    });
  }

  async function useSample(r: { path: string; text: string; seconds: number }) {
    set("tts.clone.reference", r.path, false);
    set("tts.clone.reference_text", r.text, false);
    set("tts.engine", "clone", false);
    await saveNow();
    toast(`Образец готов: ${r.seconds} с`, "success");
  }

  async function record() {
    recording = 10;
    const timer = setInterval(() => (recording = Math.max(0, recording - 1)), 1000);
    try {
      await useSample(await api.voiceRecord(10));
    } catch (e) {
      toastError(e);
    } finally {
      clearInterval(timer);
      recording = 0;
    }
  }

  async function pick() {
    const path = await openFile({ multiple: false, filters: [{ name: "Аудио", extensions: ["wav", "mp3", "flac", "ogg"] }] });
    if (!path) return;
    importing = true;
    try {
      await useSample(await api.voiceImport(path as string));
    } catch (e) {
      toastError(e);
    } finally {
      importing = false;
    }
  }

  /** Перезапустить ядро с клоном, дождаться загрузки модели голоса и сказать фразу. */
  async function listen() {
    applying = true;
    try {
      await saveNow();
      await api.coreRestart();
      const end = Date.now() + 180000;
      while (Date.now() < end) {
        await new Promise((r) => setTimeout(r, 2000));
        await refreshStatus();
        if (app.status?.clone_ready) break;
        if (app.status?.voice_status?.phase === "error") throw "Голос не загрузился — подробности в журнале (Система → Журнал).";
      }
      if (!app.status?.clone_ready) throw "Голос не загрузился — подробности в журнале (Система → Журнал).";
      await api.say("Добрый день, сэр. Все системы в норме. Чем могу помочь?");
      app.dirty = false;
    } catch (e) {
      toastError(e);
    } finally {
      applying = false;
    }
  }
</script>

<div class="clone" class:compact>
  {#if installed === null}
    <LoaderCircle class="spin" size={18} />
  {:else if !installed}
    <p class="muted">{uiText("Голос персонажа читает новые ответы, сохраняя тембр записи. Для установки нужны видеокарта NVIDIA от 8 ГБ и около 5 ГБ загрузки.")}</p>
    {#if installing}
      <div class="bar"><div style="width:{progress.pct}%"></div></div>
      <div class="mono note">{uiText(progress.text)}</div>
    {:else}
      <button class="btn" onclick={install}><Download size={15} />{uiText(" Установить фирменный голос")}</button>
    {/if}
  {:else}
    <div class="row-btns">
      <button class="btn" disabled={!!recording || importing || !app.status} onclick={record}>
        {#if recording}<span class="rec"></span>{uiText(" Читайте… ")}{uiText(recording)}{:else}<Mic size={15} />{uiText(" Записать свой голос")}{/if}
      </button>
      <button class="btn" disabled={!!recording || importing || !app.status} onclick={pick}>
        {#if importing}<LoaderCircle class="spin" size={15} />{:else}<FolderOpen size={15} />{/if}{uiText(" Выбрать запись\n      ")}</button>
      <button class="btn primary" disabled={!sample || applying || !app.core?.running} onclick={listen}>
        {#if applying}<LoaderCircle class="spin" size={15} />{uiText(" Загружаю голос…")}{:else}<Volume2 size={15} />{uiText(" Прослушать")}{/if}
      </button>
    </div>
    {#if recording}
      <div class="phrase">«{uiText(PHRASE)}»</div>
    {/if}
    {#if sample}
      <label class="field">
        <span><Check size={13} />{uiText(" Образец: ")}{uiText(sample)}{uiText(". Текст образца (поправьте, если распознан с ошибкой):")}</span>
        <textarea rows="2" value={sampleText} onchange={(e) => set("tts.clone.reference_text", (e.target as HTMLTextAreaElement).value.trim())}></textarea>
      </label>
    {:else}
      <p class="dim note">{uiText("Запишите 10 секунд своей речи или выберите запись 5–15 секунд чистого голоса без музыки.")}</p>
    {/if}
    <p class="rights"><ShieldAlert size={13} />{uiText(" Используйте только свой голос или голос, на который у вас есть разрешение.")}</p>
  {/if}
</div>

<style>
  .clone {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 8px 0 4px;
  }
  .row-btns {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  .bar {
    height: 8px;
    border-radius: 4px;
    background: #061219;
    overflow: hidden;
  }
  .bar div {
    height: 100%;
    background: linear-gradient(90deg, #1b7fa3, #7fe6ff);
    transition: width 400ms;
  }
  .note {
    font-size: 12px;
    color: var(--text-2);
  }
  .phrase {
    padding: 12px 14px;
    border-radius: 12px;
    border: 1px solid rgba(255, 182, 72, 0.4);
    background: rgba(255, 182, 72, 0.06);
    color: #ffd8a0;
    font-size: 15px;
  }
  .rec {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--bad);
    animation: blink 1s infinite;
  }
  @keyframes blink {
    50% {
      opacity: 0.25;
    }
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .field span {
    display: flex;
    align-items: center;
    gap: 6px;
    color: var(--ok);
    font-size: 12.5px;
  }
  textarea {
    width: 100%;
  }
  .rights {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--text-3);
  }
</style>
