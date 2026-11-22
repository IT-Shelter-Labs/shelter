// Вопрос в окне: «Сохранить изменения?» и подтверждения — вместо системных confirm().
export type DialogChoice = "ok" | "extra" | "cancel";
type Request = { title: string; text: string; ok: string; extra?: string; cancel?: string; danger?: boolean; resolve: (c: DialogChoice) => void };

export const dialog = $state({ current: null as Request | null });

export function ask(options: { title: string; text: string; ok?: string; extra?: string; cancel?: string; danger?: boolean }) {
  return new Promise<DialogChoice>((resolve) => {
    dialog.current?.resolve("cancel");
    dialog.current = { ok: "Да", ...options, resolve };
  });
}

export function answer(choice: DialogChoice) {
  const current = dialog.current;
  dialog.current = null;
  current?.resolve(choice);
}
