<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  import { invoke } from "@tauri-apps/api/core";
  import { UserRound } from "@lucide/svelte";
  let { path, name }: { path?: string; name: string } = $props();
  let image = $state("");
  $effect(() => {
    const source = path;
    let gone = false;
    let url = "";
    image = "";
    if (source) {
      invoke<ArrayBuffer>("avatar_portrait", { path: source }).then(bytes => {
        if (gone) return;
        url = URL.createObjectURL(new Blob([bytes], { type: "image/png" }));
        image = url;
      }).catch(() => {});
    }
    return () => { gone = true; if (url) URL.revokeObjectURL(url); };
  });
</script>

<div class="portrait">
  {#if image}
    <img src={image} alt={name} loading="lazy" />
  {:else}
    <div class="placeholder"><UserRound size={36} strokeWidth={1.35} aria-hidden="true" /><span>{uiText("Портрет не подключён")}</span></div>
  {/if}
</div>

<style>
  .portrait { position: relative; height: 190px; display: grid; place-items: center; overflow: hidden; border-radius: 12px;
    background: radial-gradient(ellipse at 50% 30%, #29394b, #101722 75%); margin-bottom: 6px; }
  img { width: 100%; height: 100%; min-height: 0; padding: 8px 12px 0; object-fit: contain; object-position: center bottom;
    mask-image: linear-gradient(to bottom, #000 92%, transparent 100%); }
  .placeholder { display: grid; justify-items: center; gap: 8px; padding: 12px; color: var(--text-2); text-align: center; font-size: 12px; }
</style>
