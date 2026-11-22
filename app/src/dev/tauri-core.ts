// Только для разработки в браузере (npm run dev:bridge): вместо Tauri —
// HTTP-мост Vite к тестовому стенду ядра (tools/dev_core.py). В сборку не попадает.
export async function invoke<T>(command: string, args: Record<string, unknown> = {}): Promise<T> {
  const response = await fetch("/__bridge/invoke", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command, args }),
  });
  if (response.ok && command === "avatar_portrait") return await response.arrayBuffer() as T;
  const data = await response.json();
  if (!response.ok) throw data.error ?? `ошибка ${response.status}`;
  return data as T;
}
export function convertFileSrc(path: string) {
  return path;
}
