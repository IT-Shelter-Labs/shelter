<script lang="ts">
  import { onMount } from "svelte";
  import { invoke } from "@tauri-apps/api/core";
  import { openUrl, revealItemInDir } from "@tauri-apps/plugin-opener";
  import { Blocks, CircleAlert, Compass, Copy, LogOut, Plug, Square } from "@lucide/svelte";
  import { locale, t } from "../lib/i18n.svelte";

  type Settings = { host: string; port: number; owner: string; auth: "microsoft" | "offline"; chat: boolean; ai_chat: boolean; speak_chat: boolean; trust_local_chat: boolean; relay_replies: boolean };
  type GameTask = { id: number; op: string; item?: string; count?: number; mode?: string };
  type Snapshot = { phase: string; error: string; last: string; code: string; installed: boolean; node: boolean;
    history?: { id: number; op: string; state: string; message: string }[];
    info: { name?: string; version?: string; health?: number; food?: number; position?: number[]; items?: [string, number][]; itemLabels?: Record<string, string>; active?: string; step?: string; progress?: string; gameMode?: string; heldItem?: string; task?: GameTask; queue?: GameTask[] };
    settings: Partial<Settings> };

  const endpoint = "/api/minecraft";
  let snapshot = $state<Snapshot>();
  let form = $state<Settings>({ host: "127.0.0.1", port: 25565, owner: "", auth: "microsoft", chat: true, ai_chat: false, speak_chat: false, trust_local_chat: false, relay_replies: true });
  let pending = $state("");
  let note = $state("");
  let error = $state("");
  let logout = $state(false);
  let helpOpen = $state(false);
  let inventoryOpen = $state(false);
  let gameInventoryOpen = $state(false);
  let inventoryPlugin = $state("");
  let tasksOpen = $state(false);
  let selectedItem = $state("");
  let quantity = $state<number | undefined>(1);
  let desiredMode = $state("");
  let available = $derived(snapshot?.info.items?.find(([name]) => name === selectedItem)?.[1] ?? 0);
  let inventoryBusy = $derived(Boolean(pending) || Boolean(snapshot?.info.active && !["follow", "guard"].includes(snapshot.info.active)));
  const gameModes: Record<string, string> = { survival: "Выживание", creative: "Творческий", adventure: "Приключение", spectator: "Наблюдатель" };
  let locked = $derived(Boolean(pending) || ["connecting", "auth", "ready", "installing"].includes(snapshot?.phase || ""));
  const phases: Record<string, string> = { idle: "Не подключён", installing: "Устанавливается игровой клиент",
    connecting: "Подключается к миру", auth: "Ждёт входа Microsoft", ready: "В мире", error: "Ошибка подключения" };
  const skills: Record<string, string> = { follow: "Иду за вами", come: "Подхожу", mine: "Добываю блоки", craft: "Создаю предметы", give: "Передаю предметы",
    obtain: "Готовлю предметы", teleport: "Жду телепорта", deliver: "Готовлю доставку",
    guard: "Защищаю игрока", equip: "Беру в руку", build: "Строю", set_mode: "Жду смены режима", give_stock: "Передаю предметы", navigate: "Иду к координатам", eat: "Ем", fish: "Рыбачу", sequence: "Выполняю план" };
  const steps: Record<string, string> = { prepare: "Подготовка предметов", craft_for_give: "Готовлю предметы", approach: "Подход к игроку", transfer: "Передача предметов",
    mine: "Добываю блоки", craft: "Создаю предметы", place_station: "Ставлю верстак или печь", smelt: "Переплавляю", watch: "Охраняю игрока", defend: "Атакую враждебного моба", creative_inventory: "Беру из творческого инвентаря" };

  onMount(() => {
    let alive = true;
    let fetching = false;
    let loaded = false;
    async function refresh() {
      if (fetching || pending || document.hidden) return;
      fetching = true;
      try {
        const data = await invoke<Snapshot>("core_get", { path: endpoint });
        if (!alive || pending) return;
        snapshot = data;
        if (!loaded) { form = { ...form, ...data.settings }; loaded = true; }
      } catch {
        if (alive && !snapshot) error = "Сначала включите Джарвиса — подключение запускает ядро.";
      } finally { fetching = false; }
    }
    void refresh();
    const timer = setInterval(refresh, 1600);
    return () => { alive = false; clearInterval(timer); };
  });

  async function run(op: string, parameters: Record<string, unknown> = {}) {
    if (pending) return;
    pending = op;
    note = error = "";
    try {
      const body = op === "connect" ? { ...form, op } : { ...parameters, op };
      if (op === "lan") {
        const result = await invoke<{ port: number | null }>("core_post", { path: endpoint, body });
        if (result.port) { form.host = "127.0.0.1"; form.port = result.port; note = "Порт найден. Введите свой ник и подключите напарника."; }
        else note = "Порт не найден. Введите вручную число из сообщения Minecraft об открытии мира для сети.";
      } else if (op === "package_inventory") {
        inventoryPlugin = (await invoke<{ file: string }>("core_post", { path: endpoint, body })).file;
      } else {
        snapshot = await invoke<Snapshot>("core_post", { path: endpoint, body });
        if (op === "logout") { logout = false; note = "Вход Minecraft сброшен."; }
      }
    } catch (cause) { error = String(cause); }
    finally { pending = ""; }
  }

  function inventoryAction(action: "give" | "equip") {
    if (!selectedItem || !available) return;
    return run("inventory_action", { action, item: selectedItem, count: action === "equip" ? 1 : quantity });
  }

  function itemLabel(id: string) {
    return (locale.language === "ru" && snapshot?.info.itemLabels?.[id]) || id.replaceAll("_", " ");
  }

  function taskLabel(task: GameTask) {
    const material = task.item ? ` · ${itemLabel(task.item)}${task.count ? ` ×${task.count}` : ""}` : "";
    return t(skills[task.op] || task.op) + material;
  }

  async function login(copy: boolean) {
    try {
      if (copy && snapshot?.code) await navigator.clipboard.writeText(snapshot.code);
      else await openUrl("https://www.microsoft.com/link");
      if (copy) note = "Код скопирован.";
    } catch { error = "Не удалось открыть браузер или скопировать код. Сделайте это вручную."; }
  }
