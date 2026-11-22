export function voiceName(engine?: string) {
  return ({ clone: "Голос персонажа", piper: "Лёгкий голос", silero: "Silero", files: "Готовые записи",
    plugin: "Голос из дополнения", cloud: "Облачная озвучка" } as Record<string, string>)[engine ?? ""] ?? engine ?? "Не выбран";
}

export function voicePhase(status?: { phase: string; reason?: string } | null, ready?: boolean | null) {
  if (status?.phase === "ready") return status.reason ? "Основная модель" : "";
  const phases: Record<string, string> = { idle: "Проверка", checking: "Проверка", repairing: "Восстанавливается",
    downloading: "Скачивается", loading: "Запускается", error: "Запасной голос" };
  return status ? phases[status.phase] ?? "" : ready === false ? "Недоступен" : "";
}

export function voiceHint(status?: { phase: string; reason?: string } | null) {
  const reasons: Record<string, string> = {
    reference: "Запись голоса не найдена. Выберите или запишите её в разделе «Голос и слух».",
    runtime: "Движок голоса не установлен. Проверьте раздел «Голос и слух».",
    gpu: "Движку нужен доступ к видеокарте NVIDIA. Проверьте драйвер.",
    repair: "Не удалось восстановить движок. Проверьте интернет и свободное место, затем перезапустите Джарвиса.",
    server: "Движок неожиданно завершился. Подробности в журнале голосового сервера.",
    model: "Модель не запустилась. Подробности в журнале голосового сервера.",
    timeout: "Запуск голоса не завершился вовремя. Пока доступен запасной голос.",
    adapter: "Файл индивидуального голоса не найден. Используется основная модель; верните файл из резервной копии.",
  };
  if (status?.reason) return reasons[status.reason] ?? "";
  return status && status.phase !== "ready" ? "Пока Джарвис отвечает запасным голосом." : "";
}
