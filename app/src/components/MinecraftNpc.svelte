<script lang="ts">
  import { onMount } from "svelte";
  import { invoke } from "@tauri-apps/api/core";
  import { revealItemInDir, openUrl } from "@tauri-apps/plugin-opener";
  import { app } from "../lib/store.svelte";
  import { t } from "../lib/i18n.svelte";
  import { open } from "../lib/fileDialogs";

  type State = { paired: boolean; state?: string; message?: string; x?: number; y?: number; z?: number;
    platform?: "paper" | "fabric"; kind?: string; gameMode?: string; neoforge_available?: boolean };
  let snapshot = $state<State>();
  let platform = $state<"paper" | "fabric">("paper");
  let instructionsOpen = $state(true);
  let token = $state("");
  let text = $state("");
  let reply = $state("");
  let error = $state("");
  let pollError = $state("");
  let file = $state("");
  let neoForgeFile = $state("");
  let pending = $state("");
  let asking = $state(false);
  let generation = 0;
  const endpoint = "/api/minecraft/npc";

  onMount(() => {
    let active = true;
    let polling = false;
    async function refresh() {
      if (!app.status || pending || polling || document.hidden) return;
      const current = generation;
      polling = true;
      try {
        const next = await invoke<State>("core_post", { path: endpoint, body: { op: "status" } });
        if (active && generation === current) {
          snapshot = next;
          pollError = "";
          if (next.paired && next.platform) platform = next.platform;
        }
      } catch (reason) {
        if (active && generation === current && snapshot?.paired) {
          pollError = String(reason);
        }
      } finally { polling = false; }
    }
    void refresh();
    const timer = setInterval(refresh, 1500);
    return () => { active = false; clearInterval(timer); };
  });

  async function run(op: string) {
    if (pending) return;
    generation += 1;
    pending = op;
    error = "";
    pollError = "";
    try {
      if (op === "package") {
        file = (await invoke<{ file: string }>("core_post", { path: endpoint, body: { op, platform } })).file;
      } else if (op === "package_neoforge") {
        neoForgeFile = (await invoke<{ file: string }>("core_post", { path: endpoint, body: { op: "package", platform: "neoforge" } })).file;
      } else if (op === "pair" && platform === "fabric") {
        const folder = await open({ directory: true, title: "Выберите папку scripts мира Minecraft" });
        if (typeof folder === "string") snapshot = await invoke<State>("core_post", { path: endpoint, body: { op, platform, folder } });
      } else {
        snapshot = await invoke<State>("core_post", { path: endpoint, body: op === "pair" ? { op, platform, token: token.trim() } : { op } });
      }
    } catch (reason) { error = String(reason); }
    finally {
      if (op === "pair") token = "";
      pending = "";
    }
  }
  async function askNpc() {
    if (asking || !text.trim()) return;
    asking = true;
    error = "";
    try {
      reply = (await invoke<{ reply: string }>("core_post", { path: endpoint, body: { op: "ask", text } })).reply;
      text = "";
    } catch (reason) { error = String(reason); }
    finally { asking = false; }
  }
  const gameModes: Record<string, string> = { survival: "Выживание", creative: "Творческий", adventure: "Приключение", spectator: "Наблюдатель" };
</script>

