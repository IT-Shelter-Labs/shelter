// Мост событий для разработки: core:event — поток ядра через Vite (SSE).
export type UnlistenFn = () => void;
type Handler = (event: { payload: any }) => void;
const handlers = new Map<string, Set<Handler>>();
let source: EventSource | undefined;

function connect() {
  if (source) return;
  source = new EventSource("/__bridge/events");
  source.onmessage = (message) => {
    const event = JSON.parse(message.data);
    if (event.kind === "ping") return;
    for (const h of handlers.get("core:event") ?? []) h({ payload: event });
  };
  source.onopen = () => { for (const h of handlers.get("core:connected") ?? []) h({ payload: true }); };
}

export async function listen(name: string, handler: Handler): Promise<UnlistenFn> {
  if (!handlers.has(name)) handlers.set(name, new Set());
  handlers.get(name)!.add(handler);
  if (name === "core:event") connect();
  return () => handlers.get(name)?.delete(handler);
}
export async function emit() {}
