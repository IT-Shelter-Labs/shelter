<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  import { get, set } from "../lib/store.svelte";
  import Setting from "./Setting.svelte";
  import Toggle from "./Toggle.svelte";
  let { id, schema }: {id: string; schema: any} = $props();
  const fields = $derived(Object.entries(schema?.properties || {}).slice(0, 30) as [string, any][]);
  function value(key: string, fallback: any) { return get<Record<string, any>>("plugins.settings", {})[id]?.[key] ?? fallback; }
  function change(key: string, v: any) {
    const settings = get<Record<string, any>>("plugins.settings", {});
    set("plugins.settings", {...settings, [id]: {...settings[id], [key]:v}});
  }
</script>
{#if fields.length}<details class="plugin-settings"><summary>{uiText("Настройки дополнения")}</summary>
  {#each fields as [key, field] (key)}
    <Setting title={uiText(String(field.title || key))} hint={uiText(String(field.description || "Параметр, объявленный автором дополнения"))}>
      {#if field.type === "boolean"}<Toggle label={uiText(String(field.title || key))} checked={!!value(key, field.default || false)} onchange={v => change(key, v)} />
      {:else if Array.isArray(field.enum)}<select aria-label={uiText(String(field.title || key))} value={value(key, field.default ?? field.enum[0])} onchange={e=>change(key, field.enum.find((v: any)=>String(v)===e.currentTarget.value))}>{#each field.enum.slice(0, 100) as v}<option value={String(v)}>{uiText(String(v))}</option>{/each}</select>
      {:else if field.type === "number" || field.type === "integer"}<input aria-label={uiText(String(field.title || key))} type="number" min={field.minimum} max={field.maximum} step={field.type === "integer" ? 1 : "any"} value={value(key, field.default ?? 0)} onchange={e=>{const n=Number(e.currentTarget.value); if(Number.isFinite(n))change(key, Math.max(field.minimum ?? -Infinity, Math.min(field.maximum ?? Infinity, field.type === "integer" ? Math.round(n) : n)));}} />
      {:else if field.type === "string" || !field.type}<input aria-label={uiText(String(field.title || key))} type={field.format === "password" || /key|token|password|secret/i.test(key) ? "password" : "text"} autocomplete="off" maxlength={Math.min(field.maxLength || 4000, 4000)} value={value(key, field.default || "")} onchange={e=>change(key, e.currentTarget.value)} />
      {:else}<span class="dim small">{uiText("Сложный параметр: настройте по инструкции автора.")}</span>{/if}
    </Setting>
  {/each}
</details>{/if}
<style>.plugin-settings {margin: 6px 0 15px;} summary {font-size:12px; cursor:pointer; color:var(--accent-2);}</style>
