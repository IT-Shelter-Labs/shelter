<script lang="ts">
  import { t as uiText } from "../../lib/i18n.svelte";

  // Редактор сценария: «Что сказать → Когда выполнять → Шаги → Проверка → Сохранить».
  // Черновик живёт в drafts (переходы по окну его не теряют); Ctrl+Z / Ctrl+Y — отмена и повтор.
  import { onMount } from "svelte";
  import { MessageSquareQuote, CalendarClock, ListOrdered, ShieldCheck, Save, Undo2, Redo2, Play, X, Plus, Braces, Trash2, Download, CircleAlert, Info } from "@lucide/svelte";
  import { save as saveDialog } from "../../lib/fileDialogs";
  import StepList from "./StepList.svelte";
  import FlowEditor from "./FlowEditor.svelte";
  import Segmented from "../Segmented.svelte";
  import FieldInput from "./FieldInput.svelte";
  import ConditionInput from "./ConditionInput.svelte";
  import PhraseTester from "./PhraseTester.svelte";
  import RunPanel from "./RunPanel.svelte";
  import { app, navigate, setGuard, toast, toastError } from "../../lib/store.svelte";
  import { api, type Scenario, type Plan, type Trigger } from "../../lib/api";
  import { drafts, remember, forget, isDirty } from "../../lib/drafts.svelte";
  import { ask } from "../../lib/dialog.svelte";

  let { isNew = false, notes = [] as string[] }: { isNew?: boolean; notes?: string[] } = $props();
  let advanced = $state(false);
  let stepView = $state("cards");
  let jsonMode = $state(false);
  let jsonText = $state("");
  let jsonError = $state("");
  let phraseInput = $state("");
  let plan = $state<Plan | null>(null);
  let conflicts = $state<{ text: string }[]>([]);
  let saving = $state(false);
  let run = $state("");
  let planTimer: ReturnType<typeof setTimeout> | undefined;
  let historyTimer: ReturnType<typeof setTimeout> | undefined;

  const d = $derived(drafts.current!);
  const triggerSpecs = $derived(app.scenarios?.triggers ?? {});
  const extraTriggers = $derived((d?.triggers ?? []).map((t, i) => ({ t, i })).filter(({ t }) => !["voice", "button"].includes(t.type)));
  const categories = $derived([...new Set(["Мои", "Программы", "Музыка", "Режимы", "Компьютер", "Стрим", "Учёба", "Разговор", "Личное", ...(app.scenarios?.items ?? []).map((s: Scenario) => s.category)])]);

  // ------------------------------------------------------------ правки и история
  function change(patch: Partial<Scenario>) {
    const before = JSON.stringify($state.snapshot(drafts.current));
    Object.assign(drafts.current!, patch);
    clearTimeout(historyTimer);
    if (!historyTimer) drafts.history.push(before);
    historyTimer = setTimeout(() => (historyTimer = undefined), 600);   // несколько нажатий подряд — одна отмена
    drafts.future = [];
    if (drafts.history.length > 80) drafts.history.shift();
    remember();
    schedulePlan();
  }
  function undo() {
    const prev = drafts.history.pop();
    if (!prev) return;
    drafts.future.push(JSON.stringify($state.snapshot(drafts.current)));
    drafts.current = JSON.parse(prev);
    remember();
    schedulePlan();
  }
  function redo() {
    const next = drafts.future.pop();
    if (!next) return;
    drafts.history.push(JSON.stringify($state.snapshot(drafts.current)));
    drafts.current = JSON.parse(next);
    remember();
    schedulePlan();
  }
  function keys(e: KeyboardEvent) {
    if (!(e.ctrlKey || e.metaKey)) return;
    const k = e.key.toLowerCase();
    if (k === "s") { e.preventDefault(); save(); return; }
    // В текстовом поле Ctrl+Z отменяет набор в самом поле.
    if (["INPUT", "TEXTAREA", "SELECT"].includes((e.target as HTMLElement).tagName)) return;
    if (k === "z" && !e.shiftKey) { e.preventDefault(); undo(); }
    else if (k === "y" || (k === "z" && e.shiftKey)) { e.preventDefault(); redo(); }
  }

  // ---------------------------------------------------------------- фразы
  function addPhrase(from?: HTMLInputElement) {
    // Значение берём из самого поля: вставка из буфера или автозаполнение могут не обновить привязку.
    if (from) phraseInput = from.value;
    const words = phraseInput.split(/[,;\n]/).map((p) => p.trim().toLowerCase().replace(/ё/g, "е")).filter(Boolean);
    if (!words.length) return;
    change({ phrases: [...new Set([...(d.phrases ?? []), ...words])] });
    phraseInput = "";
  }
  const hasTrigger = (type: string) => (d.triggers ?? []).some((t) => t.type === type);
  function setTrigger(type: string, on: boolean) {
    change({ triggers: on ? [...d.triggers, { type }] : d.triggers.filter((t) => t.type !== type) });
  }
  function addTrigger(type: string) {
    const t: Trigger = { type };
    for (const f of triggerSpecs[type]?.fields ?? []) if (f.default !== undefined) t[f.key] = f.default;
    change({ triggers: [...d.triggers, t] });
  }

  // -------------------------------------------------------------- проверка
  function schedulePlan() {
    clearTimeout(planTimer);
    planTimer = setTimeout(refreshPlan, 450);
  }
  async function refreshPlan() {
    if (!app.status || !drafts.current) return;
    const item = $state.snapshot(drafts.current);
    try {
      const [p, v] = await Promise.all([api.scenarioOp<Plan>({ op: "plan", item }), api.scenarioOp<{ problems: string[]; conflicts: { text: string }[] }>({ op: "validate", item })]);
      plan = p;
      conflicts = v.conflicts;
    } catch (e) {
      plan = null;
    }
  }
  async function tryRun() {
    if (plan?.problems.length) { toastError("Сначала исправьте: " + plan.problems[0]); return; }
    const irreversible = plan?.steps.some((s) => s.irreversible && !s.off);
    if (irreversible && (await ask({ title: "Пробный запуск", text: "В сценарии есть необратимые шаги (например, команда Windows). Их нельзя отменить. Запустить по-настоящему?", ok: "Запустить", danger: true })) !== "ok") return;
    try {
      const r = await api.scenarioOp<{ run: string }>({ op: "run_draft", item: $state.snapshot(drafts.current), confirmed: true });
      run = r.run;
    } catch (e) { toastError(e); }
  }

  // ------------------------------------------------------------- сохранение
  async function save() {
    if (!drafts.current) return false;
    saving = true;
    try {
      const wasNew = !drafts.current.id;
      const r = await api.scenarioOp<{ item: Scenario; conflicts: { text: string }[] }>({ op: "save", item: $state.snapshot(drafts.current) });
      drafts.current = r.item;
      drafts.original = JSON.stringify(r.item);
      remember();
      app.scenarios = await api.scenarios();
      toast(`«${r.item.name}» сохранён и уже работает`, "success");
      if (r.conflicts.length) toast(r.conflicts[0].text, "info");
      if (wasNew) navigate("commands", "edit:" + r.item.id, false);
      return true;
    } catch (e) {
      toastError(e);
      return false;
    } finally {
      saving = false;
    }
  }
  async function close() {
    if (await leaveGuard()) { forget(); setGuard(null); navigate("commands", ""); }
  }
  async function leaveGuard() {
    if (!isDirty()) return true;
    const choice = await ask({ title: "Сохранить изменения?", text: `В сценарии «${d.name || "без названия"}» есть несохранённые правки.`, ok: "Сохранить", extra: "Не сохранять", cancel: "Остаться" });
    if (choice === "ok") return await save();
    if (choice === "extra") { forget(); return true; }
    return false;
  }
  async function remove() {
    if ((await ask({ title: "Удалить сценарий?", text: `«${d.name}» будет удалён. Копия списка сохранится в резервных копиях — его можно вернуть.`, ok: "Удалить", danger: true })) !== "ok") return;
    try {
      await api.scenarioOp({ op: "delete", id: d.id });
      app.scenarios = await api.scenarios();
      forget();
      setGuard(null);
      navigate("commands", "");
      toast("Удалено. Вернуть можно из резервной копии");
    } catch (e) { toastError(e); }
  }
  async function exportOne() {
    const path = await saveDialog({ defaultPath: `${d.name || "сценарий"}.jarvis.json`, filters: [{ name: "Сценарий Джарвиса", extensions: ["json"] }] });
    if (!path) return;
    try { const r = await api.scenarioOp<{ removed: string[] }>({ op: "export_file", path, ids: [d.id] }); toast(r.removed.length ? `Сохранено. Убраны секреты: ${r.removed.length}` : "Сохранено", "success"); }
    catch (e) { toastError(e); }
  }

  // ------------------------------------------------------------------ JSON
  function openJson() {
    jsonText = JSON.stringify($state.snapshot(drafts.current), null, 2);
    jsonError = "";
    jsonMode = true;
  }
  function applyJson() {
    try {
      const value = JSON.parse(jsonText);
      if (typeof value !== "object" || Array.isArray(value) || !Array.isArray(value.steps)) throw new Error("нужен объект сценария со списком steps");
      change(value);
      jsonMode = false;
    } catch (e) { jsonError = "Ошибка в JSON: " + (e as Error).message; }
  }

  onMount(() => {
    setGuard(leaveGuard);
    refreshPlan();
    return () => setGuard(null);
  });
