// Опрос ядра только пока карточка на экране и окно не свёрнуто:
// скрытая карточка размонтирована — её таймер остановлен.
export function poll(fn: () => unknown, ms: number) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let stopped = false;
  let busy = false;
  const tick = async () => {
    if (stopped || busy || document.visibilityState !== "visible") return;
    clearTimeout(timer);
    busy = true;
    if (document.visibilityState === "visible") {
      try { await fn(); } catch { /* сеть или ядро недоступно — следующий раз */ }
    }
    busy = false;
    if (!stopped) timer = setTimeout(tick, ms);
  };
  tick();
  const wake = () => { if (document.visibilityState === "visible") { clearTimeout(timer); tick(); } };
  document.addEventListener("visibilitychange", wake);
  return () => { stopped = true; clearTimeout(timer); document.removeEventListener("visibilitychange", wake); };
}
