<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { Blocks, Factory, MapPinned, FolderOpen, Download, RefreshCw } from "@lucide/svelte";
  import MinecraftCompanion from "../components/MinecraftCompanion.svelte";
  import MinecraftNpc from "../components/MinecraftNpc.svelte";
  import { open } from "../lib/fileDialogs";
  import { app, get, set, nav, toastError } from "../lib/store.svelte";
  import { t as uiText } from "../lib/i18n.svelte";

  const games = [
    { id: "minecraft", title: "Minecraft", icon: Blocks, detail: "Напарник в мире Java Edition" },
    { id: "factorio", title: "Factorio", icon: Factory, detail: "Производство, инвентарь и исследования" },
    { id: "hoi4", title: "Hearts of Iron IV", icon: MapPinned, detail: "Обзор открытого игрового экрана" },
  ];
  type Job = { recipe: string; total: number; done: number; state: keyof typeof jobStates };
  const jobStates = {
    waiting: "Ожидает свободной очереди", crafting: "Изготавливается", complete: "Выполнено",
    blocked: "Не хватает материалов или рецепт недоступен", stopped: "Остановлено", timeout: "Истекло время задачи",
  };
  type State = { player: string; surface: string; x: number; y: number; research: string; progress: number; age: number; inventory: { name: string; count: number }[]; job?: Job };
  type Snapshot = { path: string; state: State | null; message: string };
  let selected = $state("");
  const game = $derived(selected || nav.sub || "minecraft");
  let status = $state<Snapshot | null>(null);
  let mod = $state("");
  let factorioBranch = $state<"2.0" | "2.1">("2.1");
  let hoiMod = $state("");
  let minecraftMode = $state<"player" | "npc">("player");
  let busy = $state(false);
  const saved = $derived(get<string>("factorio.snapshot", ""));
  const online = $derived(!!app.status);
  let recipe = $state("");
  let quantity = $state<number | undefined>(10);
  const command = $derived(/^[a-zA-Z0-9_-]{1,160}$/.test(recipe.trim()) && quantity && Number.isInteger(quantity) && quantity <= 100 && quantity >= 1
    ? `/shelter-craft ${recipe.trim()} ${quantity}` : "");

  $effect(() => {
    if (game !== "factorio" || !online) return;
    const path = saved;
    let active = true;
    let pending = false;
    async function poll() {
      if (pending || document.hidden) return;
      pending = true;
      try {
        const next = await factorio<Snapshot>({ op: "status", path });
        if (active) status = next;
      } catch {
        if (active) status = null;
      } finally { pending = false; }
    }
    void poll();
    const timer = setInterval(poll, 2200);
    return () => { active = false; clearInterval(timer); };
  });

  function factorio<T>(body: Record<string, unknown>) {
    return invoke<T>("core_post", { path: "/api/factorio", body });
  }
  async function check(path = saved) {
    busy = true;
    try { status = await factorio({ op: "status", path }); }
    catch (error) { toastError(error); }
    finally { busy = false; }
  }
  async function choose() {
    try {
      const path = await open({ title: "Выберите файл Factorio", filters: [{ name: "Данные Factorio", extensions: ["json"] }] });
      if (typeof path === "string" && /[\\/]shelter-factorio\.json$/i.test(path)) {
        set("factorio.snapshot", path);
        await check(path);
      } else if (path) toastError("Выберите файл shelter-factorio.json из папки script-output.");
    } catch (error) { toastError(error); }
  }
  async function prepare() {
    busy = true;
    try { mod = (await factorio<{ file: string }>({ op: "prepare", branch: factorioBranch })).file; }
    catch (error) { toastError(error); }
    finally { busy = false; }
  }
  async function prepareHoi() {
    busy = true;
    try { hoiMod = (await factorio<{ file: string }>({ op: "prepare-hoi4" })).file; }
    catch (error) { toastError(error); }
    finally { busy = false; }
  }
  async function copyCommand(value: string) {
    try { await navigator.clipboard.writeText(value); }
    catch (error) { toastError(error); }
  }
</script>

