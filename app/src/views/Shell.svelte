<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  import { onMount } from "svelte";
  import { openUrl } from "@tauri-apps/plugin-opener";
  import { House, Workflow, Plug, Database, UserRound, Settings2, Power, RotateCw, ArrowLeft, Search, PanelLeftClose, PanelLeftOpen, Gamepad2, Send, Heart } from "@lucide/svelte";
  import TitleBar from "../components/TitleBar.svelte";
  import Palette from "../components/Palette.svelte";
  import DemoBanner from "../components/DemoBanner.svelte";
  import { APP_VERSION } from "../lib/version";
  import { app, nav, navigate, back, applySettings, get, set, toastError } from "../lib/store.svelte";
  import { api, on } from "../lib/api";
  import Home from "./Home.svelte";
  // Остальные страницы грузятся при первом открытии: быстрее старт на слабом компьютере.
  const lazy = {
    commands: () => import("./Commands.svelte"),
    connections: () => import("./Connections.svelte"),
    memory: () => import("./Memory.svelte"),
    persona: () => import("./Persona.svelte"),
    settings: () => import("./Settings.svelte"),
    games: () => import("./Games.svelte"),
  } as const;
  const loaded = new Map<string, Promise<any>>();
  const load = (id: string) => {
    if (!loaded.has(id)) loaded.set(id, (lazy as any)[id]().then((m: any) => m.default));
    return loaded.get(id)!;
  };

  const pages = [
    { id: "home", title: "Главная", icon: House, hint: "Состояние, история и быстрые действия" },
    { id: "commands", title: "Команды", icon: Workflow, hint: "Сценарии, фразы и наборы" },
    { id: "connections", title: "Подключения", icon: Plug, hint: "Умный дом, OBS, Telegram, телефон, дополнения" },
    { id: "games", title: "Игры", icon: Gamepad2, hint: "Minecraft, Factorio и Hearts of Iron IV" },
    { id: "memory", title: "Память и проекты", icon: Database, hint: "Факты, проекты и материалы" },
    { id: "persona", title: "Персонаж", icon: UserRound, hint: "Характер, голос и внешность" },
    { id: "settings", title: "Настройки", icon: Settings2, hint: "Голос, модели, оформление, система" },
  ] as const;
  const projectLinks = [
    { title: "Telegram", icon: Send, url: "https://t.me/+tqB8b6h4JbYwZWVi" },
    { title: "Поддержать проект", icon: Heart, url: "https://t.me/itshelter_bot?start=donate" },
  ];

  const current = $derived(pages.find((p) => p.id === nav.page) ?? pages[0]);
  const collapsed = $derived(get<boolean>("ui.nav_collapsed", false));
  const failed = $derived(Object.entries(app.status?.workers ?? {}).filter(([, w]) => w.state === "failed" || w.state === "error"));
  const coreLabel = $derived(app.core?.running ? (failed.length ? "ошибка модуля" : app.status ? "в сети" : "запускается") : app.core?.paused ? "пауза" : "выключен");
  const coreTone = $derived(app.core?.running ? (failed.length || !app.status ? "warn" : "ok") : "bad");

  onMount(() => {
    if (app.info?.contextRequested) app.contextOpen = true;
    let closed = false;
    const disposers: (() => void)[] = [];
    const keep = (p: Promise<() => void>) => p.then((f) => (closed ? f() : disposers.push(f))).catch(toastError);
    keep(on("avatar:settings", () => navigate("persona")));
    keep(on<boolean>("assistant:context", () => { navigate("home"); app.contextOpen = true; }));
    // Горячая клавиша Ctrl+Alt+T или «исправь выделенное» — показать панель текста на главной.
    keep(on<boolean>("textops:open", () => { navigate("home"); setTimeout(() => document.querySelector('[data-home-card="text"]')?.scrollIntoView({ block: "center" }), 150); }));
    const keys = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); nav.palette = true; }
      else if (e.altKey && e.key === "ArrowLeft") { e.preventDefault(); back(); }
      else if (e.altKey && /^[1-7]$/.test(e.key)) { e.preventDefault(); navigate(pages[Number(e.key) - 1].id); }
    };
    window.addEventListener("keydown", keys);
    return () => { closed = true; disposers.forEach((f) => f()); window.removeEventListener("keydown", keys); };
  });

  async function togglePower() {
    try {
      if (app.core?.running) await api.coreStop();
      else await api.coreStart();
    } catch (e) {
      toastError(e);
    }
  }
