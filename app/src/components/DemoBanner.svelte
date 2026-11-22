<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  // Индикатор записи «Покажу один раз»: виден на любой странице, остановка — одной кнопкой.
  import { Circle, Square } from "@lucide/svelte";
  import { app, navigate, toastError } from "../lib/store.svelte";
  import { api } from "../lib/api";
  import { drafts } from "../lib/drafts.svelte";

  let seconds = $state(0);
  const last = $derived([...app.feed].reverse().find((e) => e.kind === "demo") as any);
  const recording = $derived(last?.state === "recording" || last?.state === "step");
  const lastStep = $derived([...app.feed].reverse().find((e: any) => e.kind === "demo" && e.state === "step") as any);
  $effect(() => {
    if (!recording) return;
    const started = Date.now();
    const timer = setInterval(() => (seconds = Math.round((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  });
  $effect(() => { if (last?.state === "limit") stop(); });

  async function stop() {
    try {
      const r = await api.scenarioOp<{ draft: any; notes: string[] }>({ op: "demo_stop" });
      if (r.draft) {
        drafts.fromTask = { draft: r.draft, skipped: r.notes };
        navigate("commands", "task");
      } else toastError(r.notes[0]);
    } catch (e) { toastError(e); }
  }
</script>

{#if recording}
  <div class="demo" role="status">
    <Circle size={12} fill="currentColor" class="rec" />
    <b>{uiText("Запись: показываю один раз")}</b>
    <span class="mono">{uiText(Math.floor(seconds / 60))}:{uiText(String(seconds % 60).padStart(2, "0"))}</span>
    <span class="dim small">{uiText(lastStep?.text ?? "Откройте программы и расставьте окна. Клавиши и текст не записываются.")}</span>
    <button class="btn stop sm" onclick={stop}><Square size={12} />{uiText(" Остановить и показать шаги")}</button>
  </div>
{/if}

<style>
  .demo {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    padding: 8px 14px;
    background: var(--bad-soft);
    border-bottom: 1px solid color-mix(in srgb, var(--bad) 40%, transparent);
    color: var(--text);
  }
  .demo :global(.rec) {
    color: var(--bad);
    animation: blink 1s ease-in-out infinite;
  }
  .demo .btn {
    margin-left: auto;
  }
  .small {
    font-size: 12.5px;
  }
  @keyframes blink {
    50% {
      opacity: 0.3;
    }
  }
</style>
