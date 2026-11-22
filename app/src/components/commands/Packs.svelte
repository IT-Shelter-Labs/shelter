<script lang="ts">
  import { t as uiText, count } from "../../lib/i18n.svelte";

  // Начальные наборы: предпросмотр, найденные/отсутствующие программы, параметры, установка.
  import { onMount } from "svelte";
  import { Briefcase, GraduationCap, Radio, Music, WandSparkles, CircleCheck, CircleAlert, Download, LoaderCircle } from "@lucide/svelte";
  import { app, toast, toastError } from "../../lib/store.svelte";
  import { api, type Pack } from "../../lib/api";

  let packs = $state<Pack[]>([]);
  let loading = $state(true);
  let params = $state<Record<string, Record<string, string>>>({});
  let installing = $state("");
  let result = $state<Record<string, { added: string[]; notes: string[] }>>({});
  const icons: Record<string, any> = { briefcase: Briefcase, "graduation-cap": GraduationCap, radio: Radio, music: Music, "wand-sparkles": WandSparkles };

  onMount(async () => {
    try {
      packs = (await api.scenarioOp<{ packs: Pack[] }>({ op: "packs" })).packs;
      for (const p of packs) params[p.id] = Object.fromEntries(p.params.map((x) => [x.key, x.default]));
    } catch (e) { toastError(e); }
    finally { loading = false; }
  });

  async function install(p: Pack) {
    installing = p.id;
    try {
      result[p.id] = await api.scenarioOp({ op: "install_pack", id: p.id, params: params[p.id] });
      app.scenarios = await api.scenarios();
      packs = (await api.scenarioOp<{ packs: Pack[] }>({ op: "packs" })).packs;
      toast(`Набор «${p.name}» установлен`, "success");
    } catch (e) { toastError(e); }
    finally { installing = ""; }
  }
</script>

<p class="lead">{uiText("Готовые сценарии под типичные дела. Перед установкой видно, какие программы найдены на этом компьютере. Если чего-то нет, этот шаг выключится, а остальной набор будет работать.")}</p>

{#if loading}
  <div class="empty"><LoaderCircle size={20} class="spin" />{uiText(" Ищу программы на компьютере…")}</div>
{:else if !app.status}
  <div class="empty"><b>{uiText("Джарвис выключен")}</b><span>{uiText("Включите его — проверка программ идёт через ядро.")}</span></div>
{/if}

<div class="packs">
  {#each packs as p (p.id)}
    {@const Icon = icons[p.icon] ?? WandSparkles}
    <article class="card pack">
      <header>
        <span class="icon"><Icon size={20} /></span>
        <div><h3>{uiText(p.name)}</h3>{#if p.installed}<span class="badge ok">{uiText("установлен")}</span>{/if}</div>
      </header>
      <p class="about">{uiText(p.about)}</p>
      {#if p.requires.length}
        <ul class="needs">
          {#each p.requires as r}
            <li>{#if r.found}<CircleCheck size={14} color="var(--ok)" />{:else}<CircleAlert size={14} color={r.optional ? "var(--warn)" : "var(--bad)"} />{/if}
              {uiText(r.label)} — {uiText(r.found ? "Доступно" : r.optional ? "Не установлено; шаг будет пропущен" : "Не установлено: установите приложение")}</li>
          {/each}
        </ul>
      {/if}
      <details>
        <summary>{uiText("Что внутри: ")}{uiText(p.items.length)} {uiText(count(p.items.length,{one:"сценарий",few:"сценария",many:"сценариев"}))}</summary>
        {#each p.items as item}
          <div class="item"><b>{uiText(item.name)}</b>{#if item.phrases.length}<span class="dim"> · «{item.phrases[0]}»</span>{/if}
            <ol>{#each item.steps as s}<li>{uiText(s)}</li>{/each}</ol></div>
        {/each}
      </details>
      {#each p.params as prm}
        <label class="field"><span>{uiText(prm.label)}</span><input type="text" bind:value={params[p.id][prm.key]} />{#if prm.hint}<span class="help">{uiText(prm.hint)}</span>{/if}</label>
      {/each}
      {#if result[p.id]}
        <div class="notice ok small">{uiText("Добавлено: ")}{uiText(result[p.id].added.join(", ") || "ничего")}</div>
        {#each result[p.id].notes as n}<div class="notice warn small">{uiText(n)}</div>{/each}
      {/if}
      <button class="btn install {p.installed ? '' : 'primary'}" disabled={!!installing || !app.status} onclick={() => install(p)}>
        {#if installing === p.id}<LoaderCircle size={14} class="spin" />{:else}<Download size={14} />{/if} {uiText(p.installed ? "Переустановить" : "Установить")}
      </button>
    </article>
  {/each}
</div>

<style>
  .packs {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
    gap: 12px;
  }
  .pack {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .pack + .pack {
    margin-top: 0;
  }
  header {
    display: flex;
    gap: 10px;
    align-items: center;
  }
  .icon {
    display: grid;
    place-items: center;
    width: 38px;
    height: 38px;
    border-radius: 10px;
    background: var(--accent-soft);
    color: var(--accent-2);
  }
  .about {
    color: var(--text-2);
    font-size: 13px;
  }
  .needs {
    list-style: none;
    padding: 0;
    margin: 0;
    font-size: 12.5px;
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .needs li {
    display: flex;
    gap: 6px;
    align-items: center;
  }
  .item {
    font-size: 13px;
    margin: 6px 0;
  }
  .item ol {
    margin: 4px 0 0;
    padding-left: 18px;
    color: var(--text-2);
  }
  .pack .btn {
    align-self: flex-start;
  }
  .pack .install { margin-top:auto; }
  .small {
    font-size: 12.5px;
  }
</style>