<h1>{uiText("Игры")}</h1>
<p class="lead">{uiText("Подключите свой мир, запускайте задачи и следите за их выполнением.")}</p>
<div class="game-grid">
  {#each games as item}
    <button class="card game" class:active={item.id === game} aria-pressed={item.id === game} onclick={() => selected = item.id}>
      <item.icon size={22} />
      <span><b>{item.title}</b><small>{uiText(item.detail)}</small></span>
    </button>
  {/each}
</div>
{#if game === "minecraft"}
  <div class="buttons mode">
    <button class="btn" aria-pressed={minecraftMode === "player"} onclick={() => minecraftMode = "player"}>{uiText("Отдельный аккаунт")}</button>
    <button class="btn" aria-pressed={minecraftMode === "npc"} onclick={() => minecraftMode = "npc"}>{uiText("Без отдельного аккаунта")}</button>
  </div>
  {#if minecraftMode === "npc"}<MinecraftNpc />{:else}<MinecraftCompanion />{/if}
{:else if game === "factorio"}
  <section class="card">
    <h3>Factorio 2.0 / 2.1</h3>
    <p>{uiText("Подготовьте ZIP, положите его в папку mods игры и загрузите мир. В игровом чате введите /shelter-export. Экспорт обновляется каждые две секунды.")}</p>
    <div class="buttons">
      <label>{uiText("Версия Factorio")} <select bind:value={factorioBranch} onchange={() => (mod = "")} disabled={busy}>
        <option value="2.1">2.1</option><option value="2.0">2.0</option>
      </select></label>
      <button class="btn" disabled={busy || !app.status} onclick={prepare}><Download size={15} />{uiText("Подготовить мод Factorio")}</button>
      <button class="btn" disabled={busy || !app.status} onclick={choose}><FolderOpen size={15} />{uiText("Выбрать файл данных")}</button>
      <button class="btn" disabled={busy || !app.status} onclick={() => check()}><RefreshCw size={15} />{uiText("Проверить данные")}</button>
    </div>
    {#if mod}<p class="mono dim">{mod}</p>{/if}
    <h3>{uiText("Задача на ручное производство")}</h3>
    <p>{uiText("С модом 0.2.0 вставьте команду в чат своего мира. Количество задаёт число выполнений рецепта. Используются материалы вашего персонажа.")}</p>
    <div class="buttons">
      <label>{uiText("ID рецепта")} <input bind:value={recipe} placeholder="iron-gear-wheel" maxlength="160" /></label>
      <label>{uiText("Количество")} <input type="number" bind:value={quantity} min="1" max="100" step="1" /></label>
    </div>
    {#if command}
      <p class="buttons"><code>{command}</code><button class="btn sm" onclick={() => copyCommand(command)}>{uiText("Скопировать команду")}</button></p>
    {/if}
    <p class="dim">{uiText("Команда /shelter-stop прекращает добавлять работы. Текущий рецепт можно отменить в очереди Factorio.")}</p>
    <button class="btn sm" onclick={() => copyCommand("/shelter-stop")}>{uiText("Скопировать команду остановки")}</button>
    {#if status}
      <p class="mono dim">{status.path}</p>
      {#if status.state}
        {@const state = status.state}
        <p><b>{state.player}</b> · {state.surface} · {Math.round(state.x)}, {Math.round(state.y)}</p>
        <p>{state.research || uiText("Активного исследования нет.")}{state.research ? " · " + Math.round(state.progress * 100) + "%" : ""}</p>
        {#if state.age > 10}<p class="dim">{uiText("Показан последний сохранённый снимок.")}</p>{/if}
        {#if state.job}
          <p role="status"><b>{state.job.recipe}</b> · {state.job.done}/{state.job.total} · {uiText(jobStates[state.job.state])}</p>
          <progress aria-label={uiText("Прогресс производства")} max={state.job.total} value={state.job.done}></progress>
        {/if}
        <ul>{#each state.inventory as item}<li>{item.name} × {item.count}</li>{/each}</ul>
      {:else}<p role="status">{uiText(status.message)}</p>{/if}
    {/if}
    <p class="dim">{uiText("В игре спросите: «Что у меня в инвентаре в Factorio?» или «Factorio, какое сейчас исследование?»")}</p>
  </section>
{:else}
  <section class="card">
    <h3>Hearts of Iron IV</h3>
    <p>{uiText("Мод кампании добавляет решение для создания линии пехотного снаряжения I и миссию на 500 единиц в запасе. Миссию можно остановить в решениях, а линию — в производстве.")}</p>
    <p class="dim">{uiText("Распакуйте архив в папку mod игры и включите Shelter Campaign Tasks в наборе модов. Запуск в кампании ещё не проверен.")}</p>
    <button class="btn" disabled={busy || !app.status} onclick={prepareHoi}><Download size={15} />{uiText("Подготовить мод кампании")}</button>
    {#if hoiMod}<p class="mono dim">{hoiMod}</p>{/if}
    <p>{uiText("Откройте нужную карту или панель в игре и скажите: «Опиши экран Hearts of Iron IV». Ассистент объяснит то, что видно на текущем экране.")}</p>
    <p class="dim">{uiText("Выберите модель зрения в разделе «Модели и разум». Снимок будет отправлен выбранному провайдеру только по запросу.")}</p>
  </section>
{/if}

<style>
  .game-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; margin: 14px 0; }
  .game-grid .card { margin: 0; }
  .game { display: flex; align-items: center; gap: 12px; text-align: left; color: var(--text); cursor: pointer; }
  .game.active { border-color: var(--accent); background: var(--accent-soft); }
  .game small { display: block; color: var(--text-2); margin-top: 4px; }
  .buttons { flex-wrap: wrap; }
  .mode { margin-bottom: 12px; }
  p { overflow-wrap: anywhere; }
</style>
