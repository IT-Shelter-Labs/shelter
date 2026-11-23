<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  // Подключения: что поддерживается, что нужно, проверка отдельно от сохранения.
  import { Lightbulb, Clapperboard, Headphones, Gamepad2, Smartphone, Puzzle, Send, CircleCheck, CircleAlert, LoaderCircle, Eye, EyeOff } from "@lucide/svelte";
  import Integrations from "../components/Integrations.svelte";
  import PairedDevices from "../components/PairedDevices.svelte";
  import Plugins from "../components/Plugins.svelte";
  import Toggle from "../components/Toggle.svelte";
  import { app, get, set, toast, nav } from "../lib/store.svelte";
  import { invoke } from "@tauri-apps/api/core";

  let open = $state<string>("");
  $effect(() => { if (nav.sub === "plugins") open = "plugins"; });
  let testing = $state("");
  let results = $state<Record<string, { ok: boolean; text: string; items?: string[] }>>({});
  let show = $state<Record<string, boolean>>({});

  // Значения формы — отдельно от сохранённых: «Проверить» не сохраняет, «Сохранить» не проверяет.
  let ha = $state({ url: get("smarthome.homeassistant.url", ""), token: get("smarthome.homeassistant.token", "") });
  let yandex = $state({ token: get("smarthome.yandex.token", "") });
  let obs = $state({ url: get("obs.url", "ws://127.0.0.1:4455"), password: get("obs.password", ""), microphone: get("obs.microphone", "") });
  let telegram = $state({ token: get("telegram.token", "") });
  let discord = $state({
    mute: get("discord.mute", "ctrl+shift+f9"), deafen: get("discord.deafen", "ctrl+shift+f10"),
    bot_token: get("discord.bot_token", ""), guild_id: get("discord.guild_id", ""),
    user_id: get("discord.user_id", ""), channel_id: get("discord.channel_id", ""),
  });
  function saveDiscord() {
    for (const [key, value] of Object.entries(discord)) set("discord." + key, value.trim());
    toast("Сохранено", "success");
  }

  const cards = $derived([
    { id: "home", icon: Lightbulb, title: "Умный дом", about: "Управляйте светом, розетками и другой техникой голосом или в сценариях. Подключите Home Assistant или Умный дом Яндекса.",
      state: get("smarthome.enabled", false) ? (ha.url || yandex.token ? "on" : "need") : "off", where: "Ваша локальная сеть или облако Яндекса" },
    { id: "obs", icon: Clapperboard, title: "OBS Studio", about: "Запись, повторы, сцены, источники и микрофон через WebSocket OBS.",
      state: obs.url ? "on" : "off", where: "На этом компьютере, WebSocket" },
    { id: "discord", icon: Headphones, title: "Discord", about: "Горячие клавиши для звука, проверка голосового состояния и сообщения через бота.",
      state: discord.guild_id && discord.user_id ? "on" : "manual", where: "Приложение Discord и ваш сервер" },
    { id: "steam", icon: Gamepad2, title: "Steam", about: "Читает библиотеку и запускает игры по названию: «запусти ведьмака».", state: "auto", where: "На этом компьютере" },
    { id: "phone", icon: Smartphone, title: "Телефон", about: "Android-клиент и пульт в браузере: команды, текст, статус и остановка. Android также воспроизводит голосовой ответ с ПК.",
      state: get("companion.enabled", false) ? "on" : "off", where: "Ваша Wi-Fi сеть; ПК должен быть включён" },
    { id: "telegram", icon: Send, title: "Telegram", about: "Пишите Джарвису или отправляйте голосовые в своём боте. Можно запускать сценарии и останавливать задачи прямо из чата.",
      state: get("telegram.enabled", false) ? (telegram.token ? "on" : "need") : "off", where: "Через серверы Telegram; ПК должен быть включён" },
    { id: "plugins", icon: Puzzle, title: "Дополнения", about: "Добавляйте голос, новые действия, виджеты и реакции персонажа. Выберите дополнение из каталога или установите свой пакет.",
      state: "on", where: "На этом компьютере" },
    { id: "mcp", icon: Puzzle, title: "Внешние инструменты (MCP)", about: "Свои сервисы и программы по протоколу MCP. Для опытных.",
      state: get("integrations.enabled", false) ? "on" : "off", where: "Как настроите" },
  ]);
  const stateText: Record<string, [string, string]> = { on: ["Включено", "ok"], off: ["Выключено", ""], need: ["Нужна настройка", "warn"], auto: ["Определяется автоматически", "plain"], manual: ["По запросу", "plain"] };

  async function test(kind: string, body: Record<string, string>) {
    if (!app.core?.running) { results[kind] = { ok: false, text: "Сначала включите Джарвиса — проверку делает ядро" }; return; }
    testing = kind;
    try { results[kind] = await invoke("core_post", { path: "/api/connections/test", body: { kind, ...body } }); }
    catch (e) { results[kind] = { ok: false, text: String(e) }; }
    finally { testing = ""; }
  }
  function saveHome() {
    set("smarthome.homeassistant.url", ha.url.trim());
    set("smarthome.homeassistant.token", ha.token.trim());
    set("smarthome.homeassistant.auto", !!ha.url.trim());
    set("smarthome.yandex.token", yandex.token.trim());
    set("smarthome.yandex.auto", !!yandex.token.trim());
    toast("Сохранено", "success");
  }
