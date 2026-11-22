<script lang="ts">
  import { t as uiText } from "../../lib/i18n.svelte";

  import { Play, Pause, SkipBack, SkipForward, Film } from "@lucide/svelte";
  import { onMount } from "svelte";
  import { app, toastError } from "../../lib/store.svelte";
  import { api } from "../../lib/api";
  import { poll } from "../../lib/poll";

  let now = $state<Awaited<ReturnType<typeof api.media>>["playing"]>(null);
  onMount(() => poll(async () => { if (app.status) now = (await api.media()).playing; }, 4000));

  async function press(key: string) {
    if (!now) return;
    try {
      const result = await api.mediaControl(key,now.source);
      if (!result.ok) throw new Error("Плеер не выполнил команду");
      setTimeout(async () => { now = (await api.media().catch(() => ({ playing: now }))).playing; }, 900);
    } catch (e) {
      toastError(e);
    }
  }
</script>

{#if !now}
  <p class="line dim"><Film size={14} />{uiText("Запустите видео или музыку. Здесь появится плеер, если он доступен системе.")}</p>
{:else}
  <div class="track">
    <div class="meta"><b>{now.title || uiText("Без названия")}</b><span class="dim">{now.artist || now.app}</span></div>
    <div class="controls">
      <button class="btn ghost icon sm" disabled={now.previous_enabled === false} aria-label={uiText("Предыдущий элемент")} onclick={() => press("previous")}><SkipBack size={15} /></button>
      <button class="btn icon" aria-label={uiText(now.playing ? "Пауза" : "Продолжить")} onclick={() => press(now?.playing ? "pause" : "play")}>
        {#if now.playing}<Pause size={16} />{:else}<Play size={16} />{/if}
      </button>
      <button class="btn ghost icon sm" disabled={now.next_enabled === false} aria-label={uiText("Следующий элемент")} onclick={() => press("next")}><SkipForward size={15} /></button>
    </div>
  </div>
{/if}

<style>
  .line { display: flex; gap: 8px; align-items: center; font-size: 13px; }
  .track { display: flex; align-items: center; gap: 12px; }
  .meta { flex: 1; min-width: 0; display: flex; flex-direction: column; }
  .meta b, .meta span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .meta span { font-size: 12.5px; }
  .controls { display: flex; align-items: center; gap: 4px; }
</style>