<section class="card">
  <h2>{t("Напарник без отдельного аккаунта")}</h2>
  <p>{t("Добавьте персонажа с обликом игрока в свой мир на этом компьютере. Minecraft Java Edition 1.21.11.")}</p>
  <div class="buttons">
    <label>{t("Платформа мира")} <select bind:value={platform} onchange={() => { file = ""; error = ""; }} disabled={!!pending || !!snapshot?.paired}>
      <option value="paper">Paper 1.21.11</option><option value="fabric">Fabric 1.21.11 + Carpet</option>
    </select></label>
    <button class="btn" disabled={!app.status || !!pending} onclick={() => run("package")}>{t("Подготовить мод Minecraft")}</button>
    {#if file}<button class="btn" onclick={() => revealItemInDir(file).catch(reason => error = String(reason))}>{t("Показать в папке")}</button>{/if}
  </div>
  {#if file}<p class="mono dim">{file}</p>{/if}
  <button type="button" class="fold-toggle" aria-expanded={instructionsOpen} aria-controls="mc-npc-help" onclick={() => instructionsOpen = !instructionsOpen}>{instructionsOpen ? "▾" : "▸"} {t("Как подключить напарника")}</button>
  {#if instructionsOpen}<div id="mc-npc-help">
    {#if platform === "paper"}
      <ol>
        <li>{t("Положите подготовленный JAR в папку plugins сервера Paper. Если установлен ShelterNpc 0.1.0, замените его при выключенном сервере.")}</li>
        <li>{t("Войдите на сервер с правами оператора и выполните /shelternpc pair. Нажмите на сообщение в чате, чтобы скопировать код.")}</li>
        <li>{t("Вставьте код ниже, подключитесь и нажмите «Вызвать напарника».")}</li>
      </ol>
      <p class="dim">{t("Paper показывает персонажа со скином игрока. Он умеет подходить и следовать за вами.")}</p>
    {:else}
      <ol>
        <li>{t("Установите Carpet 1.4.193 для Fabric 1.21.11 в папку mods. Подойдёт одиночный мир с разрешёнными командами или свой сервер на этом компьютере.")}
          <button class="btn sm" onclick={() => openUrl("https://github.com/gnembon/fabric-carpet/releases/tag/1.4.193").catch(reason => error = String(reason))}>Carpet 1.4.193</button></li>
        <li>{t("Распакуйте подготовленный ZIP в папку мира. В игре выполните /script load sheltercompanion, затем /sheltercompanion pair.")}</li>
        <li>{t("В течение минуты выберите получившуюся папку scripts. Затем нажмите «Вызвать напарника».")}</li>
      </ol>
      <p class="dim">{t("Carpet создаёт отдельного игрока в мире. На открытом месте он может подойти и следовать за вами.")}</p>
    {/if}
    <p class="dim">{t("Ответы Джарвиса появляются в вашем игровом чате после вызова напарника.")}</p>
  </div>{/if}
  {#if !snapshot?.paired}
    {#if platform === "paper"}
      <form class="buttons" onsubmit={(e) => { e.preventDefault(); void run("pair"); }}>
        <label>{t("Код подключения")} <input type="password" maxlength="64" autocomplete="off" bind:value={token} /></label>
        <button class="btn primary" disabled={!app.status || !!pending || !/^[a-f0-9]{64}$/.test(token.trim())}>{t("Подключить напарника")}</button>
      </form>
    {:else}
      <div class="buttons"><button class="btn primary" disabled={!app.status || !!pending} onclick={() => run("pair")}>{t("Выбрать папку scripts и подключить")}</button></div>
    {/if}
  {:else}
    <div class="buttons">
      {#if snapshot.x === undefined && ["idle", "spawn_failed", "name_taken"].includes(snapshot.state ?? "")}
        <button class="btn primary" disabled={!!pending} onclick={() => run("spawn")}>{t("Вызвать напарника")}</button>
      {:else if snapshot.x !== undefined}
        <button class="btn" disabled={!!pending} onclick={() => run("come")}>{t("Подойди ко мне")}</button>
        <button class="btn" disabled={!!pending} onclick={() => run("follow")}>{t("Следуй за мной")}</button>
        <button class="btn" disabled={!!pending} onclick={() => run("stop")}>{t("Остановить действие")}</button>
      {/if}
      <button class="btn" disabled={!!pending} onclick={() => run("disconnect")}>{t("Отключить напарника")}</button>
    </div>
    {#if snapshot.x !== undefined}
      <form class="buttons" onsubmit={(e) => { e.preventDefault(); void askNpc(); }}>
        <label>{t("Спросить напарника")} <input type="text" maxlength="200" bind:value={text} /></label>
        <button class="btn" disabled={!!pending || asking || !text.trim()}>{t(asking ? "Думаю…" : "Отправить")}</button>
      </form>
      <p class="dim">{t("Сообщение отправляется модели чата, выбранной в Джарвисе.")}</p>
      {#if reply}<p role="status">{reply}</p>{/if}
    {/if}
    <p role="status">{t(snapshot.message ?? "")}{snapshot.x !== undefined ? ` · ${snapshot.x}, ${snapshot.y}, ${snapshot.z}` : ""}</p>
    {#if snapshot.gameMode}<p>{t("Игровой режим")}: {t(gameModes[snapshot.gameMode] ?? "Нет данных")}</p>{/if}
    {#if snapshot.x !== undefined && snapshot.kind === "legacy"}<p class="dim">{t("На сервере старая версия ShelterNpc. Подготовьте новый JAR, чтобы сменить облик напарника.")}</p>{/if}
  {/if}
  {#if error || pollError}<p role="alert" class="notice bad">{t(error || pollError)}</p>{/if}
  {#if snapshot?.neoforge_available || neoForgeFile}<div class="neo-forge">
    <h3>NeoForge 1.21.1</h3>
    <p>{t("Отдельный мод для одиночного мира или сервера NeoForge. После установки вызовите напарника командой /companion summon и откройте его инвентарь через !inv.")}</p>
    <div class="buttons">
      <button class="btn" disabled={!app.status || !!pending} onclick={() => run("package_neoforge")}>{t("Подготовить мод NeoForge")}</button>
      {#if neoForgeFile}<button class="btn" onclick={() => revealItemInDir(neoForgeFile).catch(reason => error = String(reason))}>{t("Показать в папке")}</button>{/if}
    </div>
  </div>{/if}
</section>

<style>
  .buttons { flex-wrap: wrap; margin-top: 12px; }
  .fold-toggle { background: transparent; border: 0; color: var(--accent); cursor: pointer; font-weight: 600; margin-top: 10px; padding: 5px 0; }
  .neo-forge { border-top: 1px solid var(--line); margin-top: 16px; }
  li { margin-block: 4px; }
  input { max-width: 100%; }
</style>
