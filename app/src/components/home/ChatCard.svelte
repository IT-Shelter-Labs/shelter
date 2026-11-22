<script lang="ts">
  import { t as uiText, locale } from "../../lib/i18n.svelte";

  // Текстовый разговор — дополнение к голосу, а не главный экран.
  import { tick } from "svelte";
  import { Send, Volume2, FolderKanban } from "@lucide/svelte";
  import AssistantPanel from "../AssistantPanel.svelte";
  import { app, toastError } from "../../lib/store.svelte";
  import { api, type FeedEvent } from "../../lib/api";

  let text = $state("");
  let box: HTMLDivElement | undefined = $state();
  let context = $state(false);
  let last = "";

  const messages = $derived.by(() => {
    const saved: FeedEvent[] = (app.assistant?.messages ?? []).map((m) => ({ kind: m.role === "user" ? "query" : "reply", text: m.content, time: m.created }));
    const lastSaved = saved.at(-1)?.time ?? 0;
    const fresh = app.feed.filter((e) => ["typed", "query", "reply"].includes(e.kind) && e.time > lastSaved
      && (!app.assistant || !e.session_id || e.session_id === app.assistant.session_id));
    const out: FeedEvent[] = [];
    const typed = new Map<string, number>();
    for (const e of [...saved, ...fresh]) {
      if (e.kind === "typed") typed.set(e.text ?? "", (typed.get(e.text ?? "") ?? 0) + 1);
      else if (e.kind === "query" && (typed.get(e.text ?? "") ?? 0) > 0) { typed.set(e.text ?? "", typed.get(e.text ?? "")! - 1); continue; }
      out.push(e);
    }
    return out.slice(-40);
  });

  $effect(() => {
    const end = messages.at(-1);
    const key = end ? `${end.time}:${end.text?.length}` : "";
    if (key !== last) {
      last = key;
      tick().then(() => box?.scrollTo({ top: box.scrollHeight }));
    }
  });

  async function send() {
    const phrase = text.trim();
    if (!phrase) return;
    if (!app.core?.running) { toastError("Джарвис выключен — включите его кнопкой «Включить»."); return; }
    text = "";
    try { await api.ask(phrase, app.assistant?.session_id); }
    catch (e) { text = phrase; toastError(e); }      // не терять напечатанное при ошибке
  }
  const time = (t: number) => new Date(t * 1000).toLocaleTimeString((locale.language === "ru" ? "ru-RU" : "en-US"), { hour: "2-digit", minute: "2-digit" });
</script>

<div class="chat">
  <div class="messages selectable" bind:this={box} aria-live="polite">
    {#each messages as m (m.kind + m.time + (m.text?.length ?? 0))}
      <div class="msg {m.kind === 'reply' ? 'jarvis' : 'me'}">
        <div class="bubble">{m.text}</div>
        <span class="t">{uiText(time(m.time))}{#if m.kind === "reply"} · <button class="link" onclick={() => api.say(m.text ?? "").catch(toastError)}><Volume2 size={11} />{uiText(" зачитать")}</button>{/if}</span>
      </div>
    {:else}
      <p class="dim hint">{uiText("Напишите, если неудобно говорить. Ответ появится здесь и прозвучит голосом.")}</p>
    {/each}
  </div>
  <form class="input" onsubmit={(e) => { e.preventDefault(); send(); }}>
    <input type="text" placeholder={uiText("Написать Джарвису…")} aria-label={uiText("Сообщение Джарвису")} bind:value={text} />
    <button class="btn primary icon" type="submit" aria-label={uiText("Отправить")} disabled={!text.trim()}><Send size={15} /></button>
  </form>
  <button class="link ctx" onclick={() => (context = !context)} aria-expanded={context}><FolderKanban size={13} /> {uiText(context ? "Скрыть" : "Проект, разговоры и материалы")}</button>
  {#if context}<div class="fade-in"><AssistantPanel /></div>{/if}
</div>

<style>
  .chat { display: flex; flex-direction: column; gap: 10px; }
  .messages { max-height: 320px; min-height: 80px; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; padding-right: 4px; }
  .msg { display: flex; flex-direction: column; max-width: 84%; }
  .msg.me { align-self: flex-end; align-items: flex-end; }
  .bubble { padding: 8px 12px; border-radius: 14px; line-height: 1.45; white-space: pre-wrap; overflow-wrap: anywhere; }
  .me .bubble { background: var(--surface-3); border: 1px solid var(--line-2); border-bottom-right-radius: 4px; }
  .jarvis .bubble { background: var(--accent-soft); border: 1px solid var(--line-2); border-bottom-left-radius: 4px; }
  .t { font-size: 11px; color: var(--text-3); margin: 2px 6px 0; display: inline-flex; gap: 4px; align-items: center; }
  .t .link { font-size: 11px; display: inline-flex; gap: 3px; align-items: center; }
  .input { display: flex; gap: 8px; }
  .input input { flex: 1; }
  .hint { font-size: 13px; }
  .ctx { align-self: flex-start; display: inline-flex; gap: 5px; align-items: center; font-size: 12.5px; }
</style>
