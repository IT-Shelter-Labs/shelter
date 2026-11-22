<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";
  import CloudMedia from "../components/CloudMedia.svelte";

  import { onMount, onDestroy } from "svelte";
  import { Volume2 } from "@lucide/svelte";
  import Setting from "../components/Setting.svelte";
  import Toggle from "../components/Toggle.svelte";
  import Segmented from "../components/Segmented.svelte";
  import Range from "../components/Range.svelte";
  import MicMeter from "../components/MicMeter.svelte";
  import VoiceClone from "../components/VoiceClone.svelte";
  import OwnerVoice from "../components/OwnerVoice.svelte";
  import MicWizard from "../components/MicWizard.svelte";
  import SpeechExtensions from "../components/SpeechExtensions.svelte";
  import { app, get, set, toast, toastError } from "../lib/store.svelte";
  import { api, on, type SetupEvent } from "../lib/api";

  let devices = $state<{ index: number; name: string; default: boolean }[]>([]);
  let installed = $state<Record<string, any>>({});
  let installing = $state(false);
  let installingModel = $state(false);
  let installText = $state("");
  let kwsInstalling = $state(false);
  let aecInstalling = $state(false);
  let unlisten: (() => void) | undefined;
  let testPhrase = $state("Добрый день, сэр. Все системы работают в штатном режиме.");
  const checks = [
    {name:"Обычная речь",text:"Добрый день, сэр. Все системы работают в штатном режиме."},
    {name:"Числа и время",text:"Напоминание на 18:45. Температура −12 градусов, осталось 25% заряда и 16 ГБ памяти."},
    {name:"Ударения",text:"Он звонит по средам. В старом замке сломался дверной замок. Эти проекты уже готовы."},
    {name:"Вопросы",text:"Вы хотите продолжить? Что поставить в расписание на завтра? Всё готово!"},
  ];

  onMount(async () => {
    installed = await api.setupCheck().catch(() => ({}));
    if (app.core?.running) devices = (await api.devices().catch(() => ({ devices: [] }))).devices;
    unlisten = await on<SetupEvent>("setup:event", e=>{
      if(e.status==="finished") { installingModel=false; installing=false; kwsInstalling=false; }
      if(e.component==="aec"&&(e.status==="ok"||e.status==="error")){
        aecInstalling=false;
        if(e.status==="error")toastError(e.message);
        else { set("audio.echo_cancel",true); api.setupCheck().then(c=>installed=c).catch(toastError); }
      }
      if(e.component==="kws"&&(e.status==="ok"||e.status==="error")){
        kwsInstalling=false;
        if(e.status==="error")toastError(e.message);
        else { set("wake.engine","kws"); api.setupCheck().then(c=>installed=c).catch(toastError); }
      }
      if(e.component!=="silero")return;
      if(e.text)installText=e.text;
      if(e.total)installText=`Загружаю: ${Math.round((e.done ?? 0)/e.total*100)}%`;
      if(e.status==="ok"||e.status==="error"){
        installing=false;
        if(e.status==="error")toastError(e.message);
        else api.setupCheck().then(c=>installed=c).catch(toastError);
      }
    });
  });
  onDestroy(()=>unlisten?.());

  const piperVoices = [
    { value: "ruslan", label: "Руслан" },
    { value: "dmitri", label: "Дмитрий" },
    { value: "denis", label: "Денис" },
    { value: "irina", label: "Ирина" },
  ];
  const words = $derived((get<string[]>("wake.words", ["джарвис"]) ?? []).join(", "));

  async function speakers(on: boolean) {
    if (on && !installed.aec?.ok) {
      aecInstalling = true;
      toast("Загружаю подавление эха (~15 МБ)…");
      await api.setupInstall(["aec"]).catch((e) => { aecInstalling = false; toastError(e); });
      return;
    }
    set("audio.echo_cancel", on);
  }

  async function wakeEngine(v: string) {
    if (v === "kws" && !installed.kws?.ok) {
      kwsInstalling = true;
      toast("Загружаю модель слова-обращения (22 МБ)…");
      await api.setupInstall(["kws"]).catch((e) => { kwsInstalling = false; toastError(e); });
      return;
    }
    set("wake.engine", v);
  }

  async function testVoice() {
    try {
      await api.say(testPhrase);
    } catch (e) {
      toastError(e);
    }
  }
  function dictionary(raw:string, path:string) {
    const result:Record<string,string>={};
    for(const line of raw.split("\n").filter(l=>l.trim())) {
      const cut=line.indexOf("=");
      if(cut<=0||!line.slice(cut+1).trim()){toastError("Каждая строка: слово=произношение");return;}
      result[line.slice(0,cut).trim()]=line.slice(cut+1).trim();
    }
    set(path,result);
  }