</script>

<h1>{uiText("Подключения")}</h1>
<p class="lead">{uiText("Подключите сервисы и приложения, которыми хотите управлять через Джарвиса. Проверка не сохраняет настройки. Ключи остаются на этом компьютере.")}</p>

<div class="grid">
  {#each cards as c}
    <article class="card conn" class:open={open === c.id}>
      <header>
        <span class="icon"><c.icon size={20} /></span>
        <div class="title"><h3>{uiText(c.title)}</h3><span class="badge {stateText[c.state][1] || 'plain'}">{uiText(stateText[c.state][0])}</span></div>
      </header>
      <p class="about">{uiText(c.about)}</p>
      <p class="where dim">{uiText(c.where)}</p>
      {#if c.state !== "auto" && c.state !== "soon"}
        <button class="btn sm" aria-expanded={open === c.id} onclick={() => (open = open === c.id ? "" : c.id)}>{uiText(open === c.id ? "Свернуть" : "Настроить")}</button>
      {/if}
    </article>
  {/each}
</div>

{#if open === "home"}
  <section class="card fade-in">
    <div class="card-head"><h3><Lightbulb size={18} />{uiText(" Умный дом")}</h3><Toggle label={uiText("Умный дом включён")} checked={get("smarthome.enabled", false)} onchange={(v) => set("smarthome.enabled", v)} /></div>
    <ol class="steps">
      <li><b>{uiText("Возможности:")}</b>{uiText(" включать, выключать и регулировать устройства голосом. Замки и обогрев Джарвис переспрашивает.")}</li>
      <li><b>{uiText("Доступ:")}</b>{uiText(" в Home Assistant откройте Профиль → Безопасность → «Долгосрочные токены доступа» → Создать.")}</li>
      <li><b>{uiText("Подключение:")}</b>{uiText(" адрес и токен ниже → «Проверить» → «Сохранить».")}</li>
    </ol>
    <div class="form">
      <label class="field"><span>{uiText("Адрес Home Assistant")}</span><input placeholder="http://homeassistant.local:8123" bind:value={ha.url} /><span class="help">{uiText("Можно оставить пустым, если используете только Яндекс")}</span></label>
      <label class="field"><span>{uiText("Токен Home Assistant")}</span>
        <span class="secret"><input type={show.ha ? "text" : "password"} autocomplete="off" bind:value={ha.token} />
          <button class="btn ghost icon sm" type="button" aria-label={uiText(show.ha ? "Скрыть токен" : "Показать токен")} onclick={() => (show.ha = !show.ha)}>{#if show.ha}<EyeOff size={15} />{:else}<Eye size={15} />{/if}</button></span></label>
      <label class="field"><span>{uiText("Токен Умного дома Яндекса (необязательно)")}</span><input type="password" autocomplete="off" bind:value={yandex.token} /><span class="help">{uiText("OAuth-токен с правом iot:control. Команды идут через облако Яндекса")}</span></label>
    </div>
    <div class="actions">
      <button class="btn" disabled={testing === "homeassistant" || !ha.url} onclick={() => test("homeassistant", ha)}>{#if testing === "homeassistant"}<LoaderCircle size={14} class="spin" />{/if}{uiText(" Проверить Home Assistant")}</button>
      <button class="btn" disabled={testing === "yandex" || !yandex.token} onclick={() => test("yandex", yandex)}>{uiText("Проверить Яндекс")}</button>
      <button class="btn primary" onclick={saveHome}>{uiText("Сохранить")}</button>
    </div>
    {#each ["homeassistant", "yandex"] as k}{#if results[k]}<div class="notice {results[k].ok ? 'ok' : 'bad'}">{#if results[k].ok}<CircleCheck size={16} />{:else}<CircleAlert size={16} />{/if}<span>{uiText(results[k].text)}{#if results[k].items?.length}<br /><small class="dim">{results[k].items?.join(", ")}</small>{/if}</span></div>{/if}{/each}
  </section>
{:else if open === "obs"}
  <section class="card fade-in">
    <h3><Clapperboard size={18} /> OBS Studio</h3>
    <ol class="steps">
      <li>{uiText("В OBS: ")}<b>{uiText("Сервис → Настройки сервера WebSocket → Включить сервер")}</b>{uiText(". Там же — пароль.")}</li>
      <li>{uiText("Впишите адрес и пароль → «Проверить» → «Сохранить». Буфер повтора Джарвис включит сам.")}</li>
    </ol>
    <div class="form">
      <label class="field"><span>{uiText("Адрес")}</span><input bind:value={obs.url} /></label>
      <label class="field"><span>{uiText("Пароль WebSocket")}</span><input type="password" autocomplete="off" bind:value={obs.password} /></label>
      <label class="field"><span>{uiText("Имя микрофона в аудиомикшере")}</span><input bind:value={obs.microphone} placeholder="Mic/Aux" /></label>
    </div>
    <div class="actions">
      <button class="btn" disabled={testing === "obs"} onclick={() => test("obs", obs)}>{#if testing === "obs"}<LoaderCircle size={14} class="spin" />{/if}{uiText(" Проверить")}</button>
      <button class="btn primary" onclick={() => { set("obs.url", obs.url.trim()); set("obs.password", obs.password); set("obs.microphone", obs.microphone.trim()); toast("Сохранено", "success"); }}>{uiText("Сохранить")}</button>
    </div>
    {#if results.obs}<div class="notice {results.obs.ok ? 'ok' : 'bad'}">{uiText(results.obs.text)}</div>{/if}
    <p class="about">{uiText("Примеры: «Статус записи в OBS», «Покажи сцены в OBS», «Выбери сцену Игра в OBS», «Выключи микрофон в OBS».")}</p>
  </section>
{:else if open === "discord"}
  <section class="card fade-in">
    <h3><Headphones size={18} /> Discord</h3>
    <p class="about">{uiText("Один раз задайте в Discord: ")}<b>{uiText("Настройки → Горячие клавиши → Добавить")}</b>{uiText(": «Вкл./выкл. микрофон» и «Вкл./выкл. звук». Джарвис нажимает эти сочетания — доступа к аккаунту ему не нужно.")}</p>
    <div class="form">
      <label class="field"><span>{uiText("Микрофон в Discord")}</span><input bind:value={discord.mute} /></label>
      <label class="field"><span>{uiText("Звук в Discord")}</span><input bind:value={discord.deafen} /></label>
    </div>
    <h3>{uiText("Бот Discord")}</h3>
    <p class="about">{uiText("Добавьте своего бота на сервер. Для чтения звука ему нужен доступ к голосовому каналу. Для сообщений укажите текстовый канал и разрешите боту туда писать.")}</p>
    <div class="form">
      <label class="field"><span>{uiText("Токен бота")}</span><input type="password" autocomplete="off" bind:value={discord.bot_token} /></label>
      <label class="field"><span>{uiText("ID сервера")}</span><input inputmode="numeric" bind:value={discord.guild_id} /></label>
      <label class="field"><span>{uiText("Ваш ID пользователя")}</span><input inputmode="numeric" bind:value={discord.user_id} /></label>
      <label class="field"><span>{uiText("ID канала для сообщений")}</span><input inputmode="numeric" bind:value={discord.channel_id} /></label>
    </div>
    <div class="actions">
      <button class="btn" disabled={testing === "discord" || !discord.guild_id || !discord.user_id} onclick={() => test("discord", discord)}>{uiText(" Проверить")}</button>
      <button class="btn primary" onclick={saveDiscord}>{uiText("Сохранить")}</button>
    </div>
    {#if results.discord}<div class="notice {results.discord.ok ? 'ok' : 'bad'}">{uiText(results.discord.text)}</div>{/if}
  </section>
{:else if open === "phone"}
  <section class="card fade-in">
    <div class="card-head"><h3><Smartphone size={18} />{uiText(" Телефон")}</h3><Toggle label={uiText("Пульт для телефона")} checked={get("companion.enabled", false)} onchange={(v) => set("companion.enabled", v)} /></div>
    <ol class="steps">
      <li>{uiText("Включите пульт и выберите, откуда к нему можно подключаться.")}</li>
      <li>{uiText("На телефоне в той же Wi-Fi сети откройте адрес ")}<span class="mono">{uiText("http://<IP компьютера>:")}{uiText(get("companion.port", 8765))}</span>{uiText(" и введите код доступа.")}</li>
      <li>{uiText("Телефон показывает реальный итог задачи. Повтор одного и того же нажатия не выполняет действие дважды.")}</li>
    </ol>
    <PairedDevices kind="phone" />
    <div class="form">
      <label class="field"><span>{uiText("Откуда можно подключаться")}</span>
        <select value={get("companion.host", "127.0.0.1")} onchange={(e) => set("companion.host", e.currentTarget.value)}>
          <option value="127.0.0.1">{uiText("Только с этого компьютера")}</option>
          <option value="0.0.0.0">{uiText("Из домашней сети (Wi-Fi)")}</option>
        </select>
        <span class="help">{uiText("Не открывайте этот порт в интернет. Для доступа извне используйте VPN (например Tailscale)")}</span></label>
    </div>
  </section>
{:else if open === "telegram"}
  <section class="card fade-in">
    <div class="card-head"><h3><Send size={18} /> Telegram</h3><Toggle label={uiText("Telegram-бот")} checked={get("telegram.enabled", false)} onchange={(v) => set("telegram.enabled", v)} /></div>
    <ol class="steps">
      <li><b>{uiText("Создайте бота:")}</b>{uiText(" в Telegram напишите @BotFather → /newbot → получите ключ вида ")}<span class="mono">123456:ABC…</span></li>
      <li><b>{uiText("Подключение:")}</b>{uiText(" вставьте ключ → «Проверить» → «Сохранить» → включите переключатель и перезапустите Джарвиса.")}</li>
      <li><b>{uiText("Владелец:")}</b>{uiText(" «Получить код» ниже и отправьте боту ")}<span class="mono">{uiText("/start код")}</span>{uiText(". Чужие чаты бот игнорирует.")}</li>
    </ol>
    <p class="about">{uiText("Сообщения идут через серверы Telegram. Голосовые распознаются на вашем компьютере. Команды: /stop — остановить, /status — состояние. Опасные действия бот переспрашивает кнопками «Да/Нет».")}</p>
    <div class="form">
      <label class="field"><span>{uiText("Ключ бота")}</span>
        <span class="secret"><input type={show.tg ? "text" : "password"} autocomplete="off" bind:value={telegram.token} />
          <button class="btn ghost icon sm" type="button" aria-label={uiText(show.tg ? "Скрыть ключ" : "Показать ключ")} onclick={() => (show.tg = !show.tg)}>{#if show.tg}<EyeOff size={15} />{:else}<Eye size={15} />{/if}</button></span>
        <span class="help">{uiText("Хранится зашифрованным на этом компьютере; в экспорт и отчёты не попадает")}</span></label>
    </div>
    <div class="actions">
      <button class="btn" disabled={testing === "telegram" || !telegram.token} onclick={() => test("telegram", telegram)}>{#if testing === "telegram"}<LoaderCircle size={14} class="spin" />{/if}{uiText(" Проверить")}</button>
      <button class="btn primary" onclick={() => { set("telegram.token", telegram.token.trim()); toast("Сохранено", "success"); }}>{uiText("Сохранить")}</button>
    </div>
    {#if results.telegram}<div class="notice {results.telegram.ok ? 'ok' : 'bad'}">{uiText(results.telegram.text)}</div>{/if}
    <PairedDevices kind="telegram" />
  </section>
{:else if open === "plugins"}
  <div class="fade-in"><Plugins /></div>
{:else if open === "mcp"}
  <div class="fade-in"><Integrations /></div>
{/if}

<style>
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
    gap: 12px;
    margin-bottom: 16px;
  }
  .conn {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 16px;
  }
  .conn.open {
    border-color: var(--accent);
  }
  .conn + .conn {
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
    flex: none;
    border-radius: 10px;
    background: var(--accent-soft);
    color: var(--accent-2);
  }
  .title {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 3px;
  }
  .about {
    color: var(--text-2);
    font-size: 13px;
    line-height: 1.5;
  }
  .where {
    font-size: 12px;
    flex: 1;
  }
  .conn .btn {
    align-self: flex-start;
  }
  section h3 {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
  }
  .steps {
    margin: 6px 0 14px;
    padding-left: 20px;
    color: var(--text-2);
    font-size: 13px;
    line-height: 1.7;
  }
  .form {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 14px;
  }
  .secret {
    display: flex;
    gap: 6px;
  }
  .secret input {
    flex: 1;
  }
  .actions {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin: 16px 0 10px;
  }
  .notice + .notice {
    margin-top: 8px;
  }
</style>
