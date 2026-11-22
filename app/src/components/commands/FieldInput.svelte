<script lang="ts">
  import { t as uiText } from "../../lib/i18n.svelte";

  // Одно поле шага по описанию из реестра ядра: подпись, элемент, пояснение, ошибка.
  import { open } from "../../lib/fileDialogs";
  import { FolderOpen, Keyboard } from "@lucide/svelte";
  import type { Field } from "../../lib/api";
  import { app } from "../../lib/store.svelte";
  import ConditionInput from "./ConditionInput.svelte";
  import FieldInput from "./FieldInput.svelte";

  let { field, value, onchange, id, step = {} }: { field: Field; value: any; onchange: (v: any) => void; id: string; step?: Record<string, any> } = $props();
  const choices = $derived(app.scenarios?.choices ?? { apps: [], monitors: 1, devices: [], animations: [], personas: [], plugins: [] });
  const plugin = $derived((choices.plugins ?? []).find((p: any) => p.id === step.name));
  const pluginAction = $derived(plugin?.actions?.find((a: any) => a.id === (step.action || plugin?.actions?.[0]?.id)));
  const shown = $derived(value ?? field.default ?? (field.kind === "days" ? [] : ""));
  const empty = $derived(value === undefined || value === null || value === "" || (Array.isArray(value) && !value.length));
  const error = $derived.by(() => {
    if (field.required && empty) return "Заполните это поле";
    if (["number", "range"].includes(field.kind) && !empty) {
      const n = Number(value);
      if (!Number.isFinite(n)) return "Нужно число";
      if ((field.min !== undefined && n < field.min) || (field.max !== undefined && n > field.max)) return `От ${field.min} до ${field.max}`;
    }
    if (field.kind === "json" && typeof value === "string" && value.trim()) {
      try { JSON.parse(value); } catch { return "Неверный JSON"; }
    }
    return "";
  });
  const days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
  let recording = $state(false);

  async function pick() {
    const path = await open({ multiple: false, directory: false });
    if (typeof path === "string") onchange(path);
  }
  function record(e: KeyboardEvent) {
    if (!recording) return;
    e.preventDefault();
    if (["Control", "Shift", "Alt", "Meta"].includes(e.key)) return;
    const parts = [e.ctrlKey && "ctrl", e.shiftKey && "shift", e.altKey && "alt", e.metaKey && "win"].filter(Boolean) as string[];
    const key = e.key.length === 1 ? e.key.toLowerCase() : e.key.toLowerCase().replace("arrow", "").replace("escape", "esc").replace(" ", "space");
    onchange([...parts, key].join("+"));
    recording = false;
  }
  function number(raw: string) {
    if (raw === "") return onchange(undefined);
    const n = Number(raw);
    onchange(Number.isFinite(n) ? n : raw);
  }
</script>

