<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";
  import { locale } from "../lib/i18n.svelte";

  import { onMount, onDestroy, tick } from "svelte";
  import { open as openFile, save as saveFile } from "../lib/fileDialogs";
  import { invoke } from "@tauri-apps/api/core";
  import { Check, Pencil, Copy, Trash2, Mic, FileAudio, Box, Sparkles, Download, Upload, CircleAlert } from "@lucide/svelte";
  import { ask as askDialog } from "../lib/dialog.svelte";
  import Setting from "../components/Setting.svelte";
  import Segmented from "../components/Segmented.svelte";
  import Range from "../components/Range.svelte";
  import Toggle from "../components/Toggle.svelte";
  import CompanionEditor from "../components/CompanionEditor.svelte";
  import AvatarPortrait from "../components/AvatarPortrait.svelte";
  import Reactor from "../components/Reactor.svelte";
  import { app, get, set, setGuard, toast, toastError } from "../lib/store.svelte";
  import { leaveDraft } from "../lib/navigation";
  import { api, on, type Persona } from "../lib/api";

  let list = $state<Persona[]>([]);
  let active = $state("jarvis");
  let draft = $state<Persona | null>(null);
  let originalDraft = "";
  let busy = $state("");
  let unlisten: (() => void) | undefined;
  let destroyed = false;
  let editor = $state<HTMLDivElement>();

  function description(p: Persona) {
    const title=p.title || '';
    if (/^[\d,.\s]+ треугольник[а-яё]* · \d+ материал/i.test(title)) return "";
    return p.builtin ? uiText(title) : title;
  }

  async function openEditor(value: Persona) {
    if (!(await canLeave())) return;
    draft = value;
    originalDraft = JSON.stringify(value);
    await tick();
    const content = editor?.closest("main");
    if (content) content.scrollTo({ top: 0 });
    else editor?.scrollIntoView({ block: "start" });
    editor?.focus({ preventScroll: true });
  }

  async function refresh() {
    if (!app.core?.running) return;
    try {
      const data = await api.personas();
      list = data.personas;
      active = data.active;
    } catch (e) {
      toastError(e);
    }
  }

  onMount(async () => {
    setGuard(canLeave);
    await refresh();
    const dispose = await on<any>("core:event", (e) => {
      if (e.kind === "persona") refresh();
    });
    if (destroyed) dispose(); else unlisten = dispose;
  });
  onDestroy(() => { destroyed = true; setGuard(null); unlisten?.(); });

  async function canLeave() {
    if (busy) {
      toast("Дождитесь завершения текущего действия с персонажем");
      return false;
    }
    return leaveDraft({
      busy: false,
      dirty: !!draft && JSON.stringify($state.snapshot(draft)) !== originalDraft,
      ask: () => askDialog({ title: "Сохранить персонажа?", text: "Есть несохранённые изменения внешности, голоса или характера.",
        ok: "Сохранить", extra: "Не сохранять", cancel: "Продолжить редактирование" }),
      save,
      discard: () => { draft = null; },
    });
  }

  async function closeEditor() {
    if (await canLeave()) draft = null;
  }

  async function choose(p: Persona) {
    busy = "switch:" + p.id;
    try {
      await api.persona(p.id);
      active = p.id;
      toast(`Теперь ${p.name}`, "success");
    } catch (e) {
      toastError(e);
    } finally {
      busy = "";
    }
  }

  function edit(p: Persona, copy = false) {
    const clone: Persona = JSON.parse(JSON.stringify(p));
    if (copy || p.builtin) {
      // Встроенный персонаж правится копией: оригинал остаётся как был.
      clone.id = uniqueId(p.id);
      if (copy) clone.name = p.name + " 2";
    }
    clone.voice ??= {};
    clone.avatar ??= { type: "hud" };
    void openEditor(clone);
  }

  function uniqueId(base: string) {
    let n = 2;
    while (list.some((p) => p.id === `${base}-${n}`)) n++;
    return `${base}-${n}`;
  }

  function create() {
    void openEditor({
      id: uniqueId("custom"), name: "", title: "", address: "хозяин", gender: "f", aliases: [],
      system: "", wake_reply: "Да?", switch_reply: "", voice: { silero: "xenia", piper: "irina", pitch: 1.0 },
      avatar: { type: "hud" },
    });
  }

  async function sample(kind: "record" | "file") {
    if (!draft) return;
    const editing = draft;
    busy = "voice";
    try {
      let result;
      if (kind === "record") {
        toast("Говорите 10 секунд…");
        result = await api.voiceRecord(10, "persona");
      } else {
        const path = await openFile({ multiple: false, filters: [{ name: "Аудио", extensions: ["wav", "mp3", "flac", "ogg"] }] });
        if (!path) return;
        result = await api.voiceImport(path as string, "persona");
      }
      if (draft !== editing) return;
      draft.voice = { ...draft.voice, reference: result.path, reference_text: result.text };
      toast(`Образец ${result.seconds} с — проверьте расшифровку`, "success");
    } catch (e) {
      toastError(e);
    } finally {
      busy = "";
    }
  }

  async function pickModel(addLook = false) {
    if (!draft) return;
    try {
      const path = await openFile({ multiple: false, filters: [{ name: "Модель VRM", extensions: ["vrm"] }] });
      if (path) {
        if (addLook) {
          draft.appearances ??= [];
          if (!draft.appearances.length && draft.avatar?.model) {
            draft.appearances.push({ id: "original", name: "Основной", model: draft.avatar.model, preview: draft.avatar.preview });
          }
          const id = `look-${Date.now()}`;
          draft.appearances.push({ id, name: fileName(path as string)?.replace(/\.vrm$/i, "") || "Новый облик", model: path as string });
          draft.appearance = id;
        } else {
          const look = draft.appearances?.find(s => s.id === draft?.appearance);
          if (look) { look.model = path as string; delete look.preview; }
        }
        draft.avatar = { ...draft.avatar, type: "vrm", model: path as string, preview: undefined };
      }
    } catch (e) { toastError(e); }
  }

  async function pickAnimation() {
    if (!draft) return;
    try {
      const path = await openFile({ multiple: false, filters: [{ name: "Анимация VRM", extensions: ["vrma"] }] });
      if (!path) return;
      draft.animations ??= [];
      let n = draft.animations.length + 1;
      while (draft.animations.some(a => a.id === `motion-${n}`)) n++;
      draft.animations.push({ id: `motion-${n}`, name: `Движение ${n}`, file: path as string,
        phrases: [`покажи движение ${n}`], loop: false });
    } catch (e) { toastError(e); }
  }

  async function windowOption(key: string, value: boolean) {
    try {
      await api.avatarOptions({ [key]: value });
      set(`ui.avatar.${key}`, value, false);     // уже применено на лету — перезапуск не нужен
    } catch (e) { toastError(e); }
  }

  async function save(): Promise<boolean> {
    if (!draft || busy) return false;
    if (!draft.name.trim()) { toastError("Дайте персонажу имя"); return false; }
    busy = "save";
    try {
      const body = { ...draft, aliases: (draft.aliases ?? []).filter(Boolean) };
      await api.personaSave(body);
      toast("Персонаж сохранён", "success");
      draft = null;
      await refresh();
      return true;
    } catch (e) {
      toastError(e);
      return false;
    } finally {
      busy = "";
    }
  }

  async function remove(p: Persona) {
    if (!confirm(uiText(`Удалить персонажа «${p.name}»? Его голос и модель тоже удалятся.`))) return;
    try {
      await api.personaDelete(p.id);
      await refresh();
    } catch (e) {
      toastError(e);
    }
  }

  const fileName = (path?: string) => (path ? path.split(/[\\/]/).pop() : "");
  const sileroVoices = ["xenia", "kseniya", "baya", "aidar", "eugene"];
  const piperVoices = [{ value: "irina", label: "Ирина" }, { value: "ruslan", label: "Руслан" }, { value: "dmitri", label: "Дмитрий" }, { value: "denis", label: "Денис" }];

  async function exportPersona(p: Persona) {
    const path = await saveFile({ defaultPath: `${p.name}.jarvis-persona.zip`, filters: [{ name: "Пакет персонажа", extensions: ["zip"] }] });
    if (!path) return;
    let includeVoice = false;
    if (p.voice?.reference) {
      const choice = await askDialog({ title: "Включить образец голоса?", text: "Образец голоса позволяет клонировать этот голос. Включайте, только если у вас есть права на него и вы доверяете получателю.", ok: "Включить голос", extra: "Без голоса", cancel: "Отмена" });
      if (choice === "cancel") return;
      includeVoice = choice === "ok";
    }
    busy = "export";
    try {
      const r = await invoke<{ path: string; files: number; notes: string[] }>("core_post", { path: "/api/persona/export", body: { id: p.id, path, include_voice: includeVoice } });
      toast(`Пакет сохранён (${r.files} файлов). Ключи, память и личные пути не включены`, "success");
      for (const n of r.notes) toast(n, "info");
    } catch (e) { toastError(e); }
    finally { busy = ""; }
  }
  async function importPersona() {
    const path = await openFile({ multiple: false, filters: [{ name: "Пакет персонажа", extensions: ["zip"] }] });
    if (typeof path !== "string") return;
    busy = "import";
    try {
      const r = await invoke<{ id: string; name: string; voice_included: boolean; license: string }>("core_post", { path: "/api/persona/import", body: { path } });
      toast(`«${r.name}» добавлен${r.license ? ` · лицензия: ${r.license}` : ""}`, "success");
      if (!r.voice_included) toast("Голос по образцу не входил в пакет — пока звучит запасной голос", "info");
      await refresh();
    } catch (e) { toastError(e); }
    finally { busy = ""; }
  }
