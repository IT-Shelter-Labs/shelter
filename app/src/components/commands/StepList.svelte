<script lang="ts">
  import { t as uiText } from "../../lib/i18n.svelte";

  // Шаги сценария карточками: перестановка (кнопки и перетаскивание), копия,
  // выключение шага, вложенные «если/иначе» и «повторить».
  import { ChevronDown, ChevronRight, ArrowUp, ArrowDown, Copy, Trash2, GripVertical, Plus, Power, TriangleAlert } from "@lucide/svelte";
  import StepList from "./StepList.svelte";
  import FieldInput from "./FieldInput.svelte";
  import StepPicker from "./StepPicker.svelte";
  import { app } from "../../lib/store.svelte";
  import type { Step } from "../../lib/api";

  let { steps, onchange, advanced = false, depth = 0, path = "s" }: { steps: Step[]; onchange: (s: Step[]) => void; advanced?: boolean; depth?: number; path?: string } = $props();
  const specs = $derived(app.scenarios?.actions ?? {});
  let openIndex = $state<number | null>(null);
  let picking = $state(false);
  let dragFrom: number | null = null;
  let dropAt = $state<number | null>(null);

  const replace = (i: number, step: Step) => onchange(steps.map((s, k) => (k === i ? step : s)));
  function move(i: number, d: number) {
    const j = i + d;
    if (j < 0 || j >= steps.length) return;
    const next = [...steps];
    [next[i], next[j]] = [next[j], next[i]];
    onchange(next);
    if (openIndex === i) openIndex = j;
  }
  function add(type: string) {
    const spec = specs[type];
    const step: Step = { type };
    for (const f of spec?.fields ?? []) if (f.default !== undefined) step[f.key] = f.default;
    if (type === "if") Object.assign(step, { then: [], else: [] });
    if (type === "repeat") step.steps = [];
    const index = steps.length;          // до onchange: свойство steps «живое» и сразу удлинится
    onchange([...steps, step]);
    openIndex = index;
    picking = false;
  }
  function summary(step: Step) {
    const spec = specs[step.type];
    const first = spec?.fields.find((f) => step[f.key] !== undefined && step[f.key] !== "" && typeof step[f.key] !== "object");
    if (!first) return "";
    const value = step[first.key];
    const option = first.options?.find(([v]) => v === value)?.[1];
    const text = String(option ?? value);
    return text.length > 60 ? text.slice(0, 59) + "…" : text;
  }
  const missing = (step: Step) => (specs[step.type]?.fields ?? []).some((f) => f.required && (step[f.key] === undefined || step[f.key] === "" ) && f.kind !== "condition");

  function drop(i: number) {
    if (dragFrom === null || dragFrom === i) { dropAt = null; return; }
    const next = [...steps];
    const [item] = next.splice(dragFrom, 1);
    next.splice(dragFrom < i ? i - 1 : i, 0, item);
    onchange(next);
    dragFrom = null;
    dropAt = null;
  }
</script>