</script>

<svelte:window onkeydown={keys} />

{#if d}
<div class="editor">
  <header class="top">
    <div>
      <span class="caps">{uiText(isNew ? "Новый сценарий" : "Сценарий")}</span>
      <h1>{uiText(d.name || "Без названия")}</h1>
    </div>
    <div class="actions">
      <button class="btn ghost icon" aria-label={uiText("Отменить правку (Ctrl+Z)")} title={uiText("Отменить (Ctrl+Z)")} disabled={!drafts.history.length} onclick={undo}><Undo2 size={16} /></button>
      <button class="btn ghost icon" aria-label={uiText("Повторить правку (Ctrl+Y)")} title={uiText("Повторить (Ctrl+Y)")} disabled={!drafts.future.length} onclick={redo}><Redo2 size={16} /></button>
      <button class="btn ghost" onclick={close}><X size={15} />{uiText(" Закрыть")}</button>
      <button class="btn primary" disabled={saving || !isDirty()} onclick={save} title={uiText("Сохранить (Ctrl+S)")}><Save size={15} /> {uiText(isDirty() ? "Сохранить" : "Сохранено")}</button>
    </div>
  </header>
  {#each notes as n}<div class="notice warn"><Info size={15} /> {n}</div>{/each}

  <!-- 1. Что сказать -->
  <section class="card section">
    <h2><span class="n">1</span><MessageSquareQuote size={18} />{uiText(" Что сказать")}</h2>
    <div class="grid">
      <label class="field"><span>{uiText("Название")}</span><input type="text" value={d.name} maxlength="80" aria-invalid={!d.name.trim()} oninput={(e) => change({ name: e.currentTarget.value })} placeholder={uiText("Например: Рабочий режим")} />{#if !d.name.trim()}<span class="error">{uiText("Дайте название")}</span>{/if}</label>
      <label class="field"><span>{uiText("Раздел")}</span><input type="text" list="categories" value={d.category} oninput={(e) => change({ category: e.currentTarget.value })} /></label>
    </div>
    <datalist id="categories">{#each categories as c}<option value={c}></option>{/each}</datalist>
    <div class="field phrases">
      <span>{uiText("Фразы для голоса")}</span>
      <div class="chips">
        {#each d.phrases as p, i}
          <span class="phrase">«{uiText(p)}»<button aria-label={uiText("Убрать фразу " + String(p))} onclick={() => change({ phrases: d.phrases.filter((_, k) => k !== i) })}><X size={12} /></button></span>
        {/each}
        <form onsubmit={(e) => { e.preventDefault(); addPhrase(e.currentTarget.querySelector("input") ?? undefined); }}>
          <input type="text" placeholder={uiText(d.phrases.length ? "Ещё фраза…" : "Например: рабочий режим")} aria-label={uiText("Новая фраза")} bind:value={phraseInput}
                 onblur={(e) => addPhrase(e.currentTarget)} onchange={(e) => addPhrase(e.currentTarget)} />
          <button class="btn sm" type="submit" disabled={!phraseInput.trim()}><Plus size={13} />{uiText(" Добавить")}</button>
        </form>
      </div>
      <span class="help">{uiText("Enter — добавить. Звёздочка в конце — «по началу слова»: «музык*» сработает на «музыку» и «музыкальный».")}</span>
    </div>
    <div class="options">
      <label><input type="radio" name="match" checked={d.match === "word"} onchange={() => change({ match: "word" })} />{uiText(" Фраза может быть частью короткой просьбы ")}<small class="dim">{uiText("(«включи ")}<b>{uiText("музыку")}</b>{uiText(" пожалуйста»)")}</small></label>
      <label><input type="radio" name="match" checked={d.match === "whole"} onchange={() => change({ match: "whole" })} />{uiText(" Только фраза целиком ")}<small class="dim">{uiText("(«пока», но не «пока не закрывай»)")}</small></label>
      <label><input type="checkbox" checked={d.keep_listening} onchange={(e) => change({ keep_listening: e.currentTarget.checked })} />{uiText(" После выполнения продолжать слушать")}</label>
    </div>
  </section>

  <!-- 2. Когда выполнять -->
  <section class="card section">
    <h2><span class="n">2</span><CalendarClock size={18} />{uiText(" Когда выполнять")}</h2>
    <div class="options">
      <label><input type="checkbox" checked={hasTrigger("voice")} onchange={(e) => setTrigger("voice", e.currentTarget.checked)} />{uiText(" Голосом — по фразам выше")}</label>
      <label><input type="checkbox" checked={hasTrigger("button")} onchange={(e) => setTrigger("button", e.currentTarget.checked)} />{uiText(" Кнопкой на главной и с телефона")}</label>
    </div>
    {#each extraTriggers as { t, i } (i)}
      {@const spec = triggerSpecs[t.type]}
      <div class="trigger">
        <div class="trigger-head"><b>{uiText(spec?.label ?? t.type)}</b>
          {#if spec?.unavailable}<span class="badge warn">{uiText(spec.unavailable)}</span>{/if}
          {#if spec?.hint}<span class="dim small">{uiText(spec.hint)}</span>{/if}
          <button class="btn ghost icon sm" aria-label={uiText("Убрать способ запуска")} onclick={() => change({ triggers: d.triggers.filter((_, k) => k !== i) })}><Trash2 size={13} /></button></div>
        <div class="grid">
          {#each spec?.fields ?? [] as f}<FieldInput field={f} value={t[f.key]} id={`trg-${i}-${f.key}`} onchange={(v) => change({ triggers: d.triggers.map((x, k) => (k === i ? { ...x, [f.key]: v } : x)) })} />{/each}
        </div>
      </div>
    {/each}
    <label class="field add-trigger"><span>{uiText("Добавить автоматический запуск")}</span>
      <select value="" onchange={(e) => { if (e.currentTarget.value) addTrigger(e.currentTarget.value); e.currentTarget.value = ""; }}>
        <option value="">{uiText("— выберите событие —")}</option>
        {#each Object.entries(triggerSpecs).filter(([id]) => !["voice", "button"].includes(id)) as [id, spec]}
          <option value={id} disabled={!!spec.unavailable || (!!spec.platforms && !spec.platforms.includes(app.scenarios?.platform ?? "windows"))}>{uiText(spec.label)}{uiText(spec.unavailable ? " — недоступно" : "")}</option>
        {/each}
      </select>
      <span class="help">{uiText("События проверяются без нейросети раз в несколько секунд. Повтор не чаще, чем раз в ")}{uiText(d.cooldown)}{uiText(" с.")}</span>
    </label>

    <div class="sub">
      <span class="caps">{uiText("Условия запуска")}</span>
      {#each d.conditions as c, i}
        <div class="cond"><ConditionInput value={c} onchange={(v) => change({ conditions: d.conditions.map((x, k) => (k === i ? v : x)) })} />
          <button class="btn ghost icon sm" aria-label={uiText("Убрать условие")} onclick={() => change({ conditions: d.conditions.filter((_, k) => k !== i) })}><Trash2 size={13} /></button></div>
      {:else}<p class="dim small">{uiText("Без условий — выполняется всегда.")}</p>{/each}
      <button class="btn sm" onclick={() => change({ conditions: [...d.conditions, { type: "time_between", from: "08:00", to: "23:00" }] })}><Plus size={13} />{uiText(" Условие")}</button>
    </div>
    <div class="grid">
      <label class="field"><span>{uiText("Переспросить перед запуском (необязательно)")}</span><input type="text" value={d.confirm} placeholder={uiText("Например: Точно выключить компьютер?")} oninput={(e) => change({ confirm: e.currentTarget.value })} /><span class="help">{uiText("Для опасного: выключение, закрытие программ")}</span></label>
      <label class="field"><span>{uiText("Если шаг не удался")}</span>
        <select value={d.on_error} onchange={(e) => change({ on_error: e.currentTarget.value as any })}>
          <option value="stop">{uiText("Остановиться и сказать причину")}</option>
          <option value="continue">{uiText("Пропустить шаг и продолжить")}</option>
        </select></label>
      {#if advanced}
        <label class="field"><span>{uiText("Ограничение времени, с")}</span><input type="number" min="1" max="3600" value={d.timeout} oninput={(e) => change({ timeout: Number(e.currentTarget.value) })} /></label>
        <label class="field"><span>{uiText("Пауза между автозапусками, с")}</span><input type="number" min="0" max="86400" value={d.cooldown} oninput={(e) => change({ cooldown: Number(e.currentTarget.value) })} /></label>
      {/if}
    </div>
  </section>

  <!-- 3. Шаги -->
  <section class="card section">
    <div class="card-head">
      <h2><span class="n">3</span><ListOrdered size={18} />{uiText(" Шаги")}</h2>
      <label class="adv"><input type="checkbox" bind:checked={advanced} />{uiText(" Продвинутый режим")}</label>
    </div>
    {#if !d.steps.length}<p class="dim small">{uiText("Добавьте первое действие: открыть программу, поставить окно на монитор, включить музыку…")}</p>{/if}
    <div class="step-view"><Segmented value={stepView} options={[{value: "cards", label: "Карточки"}, {value: "flow", label: "Схема"}]} onchange={value => stepView = value} /></div>
    {#if stepView === "flow"}<FlowEditor steps={d.steps} {advanced} onchange={(steps) => change({steps})} />
    {:else}<StepList steps={d.steps} {advanced} onchange={(steps) => change({ steps })} />{/if}
  </section>

  <!-- 4. Проверка -->
  <section class="card section">
    <h2><span class="n">4</span><ShieldCheck size={18} />{uiText(" Проверка")}</h2>
    {#if !app.status}
      <p class="dim">{uiText("Включите Джарвиса, чтобы проверить сценарий.")}</p>
    {:else if plan}
      {#if plan.problems.length}
        <div class="notice bad"><CircleAlert size={15} /><div>{#each plan.problems as p}<div>{uiText(p)}</div>{/each}</div></div>
      {:else}
        <div class="notice ok"><ShieldCheck size={15} />{uiText(" Можно сохранять. Вот что произойдёт — ничего не выполняется, пока вы не нажмёте «Пробный запуск».")}</div>
      {/if}
      {#each conflicts as c}<div class="notice warn"><CircleAlert size={15} /> {uiText(c.text)}</div>{/each}
      <div class="plan">
        <p class="small"><b>{uiText("Запуск:")}</b> {uiText(plan.triggers.join("; ") || "не задан")}{uiText(plan.conditions.length ? ` · если ${plan.conditions.join(", ")}` : "")}{uiText(plan.confirm ? ` · сначала спросит «${plan.confirm}»` : "")}</p>
        <ol>{#each plan.steps.filter((l) => !l.group) as line}<li style="margin-left:{line.depth * 16}px" class:off={line.off}>{uiText(line.text)}
          {#if line.note}<span class="badge warn">{uiText(line.note)}</span>{/if}{#if line.irreversible}<span class="badge warn">{uiText("необратимо")}</span>{/if}{#if line.llm}<span class="badge">{uiText("нейросеть")}</span>{/if}</li>{/each}</ol>
        {#if plan.uses_llm}<p class="dim small">{uiText("Шаг «Спросить нейросеть» думает; остальные шаги выполняются без модели.")}</p>{/if}
      </div>
      <PhraseTester draft={d} compact />
      <div class="try">
        <button class="btn" onclick={tryRun} disabled={!!plan.problems.length}><Play size={14} />{uiText(" Пробный запуск")}</button>
        <span class="dim small">{uiText("Выполняет шаги по-настоящему, не сохраняя сценарий.")}</span>
      </div>
      {#if run}<RunPanel {run} />{/if}
    {:else}
      <p class="dim">{uiText("Проверяю…")}</p>
    {/if}
  </section>

  <!-- 5. Сохранить -->
  <section class="card section final">
    <h2><span class="n">5</span><Save size={18} />{uiText(" Сохранить")}</h2>
    <div class="actions">
      <button class="btn primary lg" disabled={saving || !isDirty()} onclick={save}><Save size={16} /> {uiText(isDirty() ? "Сохранить" : "Сохранено")}</button>
      {#if !isNew}<button class="btn" onclick={exportOne}><Download size={15} />{uiText(" Экспорт в файл")}</button>{/if}
      <button class="btn" onclick={openJson}><Braces size={15} /> JSON</button>
      {#if !isNew}<button class="btn danger" onclick={remove}><Trash2 size={15} />{uiText(" Удалить")}</button>{/if}
    </div>
    {#if jsonMode}
      <div class="json fade-in">
        <p class="dim small">{uiText("Для опытных. Изменения проверяются ядром перед сохранением; неизвестные действия отклоняются с объяснением.")}</p>
        <textarea class="mono" rows="16" bind:value={jsonText} aria-invalid={!!jsonError} spellcheck="false"></textarea>
        {#if jsonError}<p class="error">{uiText(jsonError)}</p>{/if}
        <div class="actions"><button class="btn" onclick={applyJson}>{uiText("Применить JSON")}</button><button class="btn ghost" onclick={() => (jsonMode = false)}>{uiText("Отмена")}</button></div>
      </div>
    {/if}
  </section>
</div>
{/if}

<style>
  .editor {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .top {
    position: sticky;
    top: -18px;
    z-index: 4;
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    gap: 12px;
    padding: 10px 0;
    background: var(--bg);
    flex-wrap: wrap;
  }
  .top h1 {
    font-size: 22px;
  }
  .actions {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    align-items: center;
  }
  .section + .section {
    margin-top: 0;
  }
  .section h2 {
    display: flex;
    align-items: center;
    gap: 9px;
    margin-bottom: 12px;
    font-size: 17px;
  }
  .n {
    display: grid;
    place-items: center;
    width: 24px;
    height: 24px;
    border-radius: 50%;
    background: var(--accent-soft);
    color: var(--accent-2);
    font-size: 13px;
    font-weight: 700;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
    gap: 12px;
    margin-top: 10px;
  }
  .phrases {
    margin-top: 12px;
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
    padding: 6px;
    border-radius: 10px;
    border: 1px solid var(--line-2);
    background: var(--field);
  }
  .chips form {
    flex: 1;
    min-width: 160px;
    display: flex;
    gap: 6px;
  }
  .chips input {
    width: 100%;
    border: none;
    background: transparent;
    box-shadow: none !important;
    height: 28px;
    padding: 0 4px;
  }
  .phrase {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 3px 4px 3px 10px;
    border-radius: 999px;
    background: var(--accent-soft);
    color: var(--accent-2);
    font-size: 13px;
  }
  .phrase button {
    display: grid;
    place-items: center;
    width: 20px;
    height: 20px;
    border: none;
    border-radius: 50%;
    background: transparent;
    color: inherit;
    cursor: pointer;
  }
  .phrase button:hover {
    background: var(--press);
  }
  .options {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin-top: 12px;
    font-size: 13.5px;
  }
  .options label,
  .adv {
    display: flex;
    gap: 8px;
    align-items: baseline;
  }
  .adv {
    font-size: 13px;
    color: var(--text-2);
  }
  .trigger,
  .cond {
    margin-top: 10px;
    padding: 10px 12px;
    border-radius: 10px;
    border: 1px solid var(--line-2);
    background: var(--surface-2);
  }
  .cond {
    display: flex;
    gap: 6px;
    align-items: flex-start;
    padding: 4px;
    border: none;
    background: none;
  }
  .cond :global(.condition) {
    flex: 1;
  }
  .trigger-head {
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .trigger-head b {
    flex: none;
  }
  .trigger-head button {
    margin-left: auto;
  }
  .add-trigger {
    margin-top: 12px;
    max-width: 420px;
  }
  .sub {
    margin-top: 16px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    align-items: flex-start;
  }
  .sub .cond {
    align-self: stretch;
  }
  .small {
    font-size: 12.5px;
  }
  .plan {
    margin: 10px 0 14px;
    padding: 10px 14px;
    border-radius: 10px;
    background: var(--surface-2);
    border: 1px solid var(--line);
  }
  .plan ol {
    margin: 6px 0 0;
    padding-left: 20px;
    font-size: 13px;
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .plan .off {
    text-decoration: line-through;
    opacity: 0.55;
  }
  .notice + .notice,
  .notice {
    margin-bottom: 8px;
  }
  .try {
    display: flex;
    gap: 10px;
    align-items: center;
    margin-top: 12px;
    flex-wrap: wrap;
  }
  .json {
    margin-top: 12px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .json textarea {
    width: 100%;
    font-size: 12.5px;
  }
  .error {
    color: var(--bad);
  }
</style>