</script>

{#if !draft}
<h1>{uiText("Персонаж")}</h1>
<p class="muted lead">{uiText("Выберите персонажа: его характер, голос и облик меняются вместе.")}</p>

{#if !app.core?.running}
  <div class="card muted">{uiText("Включите Джарвиса, чтобы выбрать персонажа.")}</div>
{:else}
  <div class="grid">
    {#each list as p (p.id)}
      <div class="card persona {p.id === active ? 'on' : ''}">
        {#if p.avatar?.type === "vrm"}<AvatarPortrait path={p.avatar.preview} name={p.name} />
        {:else}<div class="reactor-portrait" role="img" aria-label={uiText("Реактор " + String(p.name))}><Reactor size={150} animated={false} /></div>{/if}
        <div class="head">
          <span class="badge">{uiText(p.avatar?.type === "vrm" ? "3D" : "HUD")}</span>
          <h3>{p.builtin ? uiText(p.name) : p.name}</h3>
          {#if p.id === active}<span class="chip ok"><Check size={12} />{uiText(" сейчас")}</span>{/if}
        </div>
        {#if description(p)}<p class="dim">{description(p)}</p>{/if}
        <p class="dim small">{uiText("Обращение:")} <q>{p.builtin ? uiText(p.address || "сэр") : (p.address || uiText("сэр"))}</q>
          {#if locale.language === "ru"} · {uiText("Смена персонажа:")} <q data-i18n="off">{(p.builtin && p.switch_hint) || `Переключись на «${p.name}»`}</q>{/if}
        </p>
        <div class="buttons">
          <button class="btn primary" disabled={p.id === active || busy !== ""} onclick={() => choose(p)}>
            <Sparkles size={14} /> {uiText(busy === "switch:" + p.id ? "Превращаюсь…" : "Выбрать")}
          </button>
          <button class="btn" disabled={busy !== ""} title={uiText("Изменить")} onclick={() => edit(p)}><Pencil size={14} /></button>
          <button class="btn" disabled={busy !== ""} title={uiText("Сделать копию")} onclick={() => edit(p, true)}><Copy size={14} /></button>
          <button class="btn" disabled={busy !== ""} title={uiText("Экспорт в пакет")} aria-label={uiText("Экспорт «" + String(p.name) + "» в пакет")} onclick={() => exportPersona(p)}><Download size={14} /></button>
          {#if !p.builtin}<button class="btn" disabled={busy !== ""} title={uiText("Удалить")} aria-label={uiText("Удалить «" + String(p.name) + "»")} onclick={() => remove(p)}><Trash2 size={14} /></button>{/if}
        </div>
        {#if p.voice?.status}<p class="voice-status"><CircleAlert size={13} /> {uiText(p.voice.status)}</p>{/if}
      </div>
    {/each}
    <div class="add-col">
      <button class="card persona add" disabled={busy !== ""} onclick={create}>{uiText("+ Свой персонаж")}</button>
      <button class="btn" disabled={busy !== ""} onclick={importPersona}><Upload size={14} /> {uiText(busy === "import" ? "Проверяю пакет…" : "Импорт из пакета")}</button>
    </div>
  </div>

  <div class="card">
    <div class="caps">{uiText("Окно персонажа")}</div>
    <Setting title={uiText("Всегда на экране")} hint={uiText("Выключено — модель появляется, когда вы зовёте ассистента, и прячется после разговора. Окно можно перетащить мышью")}>
      <Toggle checked={get("ui.avatar.always", false)} onchange={(v) => windowOption("always", v)} />
    </Setting>
    <Setting title={uiText("Клики проходят насквозь")} hint={uiText("Можно нажимать на окна под персонажем. Чтобы перетаскивать персонажа, выключите этот переключатель. Прозрачная область всегда пропускает клики")}>
      <Toggle checked={get("ui.avatar.click_through", false)} onchange={(v) => windowOption("click_through", v)} />
    </Setting>
    <Setting title={uiText("Прятать в игре и полноэкранных приложениях")} hint={uiText("Разговор продолжится. После выхода из игры персонаж вернётся, если ещё должен быть виден")}>
      <Toggle checked={get("ui.avatar.hide_busy", true)} onchange={(v) => windowOption("hide_busy", v)} />
    </Setting>
  </div>

{/if}
{/if}

{#if draft}
  <button class="btn" onclick={closeEditor}>{uiText("← К персонажам")}</button>
  <div class="card editor" bind:this={editor} tabindex="-1" role="region" aria-label={uiText("Редактор персонажа")}>
    <div class="caps">{uiText(list.some((p) => p.id === draft?.id && !p.builtin) ? "Изменить" : "Новый персонаж")} · {draft.name || uiText("без имени")}</div>
    {#if draft.builtin}<p class="dim small">{uiText("Изменения встроенного персонажа сохранятся отдельной копией.")}</p>{/if}
    <Setting title={uiText("Имя")}><input type="text" bind:value={draft.name} placeholder={uiText("Юки")} /></Setting>
    <Setting title={uiText("Названия для голосового переключения")} hint={uiText("Перечислите названия через запятую, например «Юки, помощница». Скажите «Переключись на Юки».")} wide>
      <input type="text" value={(draft.aliases ?? []).join(", ")} onchange={(e) => draft && (draft.aliases = e.currentTarget.value.split(",").map(s => s.trim()).filter(Boolean))} />
    </Setting>
    <Setting title={uiText("Имена для вызова")} hint={uiText("Русские имена через запятую, например «Пиппа, Пипа». Пустое поле — имя персонажа автоматически. После сохранения и выбора персонажа применяется без перезапуска. Язык интерфейса не меняет язык распознавания")} wide>
      <input type="text" value={(draft.wake_words ?? []).join(', ')} placeholder={uiText("Автоматически по имени персонажа")}
        onchange={e => draft && (draft.wake_words=e.currentTarget.value.split(',').map(s=>s.trim()).filter(Boolean))} />
    </Setting>
    <Setting title={uiText("Описание")} hint={uiText("Коротко — для карточки")}><input type="text" style="width:320px" bind:value={draft.title} /></Setting>
    <Setting title={uiText("Как обращается к вам")} hint={uiText("Заменит «сэр» в готовых фразах: «Готово, хозяин»")}>
      <input type="text" bind:value={draft.address} placeholder={uiText("хозяин")} />
    </Setting>
    <Setting title={uiText("Говорит о себе")} hint={uiText("Женский род: «запомнила», «нашла»")}>
      <Segmented value={draft.gender ?? "m"} options={[{ value: "m", label: "Он" }, { value: "f", label: "Она" }]} onchange={(v) => draft && (draft.gender = v)} />
    </Setting>
    <Setting title={uiText("Характер")} hint={uiText("Кто это, как говорит, как обращается. Модель будет держаться этой роли")} wide>
      <textarea rows="6" bind:value={draft.system} placeholder={uiText("Ты Юки — милая и заботливая помощница. О себе говоришь в женском роде…")}></textarea>
    </Setting>
    <Setting title={uiText("Ответ на обращение")}><input type="text" bind:value={draft.wake_reply} placeholder={uiText("Да, хозяин?")} /></Setting>
    <Setting title={uiText("Фраза при превращении")}><input type="text" style="width:320px" bind:value={draft.switch_reply} placeholder={uiText("Теперь я Юки!")} /></Setting>

    <div class="caps sub">{uiText("Голос")}</div>
    <Setting title={uiText("Образец голоса")} hint={uiText(draft.voice?.reference ? `${fileName(draft.voice.reference)} — клон говорит этим голосом (нужна видеокарта NVIDIA). Используйте только голос, на который у вас есть права` : "5–15 секунд чистой речи. Без образца — запасной голос ниже")}>
      <button class="btn" disabled={busy !== ""} onclick={() => sample("record")}><Mic size={14} /> {uiText(busy === "voice" ? "Слушаю…" : "Записать")}</button>
      <button class="btn" disabled={busy !== ""} onclick={() => sample("file")}><FileAudio size={14} />{uiText(" Из файла")}</button>
    </Setting>
    {#if draft.voice?.reference}
      <Setting title={uiText("Что сказано в образце")} hint={uiText("Точная расшифровка — без неё клон звучит хуже")} wide>
        <input type="text" bind:value={draft.voice.reference_text} />
      </Setting>
    {/if}
    <Setting title={uiText("Запасной голос")} hint={uiText("Без видеокарты: Silero (если установлен) или Piper")}>
      <select value={draft.voice?.silero ?? "xenia"} onchange={(e) => draft && (draft.voice = { ...draft.voice, silero: e.currentTarget.value })}>
        {#each sileroVoices as v}<option value={v}>{v}</option>{/each}
      </select>
      <select value={draft.voice?.piper ?? "irina"} onchange={(e) => draft && (draft.voice = { ...draft.voice, piper: e.currentTarget.value })}>
        {#each piperVoices as v}<option value={v.value}>{uiText(v.label)}</option>{/each}
      </select>
    </Setting>
    <Setting title={uiText("Высота запасного голоса")} hint={uiText("Выше — моложе и «анимешнее»; темп Piper не меняется")}>
      <Range value={Math.round((draft.voice?.pitch ?? 1) * 100)} min={85} max={135} step={1} format={(v) => (v / 100).toFixed(2) + "×"}
             onchange={(v) => draft && (draft.voice = { ...draft.voice, pitch: v / 100 })} />
    </Setting>
    <Setting title={uiText("Эффект голоса")} hint={uiText("Робот — металлический голос автоматона поверх любого голоса: клона, Piper или Silero")}>
      <Segmented value={draft.voice?.effect ?? ""} options={[{ value: "", label: "Обычный" }, { value: "robot", label: "Робот" }]}
                 onchange={(v) => draft && (draft.voice = { ...draft.voice, effect: v })} />
    </Setting>

    <div class="caps sub">{uiText("Облик")}</div>
    {#if draft.appearances?.length}
      <Setting title={uiText("Вариант внешности")} hint={uiText("Меняется только облик этого персонажа. Голос, характер и команды остаются общими")}>
        <select bind:value={draft.appearance}>
          {#each draft.appearances as look}<option value={look.id}>{look.name}</option>{/each}
        </select>
      </Setting>
    {/if}
    <Setting title={uiText("Вместо окна Джарвиса")} hint={draft.avatar?.type === "vrm" ? (draft.avatar?.model ? fileName(draft.avatar.model) : uiText("Выберите модель .vrm")) : uiText("Реактор Джарвиса")}>
      <Segmented value={draft.avatar?.type ?? "hud"} options={[{ value: "hud", label: "Реактор" }, { value: "vrm", label: "3D-модель" }]}
                 onchange={(v) => draft && (draft.avatar = { ...draft.avatar, type: v })} />
      {#if draft.avatar?.type === "vrm"}<button class="btn" onclick={() => pickModel()}><Box size={14} />{uiText(" Модель .vrm")}</button>
        <button class="btn" onclick={() => pickModel(true)}>{uiText("+ Облик")}</button>{/if}
    </Setting>
    {#if draft.avatar?.type === "vrm"}
      <Setting title={uiText("Размер персонажа")} hint={uiText("От 20 до 400%. Голосом: «размер 200%», «стань больше в два раза». Жесты не меняют размер. Очень крупный персонаж может не помещаться на небольшом экране")}>
        <Range value={Math.round((draft.avatar.scale ?? 1) * 100)} min={20} max={400} step={5} format={v => `${v}%`} onchange={v => draft?.avatar && (draft.avatar.scale = v / 100)} />
      </Setting>
      <Setting title={uiText("Кадр персонажа")} hint={uiText("Выберите, какая часть модели видна в окне на рабочем столе.")}>
        <Segmented value={draft.avatar.desktop_framing ?? "full"} options={[{ value: "full", label: "В полный рост" }, { value: "waist", label: "По пояс" }, { value: "portrait", label: "Портрет" }]}
          onchange={(value) => draft?.avatar && (draft.avatar.desktop_framing = value as "full" | "waist" | "portrait")} />
      </Setting>
      <Setting title={uiText("Движения в ожидании")} hint={uiText("Персонаж дышит, слегка меняет позу и иногда оглядывается, пока ждёт. Можно отключить для спокойного рабочего стола.")}>
        <Toggle checked={draft.avatar.idle_motion ?? true} onchange={(value) => draft?.avatar && (draft.avatar.idle_motion = value)} />
      </Setting>
      <Setting title={uiText("Микродвижения")} hint={uiText("Дыхание и небольшие движения головы. Готовые жесты, походка, танец и импортированные анимации сохраняют движения своего файла")}>
        <Range value={Math.round((draft.avatar.motion ?? 1) * 100)} min={0} max={150} step={10} format={v => `${v}%`} onchange={v => draft?.avatar && (draft.avatar.motion = v / 100)} />
      </Setting>
      <Setting title={uiText("Походка")} hint={uiText("Готовая анимация всего тела. Скорость шага подстраивается под рост персонажа и расстояние; волосы и одежда двигаются, если их физика настроена в модели")}>
        <Segmented value={draft.avatar.walk ?? "natural"} options={[{ value: "natural", label: "Обычная" }, { value: "formal", label: "Сдержанная" }]} onchange={v => draft?.avatar && (draft.avatar.walk = v as "natural" | "formal")} />
      </Setting>
      <Setting title={uiText("Плавность")} hint={uiText("20 кадров — экономия ресурсов. 30 — обычный режим. 60 — плавнее, но выше нагрузка. Скрытое окно не рисуется")}>
        <Segmented value={String(draft.avatar.fps ?? 30)} options={[{ value: "20", label: "20 FPS" }, { value: "30", label: "30 FPS" }, { value: "60", label: "60 FPS" }]} onchange={v => draft?.avatar && (draft.avatar.fps = Number(v))} />
      </Setting>
      <Setting title={uiText("Темп танца")} hint={uiText("Запасной темп, если синхронизация с музыкой выключена или недоступна")}>
        <Range value={draft.avatar.bpm ?? 120} min={50} max={200} step={1} format={v => `${v} BPM`} onchange={v => draft?.avatar && (draft.avatar.bpm = v)} />
      </Setting>
      <Setting title={uiText("Субтитры")} hint={uiText("Показывать ответ рядом с моделью")}><Toggle checked={draft.avatar.subtitles ?? true} onchange={v => draft?.avatar && (draft.avatar.subtitles = v)} /></Setting>
      <Setting title={uiText("Автор модели и условия использования")} hint={uiText("Ссылка на страницу автора или текст лицензии")} wide><input type="text" bind:value={draft.avatar.credit} /></Setting>
      <CompanionEditor persona={draft} />
      <div class="caps sub">{uiText("Свои движения и фразы")}</div>
      <p class="dim small">{uiText("Импортируйте .vrma, задайте фразу — и произнесите её после обращения. Например: «Джарвис, покажи сердечко».")}</p>
      {#each draft.animations ?? [] as animation, index (animation.id)}
        <div class="animation-row">
          <Setting title={uiText("Название")} hint={fileName(animation.file)}><input type="text" bind:value={animation.name} /></Setting>
          <Setting title={uiText("Голосовые фразы")} hint={uiText("Через запятую. Без слова «Джарвис»")} wide><input type="text" value={animation.phrases.join(", ")} onchange={e => animation.phrases = e.currentTarget.value.split(",").map(s => s.trim()).filter(Boolean)} /></Setting>
          <Setting title={uiText("Повторять")} hint={uiText("Будет играть до команды «останови анимацию»")}><Toggle checked={animation.loop ?? false} onchange={v => animation.loop = v} />
            <button class="btn" onclick={() => draft?.animations?.splice(index, 1)}>{uiText("Убрать из персонажа")}</button></Setting>
        </div>
      {/each}
      <button class="btn" disabled={(draft.animations?.length ?? 0) >= 256} onclick={pickAnimation}>{uiText("+ Импорт .vrma")}</button>
    {/if}

    <div class="buttons end">
      <button class="btn" onclick={closeEditor}>{uiText("Отмена")}</button>
      <button class="btn primary" disabled={busy !== ""} onclick={save}>{uiText(busy === "save" ? "Сохраняю…" : "Сохранить")}</button>
    </div>
  </div>
{/if}

<style>
  .reactor-portrait { height: 190px; display: grid; place-items: center; border-radius: 14px; margin-bottom: 6px; overflow: hidden; background: radial-gradient(ellipse at 50% 50%, #227a9b38, #091825b3 63%, #08101c); border: 1px solid #8bddf21a; }
  .add-col { display: flex; flex-direction: column; gap: 8px; }
  .add-col .add { flex: 1; }
  .voice-status { display: flex; gap: 6px; align-items: center; font-size: 12px; color: var(--warn); margin-top: 6px; }
  .buttons { flex-wrap: wrap; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; margin-bottom: 14px; }
  .persona { min-width: 0; display: flex; flex-direction: column; gap: 6px; }
  .persona.on { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent) inset; }
  .persona.add { align-items: center; justify-content: center; min-height: 140px; cursor: pointer; color: var(--text-2);
                 border-style: dashed; font: inherit; background: transparent; }
  .persona.add:hover { color: var(--text); background: var(--hover); }
  .head { display: flex; align-items: center; gap: 8px; }
  .head h3 { margin: 0; flex: 1; min-width: 0; overflow-wrap: anywhere; }
  .badge { font-family: var(--mono); font-size: 10.5px; padding: 1px 6px; border-radius: 6px; border: 1px solid var(--line-2); color: var(--accent-2); }
  .small { font-size: 12px; }
  .buttons { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; margin-top: auto; padding-top: 6px; }
  .persona .buttons .primary { grid-column: 1 / -1; }
  .buttons button { min-width: 0; padding-inline: 5px; }
  .buttons.end { display: flex; flex-wrap: wrap; justify-content: flex-end; margin-top: 14px; }
  .editor { margin-top: 14px; }
  .sub { margin-top: 16px; }
  textarea { width: 100%; resize: vertical; font: inherit; }
  .animation-row { margin: 12px 0; padding: 10px; border: 1px solid var(--line-2); border-radius: 12px; }
</style>
