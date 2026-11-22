<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  import { onMount, onDestroy } from "svelte";
  import { Mic, Check, X, LoaderCircle, Trash2 } from "@lucide/svelte";
  import Toggle from "./Toggle.svelte";
  import Segmented from "./Segmented.svelte";
  import Range from "./Range.svelte";
  import { app, get, set, toast, toastError } from "../lib/store.svelte";
  import { api, on, type SetupEvent } from "../lib/api";

  // Узнавание хозяина: по желанию, каждый настраивает на своём компьютере.
  let status = $state<{ available?: boolean; enrolled?: boolean }>({});
  let recording = $state(0);
  let busy = $state("");
  let test = $state<{ score: number; owner: boolean } | null>(null);
  let unlisten: (() => void) | undefined;

  const PHRASES = [
    "Джарвис, какая сегодня погода и что у меня запланировано на вечер?",
    "Открой браузер и включи что-нибудь спокойное, пожалуйста.",
    "Напомни мне через полчаса проверить почту и позвонить другу.",
  ];

  async function refresh() {
    if (app.status) status = await api.speaker("status").catch(() => ({}));
  }

  onMount(async () => {
    await refresh();
    unlisten = await on<SetupEvent>("setup:event", (e) => {
      if (e.component === "speaker" && e.status === "ok") refresh();
      if (e.component === "speaker" && e.status === "error") toastError(e.message);
    });
  });
  onDestroy(() => unlisten?.());

  async function countdown(seconds: number, run: () => Promise<void>) {
    recording = seconds;
    const timer = setInterval(() => (recording = Math.max(0, recording - 1)), 1000);
    try {
      await run();
    } catch (e) {
      toastError(e);
    } finally {
      clearInterval(timer);
      recording = 0;
      busy = "";
    }
  }

  async function enable(on: boolean) {
    set("wake.owner.enabled", on);
    if (on && !status.available) {
      busy = "install";
      toast("Скачиваю модель узнавания голоса (27 МБ)…");
      await api.setupInstall(["speaker"]).catch(toastError);
    }
  }

  function enroll() {
    busy = "enroll";
    countdown(14, async () => {
      const r = await api.speaker("enroll", 14);
      status = { ...status, enrolled: true };
      toast(r.consistency && r.consistency < 0.7 ? "Голос записан, но неровно — лучше перезаписать в тишине" : "Голос запомнен, сэр", r.consistency && r.consistency < 0.7 ? "info" : "success");
    });
  }

  function check() {
    busy = "test";
    test = null;
    countdown(4, async () => {
      const r = await api.speaker("test", 4);
      test = { score: r.score ?? 0, owner: !!r.owner };
    });
  }

  async function forget() {
    await api.speaker("forget").catch(toastError);
    status = { ...status, enrolled: false };
    test = null;
  }
</script>

<div class="owner">
  <div class="line">
    <div class="label">
      <b>{uiText("Слушаться только моего голоса")}</b>
      <span>{uiText("Защита от «Джарвис, выключи компьютер» из голосового чата, стрима, YouTube или от гостей. Голос хранится только на этом компьютере.")}</span>
    </div>
    <Toggle checked={get("wake.owner.enabled", false)} onchange={enable} />
  </div>

  {#if get("wake.owner.enabled", false)}
    <div class="line">
      <div class="label"><b>{uiText("Чужой голос")}</b><span>{uiText("«Только вопросы» — гость может спросить погоду или новости, но ничего не сделает с компьютером")}</span></div>
      <Segmented value={get("wake.owner.mode", "soft")} options={[{ value: "soft", label: "Только вопросы" }, { value: "strict", label: "Не слушать" }]} onchange={(v) => set("wake.owner.mode", v)} />
    </div>

    {#if !app.status}
      <p class="dim note">{uiText("Включите Джарвиса, чтобы записать голос.")}</p>
    {:else if !status.available}
      <p class="note"><LoaderCircle class="spin" size={14} />{uiText(" Скачиваю модель узнавания…")}</p>
    {:else}
      {#if recording && busy === "enroll"}
        <div class="read">
          <div class="caps">{uiText("Читайте вслух, обычным голосом — ")}{uiText(recording)}{uiText(" с")}</div>
          {#each PHRASES as p}<p>«{uiText(p)}»</p>{/each}
        </div>
      {/if}
      <div class="buttons">
        <button class="btn" disabled={!!busy} onclick={enroll}>
          {#if busy === "enroll"}<span class="rec"></span>{uiText(" Записываю…")}{:else}<Mic size={15} /> {uiText(status.enrolled ? "Перезаписать мой голос" : "Записать мой голос")}{/if}
        </button>
        {#if status.enrolled}
          <button class="btn" disabled={!!busy} onclick={check}>
            {#if busy === "test"}<span class="rec"></span>{uiText(" Скажите любую фразу… ")}{uiText(recording)}{:else}{uiText("Проверить, узнаёт ли")}{/if}
          </button>
          <button class="btn ghost" disabled={!!busy} onclick={forget} title={uiText("Забыть голос")}><Trash2 size={15} /></button>
        {/if}
      </div>
      {#if test}
        <p class="verdict" class:ok={test.owner}>
          {#if test.owner}<Check size={15} />{uiText(" Узнал вас (сходство ")}{uiText(test.score.toFixed(2))}){:else}<X size={15} />{uiText(" Не узнал (сходство ")}{uiText(test.score.toFixed(2))}{uiText(") — перезапишите голос в тишине или снизьте строгость")}{/if}
        </p>
      {/if}
      {#if status.enrolled}
        <div class="line">
          <div class="label"><b>{uiText("Строгость")}</b><span>{uiText("Выше — надёжнее от чужих, но иногда может не узнать вас (простуда, другой микрофон)")}</span></div>
          <Range value={get("wake.owner.threshold", 0.46)} min={0.3} max={0.7} step={0.02} format={(v) => v.toFixed(2)} onchange={(v) => set("wake.owner.threshold", v)} />
        </div>
      {:else}
        <p class="dim note">{uiText("Пока голос не записан, Джарвис слушается всех.")}</p>
      {/if}
    {/if}
  {/if}
</div>

<style>
  .owner {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .line {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 18px;
    padding: 10px 0;
    border-bottom: 1px solid var(--line);
  }
  .label {
    display: flex;
    flex-direction: column;
    gap: 2px;
    max-width: 560px;
  }
  .label span {
    color: var(--text-2);
    font-size: 12.5px;
  }
  .buttons {
    display: flex;
    gap: 8px;
    padding: 8px 0;
    flex-wrap: wrap;
  }
  .read {
    padding: 12px 14px;
    border-radius: 12px;
    border: 1px solid rgba(255, 182, 72, 0.4);
    background: rgba(255, 182, 72, 0.06);
    color: #ffd8a0;
  }
  .read p {
    margin: 6px 0 0;
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
  .note {
    font-size: 12.5px;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .verdict {
    display: flex;
    align-items: center;
    gap: 6px;
    color: var(--warn);
    font-size: 13px;
  }
  .verdict.ok {
    color: var(--ok);
  }
</style>