<label class="field" class:wide={["textarea", "condition", "json", "list", "plugin_params"].includes(field.kind)} for={id}>
  <span>{uiText(field.label)}{uiText(field.required ? "" : " (необязательно)")}</span>
  {#if field.kind === "textarea"}
    <textarea {id} rows="2" value={shown} aria-invalid={!!error} maxlength={field.max} oninput={(e) => onchange(e.currentTarget.value)}></textarea>
  {:else if field.kind === "number"}
    <input {id} type="number" value={shown} min={field.min} max={field.max} step="any" aria-invalid={!!error} oninput={(e) => number(e.currentTarget.value)} />
  {:else if field.kind === "range"}
    <span class="range"><input {id} type="range" min={field.min} max={field.max} value={shown} oninput={(e) => onchange(Number(e.currentTarget.value))} /><b class="mono">{uiText(shown)}</b></span>
  {:else if field.kind === "select"}
    <select {id} value={shown} onchange={(e) => onchange(e.currentTarget.value)}>
      {#each field.options ?? [] as [v, label]}<option value={v}>{uiText(label)}</option>{/each}
    </select>
  {:else if field.kind === "app"}
    <input {id} type="text" list="apps-list" value={shown} placeholder={uiText("Начните вводить название")} aria-invalid={!!error} oninput={(e) => onchange(e.currentTarget.value)} />
  {:else if field.kind === "file"}
    <span class="row-input"><input {id} type="text" value={shown} aria-invalid={!!error} oninput={(e) => onchange(e.currentTarget.value)} />
      <button class="btn sm" type="button" onclick={pick}><FolderOpen size={14} />{uiText(" Выбрать")}</button></span>
  {:else if field.kind === "combo"}
    <span class="row-input"><input {id} type="text" value={recording ? "Нажмите сочетание…" : shown} readonly={recording} aria-invalid={!!error}
             onkeydown={record} oninput={(e) => onchange(e.currentTarget.value.toLowerCase())} />
      <button class="btn sm" type="button" aria-pressed={recording} onclick={() => { recording = !recording; document.getElementById(id)?.focus(); }}><Keyboard size={14} /> {uiText(recording ? "Отмена" : "Записать")}</button></span>
  {:else if field.kind === "monitor"}
    <select {id} value={String(shown || 1)} onchange={(e) => onchange(Number(e.currentTarget.value))}>
      {#each Array.from({ length: Math.max(3, choices.monitors) }, (_, i) => i + 1) as n}
        <option value={String(n)}>{uiText(n === 1 ? "Основной" : `Монитор ${n}`)}{uiText(n > choices.monitors ? " (сейчас не подключён)" : "")}</option>
      {/each}
    </select>
  {:else if field.kind === "time"}
    <input {id} type="time" value={shown} aria-invalid={!!error} oninput={(e) => onchange(e.currentTarget.value)} />
  {:else if field.kind === "days"}
    <span class="days" role="group" aria-label={uiText(field.label)}>
      {#each days as d, i}
        <button type="button" class:on={(shown ?? []).includes(i)} aria-pressed={(shown ?? []).includes(i)}
                onclick={() => onchange((shown ?? []).includes(i) ? shown.filter((x: number) => x !== i) : [...(shown ?? []), i].sort())}>{uiText(d)}</button>
      {/each}
    </span>
  {:else if field.kind === "device"}
    <input {id} type="text" list="devices-list" value={shown} aria-invalid={!!error} oninput={(e) => onchange(e.currentTarget.value)} />
  {:else if field.kind === "animation"}
    <select {id} value={shown} onchange={(e) => onchange(e.currentTarget.value)}>
      {#each choices.animations.length ? choices.animations : ["wave", "nod", "bow", "dance"] as a}<option value={a}>{uiText(({ wave: "Помахать", nod: "Кивнуть", bow: "Поклон", dance: "Танец", stand: "Встать", "sit-window": "Сесть на окно", "sit-taskbar": "Сесть у панели задач" } as Record<string, string>)[a] ?? a)}</option>{/each}
    </select>
  {:else if field.kind === "persona"}
    <select {id} value={shown} onchange={(e) => onchange(e.currentTarget.value)}>
      <option value="">{uiText("— выберите —")}</option>
      {#each choices.personas as p}<option value={p.id}>{p.name}</option>{/each}
    </select>
  {:else if field.kind === "scenario"}
    <select {id} value={shown} onchange={(e) => onchange(e.currentTarget.value)}>
      <option value="">{uiText("— выберите —")}</option>
      {#each app.scenarios?.items ?? [] as s}<option value={s.id}>{s.name}</option>{/each}
    </select>
  {:else if field.kind === "plugin"}
    <select {id} value={shown} onchange={(e) => onchange(e.currentTarget.value)}>
      <option value="">{uiText("— выберите дополнение —")}</option>
      {#each choices.plugins ?? [] as p}<option value={p.id} disabled={!p.enabled}>{p.name}{uiText(p.enabled ? "" : " (выключено)")}</option>{/each}
    </select>
  {:else if field.kind === "plugin_action"}
    <select {id} value={shown || plugin?.actions?.[0]?.id || ""} disabled={!plugin?.actions?.length} onchange={(e) => onchange(e.currentTarget.value)}>
      {#each plugin?.actions ?? [] as a}<option value={a.id}>{uiText(a.label ?? a.id)}</option>{:else}<option value="">{uiText("основное")}</option>{/each}
    </select>
  {:else if field.kind === "plugin_params"}
    {#if pluginAction?.fields?.length}
      <span class="sub-fields">
        {#each pluginAction.fields as f}
          <FieldInput field={f} value={(value ?? {})[f.key]} id={`${id}-${f.key}`} onchange={(v) => onchange({ ...(value ?? {}), [f.key]: v })} />
        {/each}
      </span>
    {:else}
      <textarea {id} rows="2" class="mono" value={JSON.stringify(value ?? {})} oninput={(e) => { try { onchange(JSON.parse(e.currentTarget.value)); } catch { /* ждём корректный JSON */ } }}></textarea>
    {/if}
  {:else if field.kind === "condition"}
    <ConditionInput value={value ?? { type: "time_between", from: "08:00", to: "23:00" }} {onchange} />
  {:else if field.kind === "json"}
    <textarea {id} rows="3" class="mono" value={typeof value === "string" ? value : JSON.stringify(value ?? {}, null, 1)} aria-invalid={!!error}
              oninput={(e) => { try { onchange(JSON.parse(e.currentTarget.value)); } catch { onchange(e.currentTarget.value); } }}></textarea>
  {:else if field.kind === "list"}
    <textarea {id} rows="2" value={(value ?? []).join("\n")} oninput={(e) => onchange(e.currentTarget.value.split("\n").map((l) => l.trim()).filter(Boolean))}></textarea>
  {:else}
    <input {id} type="text" value={shown} maxlength={field.max} aria-invalid={!!error} oninput={(e) => onchange(e.currentTarget.value)} />
  {/if}
  {#if error}<span class="error" role="alert">{uiText(error)}</span>{:else if field.hint}<span class="help">{uiText(field.hint)}</span>{/if}
</label>

<style>
  .sub-fields {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 10px;
  }
  .field.wide {
    grid-column: 1 / -1;
  }
  .field textarea,
  .field input[type="text"],
  .field select {
    width: 100%;
  }
  .range {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .range input {
    flex: 1;
  }
  .range b {
    min-width: 38px;
    color: var(--accent-2);
    font-size: 12.5px;
  }
  .row-input {
    display: flex;
    gap: 6px;
  }
  .row-input input {
    flex: 1;
  }
  .days {
    display: flex;
    gap: 4px;
    flex-wrap: wrap;
  }
  .days button {
    width: 38px;
    height: 32px;
    border-radius: 8px;
    border: 1px solid var(--line-2);
    background: var(--field);
    color: var(--text-2);
    font: inherit;
    font-size: 12.5px;
    cursor: pointer;
  }
  .days button.on {
    background: var(--accent);
    border-color: transparent;
    color: var(--accent-ink);
    font-weight: 650;
  }
</style>
