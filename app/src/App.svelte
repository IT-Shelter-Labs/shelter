<script lang="ts">
  import { onMount } from "svelte";
  import { getCurrentWindow } from "@tauri-apps/api/window";
  import { app, init, toastError, onThemeChange } from "./lib/store.svelte";
  import { applyTheme, watchSystemTheme } from "./lib/theme";
  import Dialog from "./components/Dialog.svelte";
  import GlassAtmosphere from "./components/GlassAtmosphere.svelte";
  import Onboarding from "./views/Onboarding.svelte";
  import Shell from "./views/Shell.svelte";
  import Toasts from "./components/Toasts.svelte";

  let ready = $state(false);

  onMount(() => {
    let closed = false;
    const stopWatching = watchSystemTheme();
    onThemeChange(applyTheme);
    void (async () => {
      try { await init(); }
      catch (e) { app.connectionError = String(e); toastError(e); }
      if (closed) return;
      applyTheme();
      ready = true;
      if (!app.info?.minimized || !app.user.onboarded) await getCurrentWindow().show();
    })().catch(toastError);
    return () => { closed = true; stopWatching(); onThemeChange(undefined); };
  });
</script>

<GlassAtmosphere />
{#if ready}
  {#if app.user.onboarded}
    <Shell />
  {:else}
    <Onboarding />
  {/if}
{/if}
<Toasts />
<Dialog />
