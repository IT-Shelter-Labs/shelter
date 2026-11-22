<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  import { invoke } from "@tauri-apps/api/core";
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
  {#if image}<img src={image} alt={name} loading="lazy" />{:else}<span aria-hidden="true">{uiText(name.trim().slice(0, 1))}</span>{/if}
</div>

<style>
  .portrait { height: 190px; display: grid; place-items: center; overflow: hidden; border-radius: 12px;
    background: radial-gradient(ellipse at 50% 30%, #29394b, #101722 75%); margin-bottom: 6px; }
  img { display: block; width: 100%; height: 100%; object-fit: contain; }
  span { font-size: 56px; font-weight: 300; opacity: .4; color: var(--accent); }
</style>
