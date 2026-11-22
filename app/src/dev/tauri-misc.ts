// Заглушки окна и плагинов Tauri для разработки в браузере.
const win = { show: async () => {}, hide: async () => {}, minimize: async () => {}, toggleMaximize: async () => {}, close: async () => {}, setFocus: async () => {}, label: "main" };
export const getCurrentWindow = () => win;
export const getCurrentWebviewWindow = () => win;
export async function open() { return null; }
export async function save() { return null; }
export async function message() {}
export async function isEnabled() { return false; }
export async function enable() {}
export async function disable() {}
export async function openUrl() {}
export async function openPath() {}
export async function revealItemInDir() {}
