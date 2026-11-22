<script lang="ts">
  import { t as uiText, locale } from "../lib/i18n.svelte";

  // Команды: свои сценарии, проверка фразы, наборы, импорт/экспорт и резервные копии.
  import { onMount, untrack } from "svelte";
  import { Plus, Search, Play, Pencil, Copy, Upload, Download, Package, History, Mic, MousePointerClick, CalendarClock, Zap, CircleAlert, RotateCcw, LoaderCircle, Circle } from "@lucide/svelte";
  import { open as openDialog, save as saveDialog } from "../lib/fileDialogs";
  import Toggle from "../components/Toggle.svelte";
  import Editor from "../components/commands/Editor.svelte";
  import Packs from "../components/commands/Packs.svelte";
  import PhraseTester from "../components/commands/PhraseTester.svelte";
  import RunPanel from "../components/commands/RunPanel.svelte";
  import { app, nav, navigate, toast, toastError } from "../lib/store.svelte";
  import { api, type Scenario } from "../lib/api";
  import { drafts, restore, forget, remember } from "../lib/drafts.svelte";
  import { ask } from "../lib/dialog.svelte";

  let query = $state("");
  let category = $state("");
  let loading = $state(false);
  let lastRun = $state<{ id: string; run: string } | null>(null);
  let stored = $state(restore());
  let notes = $state<string[]>([]);

  const items = $derived<Scenario[]>(app.scenarios?.items ?? []);
  const categories = $derived([...new Set(items.map((s) => s.category))].sort());
  const filtered = $derived(items.filter((s) => {
    const q = query.toLowerCase().replace(/ё/g, "е").trim();
    return (!category || s.category === category)
      && (!q || s.name.toLowerCase().includes(q) || uiText(s.name).toLowerCase().includes(q) || s.phrases.some((p) => p.includes(q)) || (s.description ?? "").toLowerCase().includes(q));
  }));
  const groups = $derived([...new Set(filtered.map((s) => s.category))].map((c) => [c, filtered.filter((s) => s.category === c)] as const));
  const conflictsFor = (id: string) => (app.scenarios?.conflicts ?? []).filter((c: any) => c.scenario === id);

  async function load() {
    if (!app.status) return;
    loading = true;
    try { app.scenarios = await api.scenarios(); }
    catch (e) { toastError(e); }
    finally { loading = false; }
  }
  onMount(load);

  // Открыть редактор по адресу страницы: new | edit:<id> | task
  $effect(() => {
    const sub = nav.sub;
    // Только при переходе на «Новый»: сохранение нового сценария даёт ему id, и сбрасывать его нельзя.
    if (sub === "new" && untrack(() => !drafts.current || !!drafts.current.id)) openDraft(blank(), "");
    else if (sub.startsWith("edit:") && app.scenarios) {
      const id = sub.slice(5);
      if (drafts.current?.id !== id) {
        const item = items.find((s) => s.id === id);
        if (item) openDraft(structuredClone($state.snapshot(item)), JSON.stringify(item));
      }
    } else if (sub === "task" && drafts.fromTask) {
      notes = drafts.fromTask.skipped;
      openDraft(drafts.fromTask.draft, "");
      drafts.fromTask = null;
    }
  });

  function blank(): Scenario {
    return { id: "", name: "", category: "Мои", enabled: true, phrases: [], match: "whole", keep_listening: false,
      triggers: [{ type: "voice" }, { type: "button" }], conditions: [], confirm: "", steps: [], timeout: 180,
      on_error: "stop", cooldown: 30, platforms: ["windows", "linux"] } as Scenario;
  }
  function openDraft(item: Scenario, original: string) {
    drafts.current = item;
    drafts.original = original;
    drafts.history = [];
    drafts.future = [];
    remember();
  }
  const editing = $derived(nav.sub === "new" || nav.sub === "task" || nav.sub.startsWith("edit:"));

  async function toggle(s: Scenario, enabled: boolean) {
    try { await api.scenarioOp({ op: "toggle", id: s.id, enabled }); s.enabled = enabled; toast(enabled ? `«${s.name}» включён` : `«${s.name}» выключен`); }
    catch (e) { toastError(e); }
  }
  async function run(s: Scenario) {
    if (s.confirm && (await ask({ title: s.name, text: s.confirm, ok: "Выполнить" })) !== "ok") return;
    try { const r = await api.scenarioOp<{ run: string }>({ op: "run", id: s.id, confirmed: true }); lastRun = { id: s.id, run: r.run }; }
    catch (e) { toastError(e); }
  }
  function duplicate(s: Scenario) {
    const copy = structuredClone($state.snapshot(s));
    copy.id = "";
    copy.name = s.name + " (копия)";
    copy.phrases = [];
    openDraft(copy, "");
    navigate("commands", "new");
  }
  async function importFile() {
    const path = await openDialog({ multiple: false, filters: [{ name: "Сценарии Джарвиса", extensions: ["json"] }] });
    if (typeof path !== "string") return;
    try {
      const r = await api.scenarioOp<{ added: string[]; rejected: { name: string; problems: string[] }[] }>({ op: "import_file", path });
      await load();
      toast(`Добавлено: ${r.added.length}`, "success");
      for (const bad of r.rejected) toastError(`«${bad.name}» не добавлен: ${bad.problems[0]}`);
    } catch (e) { toastError(e); }
  }
  async function exportAll() {
    const path = await saveDialog({ defaultPath: "мои-сценарии.jarvis.json", filters: [{ name: "Сценарии Джарвиса", extensions: ["json"] }] });
    if (!path) return;
    try {
      const r = await api.scenarioOp<{ count: number; removed: string[] }>({ op: "export_file", path });
      toast(`Сохранено сценариев: ${r.count}${r.removed.length ? `. Убраны секреты: ${r.removed.length}` : ""}`, "success");
    } catch (e) { toastError(e); }
  }
  async function restoreBackup(id: string, count: number) {
    if ((await ask({ title: "Вернуть резервную копию?", text: `Список сценариев заменится сохранённым (${count} шт.). Нынешний тоже сохранится копией.`, ok: "Вернуть" })) !== "ok") return;
    try { await api.scenarioOp({ op: "restore", backup: id }); await load(); toast("Список восстановлен", "success"); }
    catch (e) { toastError(e); }
  }
  const triggerIcons = (s: Scenario) => s.triggers.map((t) => t.type);
  const when = (t: number) => new Date(t * 1000).toLocaleString((locale.language === "ru" ? "ru-RU" : "en-US"), { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
</script>

{#if editing}
  {#if drafts.current}<Editor isNew={!drafts.current.id} {notes} />{/if}
{:else}
  <header class="head">
    <div>
      <h1>{uiText("Команды")}</h1>
      <p class="lead">{uiText("Свои фразы и цепочки действий. Один сценарий работает голосом, кнопкой, по расписанию, по событию и с телефона.")}</p>
    </div>
    <div class="head-actions">
      <button class="btn" disabled={!app.status} title={uiText("Записать, какие программы вы открываете и куда ставите окна — и сделать из этого сценарий")}
              onclick={() => api.scenarioOp({ op: "demo_start" }).catch(toastError)}><Circle size={13} />{uiText(" Покажу один раз")}</button>
      <button class="btn primary" onclick={() => navigate("commands", "new")}><Plus size={15} />{uiText(" Новый сценарий")}</button>
    </div>
  </header>

  {#if stored && !drafts.current && stored.current}
    <div class="notice warn">
      <CircleAlert size={16} />
      <span>{uiText("Есть несохранённый черновик «")}{uiText(stored.current.name || "без названия")}».</span>
      <button class="btn sm" onclick={() => { openDraft(stored!.current, stored!.original); navigate("commands", stored!.current.id ? "edit:" + stored!.current.id : "new"); }}>{uiText("Продолжить")}</button>
      <button class="btn ghost sm" onclick={() => { forget(); stored = null; }}>{uiText("Отбросить")}</button>
    </div>
  {/if}

  <div class="tabs" role="tablist">
    <button role="tab" aria-selected={nav.sub === ""} class:active={nav.sub === ""} onclick={() => navigate("commands", "")}>{uiText("Мои сценарии")}</button>
    <button role="tab" aria-selected={nav.sub === "packs"} class:active={nav.sub === "packs"} onclick={() => navigate("commands", "packs")}><Package size={14} />{uiText(" Наборы")}</button>
    <button role="tab" aria-selected={nav.sub === "backups"} class:active={nav.sub === "backups"} onclick={() => navigate("commands", "backups")}><History size={14} />{uiText(" Резервные копии")}</button>
  </div>

  {#if !app.status}
    <div class="card empty"><b>{uiText("Джарвис выключен")}</b><span>{uiText("Сценарии хранятся в ядре — включите его кнопкой питания вверху справа.")}</span></div>
  {:else if nav.sub === "packs"}
    <Packs />
  {:else if nav.sub === "backups"}
    <div class="card">
      <p class="muted">{uiText("Копия списка сохраняется перед переносом команд, удалением, импортом и установкой набора.")}</p>
      {#each app.scenarios?.backups ?? [] as b}
        <div class="row"><div class="label"><b>{uiText(b.reason || "Резервная копия")}</b><span>{uiText(when(b.created))} · {uiText(b.count)}{uiText(" шт.")}</span></div>
          <button class="btn sm" onclick={() => restoreBackup(b.id, b.count)}><RotateCcw size={13} />{uiText(" Вернуть")}</button></div>
      {:else}<div class="empty">{uiText("Копий пока нет.")}</div>{/each}
    </div>
  {:else}
    <section class="card tester"><PhraseTester /></section>

    <div class="toolbar">
      <label class="search"><Search size={14} /><input bind:value={query} placeholder={uiText("Найти по названию или фразе")} aria-label={uiText("Поиск сценариев")} /></label>
      <select bind:value={category} aria-label={uiText("Раздел")}><option value="">{uiText("Все разделы")}</option>{#each categories as c}<option value={c}>{uiText(c)}</option>{/each}</select>
      <button class="btn" onclick={importFile}><Upload size={14} />{uiText(" Импорт")}</button>
      <button class="btn" onclick={exportAll} disabled={!items.length}><Download size={14} />{uiText(" Экспорт")}</button>
    </div>

    {#if app.scenarios?.error}<div class="notice bad"><CircleAlert size={16} /> {uiText(app.scenarios.error)}</div>{/if}
    {#if lastRun}<RunPanel run={lastRun.run} />{/if}

    {#if loading && !items.length}
      <div class="empty"><LoaderCircle size={20} class="spin" /></div>
    {:else if !items.length}
      <div class="card empty">
        <b>{uiText("Сценариев пока нет")}</b>
        <span>{uiText("Создайте свой («Новый сценарий») или поставьте готовый набор: «Работа», «Учёба», «Стрим», «Музыка».")}</span>
        <button class="btn" onclick={() => navigate("commands", "packs")}><Package size={14} />{uiText(" Посмотреть наборы")}</button>
      </div>
    {:else if !filtered.length}
      <div class="empty">{uiText("Ничего не нашлось по «")}{uiText(query)}».</div>
    {/if}

    {#each groups as [group, list] (group)}
      <section class="group">
        <h2 class="caps">{uiText(group)} · {uiText(list.length)}</h2>
        <div class="card list">
          {#each list as s (s.id)}
            <div class="item" class:off={!s.enabled}>
              <Toggle label={uiText(s.enabled ? `Выключить «${s.name}»` : `Включить «${s.name}»`)} checked={s.enabled} onchange={(v) => toggle(s, v)} />
              <button class="main" onclick={() => navigate("commands", "edit:" + s.id)}>
                <span class="name">{s.origin === "config" || s.origin?.startsWith("pack:") ? uiText(s.name) : s.name}{#if s.origin?.startsWith("pack:")}<span class="badge plain">{uiText("набор")}</span>{/if}{#if s.origin === "personal"}<span class="badge plain">{uiText("личное")}</span>{/if}</span>
                <span class="phr">{uiText(s.phrases.length ? s.phrases.map((p) => `«${p}»`).join(", ") : s.description || "без голосовой фразы")}</span>
                {#each conflictsFor(s.id).slice(0, 1) as c}<span class="conf"><CircleAlert size={12} /> {uiText(c.text)}</span>{/each}
              </button>
              <span class="trg" aria-label={uiText("Способы запуска")}>
                {#each triggerIcons(s) as t}
                  {#if t === "voice"}<Mic size={13} aria-label={uiText("голосом")} />{:else if t === "button"}<MousePointerClick size={13} aria-label={uiText("кнопкой")} />{:else if t === "schedule"}<CalendarClock size={13} aria-label={uiText("по расписанию")} />{:else}<Zap size={13} aria-label={uiText("по событию")} />{/if}
                {/each}
              </span>
              <span class="acts">
                <button class="btn ghost icon sm" aria-label={uiText("Запустить «" + String(s.name) + "»")} title={uiText("Запустить сейчас")} disabled={!s.enabled} onclick={() => run(s)}><Play size={14} /></button>
                <button class="btn ghost icon sm" aria-label={uiText("Изменить «" + String(s.name) + "»")} title={uiText("Изменить")} onclick={() => navigate("commands", "edit:" + s.id)}><Pencil size={14} /></button>
                <button class="btn ghost icon sm" aria-label={uiText("Копия «" + String(s.name) + "»")} title={uiText("Сделать копию")} onclick={() => duplicate(s)}><Copy size={14} /></button>
              </span>
            </div>
          {/each}
        </div>
      </section>
    {/each}

    {#if app.scenarios?.events?.length}
      <section class="group">
        <h2 class="caps">{uiText("Автозапуски")}</h2>
        <div class="card list">
          {#each app.scenarios.events.slice(0, 6) as e}
            <div class="row"><div class="label"><b>{e.name}</b><span>{uiText(e.why)} — {e.result}</span></div><span class="dim mono">{uiText(when(e.time))}</span></div>
          {/each}
        </div>
      </section>
    {/if}
  {/if}
{/if}

<datalist id="apps-list">{#each app.scenarios?.choices?.apps ?? [] as a}<option value={a}></option>{/each}</datalist>
<datalist id="devices-list">{#each app.scenarios?.choices?.devices ?? [] as a}<option value={a}></option>{/each}</datalist>

<style>
  .head {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 16px;
  }
  .head-actions {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  .tabs {
    display: flex;
    gap: 4px;
    margin-bottom: 14px;
    border-bottom: 1px solid var(--line);
  }
  .tabs button {
    display: flex;
    align-items: center;
    gap: 6px;
    height: 36px;
    padding: 0 12px;
    border: none;
    border-bottom: 2px solid transparent;
    background: none;
    color: var(--text-2);
    font: inherit;
    font-weight: 560;
    cursor: pointer;
  }
  .tabs button.active {
    color: var(--accent-2);
    border-bottom-color: var(--accent-2);
  }
  .tester {
    margin-bottom: 12px;
  }
  .toolbar {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin-bottom: 12px;
  }
  .search {
    flex: 1;
    min-width: 200px;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 12px;
    border-radius: 10px;
    border: 1px solid var(--line-2);
    background: var(--field);
    color: var(--text-3);
  }
  .search:focus-within {
    border-color: var(--accent);
  }
  .search input {
    flex: 1;
    border: none;
    background: transparent;
    box-shadow: none !important;
    padding: 0;
  }
  .group {
    margin-top: 14px;
  }
  .group h2 {
    margin: 0 0 6px 4px;
  }
  .list {
    padding: 4px 8px;
  }
  .item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 4px;
    border-bottom: 1px solid var(--line);
  }
  .item:last-child {
    border-bottom: none;
  }
  .item.off .main {
    opacity: 0.55;
  }
  .main {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 1px;
    border: none;
    background: none;
    color: var(--text);
    font: inherit;
    text-align: left;
    cursor: pointer;
    padding: 2px 6px;
    border-radius: 8px;
  }
  .main:hover {
    background: var(--hover);
  }
  .name {
    display: flex;
    gap: 6px;
    align-items: center;
    font-weight: 600;
  }
  .phr {
    max-width: 100%;
    font-size: 12.5px;
    color: var(--text-2);
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .conf {
    display: flex;
    gap: 4px;
    align-items: center;
    font-size: 12px;
    color: var(--warn);
  }
  .trg {
    display: flex;
    gap: 4px;
    color: var(--text-3);
  }
  .acts {
    display: flex;
  }
  @media (max-width: 700px) {
    .head {
      flex-direction: column;
    }
    .trg {
      display: none;
    }
  }
</style>
