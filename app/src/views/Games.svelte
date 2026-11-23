<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { Blocks, Factory, MapPinned, FolderOpen, Download, RefreshCw } from "@lucide/svelte";
  import MinecraftCompanion from "../components/MinecraftCompanion.svelte";
  import MinecraftNpc from "../components/MinecraftNpc.svelte";
  import FactorioCompanion from "../components/FactorioCompanion.svelte";
  import { open } from "../lib/fileDialogs";
  import { app, get, set, nav, toastError } from "../lib/store.svelte";
  import { t as uiText } from "../lib/i18n.svelte";

  const games = [
    { id: "minecraft", title: "Minecraft", icon: Blocks, detail: "Напарник в мире Java Edition" },
    { id: "factorio", title: "Factorio", icon: Factory, detail: "Производство, инвентарь и исследования" },
    { id: "hoi4", title: "Hearts of Iron IV", icon: MapPinned, detail: "Управление кампанией, сводка и производство" },
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
  let hoiTools = $state<string[]>([]);
  let hoiOutput = $state("");
  let hoiRunning = $state(false);
  let days = $state<number | undefined>(3);
  let equipment = $state("");
  let factories = $state<number | undefined>(1);
  let hoiResearch = $state("");
  let hoiFocus = $state("");
  let minecraftMode = $state<"player" | "npc">("player");
  let busy = $state(false);
  const saved = $derived(get<string>("factorio.snapshot", ""));
  const online = $derived(!!app.status);
  let recipe = $state("");
  let quantity = $state<number | undefined>(10);
  let technology = $state("");
  let player = $state(get<string>("factorio.player", ""));
  let port = $state<number | undefined>(get<number>("factorio.rcon_port", 27015));
  let password = $state("");
  const remote = $derived(!!get<string>("factorio.player", ""));
  type CraftPlan = { craftable: number; ingredients: { name: string; type: string; required: number; carried: number }[] };
  let plan = $state<CraftPlan | null>(null);
  let researchNotice = $state("");
  let blueprintNotice = $state<{ placed: number; total: number } | null>(null);
  let machineNotice = $state<{ machine: string; recipe: string } | null>(null);
  let buildX = $state<number | undefined>();
  let buildY = $state<number | undefined>();
  const command = $derived(/^[a-zA-Z0-9_-]{1,160}$/.test(recipe.trim()) && quantity && Number.isInteger(quantity) && quantity <= 100 && quantity >= 1
    ? `/shelter-craft ${recipe.trim()} ${quantity}` : "");

  $effect(() => {
    if (game !== "factorio" || !online) return;
    const path = saved;
    const useRemote = remote;
    let active = true;
    let pending = false;
    async function poll() {
      if (pending || document.hidden) return;
      pending = true;
      try {
        const next = await factorio<Snapshot>({ op: "status", path: useRemote ? "" : path });
        if (active) status = next;
      } catch {
        if (active) status = null;
      } finally { pending = false; }
    }
    void poll();
    const timer = setInterval(poll, 2200);
    return () => { active = false; clearInterval(timer); };
  });

  $effect(() => {
    if (game !== "hoi4" || !online || !hoiRunning || busy) return;
    const timer = setTimeout(() => {
      if (!document.hidden) void hoiAction("progress");
      else void hoiAction("progress", false);
    }, 3500);
    return () => clearTimeout(timer);
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
  async function hoiAction(action: string, announceErrors = true) {
    busy = true;
    try {
      const target = action === "start-focus" ? hoiFocus : hoiResearch;
      type Reply = { text: string; available?: string[]; running?: boolean };
      let result = await factorio<Reply>({ op: "hoi4-live", action, days, equipment, factories, target });
      if (action === "progress" && hoiRunning && result.running === false) {
        hoiRunning = false;
        result = await factorio<Reply>({ op: "hoi4-live", action: "result" });
      }
      if (action === "connect") hoiTools = result.available ?? [];
      if (result.running !== undefined) hoiRunning = result.running;
      hoiOutput = result.text;
    } catch (error) {
      if (action === "connect") hoiTools = [];
      if (action === "progress") hoiRunning = false;
      if (announceErrors) toastError(error);
    } finally { busy = false; }
  }
  async function copyCommand(value: string) {
    try { await navigator.clipboard.writeText(value); }
    catch (error) { toastError(error); }
  }
  function saveLink() {
    if (player && (!/^[\w.-]{1,60}$/.test(player.trim()) || !port || !Number.isInteger(port) || port > 65535 || port < 1)) return;
    set("factorio.rcon_port", port ?? 27015);
    if (password) { set("factorio.rcon_password", password); password = ""; }
    set("factorio.player", player.trim());
    status = null;
    plan = null;
  }
  async function gameAction(op: "plan" | "craft" | "stop" | "research" | "build" | "machine") {
    busy = true;
    try {
      const result = await factorio<State & CraftPlan & { placed: number; total: number; machine: string; recipe: string }>({
        op, recipe: op === "research" ? technology.trim() : recipe.trim(), count: quantity, x: buildX, y: buildY,
      });
      if (op === "plan") plan = result;
      else if (op === "research") researchNotice = result.research;
      else if (op === "build") blueprintNotice = { placed: result.placed, total: result.total };
      else if (op === "machine") machineNotice = { machine: result.machine, recipe: result.recipe };
      else { status = { path: "127.0.0.1 · RCON", state: { ...result, age: 0 }, message: "" }; plan = null; }
    } catch (error) { toastError(error); }
    finally { busy = false; }
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
    <FactorioCompanion {online} />
    <h3>{uiText("Задача на ручное производство")}</h3>
    <p>{uiText("Количество задаёт число выполнений рецепта. Используются материалы вашего персонажа.")}</p>
    <details>
      <summary>{uiText("Управление с компьютера через RCON")}</summary>
      <p>{uiText("Запустите свой сервер с RCON на этом компьютере, установите мод 0.3.0 и в игре введите /shelter-remote. Чтобы вернуться к локальному экспорту, очистите имя игрока.")}</p>
      <div class="buttons">
        <label>{uiText("Имя игрока")} <input bind:value={player} maxlength="60" /></label>
        <label>{uiText("Порт RCON")} <input type="number" bind:value={port} min="1" max="65535" /></label>
        <label>{uiText("Пароль RCON")} <input type="password" bind:value={password} autocomplete="off" /></label>
        <button class="btn" onclick={saveLink}>{uiText("Сохранить")}</button>
      </div>
    </details>
    <div class="buttons">
      <label>{uiText("ID рецепта")} <input bind:value={recipe} oninput={() => (plan = null)} placeholder="iron-gear-wheel" maxlength="160" /></label>
      <label>{uiText("Количество")} <input type="number" bind:value={quantity} oninput={() => (plan = null)} min="1" max="100" step="1" /></label>
    </div>
    {#if remote}
      <div class="buttons">
        <button class="btn" disabled={busy || !online || !command} onclick={() => gameAction("plan")}>{uiText("Проверить материалы")}</button>
        <button class="btn primary" disabled={busy || !online || !command || !!status?.state?.job && ["waiting", "crafting"].includes(status.state.job.state)} onclick={() => gameAction("craft")}>{uiText("Запустить производство")}</button>
        <button class="btn" disabled={busy || !online} onclick={() => gameAction("stop")}>{uiText("Остановить производство")}</button>
      </div>
      {#if plan}
        <p role="status">{uiText("Доступно ручных выполнений")}: {plan.craftable}</p>
        <ul>{#each plan.ingredients || [] as item}<li>{item.name} · {uiText("Нужно")}: {item.required} · {uiText("В инвентаре")}: {item.carried}</li>{/each}</ul>
      {/if}
      <div class="buttons">
        <label>{uiText("ID технологии")} <input bind:value={technology} placeholder="automation" maxlength="160" /></label>
        <button class="btn" disabled={busy || !online || !/^[\w-]{1,160}$/.test(technology.trim())} onclick={() => gameAction("research")}>{uiText("Поставить исследование в очередь")}</button>
      </div>
      {#if researchNotice}<p role="status">{uiText("Поставлено в очередь")}: {researchNotice}</p>{/if}
      <details>
        <summary>{uiText("Строительство и сборочные автоматы")}</summary>
        <p>{uiText("Возьмите чертёж в курсор в игре. Shelter разместит строительные призраки рядом с персонажем. Для завершения постройки нужны материалы и строительные роботы или игрок.")}</p>
        <div class="buttons">
          <label>X <input type="number" step="1" bind:value={buildX} /></label>
          <label>Y <input type="number" step="1" bind:value={buildY} /></label>
          <button class="btn" disabled={busy || !online || !Number.isInteger(buildX) || !Number.isInteger(buildY)} onclick={() => gameAction("build")}>{uiText("Разместить чертёж")}</button>
          <button class="btn" disabled={busy || !online || !/^[\w-]{1,160}$/.test(recipe.trim()) || !Number.isInteger(buildX) || !Number.isInteger(buildY)} onclick={() => gameAction("machine")}>{uiText("Назначить рецепт автомату")}</button>
        </div>
        <p class="dim">{uiText("Для сборочного автомата укажите его координаты и ID рецепта выше. Автомат должен быть в пределах досягаемости и без другого активного рецепта.")}</p>
        {#if blueprintNotice}<p role="status">{uiText("Размещено строительных призраков")}: {blueprintNotice.placed}/{blueprintNotice.total}</p>{/if}
        {#if machineNotice}<p role="status">{machineNotice.machine} · {machineNotice.recipe}</p>{/if}
      </details>
    {:else if command}
      <p class="buttons"><code>{command}</code><button class="btn sm" onclick={() => copyCommand(command)}>{uiText("Скопировать команду")}</button></p>
    {/if}
    <p class="dim">{uiText("Команда /shelter-stop прекращает добавлять работы. Текущий рецепт можно отменить в очереди Factorio.")}</p>
    {#if !remote}<button class="btn sm" onclick={() => copyCommand("/shelter-stop")}>{uiText("Скопировать команду остановки")}</button>{/if}
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
    <h3>{uiText("Управление кампанией")}</h3>
    <p>{uiText("Установите HOI4 Live Tools отдельно и добавьте его в «Подключения → Внешние инструменты» с ID hoi4-live. Разрешите инструменты кампании в настройках.")}</p>
    <div class="buttons">
      <button class="btn" disabled={busy || !online} onclick={() => hoiAction("connect")}><RefreshCw size={15} />{uiText("Проверить адаптер")}</button>
      <button class="btn" disabled={busy || !hoiTools.includes("hoi4_status")} onclick={() => hoiAction("status")}>{uiText("Статус игры")}</button>
      <button class="btn" disabled={busy || !hoiTools.includes("hoi4_briefing")} onclick={() => hoiAction("briefing")}>{uiText("Сводка кампании")}</button>
      <button class="btn" disabled={busy || !hoiTools.includes("hoi4_research")} onclick={() => hoiAction("research")}>{uiText("Слоты исследований")}</button>
      <button class="btn" disabled={busy || !hoiTools.includes("hoi4_production")} onclick={() => hoiAction("production")}>{uiText("Линии производства")}</button>
      <button class="btn" disabled={busy || !hoiTools.includes("hoi4_focus")} onclick={() => hoiAction("focus")}>{uiText("Текущий фокус")}</button>
    </div>
    <div class="buttons">
      <label>{uiText("Игровые дни")} <input type="number" bind:value={days} min="1" max="14" step="1" /></label>
      <button class="btn primary" disabled={busy || !days || !hoiTools.includes("hoi4_advance") || !hoiTools.includes("hoi4_clock")} onclick={() => hoiAction("advance")}>{uiText("Запустить ход кампании")}</button>
      <button class="btn" disabled={busy || !hoiTools.includes("hoi4_clock")} onclick={() => hoiAction("progress")}>{uiText("Проверить прогресс")}</button>
      <button class="btn" disabled={busy || !hoiTools.includes("hoi4_clock")} onclick={() => hoiAction("stop")}>{uiText("Остановить ход кампании")}</button>
    </div>
    <div class="buttons">
      <label>{uiText("Снаряжение")} <input bind:value={equipment} placeholder="infantry_equipment_1" maxlength="120" /></label>
      <label>{uiText("Военные заводы")} <input type="number" bind:value={factories} min="1" max="5" step="1" /></label>
      <button class="btn" disabled={busy || !equipment.trim() || !factories || !hoiTools.includes("hoi4_production")} onclick={() => hoiAction("line")}>{uiText("Добавить линию")}</button>
    </div>
    <div class="buttons">
      <label>{uiText("ID технологии")} <input bind:value={hoiResearch} placeholder="basic_machine_tools" maxlength="120" /></label>
      <button class="btn" disabled={busy || !hoiResearch.trim() || !hoiTools.includes("hoi4_research")} onclick={() => hoiAction("start-research")}>{uiText("Начать в свободном слоте")}</button>
    </div>
    <div class="buttons">
      <label>{uiText("ID фокуса")} <input bind:value={hoiFocus} placeholder="USA_continue_the_new_deal" maxlength="120" /></label>
      <button class="btn" disabled={busy || !hoiFocus.trim() || !hoiTools.includes("hoi4_focus")} onclick={() => hoiAction("start-focus")}>{uiText("Начать фокус")}</button>
    </div>
    {#if hoiOutput}<pre class="game-output" role="status">{hoiOutput}</pre>{/if}
  </section>
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
  .game-output { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 20rem; overflow: auto; }
  .game-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; margin: 14px 0; }
  .game-grid .card { margin: 0; }
  .game { display: flex; align-items: center; gap: 12px; text-align: left; color: var(--text); cursor: pointer; }
  .game.active { border-color: var(--accent); background: var(--accent-soft); }
  .game small { display: block; color: var(--text-2); margin-top: 4px; }
  .buttons { flex-wrap: wrap; }
  .mode { margin-bottom: 12px; }
  p { overflow-wrap: anywhere; }
</style>
