<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  // Главная — центр помощника: что он делает сейчас, что было, быстрые действия.
  // Карточки включаются, скрываются и переставляются; раскладку можно сохранить.
  import { History as HistoryIcon, AlarmClock, Film, Zap, ListChecks, MessageSquare, Type, LayoutGrid, Eye, EyeOff, ArrowUp, ArrowDown, Check, Save, Lightbulb, GripVertical } from "@lucide/svelte";
  import StatusCard from "../components/home/StatusCard.svelte";
  import ExtensionWidgets from "../components/home/ExtensionWidgets.svelte";
  import History from "../components/home/History.svelte";
  import TimersCard from "../components/home/TimersCard.svelte";
  import MusicCard from "../components/home/MusicCard.svelte";
  import QuickCard from "../components/home/QuickCard.svelte";
  import TasksCard from "../components/home/TasksCard.svelte";
  import ChatCard from "../components/home/ChatCard.svelte";
  import TextCard from "../components/home/TextCard.svelte";
  import { app, get, set, saveNow, toast, toastError } from "../lib/store.svelte";
  import { api } from "../lib/api";
  import { ask } from "../lib/dialog.svelte";
  import { flip } from "svelte/animate";

  type Card = { id: string; on: boolean };
  const CARDS: Record<string, { title: string; icon: any; view: any; wide?: boolean }> = {
    history: { title: "Услышал → понял → сделал", icon: HistoryIcon, view: History, wide: true },
    quick: { title: "Быстрые сценарии", icon: Zap, view: QuickCard },
    timers: { title: "Таймеры и напоминания", icon: AlarmClock, view: TimersCard },
    music: { title: "Медиа", icon: Film, view: MusicCard },
    tasks: { title: "Задачи", icon: ListChecks, view: TasksCard },
    text: { title: "Действия с текстом", icon: Type, view: TextCard, wide: true },
    chat: { title: "Написать текстом", icon: MessageSquare, view: ChatCard, wide: true },
    tips: { title: "Что можно сказать", icon: Lightbulb, view: null, wide: true },
    extensions: { title: "Виджеты дополнений", icon: LayoutGrid, view: ExtensionWidgets },
  };
  const DEFAULT: Card[] = ["history", "quick", "timers", "music", "tasks", "text", "chat", "tips", "extensions"].map((id) => ({ id, on: id !== "extensions" }));

  let editing = $state(false);
  let naming = $state("");
  let pointer = $state<{ id: string; number: number; x: number; y: number; dx: number; dy: number; width: number; height: number; startX: number; startY: number } | null>(null);
  let draftOrder = $state<Card[] | null>(null);
  let previousTarget = "";
  const layout = $derived.by<Card[]>(() => {
    const saved = (get<Card[]>("ui.home.cards", []) ?? []).filter((c) => CARDS[c.id]);
    const missing = DEFAULT.filter((d) => !saved.some((s) => s.id === d.id));
    return saved.length ? [...saved, ...missing] : DEFAULT;
  });
  const layouts = $derived(get<Record<string, Card[]>>("ui.home.layouts", {}) ?? {});
  const visibleCards = $derived((draftOrder ?? layout).filter(card => editing || card.on));
  const held = $derived(pointer ? layout.find(card => card.id === pointer?.id) : undefined);

  function update(next: Card[]) { set("ui.home.cards", next.map((c) => ({ ...c }))); }
  async function resetOrder() {
    finishDrag();
    update(DEFAULT.map(card => ({ ...card, on: layout.find(item => item.id === card.id)?.on ?? card.on })));
    try { await saveNow(); toast("Стандартный порядок восстановлен", "success"); }
    catch (error) { toastError(error); }
  }
  function move(i: number, d: number) {
    const next = [...layout];
    const j = i + d;
    if (j < 0 || j >= next.length) return;
    [next[i], next[j]] = [next[j], next[i]];
    update(next);
  }
  function startDrag(event: PointerEvent) {
    if (!editing || pointer || event.button !== 0 || !(event.target instanceof Element)) return;
    if (event.target.closest("button, input, select, textarea, a")) return;
    const tile = event.target.closest<HTMLElement>("[data-home-card]");
    if (!tile?.dataset.homeCard) return;
    const box = tile.getBoundingClientRect();
    const { clientX: x, clientY: y, pointerId: number } = event;
    pointer = { id: tile.dataset.homeCard, number, x, y, startX: x, startY: y,
      dx: x - box.left, dy: y - box.top, width: box.width, height: box.height };
    previousTarget = "";
    (event.currentTarget as HTMLElement).setPointerCapture(number);
    event.preventDefault();
  }
  function drag(event: PointerEvent) {
    if (!pointer || pointer.number !== event.pointerId) return;
    pointer.x = event.clientX;
    pointer.y = event.clientY;
    if (!draftOrder && Math.hypot(pointer.x - pointer.startX, pointer.y - pointer.startY) < 5) return;
    const order = draftOrder ?? layout;
    const hit = document.elementFromPoint(pointer.x, pointer.y)?.closest<HTMLElement>("[data-home-card]");
    const over = hit?.dataset.homeCard;
    if (!over || over === pointer.id || over === previousTarget) {
      if (!draftOrder) draftOrder = [...order];
      return;
    }
    const from = order.findIndex(card => card.id === pointer!.id);
    const to = order.findIndex(card => card.id === over);
    if (from < 0 || to < 0) return;
    previousTarget = over;
    const next = [...order];
    next.splice(to, 0, ...next.splice(from, 1));
    draftOrder = next;
  }
  function finishDrag(event?: PointerEvent, commit = false) {
    if (!pointer || (event && pointer.number !== event.pointerId)) return;
    if (commit && draftOrder?.some((card, i) => card.id !== layout[i].id)) update(draftOrder);
    pointer = null;
    draftOrder = null;
  }
  function toggle(i: number) { update(layout.map((c, k) => (k === i ? { ...c, on: !c.on } : c))); }
  function saveLayout() {
    const name = naming.trim();
    if (!name) return;
    naming = "";
    set("ui.home.layouts", { ...layouts, [name]: layout });
    toast(`Раскладка «${name}» сохранена`, "success");
  }
  async function useLayout(name: string) { update(layouts[name]); }
  async function dropLayout(name: string) {
    if ((await ask({ title: "Удалить раскладку?", text: `«${name}» будет удалена. Текущие карточки останутся как есть.`, ok: "Удалить", danger: true })) !== "ok") return;
    const { [name]: _, ...rest } = layouts;
    set("ui.home.layouts", rest);
  }

  const examples = [
    { group: "Компьютер", items: ["Открой браузер", "Сверни все окна", "Громкость на тридцать", "Выключи компьютер через час"] },
    { group: "Игры и стрим", items: ["Запусти Стим", "Выключи микрофон в дискорде", "Сохрани момент", "Что сейчас играет?"] },
    { group: "Время и дела", items: ["Таймер на пять минут", "Напомни через час сделать перерыв", "Какие у меня напоминания?", "Доброе утро"] },
    { group: "Можно и намёком", items: ["Хочется послушать музыку", "Надо бы не забыть про чайник", "Как-то тихо тут", "Какая погода завтра?"] },
  ];
