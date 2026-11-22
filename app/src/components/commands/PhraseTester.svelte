<script lang="ts">
  import { t as uiText } from "../../lib/i18n.svelte";

  // «Что произойдёт, если сказать…» — настоящий маршрутизатор ядра, без выполнения.
  import { MessageSquareText, CircleAlert, Play, Workflow, Bot, Square, UserRound, Ear } from "@lucide/svelte";
  import { app, navigate } from "../../lib/store.svelte";
  import { api, type Explain, type Scenario } from "../../lib/api";

  let { draft = null, compact = false }: { draft?: Scenario | null; compact?: boolean } = $props();
  let phrase = $state("");
  let result = $state<Explain | null>(null);
  let busy = $state(false);
  let semantic = $state(false);
  let error = $state("");

  async function check() {
    if (!phrase.trim()) return;
    busy = true;
    error = "";
    try { result = await api.scenarioOp<Explain>({ op: "test", phrase, semantic, draft: draft ? $state.snapshot(draft) : null }); }
    catch (e) { error = String(e); result = null; }
    finally { busy = false; }
  }
  const icons: Record<string, any> = { scenario: Workflow, builtin: Play, llm: Bot, semantic: Bot, stop: Square, persona: UserRound, wake: Ear };
  const tone: Record<string, string> = { scenario: "ok", builtin: "ok", llm: "", stop: "warn", persona: "", wake: "", none: "bad", empty: "" };
</script>

<div class="tester" class:compact>
  <form onsubmit={(e) => { e.preventDefault(); check(); }}>
    <label class="input">
      <MessageSquareText size={16} />
      <input bind:value={phrase} placeholder={uiText(draft ? "Проверьте фразу на этом черновике" : "Что произойдёт, если сказать… например «закрой телеграм»")} aria-label={uiText("Фраза для проверки")} />
    </label>
    <button class="btn" disabled={busy || !phrase.trim() || !app.status} title={uiText(app.status ? "Ничего не выполняется — только проверка" : "Включите Джарвиса")}>{uiText("Проверить")}</button>
  </form>
  <label class="semantic small"><input type="checkbox" bind:checked={semantic} disabled={busy} />{uiText(" Проверить смысл нейросетью: мышь, клавиши, диктовка")}</label>
  {#if semantic}<p class="dim small">{uiText("Запрос к выбранной модели выполняется только кнопкой «Проверить». Если подключено облако, фраза будет передана ему.")}</p>{/if}
  {#if error}<div class="notice bad"><CircleAlert size={15} /> {uiText(error)}</div>{/if}
  {#if result}
    {@const Icon = icons[result.route] ?? Bot}
    <div class="result notice {tone[result.route] ?? ''} fade-in" role="status">
      <Icon size={17} />
      <div class="text">
        <b>{uiText(result.title)}</b>
        {#if result.match}<span class="badge plain">{uiText(result.match)}</span>{/if}
        {#if result.detail}<p>{uiText(result.detail)}</p>{/if}
        {#if result.calls.length}<p class="mono small">{uiText(result.calls.map((c) => `${c.text}: ${c.arg}`).join(" · "))}</p>{/if}
        {#if result.plan?.length}
          <ol class="plan">{#each result.plan.filter((l) => !l.group) as line}<li style="margin-left:{line.depth * 14}px" class:off={line.off}>{uiText(line.text)}{#if line.note} <span class="badge warn">{uiText(line.note)}</span>{/if}</li>{/each}</ol>
        {/if}
        {#each result.warnings as w}<p class="warn-text"><CircleAlert size={13} /> {uiText(w)}</p>{/each}
        {#if result.alternatives.length}
          <p class="small">{uiText("Похожие: ")}{#each result.alternatives as a, i}{uiText(i ? ", " : "")}<button class="link" onclick={() => navigate("commands", "edit:" + a.scenario)}>{a.name}</button> («{uiText(a.phrase)}»){/each}</p>
        {/if}
      </div>
    </div>
    <p class="dim small">{uiText("Проверка ничего не выполняет.")}{uiText(draft ? " Используется этот черновик, сохранённые сценарии не меняются." : "")}</p>
  {/if}
</div>

<style>
  form {
    display: flex;
    gap: 8px;
  }
  .semantic { display: flex; align-items: center; gap: 8px; margin-top: 8px; color: var(--text-2); }
  .input {
    flex: 1;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 12px;
    border-radius: 10px;
    border: 1px solid var(--line-2);
    background: var(--field);
    color: var(--text-3);
  }
  .input:focus-within {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--focus);
  }
  .input input {
    flex: 1;
    border: none;
    background: transparent;
    box-shadow: none !important;
    padding: 0;
  }
  .result {
    margin-top: 10px;
  }
  .text {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .text b {
    font-size: 14px;
  }
  .text p {
    color: var(--text-2);
  }
  .small {
    font-size: 12.5px;
  }
  .plan {
    margin: 4px 0;
    padding-left: 18px;
    font-size: 12.5px;
    color: var(--text-2);
  }
  .plan .off {
    text-decoration: line-through;
    opacity: 0.6;
  }
  .warn-text {
    color: var(--warn) !important;
    display: flex;
    gap: 6px;
    align-items: center;
  }
  .tester > .dim {
    margin-top: 6px;
  }
</style>
