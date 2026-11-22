<script lang="ts">
  import { t as uiText } from "../../lib/i18n.svelte";
  import { voiceName, voicePhase, voiceHint } from "../../lib/voiceStatus";

  // Что сейчас делает помощник — одним словом, и две главные кнопки: «Говорить» и «Стоп».
  import { Mic, Square, CircleAlert, Power, AudioLines, Cpu, BrainCircuit, Gamepad2 } from "@lucide/svelte";
  import Reactor from "../Reactor.svelte";
  import { app, get, navigate, refreshStatus, toastError } from "../../lib/store.svelte";
  import { api } from "../../lib/api";

  const s = $derived(app.status);
  const micFailed = $derived(["microphone", "vosk"].some((w) => ["failed", "error"].includes(s?.workers?.[w]?.state ?? "")));
  const phase = $derived(
    !app.core?.running ? "offline"
    : !s ? "starting"
    : micFailed ? "error"
    : s.confirming ? "confirm"
    : s.speaking ? "speaking"
    : s.thinking ? "thinking"
    : s.executing ? "executing"
    : s.recognizing ? "recognizing"
    : s.listening ? "listening"
    : "idle");
  const address = $derived(s?.persona?.address || "сэр");
  const wake = $derived(cap(s?.wake_word ?? "Джарвис"));
  const labels = $derived<Record<string, [string, string]>>({
    offline: ["Выключен", "Включите Джарвиса, чтобы он слушал"],
    starting: ["Запускаюсь", "Загружаю слух и голос…"],
    error: ["Не слышу микрофон", "Проверьте микрофон в настройках"],
    confirm: ["Жду подтверждения", "Скажите «да» или «нет»"],
    speaking: ["Говорю", "Скажите «стоп», чтобы прервать"],
    thinking: ["Думаю", s?.task ? `«${s.task}»` : "Нейросеть готовит ответ"],
    executing: ["Выполняю", s?.task || "Задача в работе"],
    recognizing: ["Распознаю", "Слушаю вашу фразу до конца"],
    listening: [`Слушаю, ${address}`, "Говорите просьбу"],
    idle: ["Готов", `Скажите «${wake}» или нажмите «Говорить»`],
  });
  const reactor = $derived(({ offline: "offline", starting: "offline", error: "offline", speaking: "speaking", thinking: "thinking", executing: "thinking", confirm: "listening", recognizing: "listening", listening: "listening" } as Record<string, any>)[phase] ?? "idle");
  const busy = $derived(["speaking", "thinking", "executing", "confirm", "recognizing", "listening"].includes(phase));

  function cap(t: string) { return t.charAt(0).toUpperCase() + t.slice(1); }
  async function talk() {
    try { await api.listen(); } catch (e) { toastError(e); }
  }
  async function stop() {
    try { await api.cancel(); await refreshStatus(); } catch (e) { toastError(e); }
  }
</script>

<section class="card glow status" aria-live="polite">
  <div class="reactor"><Reactor size={get("ui.lite", false) ? 120 : 150} state={reactor} /></div>
  <div class="info">
    <div class="phase {phase}"><span class="led"></span>{uiText(labels[phase][0])}</div>
    <p class="sub">{uiText(labels[phase][1])}</p>
    {#if (s?.queued ?? 0) > 0}<p class="dim small">{uiText("В очереди: ")}{uiText(s?.queued)}</p>{/if}
    <div class="buttons">
      {#if !app.core?.running}
        <button class="btn primary lg" onclick={() => api.coreStart().catch(toastError)}><Power size={17} />{uiText(" Включить")}</button>
      {:else}
        <button class="btn primary lg" disabled={!s} onclick={talk} title={uiText("Как сказать «" + String(wake) + "» (" + String(get('wake.hotkey', 'Ctrl+Alt+J')) + ")")}><Mic size={17} />{uiText(" Говорить")}</button>
        <button class="btn stop lg" disabled={!busy} onclick={stop} title={uiText("Остановить речь, задачу и сценарии")}><Square size={15} />{uiText(" Стоп")}</button>
      {/if}
    </div>
    {#if app.core?.lastError}<div class="notice bad small"><CircleAlert size={14} /> {uiText(app.core.lastError)}</div>{/if}
    {#if s}
      <div class="chips">
        <button class="chip {micFailed ? 'bad' : 'ok'}" title={uiText("Микрофон — открыть настройки слуха")} onclick={() => navigate("settings", "voice")}><Mic size={12} /> {uiText(s.mic || "микрофон по умолчанию")}</button>
        <span class="chip {s.asr === 'gigaam' ? 'ok' : 'warn'}" title={uiText("Распознавание речи")}><AudioLines size={12} /> {uiText(s.asr === "gigaam" ? "GigaAM" : "vosk")}</span>
        <span class="chip {s.clone_ready === false || s.voice_status?.reason ? 'warn' : 'ok'}" title={uiText(voiceHint(s.voice_status) || "Голос ответа")}><Cpu size={12} /> {uiText(voiceName(s.voice))}{#if voicePhase(s.voice_status, s.clone_ready)} · {uiText(voicePhase(s.voice_status, s.clone_ready))}{/if}</span>
        <span class="chip {s.llm.enabled ? 'ok' : 'warn'}" title={uiText("Нейросеть")}><BrainCircuit size={12} /> {uiText(s.llm.enabled ? s.llm.model : "без нейросети")}</span>
        {#if s.in_game}<span class="chip warn"><Gamepad2 size={12} />{uiText(" в игре")}</span>{/if}
      </div>
    {/if}
  </div>
</section>

<style>
  .status {
    display: flex;
    align-items: center;
    gap: 22px;
    padding: 18px 22px;
  }
  .reactor {
    flex: none;
  }
  .info {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .phase {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 22px;
    font-weight: 650;
    letter-spacing: -0.01em;
  }
  .led {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--text-3);
  }
  .phase.idle .led,
  .phase.listening .led,
  .phase.recognizing .led {
    background: var(--ok);
    box-shadow: 0 0 10px var(--ok);
  }
  .phase.thinking .led,
  .phase.executing .led,
  .phase.speaking .led {
    background: var(--accent-2);
    box-shadow: 0 0 10px var(--accent-2);
    animation: blink 1.2s ease-in-out infinite;
  }
  .phase.confirm .led,
  .phase.starting .led {
    background: var(--warn);
  }
  .phase.error .led {
    background: var(--bad);
  }
  @keyframes blink {
    50% {
      opacity: 0.35;
    }
  }
  .sub {
    color: var(--text-2);
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .small {
    font-size: 12.5px;
  }
  .buttons {
    display: flex;
    gap: 10px;
    margin: 8px 0 4px;
    flex-wrap: wrap;
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 4px;
  }
  button.chip {
    cursor: pointer;
    font: inherit;
    font-size: 12px;
  }
  @media (max-width: 640px) {
    .status {
      flex-direction: column;
      align-items: stretch;
      text-align: center;
    }
    .phase,
    .buttons,
    .chips {
      justify-content: center;
    }
  }
</style>
