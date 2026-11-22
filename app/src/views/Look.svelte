<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  import Setting from "../components/Setting.svelte";
  import Toggle from "../components/Toggle.svelte";
  import Segmented from "../components/Segmented.svelte";
  import Range from "../components/Range.svelte";
  import { get, set } from "../lib/store.svelte";
  import { ACCENTS, THEMES } from "../lib/theme";
  import { Check, Moon, Sun, Sparkles, Monitor } from "@lucide/svelte";
</script>

<h1>{uiText("Оформление")}</h1>
<p class="lead">{uiText("Как выглядит окно помощника и как персонаж появляется на рабочем столе.")}</p>

<Setting title={uiText("Язык интерфейса")} hint={uiText("Меняет подписи, подсказки и уведомления без перезапуска. Язык распознавания, голос персонажа, ваши сообщения и команды остаются прежними")}>
  <select aria-label={uiText("Язык интерфейса")} value={get('ui.language','ru')} onchange={e=>set('ui.language',e.currentTarget.value)}>
    <option value="ru">{uiText("Русский")}</option><option value="en">English</option>
  </select>
</Setting>

<div class="theme-gallery" role="group" aria-label={uiText("Тема интерфейса")}>
  {#each THEMES as theme}
    <button type="button" class="theme-option" class:selected={get("ui.theme", "dark") === theme.id}
      aria-pressed={get("ui.theme", "dark") === theme.id} onclick={() => set("ui.theme", theme.id)}>
      <span class="theme-preview" data-preview={theme.id} aria-hidden="true">
        <span class="preview-cloud"></span><span class="preview-nav"><i></i><i></i><i></i></span>
        <span class="preview-panel"><span class="preview-orb"></span><i></i><i></i></span>
        <span class="preview-pill"></span>
      </span>
      <span class="theme-label">
        {#if theme.id === "dark"}<Moon size={15} />{:else if theme.id === "light"}<Sun size={15} />{:else if theme.id === "glass"}<Sparkles size={15} />{:else}<Monitor size={15} />{/if}
        <b>{uiText(theme.label)}</b>{#if get("ui.theme", "dark") === theme.id}<Check size={15} />{/if}
      </span>
      <span class="theme-description">{uiText(theme.description)}</span>
    </button>
  {/each}
</div>

{#if get<string>("ui.theme", "dark") === "glass"}
  <div class="card glass-options">
    <div class="card-head"><h3><Sparkles size={17} />{uiText(" Жидкое стекло")}</h3><span class="chip">{uiText("Применяется сразу")}</span></div>
    <p class="glass-note">{uiText("Цветные облака мягко перетекают за стеклом. Надписи остаются чёткими; в фоне движение приостанавливается.")}</p>
    <Setting title={uiText("Оттенок стекла")} hint={uiText("Светлый, тёмный или автоматически вслед за системой")}>
      <Segmented value={get("ui.glass.tint", "dark")} options={[{ value: "dark", label: "Тёмный" }, { value: "light", label: "Светлый" }, { value: "system", label: "Системный" }]} onchange={(v) => set("ui.glass.tint", v)} />
    </Setting>
    <Setting title={uiText("Живая атмосфера")} hint={uiText("Плавное движение цветного тумана. При уменьшении движения или в облегчённом режиме анимация отключается")}>
      <Toggle checked={get("ui.glass.animate", true)} onchange={(v) => set("ui.glass.animate", v)} />
    </Setting>
    <Setting title={uiText("Прозрачность панелей")} hint={uiText("Выше — более прозрачное, чистое стекло. Надписи остаются чёткими")}>
      <Range value={100 - get("ui.glass.opacity", 30)} min={15} max={85} step={5} format={(v) => v + "%"} onchange={(v) => set("ui.glass.opacity", 100 - v)} />
    </Setting>
    <Setting title={uiText("Размытие стекла")} hint={uiText("Меньше — яснее видны цвет и фон за панелью; больше — мягкое матовое стекло")}>
      <Range value={get("ui.glass.blur", 8)} min={0} max={24} step={2} format={(v) => v + " px"} onchange={(v) => set("ui.glass.blur", v)} />
    </Setting>
    <Setting title={uiText("Рабочий стол за стеклом")} hint={uiText("В приложении Windows сквозь окно виден размытый рабочий стол. В других системах остаётся цветная атмосфера внутри окна. Плотное стекло и облегчённый режим отключают этот эффект")}>
      <Toggle checked={get("ui.glass.desktop", true)} onchange={(v) => set("ui.glass.desktop", v)} />
    </Setting>
    <Setting title={uiText("Насыщенность атмосферы")} hint={uiText("Количество цвета за стеклом; не влияет на яркость текста")}>
      <Range value={get("ui.glass.intensity", 55)} min={10} max={90} step={5} format={(v) => v + "%"} onchange={(v) => set("ui.glass.intensity", v)} />
    </Setting>
    <Setting title={uiText("Темп движения")} hint={uiText("Больше секунд — спокойнее движение облаков")}>
      <Range value={get("ui.glass.speed", 36)} min={20} max={80} step={4} format={(v) => v + " с"} onchange={(v) => set("ui.glass.speed", v)} />
    </Setting>
    <Setting title={uiText("Плотное стекло")} hint={uiText("Непрозрачные панели с цветной атмосферой вокруг: удобно для чтения. Также учитывается системное уменьшение прозрачности")}>
      <Toggle checked={get("ui.glass.opaque", false)} onchange={(v) => set("ui.glass.opaque", v)} />
    </Setting>
  </div>
{/if}

<div class="card">
  <div class="caps">{uiText("Это окно")}</div>
  <Setting title={uiText("Цвет акцента")} hint={uiText("Кнопки, выделение и подсветка")}>
    <div class="swatches" role="radiogroup" aria-label={uiText("Цвет акцента")}>
      {#each ACCENTS as a}
        <button role="radio" aria-checked={get("ui.accent", "cyan") === a.id} aria-label={uiText(a.label)} title={uiText(a.label)}
                class:on={get("ui.accent", "cyan") === a.id} style="--h:{a.hue}" onclick={() => set("ui.accent", a.id)}></button>
      {/each}
    </div>
  </Setting>
  <Setting title={uiText("Облегчённый режим")} hint={uiText("Для слабого компьютера: без размытия, свечения и анимаций в окне. Персонаж рисуется реже (24 кадра), реактор — без движения")}>
    <Toggle checked={get("ui.lite", false)} onchange={(v) => set("ui.lite", v)} />
  </Setting>
  <Setting title={uiText("Анимации")} hint={uiText("«Как в системе» учитывает параметр Windows «Показывать анимацию»")}>
    <Segmented value={get("ui.motion", "auto")} options={[{ value: "auto", label: "Как в системе" }, { value: "full", label: "Включены" }, { value: "reduce", label: "Минимум" }]} onchange={(v) => set("ui.motion", v)} />
  </Setting>
  <Setting title={uiText("Размер текста и кнопок")} hint={uiText("Если всё мелко при масштабе Windows 100% или крупно при 200%")}>
    <Range value={get("ui.text_scale", 100)} min={85} max={130} step={5} format={(v) => v + "%"} onchange={(v) => set("ui.text_scale", v)} />
  </Setting>
</div>

<div class="card" id="screen-window">
  <div class="caps">{uiText("Окно Джарвиса на экране")}</div>
  <Setting title={uiText("Вид")} hint={uiText("Авто — большое окно, а в полноэкранной игре или видео — компактно, без отвлечения")}>
    <Segmented value={get("ui.layout", "auto")} options={[{ value: "auto", label: "Авто" }, { value: "full", label: "Большое окно" }, { value: "orb", label: "Компактный реактор" }, { value: "hidden", label: "Без окна" }]} onchange={(v) => set("ui.layout", v)} />
  </Setting>
  <Setting title={uiText("Монитор")} hint={uiText("Где показываться. Голосом: «перейди на второй монитор», «встань в левый угол», «работай без окна», «покажи окно»")}>
    <select value={String(get("ui.monitor", 0))} onchange={(e) => set("ui.monitor", Number((e.target as HTMLSelectElement).value))}>
      <option value="0">{uiText("Где вы работаете")}</option>
      <option value="1">{uiText("Основной")}</option>
      <option value="2">{uiText("Второй")}</option>
      <option value="3">{uiText("Третий")}</option>
    </select>
  </Setting>
  <Setting title={uiText("Когда вы в игре")} hint={uiText("Компактный реактор в углу или большое окно на другом мониторе (если он есть)")}>
    <Segmented value={get("ui.busy", "orb")} options={[{ value: "orb", label: "Компактный реактор" }, { value: "monitor", label: "Другой монитор" }]} onchange={(v) => set("ui.busy", v)} />
  </Setting>
  <Setting title={uiText("Угол для реактора")}>
    <select value={get("ui.corner", "bottom-right")} onchange={(e) => set("ui.corner", (e.target as HTMLSelectElement).value)}>
      <option value="bottom-right">{uiText("Справа снизу")}</option>
      <option value="top-right">{uiText("Справа сверху")}</option>
      <option value="bottom-left">{uiText("Слева снизу")}</option>
      <option value="top-left">{uiText("Слева сверху")}</option>
      <option value="right">{uiText("Справа посередине")}</option>
    </select>
  </Setting>
  <Setting title={uiText("Плавность анимации")} hint={uiText("Кадров в секунду. На слабом компьютере поставьте 30")}>
    <Range value={get("ui.fps", 60)} min={24} max={60} step={6} format={(v) => v + " fps"} onchange={(v) => set("ui.fps", v)} />
  </Setting>
  <Setting title={uiText("Курсы криптовалют в HUD")} hint={uiText("Разрешает запросы к CoinGecko раз в минуту. По умолчанию сетевой виджет выключен")}>
    <Toggle checked={get("ui.markets", false)} onchange={(v) => set("ui.markets", v)} />
  </Setting>
  <Setting title={uiText("Игры в окне")} hint={uiText("Программы, при которых вы «заняты», даже если они не на весь экран. Через запятую, например: dota2.exe, cs2.exe")}>
    <input type="text" style="width:300px" value={(get<string[]>("ui.busy_apps", []) ?? []).join(", ")} onchange={(e) => set("ui.busy_apps", (e.target as HTMLInputElement).value.split(",").map((s) => s.trim().toLowerCase()).filter(Boolean))} />
  </Setting>
</div>

<div class="card">
  <div class="caps">{uiText("Игровой режим")}</div>
  <Setting title={uiText("Короткие подтверждения")} hint={uiText("В игре действия подтверждаются звуком, а не фразой — видеокарта не отвлекается на синтез голоса")}>
    <Toggle checked={get("gaming.brief", true)} onchange={(v) => set("gaming.brief", v)} />
  </Setting>
  <Setting title={uiText("Освобождать видеопамять")} hint={uiText("В игре модель выгружается через 3 минуты после ответа (обычно — через 30)")}>
    <Toggle checked={!!get("gaming.keep_alive", "3m")} onchange={(v) => set("gaming.keep_alive", v ? "3m" : null)} />
  </Setting>
</div>

<style>
  .theme-gallery { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 4px 0 20px; }
  .theme-option { min-width: 0; display: flex; flex-direction: column; gap: 7px; padding: 9px 9px 13px; text-align: left; border: 1px solid var(--line); border-radius: 18px; color: var(--text); background: var(--surface); cursor: pointer; font: inherit; transition: border-color var(--fast), box-shadow var(--fast); }
  .theme-option:hover { border-color: var(--line-2); }
  .theme-option.selected { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-soft); }
  .theme-label { display: flex; gap: 7px; align-items: center; padding: 2px 4px 0; font-size: 12px; }
  .theme-label b { flex: 1; font-weight: 600; }
  .theme-label > :global(svg) { flex: none; color: var(--accent-2); }
  .theme-description { color: var(--text-2); font-size: 11px; line-height: 1.45; padding: 0 4px; }
  .theme-preview { height: 100px; position: relative; overflow: hidden; border-radius: 11px; background: #0d1725; border: 1px solid #ffffff16; }
  .preview-nav { position: absolute; inset: 9px auto 9px 8px; width: 23%; border: 1px solid #bfeaff24; border-radius: 8px; background: #ccdfff0b; display: flex; flex-direction: column; gap: 8px; padding: 12px 6px; }
  .preview-nav i { height: 3px; background: #7b9eba55; border-radius: 3px; }
  .preview-nav i:first-child { background: #6ddce6; }
  .preview-panel { position: absolute; inset: 12px 9px 34px 37%; border: 1px solid #c5e8ff2e; border-radius: 10px; background: #c8e1ff0d; }
  .preview-panel > i { display: block; width: 28%; height: 3px; border-radius: 3px; background: #bdd9f35c; margin: 17px 0 0 56%; }
  .preview-panel > i + i { width: 20%; margin-top: 6px; opacity: .5; }
  .preview-orb { position: absolute; left: 13%; top: 20%; width: 25px; height: 25px; border-radius: 50%; border: 1px solid #80dfff8c; background: radial-gradient(circle, #ffffff 3%, #92d6ed 14%, #58c6ef22 47%, transparent 70%); box-shadow: 0 0 14px #56b9ee40; }
  .preview-pill { position: absolute; left: 38%; right: 9%; bottom: 13px; height: 13px; border: 1px solid #c5e8ff26; border-radius: 8px; background: #ddefff12; }
  [data-preview="light"] { background: #edf2f8; }
  [data-preview="light"] .preview-nav, [data-preview="light"] .preview-panel, [data-preview="light"] .preview-pill { background: #fff; border-color: #73869e38; }
  [data-preview="light"] .preview-panel > i { background: #6685a87d; }
  [data-preview="light"] .preview-orb { border-color: #45aaca; }
  [data-preview="glass"] { background: #283955; }
  [data-preview="glass"] .preview-cloud { position: absolute; inset: -30px; background: radial-gradient(ellipse at 20% 25%, #68ccd8b3, transparent 50%), radial-gradient(ellipse at 85% 65%, #d1a2e1b3, transparent 55%), radial-gradient(ellipse at 75% 10%, #f8ccbd99, transparent 50%); }
  [data-preview="glass"] .preview-nav, [data-preview="glass"] .preview-panel, [data-preview="glass"] .preview-pill { background: linear-gradient(135deg, #ffffff30, #ffffff0a); border-color: #ffffff6b; box-shadow: inset 0 1px 0 #ffffff38; }
  [data-preview="system"] { background: linear-gradient(115deg, #edf2f8 49.5%, #0d1725 50%); }
  .glass-options { margin-bottom: 18px; }
  .glass-note { color: var(--text-2); font-size: 12px; margin: 8px 0 10px; max-width: 650px; }
  @media (max-width: 1000px) { .theme-gallery { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
  @media (max-width: 520px) { .theme-label { font-size: 11px; } .theme-preview { height: 82px; } }
  .swatches {
    display: flex;
    gap: 8px;
  }
  .swatches button {
    width: 26px;
    height: 26px;
    border-radius: 50%;
    border: 2px solid transparent;
    background: hsl(var(--h), 68%, 52%);
    cursor: pointer;
    box-shadow: 0 0 0 1px var(--line-2);
  }
  .swatches button.on {
    border-color: var(--text);
    box-shadow: 0 0 0 3px hsla(var(--h), 68%, 52%, 0.35);
  }
</style>
