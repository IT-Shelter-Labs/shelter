<script lang="ts">
  import { t as uiText } from "../../lib/i18n.svelte";

  // Быстрые сценарии: запуск кнопкой тем же исполнителем, что и голосом.
  import { Play, Plus } from "@lucide/svelte";
  import { onMount } from "svelte";
  import { app, navigate, toast, toastError } from "../../lib/store.svelte";
  import { api, type Scenario } from "../../lib/api";
  import { ask } from "../../lib/dialog.svelte";

  onMount(async () => {
    if (app.status && !app.scenarios) app.scenarios = await api.scenarios().catch(() => null);
  });
  const items = $derived<Scenario[]>(((app.scenarios?.items ?? []) as Scenario[])
    .filter((s) => s.enabled && s.triggers.some((t) => t.type === "button") && !s.steps.some((st) => st.type === "close"))
    .sort((a, b) => Number(!!b.pinned) - Number(!!a.pinned))
    .slice(0, 8));

  async function run(s: Scenario) {
    if (s.confirm && (await ask({ title: s.name, text: s.confirm, ok: "Выполнить" })) !== "ok") return;
    try {
      await api.scenarioOp({ op: "run", id: s.id, confirmed: !!s.confirm });
      toast(`Запускаю «${s.name}»`);
    } catch (e) {
      toastError(e);
    }
  }
</script>

{#if !app.status}
  <p class="line dim">{uiText("Включите Джарвиса, чтобы запускать сценарии.")}</p>
{:else if !items.length}
  <p class="line dim">{uiText("Сценариев пока нет. ")}<button class="link" onclick={() => navigate("commands", "new")}>{uiText("Создать первый")}</button>{uiText(" или поставить готовый набор.")}</p>
{:else}
  <div class="quick">
    {#each items as s (s.id)}
      <button class="btn sm" title={s.phrases.length ? uiText(`Голосом: «${s.phrases[0]}»`) : s.name} onclick={() => run(s)}><Play size={13} /> <span>{s.origin === "config" || s.origin?.startsWith("pack:") ? uiText(s.name) : s.name}</span></button>
    {/each}
    <button class="btn ghost sm" onclick={() => navigate("commands", "new")}><Plus size={13} />{uiText(" Новый")}</button>
  </div>
{/if}

<style>
  .quick { display: flex; flex-wrap: wrap; gap: 6px; }
  .quick .btn { max-width: 100%; }
  .quick .btn span { overflow: hidden; text-overflow: ellipsis; }
  .line { font-size: 13px; }
</style>
