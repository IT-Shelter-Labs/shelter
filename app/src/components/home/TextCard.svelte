<script lang="ts">
  import { t as uiText } from "../../lib/i18n.svelte";

  // Быстрые действия с текстом: источник виден, результат — до замены, замена — только в то же окно.
  import { onMount } from "svelte";
  import { ClipboardPaste, Type, Wand2, Languages, Minimize2, BookOpen, Reply, Volume2, Replace, Copy, Square, LoaderCircle, CircleAlert, Cloud, HardDrive } from "@lucide/svelte";
  import { invoke } from "@tauri-apps/api/core";
  import { app, toast, toastError } from "../../lib/store.svelte";

  type State = { id: string; source: string; window_title: string; text: string; result: string; op: string; status: string; error: string; model: string; local: boolean };
  let st = $state<State | null>(null);
  let manualText = $state("");
  let typing = $state(false);
  let busy = $state(false);
  const icons: Record<string, any> = { fix: Wand2, translate: Languages, shorten: Minimize2, explain: BookOpen, reply: Reply, read: Volume2 };
  const labels: Record<string, string> = { fix: "Исправить", translate: "Перевести", shorten: "Сократить", explain: "Объяснить", reply: "Ответ", read: "Вслух" };

  async function call(body: Record<string, unknown>) {
    busy = true;
    try { st = await invoke<State>("core_post", { path: "/api/textops", body }); return true; }
    catch (e) { toastError(e); return false; }
    finally { busy = false; }
  }
  onMount(() => { if (app.status) call({ op: "state" }); });
  // Ядро сообщает о ходе работы (голосом или горячей клавишей) — подтянуть состояние.
  $effect(() => {
    const last = [...app.feed].reverse().find((e) => e.kind === "textops");
    if (last && app.status && (!st || (last as any).status !== st.status || (last as any).id !== st.id)) call({ op: "state" });
  });
  const source = $derived(!st?.text ? "" : st.source === "selection" ? `Выделение в «${st.window_title || "программе"}»` : st.source === "clipboard" ? "Буфер обмена" : "Вставлено вручную");
</script>

{#if !app.status}
  <p class="line dim">{uiText("Включите Джарвиса. Горячая клавиша ")}<kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>T</kbd>{uiText(" берёт выделенный текст из любой программы.")}</p>
{:else}
  <div class="sources">
    <button class="btn sm" disabled={busy} onclick={() => call({ op: "clipboard" })}><ClipboardPaste size={13} />{uiText(" Из буфера")}</button>
    <button class="btn sm" disabled={busy} onclick={() => (typing = !typing)} aria-expanded={typing}><Type size={13} />{uiText(" Вставить текст")}</button>
    <span class="dim small">{uiText("или выделите в любой программе и нажмите ")}<kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>T</kbd>{uiText(" · голосом: «исправь выделенное»")}</span>
  </div>
  {#if typing}
    <form class="manual" onsubmit={(e) => { e.preventDefault(); call({ op: "manual", text: manualText }).then((ok) => { if (ok) typing = false; }); }}>
      <textarea rows="3" bind:value={manualText} placeholder={uiText("Вставьте или напишите текст")} aria-label={uiText("Текст для обработки")}></textarea>
      <button class="btn sm" disabled={!manualText.trim()}>{uiText("Взять этот текст")}</button>
    </form>
  {/if}
  {#if st?.text}
    <p class="src small"><b>{uiText("Источник:")}</b> {uiText(source)} · {uiText(st.text.length)}{uiText(" знаков")}</p>
    <blockquote class="selectable">{st.text.length > 300 ? st.text.slice(0, 300) + "…" : st.text}</blockquote>
    <div class="ops">
      {#each Object.keys(labels) as op}
        {@const Icon = icons[op]}
        <button class="btn sm" class:primary={st.op === op && st.status === "ready"} disabled={busy || st.status === "running"} onclick={() => call({ op: "run", action: op })}><Icon size={13} /> {uiText(labels[op])}</button>
      {/each}
    </div>
    {#if st.status === "running"}
      <div class="notice"><LoaderCircle size={15} class="spin" /> <span>{uiText("Обрабатываю")}{uiText(st.model ? ` моделью ${st.model}` : "")}… </span>
        <button class="btn ghost sm" onclick={() => call({ op: "cancel" })}><Square size={12} />{uiText(" Отмена")}</button></div>
    {:else if st.status === "failed" || st.status === "cancelled"}
      <div class="notice bad"><CircleAlert size={15} /> {uiText(st.error)}</div>
    {/if}
    {#if st.op && st.op !== "read"}
      <p class="privacy small dim">{#if st.local}<HardDrive size={12} />{uiText(" Текст обработан на этом компьютере")}{:else}<Cloud size={12} />{uiText(" Текст отправлен внешнему сервису модели «")}{uiText(st.model)}»{/if}</p>
    {/if}
    {#if st.result}
      <div class="result">
        <span class="caps">{uiText("Результат — пока ничего не заменено")}</span>
        <p class="selectable">{st.result}</p>
        <div class="ops">
          {#if st.source === "selection" && ["fix", "translate", "shorten", "reply"].includes(st.op)}
            <button class="btn primary sm" disabled={busy || st.status === "applied"} onclick={() => call({ op: "apply" }).then((ok) => ok && toast("Заменено в исходном окне", "success"))}>
              <Replace size={13} /> {uiText(st.status === "applied" ? "Заменено" : `Заменить в «${st.window_title || "окне"}»`)}</button>
          {/if}
          <button class="btn sm" onclick={() => call({ op: "copy" }).then((ok) => ok && toast("Скопировано"))}><Copy size={13} />{uiText(" Скопировать")}</button>
        </div>
        {#if st.status === "applied"}<p class="dim small">{uiText("Исходный текст сохранён выше — его можно скопировать обратно.")}</p>{/if}
      </div>
    {/if}
  {/if}
{/if}

<style>
  .sources, .ops { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .manual { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; align-items: flex-start; }
  .manual textarea { width: 100%; }
  .src { margin: 10px 0 4px; }
  blockquote { margin: 0 0 8px; padding: 8px 12px; border-left: 3px solid var(--line-2); color: var(--text-2); font-size: 13px; white-space: pre-wrap; overflow-wrap: anywhere; }
  .result { margin-top: 10px; padding: 10px 12px; border-radius: 10px; background: var(--accent-soft); border: 1px solid var(--line-2); }
  .result p { margin: 6px 0 10px; white-space: pre-wrap; overflow-wrap: anywhere; }
  .privacy { display: flex; gap: 5px; align-items: center; margin-top: 6px; }
  .notice { margin-top: 8px; }
  .small { font-size: 12.5px; }
  .line { font-size: 13px; }
</style>
