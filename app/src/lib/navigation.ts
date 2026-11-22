/** Leave history intact when saving fails or the user cancels navigation. */
export async function goBack<T>(history: T[], visit: (entry: T) => Promise<boolean>): Promise<boolean> {
  const entry = history.at(-1);
  if (!entry || !(await visit(entry))) return false;
  if (history.at(-1) === entry) history.pop();
  return true;
}

export async function leaveDraft(options: {
  dirty: boolean;
  busy: boolean;
  ask: () => Promise<"ok" | "extra" | "cancel">;
  save: () => Promise<boolean>;
  discard: () => void;
}): Promise<boolean> {
  if (options.busy) return false;
  if (!options.dirty) return true;
  const choice = await options.ask();
  if (choice === "cancel") return false;
  if (choice === "ok") return options.save();
  options.discard();
  return true;
}
