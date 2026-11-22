<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  import Integrations from "../components/Integrations.svelte";
  import Setting from "../components/Setting.svelte";
  import Toggle from "../components/Toggle.svelte";
  import { get, set } from "../lib/store.svelte";
</script>

<h1>{uiText("Возможности")}</h1>
<p class="lead">{uiText("Подключите то, чем пользуетесь: Джарвис будет управлять этим голосом.")}</p>

<Integrations />

<div class="card">
  <div class="caps">Discord</div>
  <p class="howto">{uiText("\r\n    Чтобы говорить «выключи микрофон в дискорде», один раз задайте в Discord горячие клавиши:\r\n    ")}<b>{uiText("Настройки → Горячие клавиши → Добавить")}</b>{uiText(": «Вкл./выкл. микрофон» — ")}<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>F9</kbd>{uiText(",\r\n    «Вкл./выкл. звук» — ")}<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>F10</kbd>{uiText(". Или впишите здесь свои сочетания.\r\n  ")}</p>
  <Setting title={uiText("Микрофон в Discord")}>
    <input type="text" style="width:200px" value={get("discord.mute", "ctrl+shift+f9")} onchange={(e) => set("discord.mute", (e.target as HTMLInputElement).value.trim().toLowerCase())} />
  </Setting>
  <Setting title={uiText("Звук в Discord")}>
    <input type="text" style="width:200px" value={get("discord.deafen", "ctrl+shift+f10")} onchange={(e) => set("discord.deafen", (e.target as HTMLInputElement).value.trim().toLowerCase())} />
  </Setting>
</div>

<div class="card">
  <div class="caps">OBS Studio</div>
  <p class="howto">{uiText("\r\n    «Сохрани момент», «начни запись», «останови запись». В OBS: ")}<b>{uiText("Сервис → Настройки сервера WebSocket → Включить сервер")}</b>{uiText(",\r\n    там же — пароль. Буфер повтора Джарвис включит сам. Трансляцию голосом не запускает — нарочно.\r\n  ")}</p>
  <Setting title={uiText("Адрес")}>
    <input type="text" style="width:240px" value={get("obs.url", "ws://127.0.0.1:4455")} onchange={(e) => set("obs.url", (e.target as HTMLInputElement).value.trim())} />
  </Setting>
  <Setting title={uiText("Пароль сервера WebSocket")}>
    <input type="password" style="width:240px" value={get("obs.password", "")} onchange={(e) => set("obs.password", (e.target as HTMLInputElement).value)} />
  </Setting>
</div>

<div class="card">
  <div class="caps">{uiText("Умный дом")}</div>
  <p class="howto">{uiText("\r\n    «Выключи свет», «включи чайник», «яркость на половину». Лучше всего — через ")}<b>Home Assistant</b>{uiText(": в нём работают Tuya, Xiaomi, Sonoff, Zigbee\r\n    и сотни других брендов. Или напрямую — через Умный дом Яндекса (устройства Алисы).\r\n  ")}</p>
  <Setting title={uiText("Включить умный дом")}>
    <Toggle checked={get("smarthome.enabled", false)} onchange={(v) => set("smarthome.enabled", v)} />
  </Setting>
  {#if get("smarthome.enabled", false)}
    <Setting title={uiText("Home Assistant — адрес")} hint={uiText("Например http://homeassistant.local:8123")}>
      <input type="text" style="width:280px" value={get("smarthome.homeassistant.url", "")} onchange={(e) => set("smarthome.homeassistant.url", (e.target as HTMLInputElement).value.trim())} />
    </Setting>
    <Setting title={uiText("Home Assistant — токен")} hint={uiText("Профиль → Безопасность → Долгосрочные токены доступа → Создать")}>
      <input type="password" style="width:280px" value={get("smarthome.homeassistant.token", "")} onchange={(e) => { set("smarthome.homeassistant.token", (e.target as HTMLInputElement).value.trim()); set("smarthome.homeassistant.auto", true); }} />
    </Setting>
    <Setting title={uiText("Яндекс — токен")} hint={uiText("OAuth-токен с правом iot:control (необязательно)")}>
      <input type="password" style="width:280px" value={get("smarthome.yandex.token", "")} onchange={(e) => { const v = (e.target as HTMLInputElement).value.trim(); set("smarthome.yandex.token", v); set("smarthome.yandex.auto", !!v); }} />
    </Setting>
  {/if}
</div>

<div class="card">
  <div class="caps">{uiText("Игры")}</div>
  <Setting title="Steam" hint={uiText("Подключается сам: Джарвис читает вашу библиотеку и запускает игры по названию — «запусти ведьмака»")}>
    <span class="chip ok"><span class="dot"></span>{uiText(" автоматически")}</span>
  </Setting>
</div>

<style>
  .howto {
    color: var(--text-2);
    font-size: 13px;
    margin: 6px 0 4px;
    line-height: 1.6;
  }
  .howto b {
    color: var(--text);
    font-weight: 600;
  }
</style>