</script>

<div class="shell">
  <TitleBar>
    <div class="brand">
      <span class="logo" aria-hidden="true"></span>
      <span class="title">Shelter</span>
    </div>
    <button class="search" onclick={() => (nav.palette = true)} title={uiText("Поиск по настройкам и командам (Ctrl+K)")}>
      <Search size={14} /> <span>{uiText("Найти настройку или команду")}</span> <kbd>Ctrl K</kbd>
    </button>
    {#snippet right()}
      <span class="chip {coreTone}" title={uiText(failed.length ? failed.map(([n, w]) => `${n}: ${w.error}`).join("\n") : "")}>
        <span class="dot"></span>{uiText(coreLabel)}
      </span>
      <button class="btn ghost icon power" title={uiText(app.core?.running ? "Выключить ассистента" : "Включить ассистента")} aria-label={uiText(app.core?.running ? "Выключить ассистента" : "Включить ассистента")} onclick={togglePower}>
        <Power size={16} />
      </button>
    {/snippet}
  </TitleBar>

  <DemoBanner />
  <div class="body">
    <nav class:collapsed aria-label={uiText("Разделы")}>
      {#each pages as p, i}
        <button class:active={nav.page === p.id} aria-current={nav.page === p.id ? "page" : undefined}
                title={collapsed ? uiText(p.title) : `${uiText(p.hint)} (Alt+${i + 1})`} onclick={() => navigate(p.id)}>
          <p.icon size={18} />
          {#if !collapsed}<span>{uiText(p.title)}</span>{/if}
        </button>
      {/each}
      <div class="spacer"></div>
      {#each projectLinks as link}
        <button class="project-link" title={uiText(link.title)} aria-label={uiText(link.title)}
                onclick={() => openUrl(link.url).catch(toastError)}>
          <link.icon size={16} />
          {#if !collapsed}<span>{uiText(link.title)}</span>{/if}
        </button>
      {/each}
      <button class="collapse" title={uiText(collapsed ? "Развернуть меню" : "Свернуть меню")} aria-label={uiText(collapsed ? "Развернуть меню" : "Свернуть меню")}
              onclick={() => set("ui.nav_collapsed", !collapsed, false)}>
        {#if collapsed}<PanelLeftOpen size={16} />{:else}<PanelLeftClose size={16} />{/if}
      </button>
      {#if !collapsed}<div class="version dim mono">v{uiText(APP_VERSION)}</div>{/if}
    </nav>
    <main id="shell-content">
      {#if app.dirty}
        <div class="apply fade-in" role="status">
          <span><b>{uiText("Сохранено.")}</b>{uiText(" Чтобы применить ")}{uiText(app.dirtyReasons.join(", ") || "изменения")}{uiText(", перезапустите ассистента (около 10 секунд).")}</span>
          <button class="btn primary sm" onclick={() => applySettings().catch(toastError)}><RotateCw size={14} />{uiText(" Перезапустить")}</button>
        </div>
      {/if}
      {#if nav.history.length && nav.page !== "home"}
        <div class="page-nav"><button class="back btn ghost sm" onclick={back} title={uiText("Назад (Alt+←)")}><ArrowLeft size={16} />{uiText("Назад")}</button></div>
      {/if}
      {#key nav.page}
        <div class="page fade-in">
          {#if current.id === "home"}
            <Home />
          {:else}
            {#await load(current.id)}
              <div class="loading dim">{uiText("Открываю…")}</div>
            {:then View}
              <View />
            {:catch error}
              <div class="notice bad">{uiText("Страница не открылась: ")}{uiText(String(error))}</div>
            {/await}
          {/if}
        </div>
      {/key}
    </main>
  </div>
</div>

{#if nav.palette}<Palette onclose={() => (nav.palette = false)} />{/if}

<style>
  .shell {
    display: flex;
    flex-direction: column;
    height: 100%;
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 10px;
    flex: none;
  }
  .logo {
    width: 18px;
    height: 18px;
    border-radius: 50%;
    border: 2px solid var(--accent);
    box-shadow: 0 0 10px var(--glow), inset 0 0 6px var(--glow);
    background: radial-gradient(circle, #fff 0 18%, var(--accent-2) 30%, transparent 62%);
  }
  .title {
    font-family: var(--mono);
    font-size: 12px;
    font-weight: 600;
    color: var(--accent-2);
    letter-spacing: 0.08em;
  }
  nav button.project-link { color: var(--accent-2); gap: 9px; font-size: 13px; }
  .search {
    display: flex;
    align-items: center;
    gap: 8px;
    height: 30px;
    margin-left: 18px;
    padding: 0 10px;
    width: min(340px, 40vw);
    border-radius: 9px;
    border: 1px solid var(--line);
    background: var(--field);
    color: var(--text-3);
    font: inherit;
    font-size: 13px;
    cursor: pointer;
  }
  .search span {
    flex: 1;
    text-align: left;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .search:hover {
    border-color: var(--line-2);
    color: var(--text-2);
  }
  .body {
    flex: 1;
    display: flex;
    min-height: 0;
  }
  nav {
    width: 216px;
    flex: none;
    display: flex;
    flex-direction: column;
    gap: 3px;
    padding: 10px 12px 12px;
    border-right: 1px solid var(--line);
    background: linear-gradient(180deg, var(--bg-2), transparent);
    transition: width var(--mid) var(--ease);
  }
  nav.collapsed {
    width: 62px;
  }
  nav button {
    display: flex;
    align-items: center;
    gap: 12px;
    height: 40px;
    flex: 0 0 40px;
    padding: 0 12px;
    border: 1px solid transparent;
    border-radius: 10px;
    background: transparent;
    color: var(--text-2);
    font: inherit;
    font-weight: 560;
    cursor: pointer;
    text-align: left;
    white-space: nowrap;
    overflow: hidden;
    transition: background var(--fast), color var(--fast), border-color var(--fast);
  }
  nav button:hover {
    background: var(--hover);
    color: var(--text);
  }
  nav button.active {
    color: var(--accent-2);
    border-color: var(--line-2);
    background: var(--accent-soft);
    box-shadow: inset 2px 0 0 var(--accent-2);
  }
  nav .collapse {
    height: 32px;
    flex-basis: 32px;
    color: var(--text-3);
  }
  nav button :global(svg) { flex-shrink: 0; }
  nav button span { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  nav.collapsed button { justify-content: center; padding-inline: 0; }
  .spacer {
    flex: 1;
  }
  .version {
    font-size: 11px;
    padding-left: 12px;
  }
  main {
    flex: 1;
    min-width: 0;
    overflow-y: auto;
    padding: 18px var(--page-pad) 30px;
    overflow-anchor: none;
  }
  .page {
    max-width: 1060px;
    margin: 0 auto;
  }
  .loading {
    padding: 40px;
    text-align: center;
  }
  .page-nav {
    max-width: 1060px;
    margin: 0 auto 10px;
  }
  .back { gap: 6px; }
  .apply {
    max-width: 1060px;
    margin: 0 auto 14px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 10px 14px;
    border-radius: var(--r-md);
    border: 1px solid color-mix(in srgb, var(--warn) 40%, transparent);
    background: var(--warn-soft);
    font-size: 13px;
  }
  @media (max-width: 900px) {
    nav {
      width: 62px;
    }
    nav button span {
      display: none;
    }
    nav button { justify-content: center; padding-inline: 0; }
    .version {
      display: none;
    }
    .search span {
      display: none;
    }
    .search {
      width: auto;
    }
  }
</style>