<ol class="steps" class:nested={depth > 0}>
  {#each steps as step, i (i + ":" + step.type)}
    {@const spec = specs[step.type]}
    <li class="step" class:off={step.enabled === false} class:drop={dropAt === i}
        ondragover={(e) => { e.preventDefault(); dropAt = i; }} ondragleave={() => (dropAt = null)} ondrop={() => drop(i)}>
      <div class="head">
        <span class="grip" draggable="true" role="button" tabindex="-1" aria-label={uiText("Перетащить шаг")} title={uiText("Перетащить")}
              ondragstart={(e) => { dragFrom = i; e.dataTransfer?.setData("text/plain", String(i)); }}><GripVertical size={14} /></span>
        <span class="num mono">{uiText(i + 1)}</span>
        <button class="toggle-open" aria-expanded={openIndex === i} onclick={() => (openIndex = openIndex === i ? null : i)}>
          {#if openIndex === i}<ChevronDown size={14} />{:else}<ChevronRight size={14} />{/if}
          <b>{uiText(spec?.label ?? `Неизвестное действие «${step.type}»`)}</b>
          {#if openIndex !== i}<span class="sum">{uiText(summary(step))}</span>{/if}
          {#if !spec || missing(step)}<TriangleAlert size={13} color="var(--warn)" />{/if}
          {#if spec?.irreversible}<span class="badge warn">{uiText("необратимо")}</span>{/if}
          {#if step.type === "ask"}<span class="badge">{uiText("нейросеть")}</span>{/if}
          {#if step.enabled === false}<span class="badge plain">{uiText("выключен")}</span>{/if}
          {#if step.note}<span class="badge warn" title={uiText(step.note)}>{uiText(step.note)}</span>{/if}
        </button>
        <span class="tools">
          <button class="btn ghost icon sm" aria-label={uiText("Выше")} title={uiText("Выше")} disabled={i === 0} onclick={() => move(i, -1)}><ArrowUp size={13} /></button>
          <button class="btn ghost icon sm" aria-label={uiText("Ниже")} title={uiText("Ниже")} disabled={i === steps.length - 1} onclick={() => move(i, 1)}><ArrowDown size={13} /></button>
          <button class="btn ghost icon sm" aria-label={uiText(step.enabled === false ? "Включить шаг" : "Выключить шаг")} title={uiText(step.enabled === false ? "Включить шаг" : "Выключить шаг, не удаляя")}
                  onclick={() => replace(i, { ...step, enabled: step.enabled === false })}><Power size={13} /></button>
          <button class="btn ghost icon sm" aria-label={uiText("Копия шага")} title={uiText("Копия")} onclick={() => onchange([...steps.slice(0, i + 1), structuredClone($state.snapshot(step)), ...steps.slice(i + 1)])}><Copy size={13} /></button>
          <button class="btn ghost icon sm danger" aria-label={uiText("Удалить шаг")} title={uiText("Удалить")} onclick={() => onchange(steps.filter((_, k) => k !== i))}><Trash2 size={13} /></button>
        </span>
      </div>
      {#if openIndex === i && spec}
        <div class="body fade-in">
          {#if spec.hint}<p class="hint dim">{uiText(spec.hint)}</p>{/if}
          <div class="form">
            {#each spec.fields.filter((f) => advanced || !f.advanced) as f}
              {#if !f.show_if || Object.entries(f.show_if).every(([k, v]) => (step[k] ?? spec.fields.find((x) => x.key === k)?.default) === v)}
                <FieldInput field={f} value={step[f.key]} {step} id={`${path}-${i}-${f.key}`} onchange={(v) => replace(i, { ...step, [f.key]: v })} />
              {/if}
            {/each}
          </div>
          {#if spec.safe_retry}
            <label class="retry"><input type="checkbox" checked={!!step.retry} onchange={(e) => replace(i, { ...step, retry: e.currentTarget.checked ? 2 : 0 })} />{uiText(" Повторить до двух раз, если не получилось (это безопасно)")}</label>
          {/if}
        </div>
      {/if}
      {#if step.type === "if"}
        <div class="branch"><span class="caps">{uiText("То")}</span><StepList steps={step.then ?? []} {advanced} depth={depth + 1} path={`${path}-${i}t`} onchange={(s) => replace(i, { ...step, then: s })} /></div>
        <div class="branch"><span class="caps">{uiText("Иначе")}</span><StepList steps={step.else ?? []} {advanced} depth={depth + 1} path={`${path}-${i}e`} onchange={(s) => replace(i, { ...step, else: s })} /></div>
      {:else if step.type === "repeat"}
        <div class="branch"><span class="caps">{uiText("Повторять")}</span><StepList steps={step.steps ?? []} {advanced} depth={depth + 1} path={`${path}-${i}r`} onchange={(s) => replace(i, { ...step, steps: s })} /></div>
      {/if}
    </li>
  {/each}
</ol>

{#if picking}
  <StepPicker {advanced} nested={depth > 0} onpick={add} onclose={() => (picking = false)} />
{:else}
  <button class="btn {depth ? 'ghost sm' : ''} add" onclick={() => (picking = true)}><Plus size={14} /> {uiText(depth ? "Добавить сюда" : "Добавить шаг")}</button>
{/if}

<style>
  .steps {
    list-style: none;
    margin: 0 0 8px;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .steps.nested {
    margin-top: 4px;
  }
  .step {
    border: 1px solid var(--line-2);
    border-radius: 12px;
    background: var(--surface-2);
    padding: 4px 6px 4px 4px;
  }
  .step.off {
    opacity: 0.6;
    border-style: dashed;
  }
  .step.drop {
    box-shadow: 0 -2px 0 var(--accent);
  }
  .head {
    display: flex;
    align-items: center;
    gap: 4px;
    min-height: 34px;
  }
  .grip {
    cursor: grab;
    color: var(--text-3);
    display: grid;
    place-items: center;
    width: 20px;
  }
  .num {
    width: 20px;
    text-align: center;
    font-size: 12px;
    color: var(--text-3);
  }
  .toggle-open {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 7px;
    border: none;
    background: none;
    color: var(--text);
    font: inherit;
    text-align: left;
    cursor: pointer;
    padding: 4px;
    border-radius: 8px;
  }
  .toggle-open:hover {
    background: var(--hover);
  }
  .toggle-open b {
    font-weight: 600;
    white-space: nowrap;
  }
  .sum {
    color: var(--text-2);
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    min-width: 0;
  }
  .tools {
    display: flex;
    flex: none;
  }
  .body {
    padding: 6px 10px 12px 52px;
  }
  .hint {
    font-size: 12.5px;
    margin-bottom: 8px;
  }
  .form {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 12px;
  }
  .retry {
    display: flex;
    gap: 8px;
    align-items: center;
    margin-top: 10px;
    font-size: 12.5px;
    color: var(--text-2);
  }
  .branch {
    margin: 2px 6px 8px 52px;
    padding-left: 10px;
    border-left: 2px solid var(--line-2);
  }
  .add {
    margin-top: 2px;
  }
  @media (max-width: 700px) {
    .body,
    .branch {
      padding-left: 8px;
      margin-left: 8px;
    }
    .tools .btn:nth-child(-n + 2) {
      display: none;
    }
  }
</style>
