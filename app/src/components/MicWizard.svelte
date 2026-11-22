<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  // Мастер микрофона: устройство → тишина → контрольная фраза → «Джарвис» → команда.
  // Записи не сохраняются: звук берётся из буфера, который Джарвис и так слушает.
  import { onMount } from "svelte";
  import { Mic, CircleCheck, CircleAlert, LoaderCircle, RotateCcw, Ear, Workflow } from "@lucide/svelte";
  import MicMeter from "./MicMeter.svelte";
  import { app, get, set, applySettings, toastError } from "../lib/store.svelte";
  import { api, type Explain } from "../lib/api";
  import { invoke } from "@tauri-apps/api/core";

  type Result = { db: number; speech_db?: number; snr?: number; clipped: number; text: string; engine?: string; matched: { words: number; of: number } | null; advice: string[] };
  const PHRASES = ["Съешь же ещё этих мягких французских булок", "В понедельник в девять утра напомни про встречу", "Включи музыку погромче и открой браузер"];
  let step = $state(0);
  let busy = $state(false);
  let devices = $state<{ index: number; name: string; default: boolean }[]>([]);
  let noise = $state<Result | null>(null);
  let speech = $state<Result | null>(null);
  let phrase = $state(PHRASES[0]);
  let wakeHeard = $state<boolean | null>(null);
  let route = $state<Explain | null>(null);
  let countdown = $state(0);

  onMount(async () => {
    if (app.status) devices = (await api.devices().catch(() => ({ devices: [] }))).devices;
  });
  const micFailed = $derived(["microphone", "vosk"].some((w) => ["failed", "error"].includes(app.status?.workers?.[w]?.state ?? "")));

  async function measure(phase: "noise" | "speech", seconds: number) {
    busy = true;
    countdown = seconds;
    const timer = setInterval(() => (countdown = Math.max(0, countdown - 1)), 1000);
    try {
      return await invoke<Result>("core_post", { path: "/api/audio/test", body: { phase, seconds, expected: phase === "speech" ? phrase : "", noise_db: noise?.db } });
    } catch (e) {
      toastError(e);
      return null;
    } finally {
      clearInterval(timer);
      busy = false;
    }
  }
  async function checkWake() {
    busy = true;
    wakeHeard = null;
    const since = Date.now() / 1000;
    const until = Date.now() + 8000;
    while (Date.now() < until) {
      if (app.feed.some((e) => e.kind === "wake" && e.time >= since - 0.5)) { wakeHeard = true; break; }
      await new Promise((r) => setTimeout(r, 250));
    }
    if (wakeHeard === null) wakeHeard = false;
    busy = false;
  }
  async function checkCommand() {
    busy = true;
    route = null;
    const since = Date.now() / 1000;
    const until = Date.now() + 10000;
    let heard = "";
    // Ждём, что Джарвис услышит просьбу («query») или узнает команду, и показываем маршрут без повторного выполнения.
    while (Date.now() < until && !heard) {
      const e = [...app.feed].reverse().find((x) => (x.kind === "query" || x.kind === "command") && x.time >= since);
      if (e) heard = e.text ?? "";
      await new Promise((r) => setTimeout(r, 250));
    }
    if (heard) {
      route = await api.scenarioOp<Explain>({ op: "test", phrase: heard }).catch(() => null);
      set("audio.checked", true, false);             // мастер пройден — дальше раздел свёрнут
    }
    else route = { phrase: "", route: "none", title: "Ничего не услышал за 10 секунд", detail: "Скажите «Джарвис», затем просьбу.", scenario: null, match: "", calls: [], alternatives: [], warnings: [], ambiguous: false };
    busy = false;
  }
  const verdict = (r: Result | null) => (r && !r.advice.length ? "ok" : r ? "warn" : "");
</script>

