<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  import { onDestroy } from "svelte";
  import { api } from "../lib/api";
  import { app } from "../lib/store.svelte";

  // Живой уровень микрофона (ядро отдаёт громкость последних 0.15 с).
  let db = $state(-90);
  let peak = $state(-90);
  const timer = setInterval(async () => {
    if (!app.core?.running) return;
    try {
      db = (await api.level()).db;
      peak = Math.max(db, peak - 1.5);
    } catch {
      /* ядро ещё поднимается */
    }
  }, 120);
  onDestroy(() => clearInterval(timer));

  const pct = (v: number) => Math.max(0, Math.min(100, ((v + 70) / 70) * 100));
  const quality = $derived(peak > -12 ? "слишком громко — отодвиньте микрофон" : peak > -42 ? "отлично" : peak > -58 ? "тихо — говорите ближе или прибавьте усиление" : "не слышно");
</script>

<div class="meter">
  <div class="bar"><div class="fill" style="width:{pct(db)}%"></div><div class="peak" style="left:{pct(peak)}%"></div></div>
  <div class="info mono"><span>{uiText(db.toFixed(0))}{uiText(" дБ")}</span><span class="dim">{uiText(app.core?.running ? quality : "ядро выключено")}</span></div>
</div>

<style>
  .meter {
    width: 100%;
  }
  .bar {
    position: relative;
    height: 12px;
    border-radius: 6px;
    background: #061219;
    border: 1px solid var(--line-2);
    overflow: hidden;
  }
  .fill {
    height: 100%;
    background: linear-gradient(90deg, #1b7fa3, #7fe6ff 70%, #ffb648 92%);
    transition: width 90ms linear;
  }
  .peak {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 2px;
    background: #fff;
    opacity: 0.8;
  }
  .info {
    display: flex;
    justify-content: space-between;
    font-size: 11.5px;
    margin-top: 4px;
    color: var(--accent-2);
  }
</style>
