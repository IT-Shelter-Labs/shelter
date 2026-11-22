<script lang="ts">
  import { t as uiText } from "../../lib/i18n.svelte";

  import { GitBranch, Repeat2, CirclePlay, CircleCheck, Pencil, X } from "@lucide/svelte";
  import { app } from "../../lib/store.svelte";
  import StepList from "./StepList.svelte";
  import type { Step } from "../../lib/api";
  let { steps, advanced = false, onchange }: {steps: Step[]; advanced?: boolean; onchange: (steps: Step[]) => void} = $props();
  let selected = $state("");
  function at(root: Step[], path: string) {
    const keys = path.split(".");
    let value: any = root;
    for (const key of keys) value = value?.[key];
    return value as Step | undefined;
  }
  const current = $derived(selected ? at(steps, selected) : undefined);
  const label = (step: Step) => app.scenarios?.actions?.[step.type]?.label || step.type;
  const description = (step: Step) => String(step.text || step.target || step.name || step.title || step.url || step.animation || "").slice(0, 90);
  function edit(replacement: Step[]) {
    const next = structuredClone($state.snapshot(steps));
    const keys = selected.split(".");
    const index = Number(keys.pop());
    let parent: any = next;
    for (const key of keys) parent = parent?.[key];
    if (!Array.isArray(parent) || !Number.isInteger(index)) return;
    parent.splice(index, 1, ...replacement);
    if (!replacement.length) selected = "";
    onchange(next);
  }
</script>

<p class="explanation">{uiText("Выберите блок, чтобы изменить его. Ветвления и повторы редактируются теми же карточками; схема и список всегда описывают один сценарий.")}</p>
<div class="flow-scroll" aria-label={uiText("Графическое представление сценария")}>
  <div class="flow-start"><CirclePlay size={16} />{uiText(" Запуск")}</div>
  {#snippet branch(items: Step[], prefix: string)}
    <div class="flow-branch">
      {#each items as step, i}
        {@const path = prefix + i}
        <div class="flow-connector" aria-hidden="true">↓</div>
        <button type="button" class="flow-node" class:selected={selected === path} class:disabled-step={step.enabled === false}
          aria-pressed={selected === path} onclick={() => selected = path}>
          <span class="node-icon">{#if step.type === "if"}<GitBranch size={17} />{:else if step.type === "repeat"}<Repeat2 size={17} />{:else}<span class="step-number">{uiText(i + 1)}</span>{/if}</span>
          <span class="node-name"><b>{uiText(label(step))}</b>{#if description(step)}<small>{uiText(description(step))}</small>{/if}</span><Pencil size={12} />
        </button>
        {#if step.type === "if"}
          <div class="branches">
            <div><span class="branch-label yes">{uiText("Условие выполнено")}</span>{@render branch(step.then || [], path + ".then.")}{#if !step.then?.length}<span class="pass">{uiText("Продолжить")}</span>{/if}</div>
            <div><span class="branch-label">{uiText("Иначе")}</span>{@render branch(step.else || [], path + ".else.")}{#if !step.else?.length}<span class="pass">{uiText("Продолжить")}</span>{/if}</div>
          </div>
        {:else if step.type === "repeat"}
          <div class="repeat"><span class="branch-label">{uiText("Повторить ")}{uiText(step.times || 1)}{uiText(" раз")}</span>{@render branch(step.steps || [], path + ".steps.")}</div>
        {/if}
      {/each}
    </div>
  {/snippet}
  {@render branch(steps, "")}
  <div class="flow-connector" aria-hidden="true">↓</div>
  <div class="flow-end"><CircleCheck size={15} />{uiText(" Завершение")}</div>
</div>
{#if current}
  <div class="node-editor">
    <div class="card-head"><b>{uiText("Редактирование блока")}</b><button class="btn ghost icon sm" aria-label={uiText("Закрыть блок")} onclick={() => selected = ""}><X size={14} /></button></div>
    <StepList steps={[current]} {advanced} onchange={edit} />
  </div>
{/if}
{#if !steps.length}<StepList {steps} {advanced} {onchange} />{/if}

<style>
  .explanation { color: var(--text-2); font-size: 12px; margin: 12px 0; }
  .flow-scroll { padding: 22px 12px; border: 1px solid var(--line); border-radius: 16px; background: radial-gradient(var(--line) .7px, transparent .7px) 0 0 / 16px 16px; overflow: auto; text-align: center; max-height: 620px; }
  .flow-branch { display: flex; align-items: center; flex-direction: column; min-width: 0; }
  .flow-node { display: flex; align-items: center; gap: 10px; width: 240px; max-width: 100%; padding: 11px 13px; background: var(--surface-solid); color: var(--text); border: 1px solid var(--line-2); border-radius: 13px; box-shadow: var(--shadow-sm); text-align: left; font: inherit; cursor: pointer; }
  .flow-node:hover, .flow-node.selected { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-soft); }
  .node-icon { display: grid; place-items: center; width: 27px; height: 27px; color: var(--accent-2); border-radius: 8px; background: var(--accent-soft); flex: none; }
  .step-number { font-size: 12px; } .node-name { min-width: 0; flex: 1; } b { font-size: 12px; } small { display: block; color: var(--text-2); font-size: 11px; overflow-wrap: anywhere; margin-top: 3px; }
  .flow-connector { color: var(--text-3); height: 25px; line-height: 25px; }
  .flow-start, .flow-end { display: inline-flex; gap: 7px; align-items: center; border-radius: 22px; padding: 7px 15px; background: var(--accent-soft); color: var(--accent-2); font-size: 12px; }
  .branches { display: grid; grid-template-columns: repeat(2, minmax(250px, 1fr)); gap: 24px; border: 1px dashed var(--line-2); border-radius: 16px; padding: 12px; margin: 10px 0 0; }
  .branch-label { display: block; font-size: 11px; color: var(--text-2); padding: 3px; } .yes { color: var(--ok); } .pass { display: block; font-size: 11px; color: var(--text-3); padding: 16px; }
  .repeat { border: 1px dashed var(--line-2); border-radius: 15px; padding: 10px 14px 14px; margin-top: 10px; }
  .node-editor { padding: 14px; border: 1px solid var(--accent); border-radius: 15px; margin-top: 14px; background: var(--accent-soft); }
  .disabled-step { opacity: .45; }
</style>
