<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { openUrl } from "@tauri-apps/plugin-opener";
  import { get, set, saveNow, toast, toastError } from "../lib/store.svelte";
  import { t } from "../lib/i18n.svelte";

  let { online }: { online: boolean } = $props();
  type Status = { connected: boolean; enabled: boolean; busy: boolean; queued: number; authenticated: boolean;
    companions: { id: number; name: string; jobs: string[] }[]; job: string };
  type Action = "status" | "spawn" | "pause" | "resume" | "send" | "gather" | "follow" | "stop";
  const names: Record<string, string> = { queued: "В очереди", running: "Выполняется", waiting: "Ожидает",
    completed: "Выполнено", cancelled: "Отменено", failed: "Ошибка" };
  let port = $state<number | undefined>(get("factorio.companion_port", 3210));
  let token = $state("");
  let open = $state(false);
  let status = $state<Status | null>(null);
  let busy = $state(false);
  let pendingPoll = false;
  let selected = $state<number | undefined>();
  let name = $state("");
  let task = $state("");
  let request = $state("");
  let resource = $state("iron-ore");
  let count = $state<number | undefined>(10);
  let player = $state(get<string>("factorio.player", ""));
  const activeJobs = $derived(status?.companions.find((entry) => entry.id === selected)?.jobs ?? []);

  async function send<T>(action: Action, fields: Record<string, unknown> = {}) {
    return invoke<T>("core_post", { path: "/api/factorio", body: { op: "companion", action, ...fields } });
  }
  async function refresh() {
    status = await send<Status>("status", { request_id: request });
    if (!status.companions.some((companion) => companion.id === selected)) selected = status.companions[0]?.id;
  }
  async function perform(action: Action) {
    busy = true;
    try {
      if (action === "spawn") selected = (await send<{ id: number }>(action, { text: name })).id;
      else if (action === "send") {
        request = (await send<{ request_id: string }>(action, { text: task, companion_id: selected })).request_id;
        task = "";
      } else if (action === "gather") {
        await send(action, { text: resource.trim(), companion_id: selected, count });
      } else if (action === "follow" || action === "stop") {
        await send(action, { text: player.trim(), companion_id: selected });
      } else if (action !== "status") await send(action);
      await refresh();
    } catch (error) { toastError(error); }
    finally { busy = false; }
  }
  async function save() {
    if (!port || !Number.isInteger(port) || port < 1 || port > 65535) return;
    set("factorio.companion_port", port);
    if (token) { set("factorio.companion_token", token.trim()); token = ""; }
    await saveNow();
    toast("Сохранено", "success");
  }
  function dashboard() {
    const savedPort = get<number>("factorio.companion_port", 3210);
    if (Number.isInteger(savedPort) && savedPort >= 1 && savedPort <= 65535)
      void openUrl("http://127.0.0.1:" + savedPort).catch(toastError);
  }
  $effect(() => {
    if (!open || !online || !status) return;
    const timer = setInterval(async () => {
      if (pendingPoll || busy || document.hidden) return;
      pendingPoll = true;
      try { await refresh(); }
      catch { status = null; }
      finally { pendingPoll = false; }
    }, 3500);
    return () => clearInterval(timer);
  });
</script>

<details bind:open>
  <summary>{t("Отдельный напарник Factorio")}</summary>
  <p>{t("Запустите локальный Factorio AI Companion 0.18.3 вместе с его модом. В его панели войдите в ChatGPT для свободных задач. В Shelter сохраните порт и токен сервера напарника.")}</p>
  <div class="controls">
    <label>{t("Порт напарника")} <input type="number" bind:value={port} min="1" max="65535" /></label>
    <label>{t("Токен напарника")} <input type="password" bind:value={token} autocomplete="off" /></label>
    <button class="btn" onclick={save}>{t("Сохранить")}</button>
    <button class="btn" onclick={dashboard}>{t("Открыть панель напарника")}</button>
    <button class="btn" disabled={!online || busy} onclick={() => perform("status")}>{t("Проверить подключение")}</button>
  </div>
  {#if status}
    <p role="status">{t(status.connected ? "Мир на связи" : "Нет связи с игровым миром")} ·
      {t(status.busy ? "Выполняется" : status.enabled ? "Жду задачу" : "На паузе")} · {t("В очереди")}: {status.queued}</p>
    <div class="controls">
      <label>{t("Имя напарника")} <input bind:value={name} maxlength="60" placeholder="Shelter" /></label>
      <button class="btn" disabled={busy || !status.connected} onclick={() => perform("spawn")}>{t("Создать персонажа")}</button>
      <button class="btn" disabled={busy || !status.connected || !status.authenticated || status.enabled} onclick={() => perform("resume")}>{t("Запустить агента")}</button>
      <button class="btn" disabled={busy} onclick={() => perform("pause")}>{t("Остановить напарников")}</button>
    </div>
    {#if !status.authenticated}<p class="dim">{t("Для задач текстом войдите в ChatGPT в панели напарника.")}</p>{/if}
    {#if status.companions.length}
      <label>{t("Напарник")} <select bind:value={selected}>{#each status.companions as person}
        <option value={person.id}>{person.name}</option>
      {/each}</select></label>
      <div class="controls">
        <label>{t("ID ресурса")} <input bind:value={resource} maxlength="160" placeholder="iron-ore" /></label>
        <label>{t("Количество")} <input type="number" bind:value={count} min="1" max="1000" /></label>
        <button class="btn" disabled={busy || !status.connected || !selected || !resource.trim() || !count} onclick={() => perform("gather")}>{t("Добыть ресурс")}</button>
        <label>{t("Имя игрока")} <input bind:value={player} maxlength="60" /></label>
        <button class="btn" disabled={busy || !status.connected || !selected || !player.trim()} onclick={() => perform("follow")}>{t("Следовать за игроком")}</button>
        <button class="btn" disabled={busy || !status.connected || !selected} onclick={() => perform("stop")}>{t("Остановить напарника")}</button>
      </div>
      {#if activeJobs.length}<p role="status">{t("Активные действия")}: {activeJobs.map((job) => t(({ gather: "Добыча", follow: "Следование", craft: "Крафт" } as Record<string, string>)[job] || job)).join(", ")}</p>{/if}
      <div class="controls">
        <textarea bind:value={task} maxlength="8000" rows="2" placeholder={t("Опишите задачу напарнику")} aria-label={t("Опишите задачу напарнику")}></textarea>
        <button class="btn primary" disabled={busy || !status.connected || !task.trim() || !selected} onclick={() => perform("send")}>{t("Отправить задачу")}</button>
      </div>
    {/if}
    {#if status.job}<p role="status">{t("Задача")}: {t(names[status.job] || status.job)}</p>{/if}
  {/if}
</details>

<style>
  .controls { display: flex; flex-wrap: wrap; align-items: end; gap: .55rem; margin-block: .6rem; }
  textarea { flex: 1 1 16rem; resize: vertical; }
  label { display: inline-flex; gap: .4rem; align-items: center; flex-wrap: wrap; }
  input[type="number"] { max-width: 6rem; }
</style>
