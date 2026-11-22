<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  // Дополнения: проверенный каталог, установка из файла с предпросмотром прав, включение, откат, удаление.
  import { onMount } from "svelte";
  import { open as openFile } from "../lib/fileDialogs";
  import { invoke } from "@tauri-apps/api/core";
  import { Puzzle, Download, Upload, Undo2, Trash2, ShieldAlert, CircleAlert, LoaderCircle } from "@lucide/svelte";
  import Toggle from "./Toggle.svelte";
  import CatalogSource from "./CatalogSource.svelte";
  import PluginSettings from "./PluginSettings.svelte";
  import { app, toast, toastError } from "../lib/store.svelte";
  import { ask } from "../lib/dialog.svelte";

  type Installed = { id: string; name: string; version: string; author: string; description?: string; license?: string; source?: string;
    permissions: string[]; enabled: boolean; previous?: string[]; problems: string[]; legacy?: boolean; broken?: boolean; settings_schema?: any };
  type CatalogItem = { file: string; id: string; name: string; version: string; author: string; description: string; license: string;
    source: string; permissions: string[]; size: number; changes: string; problems: string[]; installed: string };
  let items = $state<Installed[]>([]);
  let catalog = $state<CatalogItem[]>([]);
  let allowed = $state(true);
  let busy = $state("");

  const post = <T,>(body: Record<string, unknown>) => invoke<T>("core_post", { path: "/api/plugins", body });
  async function load() {
    if (!app.status) return;
    try {
      const r = await post<{ items: Installed[]; allowed: boolean }>({ op: "list" });
      items = r.items;
      allowed = r.allowed;
      catalog = (await post<{ items: CatalogItem[] }>({ op: "catalog" })).items;
    } catch (e) { toastError(e); }
  }
  onMount(load);

  const consent = (name: string, author: string, source: string, permissions: string[], license: string) =>
    ask({ title: `Установить «${name}»?`, ok: "Установить",
      text: `Автор: ${author}\nИсточник: ${source}\nЛицензия: ${license || "не указана"}\nПрава: ${permissions.length ? permissions.join(", ") : "без особых прав"}\n\nДополнение — это программа с вашими правами в Windows. Ставьте только то, чему доверяете.` });

  async function installCatalog(c: CatalogItem) {
    if ((await consent(c.name, c.author, c.source, c.permissions, c.license)) !== "ok") return;
    busy = c.file;
    try { await post({ op: "install_catalog", file: c.file }); toast(`«${c.name}» установлено`, "success"); await load(); app.scenarios = null; }
    catch (e) { toastError(e); } finally { busy = ""; }
  }
  async function installFile() {
    const path = await openFile({ multiple: false, filters: [{ name: "Дополнение Джарвиса", extensions: ["zip"] }] });
    if (typeof path !== "string") return;
    busy = "file";
    try {
      const info = await post<{ manifest: any; problems: string[]; permissions: string[]; update_from: string }>({ op: "inspect", path });
      if (info.problems.length) { toastError("Нельзя установить: " + info.problems.join("; ")); return; }
      const m = info.manifest;
      if ((await consent(m.name, m.author, "файл с этого компьютера (не проверен)", info.permissions, m.license)) !== "ok") return;
      const r = await post<{ version: string; updated_from: string }>({ op: "install", path });
      toast(r.updated_from ? `Обновлено ${r.updated_from} → ${r.version}. Прежнюю версию можно вернуть` : `«${m.name}» установлено`, "success");
      await load();
    } catch (e) { toastError(e); } finally { busy = ""; }
  }
  async function op(name: string, id: string, label: string) {
    if (name === "remove" && (await ask({ title: "Удалить дополнение?", text: "Сценарии, где оно используется, перестанут выполнять этот шаг и сообщат об ошибке.", ok: "Удалить", danger: true })) !== "ok") return;
    try { await post({ op: name, id }); toast(label); await load(); }
    catch (e) { toastError(e); }
  }
</script>

