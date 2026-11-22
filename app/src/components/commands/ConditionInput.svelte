<script lang="ts">
  import { t as uiText } from "../../lib/i18n.svelte";

  // Условие: тип и его поля (время, дни, программа, батарея, интернет…).
  import { app } from "../../lib/store.svelte";
  import type { Condition } from "../../lib/api";
  import FieldInput from "./FieldInput.svelte";

  let { value, onchange }: { value: Condition; onchange: (v: Condition) => void } = $props();
  const specs = $derived(app.scenarios?.conditions ?? {});
  const spec = $derived(specs[value?.type] ?? { label: "", fields: [] });
  const uid = Math.random().toString(36).slice(2, 8);

  function retype(type: string) {
    const next: Condition = { type };
    for (const f of specs[type]?.fields ?? []) if (f.default !== undefined) next[f.key] = f.default;
    onchange(next);
  }
</script>

<div class="condition">
  <select aria-label={uiText("Тип условия")} value={value?.type} onchange={(e) => retype(e.currentTarget.value)}>
    {#each Object.entries(specs) as [id, c]}
      <option value={id} disabled={!!c.platforms && !c.platforms.includes(app.scenarios?.platform ?? "windows")}>{uiText(c.label)}</option>
    {/each}
  </select>
  {#each spec.fields as f}
    <FieldInput field={f} value={value?.[f.key]} id={`cond-${uid}-${f.key}`} onchange={(v) => onchange({ ...value, [f.key]: v })} />
  {/each}
</div>

<style>
  .condition {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 10px;
    align-items: end;
    padding: 10px;
    border-radius: 10px;
    border: 1px dashed var(--line-2);
  }
</style>
