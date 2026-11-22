<!-- Мягкость заложена в градиенты; движутся только transform. Без видео,
     полноэкранного canvas, покадрового blur и отдельного WebGL-контекста. -->
<script lang="ts">
  // Состояние и системные предпочтения применяются централизованно в theme.ts.
</script>
<div class="atmosphere" aria-hidden="true">
  <div class="mist mist-a"></div><div class="mist mist-b"></div>
  <div class="mist mist-c"></div><div class="mist mist-d"></div>
  <div class="grain"></div><div class="vignette"></div>
</div>

<style>
  .atmosphere { position: fixed; inset: 0; overflow: hidden; pointer-events: none; display: none; isolation: isolate; }
  :global(html[data-material="glass"]) .atmosphere { display: block; }
  .mist { position: absolute; width: 92vmax; height: 82vmax; opacity: calc(var(--mist-strength, .55) * .8); animation: drift var(--mist-duration, 36s) ease-in-out infinite alternate; }
  .mist-a { left: -40vmax; top: -30vmax; background: radial-gradient(ellipse at 52% 48%, #37bfdf 0, #137cbb66 25%, #227ab51a 43%, transparent 65%); }
  .mist-b { right: -35vmax; bottom: -34vmax; background: radial-gradient(ellipse, #a886df 0, #875ac266 25%, #7949b91a 44%, transparent 65%); animation-delay: -17s; animation-duration: calc(var(--mist-duration, 36s) * 1.3); }
  .mist-c { right: -25vmax; top: -43vmax; background: radial-gradient(ellipse, #edbac9b3 0, #d77fb559 25%, #a56ab414 43%, transparent 65%); animation-delay: -25s; animation-direction: alternate-reverse; }
  .mist-d { left: -28vmax; bottom: -53vmax; background: radial-gradient(ellipse, #6bc6b3b3 0, #55c5c54d 24%, transparent 60%); animation-delay: -11s; animation-duration: calc(var(--mist-duration, 36s) * 1.6); }
  .grain { position: absolute; inset: 0; opacity: .025; background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 180 180' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.82' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Cpath fill='%23fff' filter='url(%23n)' d='M0 0h180v180H0z'/%3E%3C/svg%3E"); }
  .vignette { position: absolute; inset: 0; background: radial-gradient(ellipse at 50% 20%, transparent 10%, #070c1814 55%, #070c1870 100%); }
  :global(html[data-theme="light"]) .mist { opacity: calc(var(--mist-strength, .55) * .42); }
  :global(html[data-theme="light"]) .vignette { background: linear-gradient(145deg, #ffffff40, transparent 50%, #dce9ef30); }
  :global(html:not([data-atmosphere="flow"])) .mist,
  :global(html[data-background]) .mist { animation-play-state: paused; }
  :global(html[data-atmosphere="off"]) .atmosphere { display: none; }
  @keyframes drift { 0% { transform: translate3d(-3%, -3%, 0) scale(.92) rotate(-9deg); } 50% { transform: translate3d(8%, 6%, 0) scale(1.08) rotate(5deg); } 100% { transform: translate3d(-1%, 14%, 0) scale(1.02) rotate(15deg); } }
</style>