<div class="card">
  <div class="card-head"><h3><Puzzle size={18} />{uiText(" Дополнения")}</h3>
    <button class="btn sm" disabled={!!busy || !app.status} onclick={installFile}>{#if busy === "file"}<LoaderCircle size={13} class="spin" />{:else}<Upload size={13} />{/if}{uiText(" Установить из файла")}</button></div>
  <p class="about">{uiText("Дополнения добавляют новые шаги для сценариев. Каждое работает в отдельном процессе с ограничением времени и памяти: зависшее дополнение не останавливает Джарвиса.\n    ")}<b>{uiText("Это не защищённая песочница")}</b>{uiText(" — у дополнения права вашей учётной записи.")}</p>
  {#if !allowed}<div class="notice warn"><ShieldAlert size={15} />{uiText(" Дополнения выключены в безопасности (security.allow_plugins). Установить можно, но выполняться они не будут.")}</div>{/if}

  {#if !app.status}
    <p class="dim">{uiText("Включите Джарвиса.")}</p>
  {:else}
    <span class="caps">{uiText("Установлены")}</span>
    {#each items as p (p.id)}
      <div class="row">
        <div class="label">
          <b>{p.name} <span class="dim mono small">{uiText(p.version)}</span></b>
          <span>{uiText(p.description || "")}{uiText(p.author ? ` · ${p.author}` : "")}{uiText(p.permissions?.length ? ` · права: ${p.permissions.join(", ")}` : "")}</span>
          {#each p.problems ?? [] as pr}<span class="bad-text"><CircleAlert size={12} /> {uiText(pr)}</span>{/each}
        </div>
        <div class="ctl">
          {#if !p.legacy}
            {#if p.previous?.length}<button class="btn ghost sm" title={uiText("Вернуть версию " + String(p.previous[0]))} onclick={() => op("rollback", p.id, "Прежняя версия возвращена")}><Undo2 size={13} /> {uiText(p.previous[0])}</button>{/if}
            <button class="btn ghost icon sm danger" aria-label={uiText("Удалить " + String(p.name))} onclick={() => op("remove", p.id, "Удалено")}><Trash2 size={13} /></button>
            <Toggle label={uiText(p.enabled ? `Выключить ${p.name}` : `Включить ${p.name}`)} checked={p.enabled} onchange={(v) => op(v ? "enable" : "disable", p.id, v ? "Включено" : "Выключено")} />
          {:else}<span class="badge plain">{uiText("старый формат")}</span>{/if}
        </div>
      </div>
      {#if p.settings_schema}<PluginSettings id={p.id} schema={p.settings_schema} />{/if}
    {:else}<p class="dim small">{uiText("Пока ничего не установлено.")}</p>{/each}

    <span class="caps cat">{uiText("Проверенный каталог")}</span>
    <div class="catalog">
      {#each catalog as c (c.file)}
        <div class="item">
          <b>{c.name}</b> <span class="dim small">{uiText(c.version)} · {uiText(c.author)} · {uiText(c.license)} · {uiText(Math.max(1, Math.round(c.size / 1024)))}{uiText(" КБ")}</span>
          <p class="small">{uiText(c.description)}</p>
          <p class="small dim">{uiText("Права: ")}{uiText(c.permissions.join(", ") || "нет")}{uiText(c.changes ? ` · Изменения: ${c.changes}` : "")}</p>
          <button class="btn sm" disabled={!!busy || c.installed === c.version || !!c.problems.length} onclick={() => installCatalog(c)}>
            {#if busy === c.file}<LoaderCircle size={13} class="spin" />{:else}<Download size={13} />{/if}
            {uiText(c.installed === c.version ? "Установлено" : c.installed ? `Обновить с ${c.installed}` : "Установить")}</button>
        </div>
      {/each}
    </div>
    <CatalogSource onchange={load} />
  {/if}
</div>

<style>
  .about { color: var(--text-2); font-size: 13px; margin: 6px 0 12px; }
  .ctl { display: flex; align-items: center; gap: 6px; flex: none; }
  .small { font-size: 12.5px; }
  .bad-text { color: var(--bad) !important; display: flex; gap: 4px; align-items: center; }
  .cat { display: block; margin-top: 16px; }
  .catalog { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 10px; margin-top: 8px; }
  .item { padding: 12px; border-radius: 10px; border: 1px solid var(--line-2); background: var(--surface-2); display: flex; flex-direction: column; gap: 4px; align-items: flex-start; }
  .item p { margin: 0; }
</style>