<div class="wizard">
  <ol class="steps" aria-label={uiText("Шаги проверки")}>
    {#each ["Устройство", "Тишина", "Фраза", "Обращение", "Команда"] as label, i}
      <li class:active={step === i} class:done={step > i}><button onclick={() => (step = i)} disabled={busy}>{uiText(i + 1)}. {uiText(label)}</button></li>
    {/each}
  </ol>

  {#if !app.status}
    <div class="notice warn"><CircleAlert size={15} />{uiText(" Включите Джарвиса: проверка слушает тем же микрофоном, что и он.")}</div>
  {:else if step === 0}
    <p class="muted">{uiText("Выберите микрофон, в который вы говорите. Полоска должна прыгать, когда вы говорите, и почти стоять в тишине.")}</p>
    {#if micFailed}<div class="notice bad"><CircleAlert size={15} />{uiText(" Микрофон не работает: ")}{uiText(app.status?.workers?.microphone?.error || app.status?.workers?.vosk?.error || "нет доступа или отключён")}{uiText(". Подключите его или выберите другой; если Windows запретил доступ — Параметры → Конфиденциальность → Микрофон.")}</div>{/if}
    <label class="field"><span>{uiText("Микрофон")}</span>
      <select value={String(get("audio.device") ?? "")} onchange={(e) => { const v = e.currentTarget.value; set("audio.device", v === "" ? null : Number(v)); set("audio.device_name", devices.find((d) => String(d.index) === v)?.name ?? null); }}>
        <option value="">{uiText("По умолчанию Windows")}</option>
        {#each devices as d}<option value={String(d.index)}>{d.name}</option>{/each}
      </select></label>
    <div class="meter"><MicMeter /></div>
    {#if app.dirty}<div class="notice warn">{uiText("Новый микрофон начнёт работать после перезапуска. ")}<button class="btn sm" onclick={() => applySettings().catch(toastError)}>{uiText("Перезапустить")}</button></div>{/if}
    <button class="btn primary" onclick={() => (step = 1)}>{uiText("Дальше")}</button>
  {:else if step === 1}
    <p class="muted">{uiText("Помолчите 3 секунды — измерю фоновый шум.")}</p>
    <button class="btn primary" disabled={busy} onclick={async () => { noise = await measure("noise", 3); }}>
      {#if busy}<LoaderCircle size={14} class="spin" />{uiText(" Тишина… ")}{uiText(countdown)}{:else}<Mic size={14} />{uiText(" Измерить тишину")}{/if}</button>
    {#if noise}
      <div class="notice {verdict(noise)}">{#if !noise.advice.length}<CircleCheck size={15} />{:else}<CircleAlert size={15} />{/if}
        <div>{uiText("Фон: ")}<b>{uiText(noise.db)}{uiText(" дБ")}</b> <span class="dim">{uiText("(ниже −50 — тихо, выше −40 — шумно)")}</span>{#each noise.advice as a}<p>{uiText(a)}</p>{/each}</div></div>
      <button class="btn" onclick={() => (step = 2)}>{uiText("Дальше")}</button>
    {/if}
  {:else if step === 2}
    <p class="muted">{uiText("Нажмите и прочитайте вслух обычным голосом (у вас 3,5 секунды):")}</p>
    <select bind:value={phrase} aria-label={uiText("Контрольная фраза")}>{#each PHRASES as p}<option value={p}>{uiText(p)}</option>{/each}</select>
    <p class="say">«{phrase}»</p>
    <button class="btn primary" disabled={busy} onclick={async () => { speech = await measure("speech", 3.5); }}>
      {#if busy}<LoaderCircle size={14} class="spin" />{uiText(" Говорите… ")}{uiText(countdown)}{:else}<Mic size={14} />{uiText(" Записать фразу")}{/if}</button>
    {#if speech}
      <div class="notice {verdict(speech)}">{#if !speech.advice.length}<CircleCheck size={15} />{:else}<CircleAlert size={15} />{/if}
        <div>
          <p>{uiText("Голос: ")}<b>{uiText(speech.speech_db)}{uiText(" дБ")}</b>{#if speech.snr !== undefined}{uiText(", громче фона на ")}<b>{uiText(speech.snr)}{uiText(" дБ")}</b> <span class="dim">{uiText("(хорошо — от 15)")}</span>{/if}{#if speech.clipped}{uiText(" · перегруз ")}{uiText(speech.clipped)}%{/if}</p>
          {#if speech.engine}<p>{uiText("Услышал (")}{speech.engine}): «{speech.text || uiText("ничего")}»{#if speech.matched}{uiText(" — совпало слов ")}{uiText(speech.matched.words)}{uiText(" из ")}{uiText(speech.matched.of)}{/if}</p>{/if}
          {#each speech.advice as a}<p>{uiText(a)}</p>{/each}
          <p class="dim small">{uiText("Одна фраза — грубый ориентир, а не точный процент качества. Запись не сохраняется.")}</p>
        </div></div>
      <div class="row-btns"><button class="btn" onclick={() => (speech = null)}><RotateCcw size={14} />{uiText(" Ещё раз")}</button><button class="btn" onclick={() => (step = 3)}>{uiText("Дальше")}</button></div>
      {#if speech.matched && speech.matched.words < speech.matched.of * 0.6}
        <p class="dim small">{uiText("Если распознаёт плохо: в «Распознавание речи» выберите GigaAM (точнее) или vosk (легче для слабого ПК). Голос озвучки от этого не меняется.")}</p>
      {/if}
    {/if}
  {:else if step === 3}
    <p class="muted">{uiText("Нажмите «Проверить» и скажите «")}{uiText((app.status?.wake_word ?? "Джарвис").replace(/^./, (c) => c.toUpperCase()))}{uiText("». Если чувствительность не подходит — она в разделе «Обращение» ниже.")}</p>
    <button class="btn primary" disabled={busy} onclick={checkWake}>{#if busy}<LoaderCircle size={14} class="spin" />{uiText(" Слушаю 8 секунд…")}{:else}<Ear size={14} />{uiText(" Проверить")}{/if}</button>
    {#if wakeHeard === true}<div class="notice ok"><CircleCheck size={15} />{uiText(" Услышал обращение.")}</div><button class="btn" onclick={() => (step = 4)}>{uiText("Дальше")}</button>{/if}
    {#if wakeHeard === false}<div class="notice warn"><CircleAlert size={15} />{uiText(" Обращение не услышано. Скажите имя чётче или поднимите «Чувствительность к имени» на 10–20%. Если фон шумный — включите фильтр шума.")}</div>{/if}
  {:else}
    <p class="muted">{uiText("Нажмите «Проверить» и скажите «Джарвис, который час». Джарвис ответит по-настоящему, а здесь появится, как он понял фразу.")}</p>
    <button class="btn primary" disabled={busy} onclick={checkCommand}>{#if busy}<LoaderCircle size={14} class="spin" />{uiText(" Жду команду…")}{:else}<Workflow size={14} />{uiText(" Проверить команду")}{/if}</button>
    {#if route}<div class="notice {route.route === 'none' ? 'warn' : 'ok'}"><div><b>{uiText(route.title)}</b>{#if route.phrase}<p>{uiText("Услышано: «")}{uiText(route.phrase)}»</p>{/if}{#if route.detail}<p class="dim">{uiText(route.detail)}</p>{/if}</div></div>{/if}
    {#if route && route.route !== "none"}<p class="ok-line"><CircleCheck size={15} />{uiText(" Готово: микрофон, обращение и команды работают.")}</p>{/if}
  {/if}
</div>

<style>
  .wizard {
    display: flex;
    flex-direction: column;
    gap: 12px;
    align-items: flex-start;
  }
  .wizard > * {
    max-width: 100%;
  }
  .steps {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    list-style: none;
    padding: 0;
    margin: 0;
  }
  .steps button {
    height: 28px;
    padding: 0 10px;
    border-radius: 999px;
    border: 1px solid var(--line-2);
    background: var(--surface-2);
    color: var(--text-2);
    font: inherit;
    font-size: 12.5px;
    cursor: pointer;
  }
  .steps .active button {
    background: var(--accent);
    color: var(--accent-ink);
    border-color: transparent;
  }
  .steps .done button {
    color: var(--ok);
  }
  .meter {
    width: 100%;
  }
  .say {
    font-size: 17px;
    font-weight: 600;
  }
  .notice {
    width: 100%;
  }
  .notice p {
    margin-top: 3px;
  }
  .small {
    font-size: 12px;
  }
  .row-btns {
    display: flex;
    gap: 8px;
  }
  .ok-line {
    display: flex;
    gap: 6px;
    align-items: center;
    color: var(--ok);
    font-weight: 600;
  }
</style>
