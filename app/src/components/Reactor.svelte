<script lang="ts">
  // Реактор Джарвиса — тот же образ, что в HUD-окне. Состояние меняет скорость и цвет.
  let { size = 220, state = "idle", animated = true }: { size?: number; state?: "offline" | "idle" | "listening" | "thinking" | "speaking"; animated?: boolean } = $props();
  const componentId = $props.id();
  const gradientId = componentId + "-core";
  const ticks = Array.from({ length: 36 }, (_, i) => i * 10);
</script>

<div class="reactor {state}" class:still={!animated} style="width:{size}px;height:{size}px">
  <svg viewBox="-110 -110 220 220">
    <defs>
      <radialGradient id={gradientId}>
        <stop offset="0%" stop-color="#ffffff" />
        <stop offset="25%" stop-color="var(--hot)" />
        <stop offset="60%" stop-color="var(--mid-c)" stop-opacity="0.45" />
        <stop offset="100%" stop-color="var(--mid-c)" stop-opacity="0" />
      </radialGradient>
    </defs>
    <circle r="104" class="frame" />
    <g class="ring r1">
      {#each [0, 90, 180, 270] as a}
        <path d="M {96 * Math.cos(((a + 8) * Math.PI) / 180)} {96 * Math.sin(((a + 8) * Math.PI) / 180)} A 96 96 0 0 1 {96 * Math.cos(((a + 70) * Math.PI) / 180)} {96 * Math.sin(((a + 70) * Math.PI) / 180)}" class="arc thick" />
      {/each}
    </g>
    <g class="ring r2">
      {#each [0, 120, 240] as a}
        <path d="M {80 * Math.cos((a * Math.PI) / 180)} {80 * Math.sin((a * Math.PI) / 180)} A 80 80 0 0 1 {80 * Math.cos(((a + 84) * Math.PI) / 180)} {80 * Math.sin(((a + 84) * Math.PI) / 180)}" class="arc" />
      {/each}
    </g>
    <g class="ring r3">
      {#each ticks as a, i}
        <line x1={64 * Math.cos((a * Math.PI) / 180)} y1={64 * Math.sin((a * Math.PI) / 180)} x2={(i % 3 ? 70 : 74) * Math.cos((a * Math.PI) / 180)} y2={(i % 3 ? 70 : 74) * Math.sin((a * Math.PI) / 180)} class="tick" class:major={i % 3 === 0} />
      {/each}
    </g>
    <g class="ring r4">
      <polygon points="0,-52 45,26 -45,26" class="tri" />
    </g>
    <circle r="46" class="core-bg" />
    <circle r="40" fill={'url(#' + gradientId + ')'} class="core" />
    <circle r="7" class="nucleus" />
    {#if state === "speaking" || state === "listening"}
      {#each [0, 1, 2] as w}
        <circle r="30" class="wave" style="animation-delay:{w * 0.45}s" />
      {/each}
    {/if}
  </svg>
</div>

<style>
  .still :global(*) { animation: none !important; }
  .reactor {
    --hot: #7fe6ff;
    --mid-c: #37b3d8;
    --speed: 1;
    position: relative;
    filter: drop-shadow(0 0 18px rgba(55, 179, 216, 0.35));
    transition: filter 400ms;
  }
  .reactor.listening {
    --speed: 1.8;
    filter: drop-shadow(0 0 26px rgba(127, 230, 255, 0.55));
  }
  .reactor.thinking {
    --speed: 3;
  }
  .reactor.speaking {
    --hot: #ffd38a;
    --mid-c: #ffb648;
    --speed: 2.2;
    filter: drop-shadow(0 0 28px rgba(255, 182, 72, 0.45));
  }
  .reactor.offline {
    --hot: #4c6b78;
    --mid-c: #2a4350;
    --speed: 0.25;
    filter: grayscale(0.6) drop-shadow(0 0 6px rgba(55, 179, 216, 0.1));
  }
  svg {
    width: 100%;
    height: 100%;
    overflow: visible;
  }
  .frame {
    fill: rgba(4, 12, 18, 0.85);
    stroke: rgba(55, 179, 216, 0.35);
    stroke-width: 1.5;
  }
  .arc {
    fill: none;
    stroke: var(--mid-c);
    stroke-width: 3;
    stroke-linecap: round;
    transition: stroke 400ms;
  }
  .arc.thick {
    stroke-width: 5;
    stroke: var(--hot);
    opacity: 0.85;
  }
  .tick {
    stroke: var(--mid-c);
    stroke-width: 1;
    opacity: 0.7;
  }
  .tick.major {
    stroke-width: 2;
    stroke: var(--hot);
  }
  .tri {
    fill: none;
    stroke: var(--mid-c);
    stroke-width: 1.5;
    opacity: 0.8;
  }
  .core-bg {
    fill: #071c26;
    stroke: rgba(55, 179, 216, 0.4);
  }
  .core {
    animation: pulse calc(2.4s / var(--speed)) ease-in-out infinite;
    transform-origin: 0 0; /* центр реактора — начало координат viewBox */
  }
  .nucleus {
    fill: #fff;
  }
  .wave {
    fill: none;
    stroke: var(--hot);
    stroke-width: 2;
    animation: wave 1.35s ease-out infinite;
    transform-origin: 0 0; /* центр реактора — начало координат viewBox */
  }
  .ring {
    transform-origin: 0 0; /* центр реактора — начало координат viewBox */
    animation: spin calc(14s / var(--speed)) linear infinite;
  }
  .r2 {
    animation-direction: reverse;
    animation-duration: calc(9s / var(--speed));
  }
  .r3 {
    animation-duration: calc(22s / var(--speed));
  }
  .r4 {
    animation-direction: reverse;
    animation-duration: calc(11s / var(--speed));
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
  @keyframes pulse {
    50% {
      transform: scale(1.12);
    }
  }
  @keyframes wave {
    from {
      transform: scale(1);
      opacity: 0.8;
    }
    to {
      transform: scale(2.6);
      opacity: 0;
    }
  }
</style>
