<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { ImagePlus, Download } from "@lucide/svelte";
  import { app, get, set, toastError } from "../lib/store.svelte";
  import { t as uiText } from "../lib/i18n.svelte";
  import Setting from "./Setting.svelte";

  const { mode }: { mode: "speech" | "image" } = $props();
  const speech = $derived(mode === "speech");
  const key = $derived(speech ? "tts.cloud" : "image_generation");
  const connection = $derived(get<string>(key + ".connection", ""));
  const providers = $derived(Object.entries(get<Record<string, { provider: string; name: string }>>("llm.connections", {}) ?? {})
    .filter(([, service]) => service.provider === "openai"));
  let prompt = $state("");
  let generating = $state(false);
  let result = $state<{ file: string; png: string } | null>(null);

  function choose(id: string) {
    set(key, { connection: id, model: "", ...(speech ? { voice: "", protocol: "compatible" } : {}) });
  }
  async function generate() {
    generating = true;
    try {
      result = await invoke("core_post", { path: "/api/image/generate", body: { prompt: prompt.trim() } });
    } catch (error) {
      toastError(error);
    } finally { generating = false; }
  }
</script>

{#snippet fields()}
  <Setting title={uiText(speech ? "Провайдер озвучки" : "Провайдер изображений")}
    hint={uiText(speech ? "Сервис получает только текст для озвучки. При сбое используется локальный голос."
      : "Сервис получает только описание изображения. Генерация может расходовать баланс API.")}>
    <select value={connection} onchange={(e) => choose(e.currentTarget.value)}>
      <option value="">{uiText("Выберите подключение")}</option>
      {#each providers as [id, service]}<option value={id}>{service.name}</option>{/each}
    </select>
  </Setting>
  {#if !providers.length}<p class="dim">{uiText("Добавьте OpenAI-совместимое подключение в разделе «Модели и разум».")}</p>{/if}
  {#if connection}
    <Setting title={uiText("ID модели")} hint={uiText("Введите идентификатор из панели провайдера.")}>
      <input value={get(key + ".model", "")} maxlength="160" onchange={e => set(key + ".model", e.currentTarget.value.trim())} />
    </Setting>
    {#if speech}
      <Setting title={uiText("API озвучки")} hint={uiText("Для Alibaba Qwen Audio укажите адрес рабочей области в сохранённом подключении.")}>
        <select value={get(key + ".protocol", "compatible")} onchange={e => set(key + ".protocol", e.currentTarget.value)}>
          <option value="compatible">OpenAI-compatible</option><option value="alibaba">Alibaba Qwen Audio</option>
        </select>
      </Setting>
      <Setting title={uiText("ID голоса")} hint={uiText("Имя системного или своего голоса из каталога сервиса.")}>
        <input value={get(key + ".voice", "")} maxlength="160" onchange={e => set(key + ".voice", e.currentTarget.value.trim())} />
      </Setting>
    {/if}
  {/if}
{/snippet}

{#if speech}
  {@render fields()}
{:else}
  <section class="card">
    <h3>{uiText("Создание изображений")}</h3>
    <p class="dim">{uiText("Поддерживаются сервисы с OpenAI-совместимым API изображений и ответом PNG/Base64.")}</p>
    {@render fields()}
    {#if connection}
      <div class="generator">
        <textarea bind:value={prompt} maxlength="2000" rows="3" placeholder={uiText("Опишите изображение")} aria-label={uiText("Описание изображения")}></textarea>
        <button class="btn primary" onclick={generate} disabled={generating || !prompt.trim() || !app.status || app.dirty}>
          <ImagePlus size={16} />{uiText(generating ? "Создаю изображение…" : "Создать изображение")}
        </button>
        {#if app.dirty}<p class="dim">{uiText("Примените настройки перед генерацией.")}</p>{/if}
        {#if result}
          <img src={"data:image/png;base64," + result.png} alt={uiText("Сгенерированное изображение")} />
          <a class="btn" href={"data:image/png;base64," + result.png} download={result.file.split(/[\\/]/).at(-1)}><Download size={15} />{uiText("Скачать PNG")}</a>
          <p class="mono dim">{result.file}</p>
        {/if}
      </div>
    {/if}
  </section>
{/if}

<style>
  .generator { display: grid; justify-items: start; gap: 12px; margin-top: 16px; }
  textarea { width: 100%; }
  input, select { max-width: 100%; }
  img { max-width: min(100%, 520px); max-height: 480px; border-radius: 12px; object-fit: contain; }
  p { overflow-wrap: anywhere; }
</style>
