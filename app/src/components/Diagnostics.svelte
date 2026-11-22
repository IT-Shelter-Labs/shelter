<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";
  import { voiceName, voicePhase, voiceHint } from "../lib/voiceStatus";

  // Что работает, что нет и что с этим делать. Отчёт копируется без секретов и личных данных.
  import { ClipboardCopy, RotateCw, CircleCheck, CircleAlert, CircleDashed } from "@lucide/svelte";
  import { app, toast, toastError } from "../lib/store.svelte";
  import { api } from "../lib/api";

  const names: Record<string, { title: string; fix: string }> = {
    vosk: { title: "Слух (распознавание)", fix: "Проверьте микрофон в «Голос и слух» и перезапустите ядро" },
    microphone: { title: "Микрофон", fix: "Выберите другое устройство или подключите микрофон заново" },
    detector: { title: "Звуковой триггер", fix: "Необязательный модуль — можно выключить" },
  };
  const modules = $derived.by(() => {
    const s = app.status;
    if (!s) return [];
    return [
      ...Object.entries(s.workers ?? {}).map(([id, w]) => ({ id, title: names[id]?.title ?? id, ok: w.state === "running",
        text: w.error || ({ running: "Работает", repairing: "Восстанавливается", error: "Ошибка", failed: "Не запустилось" } as Record<string, string>)[w.state] || w.state, fix: names[id]?.fix ?? "" })),
      { id: "asr", title: "Точное распознавание", ok: s.asr === "gigaam", text: s.asr === "gigaam" ? "GigaAM" : "vosk (запасное)", fix: "Установите GigaAM в «Компонентах» ниже" },
      { id: "voice", title: "Голос", ok: s.clone_ready !== false && !s.voice_status?.reason,
        text: [uiText(voiceName(s.voice)), uiText(voicePhase(s.voice_status, s.clone_ready))].filter(Boolean).join(" · "), fix: voiceHint(s.voice_status) },
      { id: "llm", title: "Нейросеть", ok: s.llm.enabled, text: s.llm.enabled ? `${s.llm.provider}: ${s.llm.model}` : "выключена", fix: "Включите в «Модели и разум», если нужны свободные ответы" },
      { id: "echo", title: "Подавление эха", ok: !s.echo?.error, text: s.echo ? (s.echo.error || `колонки: ${s.echo.speaker}`) : "не используется", fix: "Если не нужно — выключите «Я пользуюсь колонками»" },
    ];
  });

  function report() {
    // Только техническое: версии, состояния модулей и тексты ошибок — без имён файлов, ключей и переписки.
    const strip = (t: string) => String(t ?? "").replace(/[A-Z]:\\Users\\[^\\\s"]+/gi, "%USERPROFILE%").replace(/(token|key|password)=\S+/gi, "$1=***");
    const s = app.status;
    const data = {
      app: app.info?.version, platform: app.info?.platform, core: { running: app.core?.running, error: strip(app.core?.lastError ?? "") },
      status: s && { asr: s.asr, voice: s.voice, clone_ready: s.clone_ready, wake_engine: s.wake_engine, llm: { provider: s.llm.provider, enabled: s.llm.enabled },
        echo: s.echo && { active: !s.echo.error, error: strip(s.echo.error ?? "") }, in_game: s.in_game,
        workers: Object.fromEntries(Object.entries(s.workers ?? {}).map(([k, w]) => [k, { state: w.state, error: strip(w.error) }])) },
      errors: app.feed.filter((e) => e.kind === "error").slice(-15).map((e) => ({ time: new Date(e.time * 1000).toISOString(), text: strip(e.text ?? "") })),
    };
    navigator.clipboard.writeText(JSON.stringify(data, null, 2)).then(() => toast("Отчёт скопирован. Личные пути и ключи убраны", "success"), toastError);
  }
</script>

<div class="card" id="diagnostics">
  <div class="card-head">
    <div class="caps">{uiText("Диагностика")}</div>
    <div class="actions">
      <button class="btn sm" onclick={report}><ClipboardCopy size={14} />{uiText(" Скопировать отчёт")}</button>
      <button class="btn sm" disabled={!app.core?.running} onclick={() => api.coreRestart().then(() => toast("Перезапускаю ядро…")).catch(toastError)}><RotateCw size={14} />{uiText(" Перезапустить ядро")}</button>
    </div>
  </div>
  {#if !app.core?.running}
    <div class="empty"><CircleDashed size={22} /><b>{uiText("Джарвис выключен")}</b><span>{uiText("Включите его кнопкой питания вверху справа, чтобы проверить модули.")}</span></div>
  {:else if !modules.length}
    <div class="empty"><CircleDashed size={22} class="spin" /><span>{uiText("Ядро запускается…")}</span></div>
  {:else}
    <ul>
      {#each modules as m}
        <li>
          {#if m.ok}<CircleCheck size={16} color="var(--ok)" />{:else}<CircleAlert size={16} color="var(--warn)" />{/if}
          <span class="name">{uiText(m.title)}</span>
          <span class="text mono">{uiText(m.text)}</span>
          {#if !m.ok && m.fix}<span class="fix">{uiText(m.fix)}</span>{/if}
        </li>
      {/each}
    </ul>
  {/if}
  {#if app.core?.lastError}<div class="notice bad"><CircleAlert size={16} /> {uiText(app.core.lastError)}</div>{/if}
</div>

<style>
  .actions {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  ul {
    list-style: none;
    margin: 8px 0 0;
    padding: 0;
  }
  li {
    display: grid;
    grid-template-columns: 20px 200px 1fr;
    gap: 4px 10px;
    align-items: center;
    padding: 8px 0;
    border-bottom: 1px solid var(--line);
  }
  li:last-child {
    border-bottom: none;
  }
  .name {
    font-weight: 600;
  }
  .text {
    font-size: 12px;
    color: var(--text-2);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .fix {
    grid-column: 2 / 4;
    font-size: 12.5px;
    color: var(--warn);
  }
</style>
