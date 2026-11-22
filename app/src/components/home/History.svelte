<script lang="ts">
  import { t as uiText, locale } from "../../lib/i18n.svelte";

  // «Услышал → понял → сделал»: только итоги, без внутренних рассуждений модели.
  import { Ear, Lightbulb, CircleCheck, CircleAlert, CircleSlash, MessageSquare, Bell, Zap } from "@lucide/svelte";
  import { app } from "../../lib/store.svelte";
  import type { FeedEvent } from "../../lib/api";

  type Done = { text: string; ok: boolean | null };
  type Group = { time: number; heard: string; understood: string; done: Done[]; reply: string; error: string; source: string };

  const groups = $derived.by<Group[]>(() => {
    const out: Group[] = [];
    let current = null as Group | null;
    const open = (time: number, heard = "", source = "") => {
      current = { time, heard, understood: "", done: [], reply: "", error: "", source };
      out.push(current);
      return current;
    };
    const seen = new Set<string>();
    for (const e of app.feed as (FeedEvent & Record<string, any>)[]) {
      if (e.kind === "typed" || e.kind === "query") {
        const key = e.text ?? "";
        if (e.kind === "query" && seen.has(key)) { seen.delete(key); continue; }   // напечатанный приходит дважды
        if (e.kind === "typed") seen.add(key);
        open(e.time, e.text ?? "", e.kind === "typed" ? "текстом" : "голосом");
      } else if (e.kind === "command") {
        const g: Group = current && e.time - current.time < 3 && !current.understood ? current : open(e.time, "", "голосом");
        g.understood = `Команда «${e.text}»`;
      } else if (e.kind === "scenario" && e.status === "running" && !e.step) {
        const g: Group = current && e.time - current.time < 3 ? current : open(e.time, "", e.source || "");
        if (!g.understood) g.understood = `Сценарий «${e.name}»`;
      } else if (e.kind === "scenario" && e.step && e.state !== "running" && current) {
        current.done.push({ text: uiText(e.label) + (e.detail ? ` — ${e.detail}` : ""), ok: e.state === "done" ? true : e.state === "failed" ? false : null });
      } else if (e.kind === "scenario" && !e.step && ["failed", "cancelled"].includes(e.status) && current) {
        current.error = e.status === "cancelled" ? "Остановлено" : e.error || "Не выполнено";
      } else if (e.kind === "tool" && current) {
        if (!current.understood) current.understood = "Действие по смыслу просьбы";
        current.done.push({ text: (e.label ?? e.name ?? "") + (e.arg ? ` · ${e.arg}` : ""), ok: e.ok ?? null });
      } else if (e.kind === "reply" && current) {
        current.reply = e.text ?? "";
        if (!current.understood) current.understood = e.fast ? "Быстрая команда" : "Ответ нейросети";
      } else if (e.kind === "error") {
        (current && e.time - current.time < 60 ? current : open(e.time)).error = e.text ?? "Ошибка";
      } else if (e.kind === "reminder") {
        open(e.time, "", "напоминание").understood = `Напоминание: ${e.text || "время вышло"}`;
      } else if (e.kind === "trigger") {
        open(e.time, "", "событие").understood = `${e.name}: ${e.text}`;
      }
    }
    return out.slice(-8).reverse();
  });
  const time = (t: number) => new Date(t * 1000).toLocaleTimeString((locale.language === "ru" ? "ru-RU" : "en-US"), { hour: "2-digit", minute: "2-digit" });
</script>

{#if !groups.length}
  <div class="empty">
    <Ear size={22} />
    <b>{uiText("Пока тихо")}</b>
    <span>{uiText("Здесь появится коротко: что Джарвис услышал, как понял и что сделал.")}</span>
  </div>
{:else}
  <ol class="history">
    {#each groups as g (g.time + g.heard + g.understood)}
      <li class:failed={!!g.error}>
        <span class="time mono">{uiText(time(g.time))}</span>
        <div class="flow">
          {#if g.heard}<p class="heard"><Ear size={13} /> <span>«{g.heard}»</span>{#if g.source}<small class="dim"> · {uiText(g.source)}</small>{/if}</p>{/if}
          {#if g.understood}<p class="understood">{#if g.source === "напоминание"}<Bell size={13} />{:else if g.source === "событие"}<Zap size={13} />{:else}<Lightbulb size={13} />{/if} {uiText(g.understood)}</p>{/if}
          {#each g.done as d}
            <p class="done">
              {#if d.ok === true}<CircleCheck size={13} color="var(--ok)" />{:else if d.ok === false}<CircleAlert size={13} color="var(--bad)" />{:else}<CircleSlash size={13} />{/if}
              {d.text}
            </p>
          {/each}
          {#if g.reply}<p class="reply"><MessageSquare size={13} /> <span>{g.reply.length > 220 ? g.reply.slice(0, 220) + "…" : g.reply}</span></p>{/if}
          {#if g.error}<p class="error"><CircleAlert size={13} /> {uiText(g.error)}</p>{/if}
        </div>
      </li>
    {/each}
  </ol>
{/if}

<style>
  .history {
    list-style: none;
    margin: 6px 0 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  li {
    display: grid;
    grid-template-columns: 44px 1fr;
    gap: 10px;
    padding: 9px 0;
    border-bottom: 1px solid var(--line);
  }
  li:last-child {
    border-bottom: none;
  }
  .time {
    font-size: 11.5px;
    color: var(--text-3);
    padding-top: 2px;
  }
  .flow {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
    user-select: text;
  }
  .flow p {
    display: flex;
    gap: 7px;
    align-items: baseline;
    font-size: 13px;
    line-height: 1.45;
    color: var(--text-2);
    overflow-wrap: anywhere;
  }
  .flow :global(svg) {
    flex: none;
    position: relative;
    top: 2px;
  }
  .heard {
    color: var(--text) !important;
    font-weight: 560;
  }
  .understood {
    color: var(--accent-2) !important;
  }
  .error {
    color: var(--bad) !important;
  }
</style>