</script>

{#if app.connectionError}
  <div role="alert" class="notice bad top">{uiText("Нет связи с ядром: ")}{uiText(app.connectionError)}</div>
{/if}

<StatusCard />

<div class="bar">
  <span class="caps">{uiText("Сводка")}</span>
  <div class="bar-actions">
    {#if editing}
      <button class="btn sm" title={uiText("Видимость карточек и сохранённые раскладки сохранятся")} onclick={resetOrder}>{uiText("Вернуть стандартный порядок")}</button>
      {#each Object.keys(layouts) as name}
        <span class="layout"><button class="btn sm" onclick={() => useLayout(name)}>{uiText(name)}</button><button class="btn ghost icon sm" aria-label={uiText("Удалить раскладку " + String(name))} onclick={() => dropLayout(name)}>×</button></span>
      {/each}
      <form class="name" onsubmit={(e) => { e.preventDefault(); saveLayout(); }}>
        <input type="text" placeholder={uiText("Название раскладки")} aria-label={uiText("Название раскладки")} bind:value={naming} />
        <button class="btn sm" disabled={!naming.trim()}><Save size={13} />{uiText(" Сохранить раскладку")}</button>
      </form>
      <button class="btn primary sm" onclick={() => (editing = false)}><Check size={13} />{uiText(" Готово")}</button>
    {:else}
      {#each Object.keys(layouts) as name}<button class="btn ghost sm" onclick={() => useLayout(name)}>{uiText(name)}</button>{/each}
      <button class="btn ghost sm" onclick={() => (editing = true)}><LayoutGrid size={13} />{uiText(" Настроить")}</button>
    {/if}
  </div>
</div>

<svelte:window onkeydown={(e) => { if (e.key === "Escape") finishDrag(); }} />
<div class="cards" class:reordering={editing} role="presentation" onpointerdown={startDrag} onpointermove={drag}
     onpointerup={(e) => finishDrag(e, true)} onpointercancel={(e) => finishDrag(e)} onlostpointercapture={(e) => finishDrag(e)}>
  {#each visibleCards as card (card.id)}
    {@const meta = CARDS[card.id]}
    {@const i = layout.findIndex(item => item.id === card.id)}
      <section class="card tile" data-home-card={card.id} class:wide={meta.wide} class:off={!card.on}
        class:placeholder={!!draftOrder && pointer?.id === card.id}
        animate:flip={{duration: 160}} aria-label={uiText(meta.title)}>
        <div class="card-head">
          <h3>
            {#if editing}
              <span class="drag-handle" title={uiText("Перетащите карточку")}><GripVertical size={17} /></span>
            {/if}
            <meta.icon size={16} /> {uiText(meta.title)}
          </h3>
          {#if editing}
            <div class="edit">
              <button class="btn ghost icon sm" aria-label={uiText("Выше")} disabled={i === 0} onclick={() => move(i, -1)}><ArrowUp size={14} /></button>
              <button class="btn ghost icon sm" aria-label={uiText("Ниже")} disabled={i === layout.length - 1} onclick={() => move(i, 1)}><ArrowDown size={14} /></button>
              <button class="btn ghost icon sm" aria-label={uiText(card.on ? "Скрыть карточку" : "Показать карточку")} onclick={() => toggle(i)}>{#if card.on}<Eye size={14} />{:else}<EyeOff size={14} />{/if}</button>
            </div>
          {/if}
        </div>
        {#if card.on && !editing}
          {#if card.id === "tips"}
            <p class="dim small">{uiText("Примеры для русской речи. Язык интерфейса не меняет язык распознавания.")}</p>
            <div class="tips">
              {#each examples as g}
                <div><b>{uiText(g.group)}</b>
                  {#each g.items as phrase}<button class="phrase" title={uiText("Нажмите — Джарвис выполнит")} disabled={!app.status} onclick={() => api.ask(phrase)}>«{phrase}»</button>{/each}
                </div>
              {/each}
            </div>
          {:else}
            <meta.view />
          {/if}
        {:else if !card.on}
          <p class="dim small">{uiText("Скрыта — не обновляется и не нагружает компьютер.")}</p>
        {/if}
      </section>
  {/each}
</div>
{#if pointer && draftOrder && held}
  {@const meta = CARDS[held.id]}
  <div class="card tile floating" aria-hidden="true" style:width={pointer.width + "px"} style:height={pointer.height + "px"}
       style:left={pointer.x - pointer.dx + "px"} style:top={pointer.y - pointer.dy + "px"}>
    <div class="card-head"><h3><GripVertical size={17} /><meta.icon size={16} /> {uiText(meta.title)}</h3></div>
  </div>
{/if}

<style>
  .top {
    margin-bottom: 12px;
  }
  .bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    margin: 18px 0 8px;
    flex-wrap: wrap;
  }
  .bar-actions {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    align-items: center;
  }
  .layout {
    display: inline-flex;
  }
  .name {
    display: flex;
    gap: 6px;
  }
  .name input {
    height: 30px;
    width: 170px;
  }
  .cards {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
  }
  .tile {
    padding: 14px 16px;
    min-width: 0;
    position: relative;
  }
  .drag-handle { display: inline-flex; padding: 3px; }
  .reordering .tile { cursor: grab; touch-action: none; user-select: none; }
  .reordering .tile.placeholder { opacity: 1; background: var(--accent-soft); border: 1px dashed var(--accent); }
  .placeholder > * { visibility: hidden; }
  .tile.floating { position: fixed; box-sizing: border-box; margin: 0; z-index: 90; pointer-events: none;
    background: var(--surface-solid); border-color: var(--accent); box-shadow: 0 10px 24px #0006; }
  .tile + .tile {
    margin-top: 0;
  }
  .tile.wide {
    grid-column: 1 / -1;
  }
  .tile.off {
    opacity: 0.6;
    border-style: dashed;
  }
  .tile h3 {
    font-size: 14px;
    color: var(--text-2);
  }
  .edit {
    display: flex;
    gap: 2px;
  }
  .small {
    font-size: 12.5px;
  }
  .tips {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
    gap: 10px;
    margin-top: 6px;
  }
  .tips b {
    display: block;
    font-size: 13px;
    color: var(--accent-2);
    margin-bottom: 2px;
  }
  .phrase {
    display: block;
    text-align: left;
    border: none;
    background: transparent;
    color: var(--text-2);
    font: inherit;
    font-size: 13px;
    padding: 3px 6px;
    margin: 0 -6px;
    border-radius: 7px;
    cursor: pointer;
  }
  .phrase:hover:not(:disabled) {
    background: var(--hover);
    color: var(--text);
  }
  @media (max-width: 760px) {
    .cards {
      grid-template-columns: 1fr;
    }
  }
</style>