</script>

<section class="card minecraft fade-in" aria-label="Minecraft Java Edition">
  <header>
    <div><p class="kicker">MINECRAFT · JAVA EDITION</p><h2>{t("Напарник в Minecraft")}</h2></div>
    <span class="badge" class:ok={snapshot?.phase === "ready"} aria-live="polite">{t(phases[snapshot?.phase || ""] || "Загрузка")}</span>
  </header>

  <p class="dim">{t("Откройте свой мир для сети (Esc → Открыть для сети) или запустите собственный сервер. Джарвис зайдёт отдельным игроком.")}</p>
  {#if snapshot && !snapshot.installed}
    <div class="notice setup">
      <span>{t(snapshot.node ? "Первое подключение: установите игровой клиент. Когда интеграция выключена, он не работает в фоне." : "Для игрового клиента нужен Node.js 22 или новее. Установите его вместе с npm и перезапустите Джарвиса.")}</span>
      <button type="button" class="btn" disabled={locked || !snapshot.node} onclick={() => run("install")}>{t("Установить клиент")}</button>
    </div>
  {/if}

  <fieldset disabled={locked}>
    <div class="form-grid">
      <label class="field"><span>{t("Адрес мира или сервера")}</span><input bind:value={form.host} maxlength="253" placeholder="127.0.0.1" /></label>
      <label class="field"><span>{t("Порт Minecraft")}</span><input type="number" min="1" max="65535" bind:value={form.port} /></label>
      <label class="field"><span>{t("Ваш ник в Java Edition")}</span><input bind:value={form.owner} maxlength="16" placeholder="PlayerName" spellcheck="false" /></label>
    </div>
    <button type="button" class="btn sm" onclick={() => run("lan")}><Compass size={15} />{t("Найти порт локального мира")}</button>
    <label class="field auth"><span>{t("Вход напарника")}</span>
      <select bind:value={form.auth}>
        <option value="microsoft">Microsoft</option>
        <option value="offline">{t("Локальный тестовый сервер без авторизации")}</option>
      </select>
    </label>
    <p class="dim hint">{t(form.auth === "microsoft" ? "Для одновременной игры войдите отдельным аккаунтом Microsoft с Java Edition. Джарвис не запрашивает пароль." : "Только для уже настроенного тестового сервера на 127.0.0.1. Джарвис не меняет настройки сервера.")}</p>
    <label class="check"><input type="checkbox" bind:checked={form.chat} />{t("Принимать мои команды в игровом чате")}</label>
    <label class="check"><input type="checkbox" bind:checked={form.relay_replies} />{t("Писать все ответы Джарвиса в игровой чат")}</label>
    {#if form.relay_replies}<p class="hint dim">{t("Игроки на сервере смогут прочитать эти ответы. Игровые команды всегда получают ответ в чате.")}</p>{/if}
    {#if form.chat}
      {#if form.auth === "microsoft" && ["127.0.0.1", "::1"].includes(form.host.trim())}
        <label class="check"><input type="checkbox" bind:checked={form.trust_local_chat} />{t("Доверять чату своего локального мира")}</label>
        <p class="dim hint">{t("Включите, если чат вашего мира не подтверждает подписи. Команды по-прежнему принимаются только от вашего игрока по его UUID.")}</p>
      {/if}
      <label class="check"><input type="checkbox" bind:checked={form.speak_chat} />{t("Озвучивать ответы из игры голосом персонажа")}</label>
      <label class="check"><input type="checkbox" bind:checked={form.ai_chat} />{t("Разговаривать в игре через выбранную модель")}</label>
      {#if form.ai_chat}
        <p class="dim hint">{t("Текст после !jarvis и короткая история этого разговора передаются выбранной модели, в том числе облачной. Память и инструменты рабочего стола недоступны.")}</p>
      {/if}
    {/if}
  </fieldset>

  <div class="actions">
    {#if ["connecting", "auth", "ready"].includes(snapshot?.phase || "")}
      <button type="button" class="btn" disabled={Boolean(pending) || snapshot?.phase !== "ready"} onclick={() => run("stop")}><Square size={15} />{t("Остановить действие")}</button>
      {#if snapshot?.phase === "ready"}
        <button type="button" class="btn" disabled={inventoryBusy || snapshot.info.active === "guard"} onclick={() => run("guard")}>{t("Защищай меня")}</button>
      {/if}
      <button type="button" class="btn" disabled={Boolean(pending)} onclick={() => run("disconnect")}><LogOut size={15} />{t("Отключить напарника")}</button>
    {:else}
      <button type="button" class="btn primary" disabled={locked || !snapshot?.installed || !snapshot?.node || !form.owner.trim() || !form.port} onclick={() => run("connect")}><Plug size={15} />{t("Подключить напарника")}</button>
      <button type="button" class="btn" disabled={locked} onclick={() => { logout = !logout; }}>{t("Сбросить вход Minecraft")}</button>
    {/if}
  </div>
  {#if logout && !locked}
    <div class="notice setup">
      <span>{t("Удалить сохранённый вход напарника? При следующем подключении потребуется новый код Microsoft.")}</span>
      <button type="button" class="btn" onclick={() => run("logout")}>{t("Да, сбросить вход")}</button>
    </div>
  {/if}
  {#if snapshot?.phase === "auth" && snapshot.code}
    <div class="notice login">
      <p>{t("Откройте microsoft.com/link и введите этот код. Используйте аккаунт напарника, а не свой игровой аккаунт.")}</p>
      <div class="actions"><code>{snapshot.code}</code>
        <button type="button" class="btn" onclick={() => login(true)}><Copy size={15} />{t("Скопировать код")}</button>
        <button type="button" class="btn primary" onclick={() => login(false)}>{t("Войти через Microsoft")}</button></div>
    </div>
  {/if}
  {#if error || snapshot?.error}<div class="notice bad" role="alert"><CircleAlert size={16} /> {t(error || snapshot?.error || "")}</div>{/if}
  {#if note}<div class="notice" role="status">{t(note)}</div>{/if}

  {#if snapshot?.phase === "ready"}
    <div class="world">
      <Blocks size={20} /><div><strong>{snapshot.info.name}</strong> <span class="dim">· {snapshot.info.version}</span>
        <p class="hint dim">{t("Здоровье:")} {snapshot.info.health} · {t("Еда:")} {snapshot.info.food} · {t("Позиция:")} {snapshot.info.position?.join(", ")}</p>
        <p class="hint dim">{t("Игровой режим")}: {t(gameModes[snapshot.info.gameMode ?? ""] ?? "Нет данных")}{#if snapshot.info.heldItem} · {t("В руке")}: {itemLabel(snapshot.info.heldItem)}{/if}</p>
      </div>
      <span class="badge" class:ok={!!snapshot.info.active}>{t(steps[snapshot.info.step || ""] || skills[snapshot.info.active || ""] || "Жду команды")}</span>
    </div>
    {#if snapshot.info.progress}<p class="hint dim" role="status">{snapshot.info.progress}</p>{/if}
    {#if snapshot.last}<div class="notice" role="status">{t(snapshot.last)}</div>{/if}
    {#if snapshot.info.task || snapshot.info.queue?.length || snapshot.history?.length}
      <div class="fold">
        <button class="fold-toggle" type="button" aria-expanded={tasksOpen} aria-controls="mc-tasks" onclick={() => tasksOpen = !tasksOpen}>{tasksOpen ? "▾" : "▸"} {t("Игровые задачи")}{#if snapshot.info.queue?.length} · {snapshot.info.queue.length}{/if}</button>
        {#if tasksOpen}<div id="mc-tasks">
          {#each [snapshot.info.task, ...(snapshot.info.queue ?? [])].filter((task): task is GameTask => !!task) as task (task.id)}
            <div class="task">
              <span><span class="dim">{t(snapshot.info.task?.id === task.id ? "В работе" : "В очереди")}</span> · {taskLabel(task)}</span>
              <button type="button" class="btn" disabled={Boolean(pending)} onclick={() => run("cancel_job", { jobId: task.id })}>{t("Отменить задачу")}</button>
            </div>
          {/each}
          {#if snapshot.history?.length}
            <ul class="task-history">
              {#each snapshot.history as entry (entry.id)}
                <li><span class="dim">{t(skills[entry.op] || entry.op)}</span> · {t(entry.message)}</li>
              {/each}
            </ul>
          {/if}
        </div>{/if}
      </div>
    {/if}
    <div class="fold">
      <button class="fold-toggle" type="button" aria-expanded={inventoryOpen} aria-controls="mc-inventory" onclick={() => inventoryOpen = !inventoryOpen}>{inventoryOpen ? "▾" : "▸"} {t("Инвентарь напарника")}</button>
      {#if inventoryOpen}<div id="mc-inventory">
      {#if snapshot.info.items?.length}
        <div class="items" aria-label={t("Инвентарь напарника")}>
          {#each snapshot.info.items as [name, count] (name)}
            <button type="button" class="btn" title={name} aria-pressed={selectedItem === name} onclick={() => { selectedItem = name; quantity = 1; }}>{itemLabel(name)} ×{count}</button>
          {/each}
        </div>
        {#if available}
          <div class="actions">
            <button type="button" class="btn" disabled={inventoryBusy || selectedItem === snapshot.info.heldItem} onclick={() => inventoryAction("equip")}>{t("Взять в руку")}</button>
            <label>{t("Количество")} <input class="qty" type="number" min="1" max={Math.min(16, available)} bind:value={quantity} /></label>
            <button type="button" class="btn" disabled={inventoryBusy || !Number.isInteger(quantity) || (quantity ?? 0) < 1 || (quantity ?? 0) > Math.min(16, available)} onclick={() => inventoryAction("give")}>{t("Передать мне")}</button>
          </div>
        {/if}
      {:else}<p class="dim">{t("Инвентарь пуст.")}</p>{/if}
      </div>{/if}
    </div>
    <div class="actions">
      <select aria-label={t("Игровой режим")} bind:value={desiredMode}>
        <option value="">{t("Выберите игровой режим")}</option>
        {#each Object.entries(gameModes) as [id, label] (id)}<option value={id}>{t(label)}</option>{/each}
      </select>
      <button type="button" class="btn" disabled={inventoryBusy || !desiredMode || desiredMode === snapshot.info.gameMode} onclick={() => run("set_mode", { mode: desiredMode })}>{t("Сменить режим")}</button>
    </div>
  {/if}
  <div class="fold">
    <button class="fold-toggle" type="button" aria-expanded={gameInventoryOpen} aria-controls="mc-game-inventory" onclick={() => gameInventoryOpen = !gameInventoryOpen}>{gameInventoryOpen ? "▾" : "▸"} {t("Инвентарь в игре")}</button>
    {#if gameInventoryOpen}<div id="mc-game-inventory">
      <p>{t("На своём Paper-сервере установите ShelterInventory в папку plugins и перезапустите сервер.")}</p>
      <p>{t("После подключения Джарвиса привяжите его игровой ник командой")} <code>/shelterinventory link {snapshot?.info.name || "<ник>"}</code>.</p>
      <p>{t("Подойдите к напарнику и напишите !inv. Откроются его вещи, броня и обе руки.")}</p>
      <div class="actions">
        <button type="button" class="btn" disabled={Boolean(pending)} onclick={() => run("package_inventory")}>{t("Подготовить плагин инвентаря Paper")}</button>
        {#if inventoryPlugin}<button type="button" class="btn" onclick={() => revealItemInDir(inventoryPlugin).catch(reason => error = String(reason))}>{t("Показать в папке")}</button>{/if}
      </div>
    </div>{/if}
  </div>
  <div class="fold">
    <button class="fold-toggle" type="button" aria-expanded={helpOpen} aria-controls="mc-help" onclick={() => helpOpen = !helpOpen}>{helpOpen ? "▾" : "▸"} {t("Примеры команд")}</button>
    {#if helpOpen}<div id="mc-help">
    <p>{t("Голосом или в поле Джарвиса:")} <code>{t("Дай мне четыре камня")}</code> · <code>{t("Защищай меня")}</code> · <code>{t("Построй стену из шести досок")}</code></p>
    <p>{t("В чате игры:")} <code>{t("!jarvis инвентарь")}</code> · <code>{t("!jarvis иди за мной")}</code> · <code>{t("!jarvis стоп")}</code></p>
    <p class="dim">{t("Телепорт работает, только если сервер разрешает его игровому аккаунту напарника.")}</p>
    <p class="dim">{t("Игровой режим задаёт сервер. Бросьте инструмент рядом с напарником и проверьте его инвентарь. Для добычи он сам выберет подходящий инструмент из имеющихся.")}</p>
    <p class="dim">{t("Игровой облик — обычный скин аккаунта. Настольная 3D-модель в игру не переносится.")}</p>
    </div>{/if}
  </div>
</section>

<style>
  .minecraft { margin-top: 14px; display: grid; gap: 12px; }
  header, .setup, .world { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; }
  .kicker { font-size: 11px; letter-spacing: .13em; color: var(--accent); }
  h2, p { margin: 0; }
  fieldset { border: 0; margin: 0; padding: 0; min-width: 0; display: grid; gap: 10px; }
  fieldset > button { justify-self: start; }
  .form-grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 155px), 1fr)); }
  .auth { max-width: 420px; }
  .hint { font-size: 12px; }
  .check { display: flex; align-items: center; gap: 8px; font-size: 13px; }
  .check input { width: auto; flex: 0 0 auto; }
  .actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
  .world { justify-content: flex-start; }
  .world .badge { margin-left: auto; }
  .login .actions, .fold p, .fold .actions { margin-top: 8px; }
  .login code { font-size: 1.25rem; font-weight: 700; letter-spacing: .07em; }
  .fold { border-top: 1px solid var(--line); padding-top: 10px; }
  .fold-toggle { background: transparent; border: 0; color: var(--accent); cursor: pointer; font-weight: 600; padding: 5px 0; text-align: left; }
  .items { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
  .items button[aria-pressed="true"] { border-color: var(--accent); }
  .qty { width: 64px; }
  .task { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 8px; }
  .task-history { display: grid; gap: 6px; padding-left: 18px; }
  .notice.bad { display: flex; align-items: center; gap: 7px; }
</style>