</script>

<h1>{uiText("Слух и голос")}</h1>
<p class="lead">{uiText("Как Джарвис вас слышит и как отвечает.")}</p>

<details class="card" id="mic-wizard" open={!get("audio.checked", false)}>
  <summary>{uiText("Проверка микрофона — пошагово, около минуты")}</summary>
  <MicWizard />
</details>

<div class="card">
  <div class="caps">{uiText("Микрофон")}</div>
  <Setting title={uiText("Устройство")} hint={uiText(devices.length ? "Если Джарвис плохо слышит — выберите микрофон, в который вы говорите" : "Включите Джарвиса, чтобы увидеть список")}>
    <select style="width:300px" value={String(get("audio.device") ?? "")} onchange={(e) => { const v = (e.target as HTMLSelectElement).value; set("audio.device", v === "" ? null : Number(v)); set("audio.device_name", devices.find(d => String(d.index) === v)?.name ?? null); }}>
      <option value="">{uiText("По умолчанию Windows")}</option>
      {#each devices as d}<option value={String(d.index)}>{d.name}</option>{/each}
      {#if get("audio.device") != null && !devices.some((d) => d.index === get("audio.device"))}<option value={String(get("audio.device"))}>{uiText("Текущий микрофон (№")}{uiText(get("audio.device"))})</option>{/if}
    </select>
  </Setting>
  <div class="meter-row"><MicMeter /></div>
  <Setting title={uiText("Распознавание речи")} hint={uiText("GigaAM рекомендуется для русских фраз; vosk требует меньше ресурсов. Точность зависит от микрофона и условий.")}>
    <Segmented value={get("asr.engine", "gigaam")} options={[{ value: "gigaam", label: "GigaAM" }, { value: "vosk", label: "Быстрое (vosk)" }]} onchange={(v) => set("asr.engine", v)} />
  </Setting>
  <SpeechExtensions kind="stt" />
  <Setting title={uiText("Я пользуюсь колонками")} hint={uiText(aecInstalling ? "Загружаю…" : app.status?.echo?.error ? "Не слышу колонки: " + app.status.echo.error : "Подавление эха уменьшает звук компьютера в микрофоне: звонки, игры и голос помощника. Это снижает число случайных срабатываний, но не исключает их. С наушниками обычно не требуется")}>
    <Toggle checked={get("audio.echo_cancel", false)} onchange={speakers} />
  </Setting>
  <Setting title={uiText("Фильтр шума")} hint={uiText("Нейросеть Silero отличает голос от клавиатуры, выстрелов и музыки")}>
    <Toggle checked={get("wake.vad.engine", "silero") === "silero"} onchange={(v) => set("wake.vad.engine", v ? "silero" : "energy")} />
  </Setting>
</div>

<div class="card">
  <div class="caps">{uiText("Узнавание хозяина")}</div>
  <OwnerVoice />
</div>

<div class="card">
  <div class="caps">{uiText("Обращение")}</div>
  <Setting title={uiText("Как слушать имя")} hint={uiText(kwsInstalling ? "Загружаю модель…" : "Лёгкое — отдельная маленькая нейросеть ищет только имя: вдвое меньше нагрузки, лучше слышит «Джарвис». Vosk — прежний способ")}>
    <Segmented value={get("wake.engine", "kws")} options={[{ value: "kws", label: "Лёгкое" }, { value: "vosk", label: "vosk" }]} onchange={wakeEngine} />
  </Setting>
  {#if get("wake.engine", "kws") === "kws"}
    <Setting title={uiText("Чувствительность к имени")} hint={uiText("Выше — слышит даже невнятное «Джарвис», но чаще срабатывает на похожие слова")}>
      <Range value={Math.round(get("wake.sensitivity", 0.5) * 100)} min={10} max={90} step={10} format={(v) => v + "%"} onchange={(v) => set("wake.sensitivity", v / 100)} />
    </Setting>
  {/if}
  <Setting title={uiText("Слово-обращение")} hint={uiText(get("wake.engine", "kws") === "kws" ? "Через запятую, первое — основное. Подойдёт любое русское слово; лучше редкое — обычное («пятница») сработает и во фразе «в пятницу»" : "Через запятую. Распознаются слова из словаря русской речи; «джарвис» уже настроено")}>
    <input type="text" style="width:300px" value={words} onchange={(e) => set("wake.words", (e.target as HTMLInputElement).value.split(",").map((w) => w.trim().toLowerCase()).filter(Boolean))} />
  </Setting>
  <Setting title={uiText("Слушать после ответа")} hint={uiText("Сколько секунд можно продолжать разговор без повторного «Джарвис»")}>
    <Range value={get("wake.follow_up", 12)} min={4} max={40} format={(v) => v + " с"} onchange={(v) => set("wake.follow_up", v)} />
  </Setting>
  <Setting title={uiText("Закрывать HUD после действия")} hint={uiText("Выключено — Джарвис остаётся в разговоре до паузы и принимает следующую просьбу. Команды явного завершения разговора работают всегда.")}><Toggle checked={get("wake.close_after_action",false)} onchange={v=>set("wake.close_after_action",v)}/></Setting>
  <Setting title={uiText("Кнопка «говорить»")} hint={uiText("Нажатие — как сказать «Джарвис»: удобно в шумной игре. Например Ctrl+Alt+J или F9; пусто — выключено")}>
    <input type="text" style="width:160px" value={get("wake.hotkey", "Ctrl+Alt+J")}
           onchange={async (e) => {
             const combo = (e.target as HTMLInputElement).value.trim();
             try { await api.setHotkey(combo); set("wake.hotkey", combo, false); toast(combo ? `Кнопка «говорить»: ${combo}` : "Кнопка «говорить» выключена", "success"); }
             catch (error) { toastError(error); }
           }} />
  </Setting>
  <Setting title={uiText("Сигнал на обращение")} hint={uiText("Короткий звук сразу, как Джарвис услышал имя")}>
    <Toggle checked={get("wake.earcon", true)} onchange={(v) => set("wake.earcon", v)} />
  </Setting>
  <Setting title={uiText("Приглушать игры и музыку")} hint={uiText("Пока Джарвис слушает и говорит")}>
    <Range value={Math.round((1 - get("wake.duck", 0.3)) * 100)} min={0} max={90} step={10} format={(v) => (v ? "−" + v + "%" : "нет")} onchange={(v) => set("wake.duck", Math.round((1 - v / 100) * 100) / 100)} />
  </Setting>
  <Setting title={uiText("Перебивать ответ")} hint={uiText("«Хватит», «стоп» или «Джарвис» прямо во время его речи")}>
    <Toggle checked={get("wake.barge_in", true)} onchange={(v) => set("wake.barge_in", v)} />
  </Setting>
  <Setting title={uiText("Команды без имени")} hint={uiText("Если что-то играет: «пауза», «дальше», «громче», «тише»")}>
    <Toggle checked={get("wake.quick", true)} onchange={(v) => set("wake.quick", v)} />
  </Setting>
</div>

<div class="card">
  <div class="caps">{uiText("Голос Джарвиса")}</div>
  <Setting title={uiText("Фирменный голос")} hint={uiText("Клонированный голос по вашему образцу — видеокарта NVIDIA")} wide>
    <VoiceClone compact />
  </Setting>
  <Setting title={uiText("Движок озвучки")} hint={uiText("Piper — минимум нагрузки. Silero V5 — русский голос на процессоре. Qwen — голос по образцу, требующий больше ресурсов.")}>
      <select value={get("tts.engine", "piper")} onchange={e=>set("tts.engine",e.currentTarget.value)}><option value="piper">{uiText("Piper · лёгкий")}</option><option value="silero">{uiText("Silero V5 · русский")}</option><option value="clone">{uiText("Голос персонажа · Qwen")}</option><option value="cloud">{uiText("Облачная озвучка")}</option><option value="files">{uiText("Свои записи + запасной голос")}</option>{#if get("tts.engine") === "plugin"}<option value="plugin">{uiText("Голос из дополнения")}</option>{/if}</select>
  </Setting>
  <SpeechExtensions kind="tts" />
  {#if get("tts.engine") === "cloud"}<CloudMedia mode="speech" />{/if}
  {#if get("tts.engine")==="silero"}
    <Setting title="Silero V5.6" hint={uiText(installed.silero?.ok ? "Установлен локально; автоматические ударения и буква ё" : "Дополнительный голос и PyTorch CPU устанавливаются только по этой кнопке. Лицензия модели CC BY-NC.")}>
      {#if !installed.silero?.ok}<button class="btn" disabled={installing} onclick={()=>{installing=true;installText="Подготавливаю…";api.setupInstall(["silero"]).catch(e=>{installing=false;toastError(e);});}}>{uiText(installing ? installText : "Установить русский голос")}</button>{:else}<span class="chip ok">{uiText("Готов")}</span>{/if}
    </Setting>
    <Setting title={uiText("Голос Silero")} hint={uiText("Можно сравнить одинаковые фразы разными голосами после применения настроек.")}><select value={get("tts.speaker","aidar")} onchange={e=>set("tts.speaker",e.currentTarget.value)}>{#each ["aidar","baya","kseniya","xenia","eugene"] as speaker}<option value={speaker}>{uiText(speaker)}</option>{/each}</select></Setting>
    <Setting title={uiText("Словарь ударений Silero")} hint={uiText("Одна запись в строке: звонит=звон+ит. Плюс ставится перед ударной гласной. Этот словарь не передаётся Qwen.")} wide>
      <textarea rows="3" placeholder={uiText("звонит=звон+ит")} value={Object.entries(get<Record<string,string>>("tts.stress",{})).map(([a,b])=>`${a}=${b}`).join("\n")} onchange={e=>dictionary(e.currentTarget.value,"tts.stress")}></textarea>
    </Setting>
  {/if}
  {#if get("tts.engine")==="clone"}
    <Setting title={uiText("Размер модели Qwen")} hint={uiText("1.7B требует больше памяти. Улучшение русских ударений не гарантируется — сравните на тестовых фразах.")}><select value={get("tts.clone.model","Qwen/Qwen3-TTS-12Hz-0.6B-Base")} onchange={e=>set("tts.clone.model",e.currentTarget.value)}><option value="Qwen/Qwen3-TTS-12Hz-0.6B-Base">0.6B</option><option value="Qwen/Qwen3-TTS-12Hz-1.7B-Base">1.7B</option>{#if !["Qwen/Qwen3-TTS-12Hz-0.6B-Base","Qwen/Qwen3-TTS-12Hz-1.7B-Base"].includes(get("tts.clone.model",""))}<option value={get("tts.clone.model","")}>{uiText("Своя модель")}</option>{/if}</select></Setting>
    <Setting title={uiText("Скачать 1.7B")} hint={uiText("Необязательно: отдельные веса и больше места на диске. Устанавливается по нажатию.")}><button class="btn" disabled={installingModel} onclick={()=>{installingModel=true;api.setupInstall(["clone:1.7b"]).catch(e=>{installingModel=false;toastError(e);});}}>{uiText(installingModel?"Устанавливаю…":"Установить Qwen 1.7B")}</button></Setting>
    <details><summary>{uiText("Своя дообученная модель")}</summary>
      <Setting title={uiText("Каталог checkpoint")} hint={uiText("Полный путь к локальному checkpoint Qwen. Для стандартного клонирования оставьте имя Base-модели.")}><input value={get("tts.clone.model","")} onchange={e=>set("tts.clone.model",e.currentTarget.value.trim())}/></Setting>
      <Setting title={uiText("Имя обученного диктора")} hint={uiText("speaker_name из обучения. Пусто — обычное клонирование Base по образцу. Для CustomVoice нужен корректный checkpoint.")}><input value={get("tts.clone.speaker","")} onchange={e=>set("tts.clone.speaker",e.currentTarget.value.trim())}/></Setting>
    </details>
  {/if}
  <Setting title={uiText("Лёгкий голос")} hint={uiText("Используется без видеокарты и как запасной")}>
    <select value={get("tts.piper.voice", "ruslan")} onchange={(e) => set("tts.piper.voice", (e.target as HTMLSelectElement).value)}>
      {#each piperVoices as v}<option value={v.value} disabled={installed.piper?.voices && !installed.piper.voices.includes(v.value)}>{uiText(v.label)}{uiText(installed.piper?.voices && !installed.piper.voices.includes(v.value) ? " (не скачан)" : "")}</option>{/each}
    </select>
  </Setting>
  <Setting title={uiText("Скорость лёгкого голоса")}>
    <Range value={get("tts.piper.speed", 1)} min={0.7} max={1.4} step={0.05} format={(v) => "×" + v.toFixed(2)} onchange={(v) => set("tts.piper.speed", v)} />
  </Setting>
  <Setting title={uiText("Краткость голосового ответа")} hint={uiText("Показывается весь ответ; голосом — выбранное число предложений. Полный текст можно зачитать кнопкой у ответа.")}><Range value={get("tts.reply_sentences",3)} min={1} max={8} step={1} format={v=>`${v} предлож.`} onchange={v=>set("tts.reply_sentences",v)}/></Setting>
  <Setting title={uiText("Словарь произношений")} hint={uiText("Для имён и сокращений: Jarvis=Джарвис. Числа и единицы подготавливаются автоматически для всех движков.")} wide>
    <textarea rows="3" placeholder={uiText("Jarvis=Джарвис")} value={Object.entries(get<Record<string,string>>("tts.pronunciations",{})).map(([a,b])=>`${a}=${b}`).join("\n")} onchange={e=>dictionary(e.currentTarget.value,"tts.pronunciations")}></textarea>
  </Setting>
  <Setting title={uiText("Русские тестовые фразы")} hint={uiText("Проверяйте числа, ударения и вопросы отдельно. Отзывы других пользователей не заменяют прослушивания вашего голоса.")}>
    <select aria-label={uiText("Категория проверки голоса")} bind:value={testPhrase}>{#each checks as c}<option value={c.text}>{uiText(c.name)}</option>{/each}</select>
  </Setting>
  <Setting title={uiText("Проверить голос")} hint={uiText("Звучит текущий голос; после смены нажмите «Применить» вверху")}>
    <button class="btn" onclick={testVoice} disabled={!app.core?.running}><Volume2 size={15} />{uiText(" Прослушать")}</button>
  </Setting>
</div>

<style>
  .meter-row {
    padding: 4px 0 12px;
    border-bottom: 1px solid var(--line);
  }
</style>
