/** Отдельный VRM/VRMA не должен загружать ресурсы с диска или из сети. */
export function validateGlb(bytes: ArrayBuffer, extension?: "VRMC_vrm" | "VRMC_vrm_animation") {
  const view = new DataView(bytes);
  if (bytes.byteLength < 20 || view.getUint32(0, true) !== 0x46546c67 || view.getUint32(4, true) !== 2 ||
      view.getUint32(8, true) !== bytes.byteLength || view.getUint32(16, true) !== 0x4e4f534a) {
    throw new Error("Нужен корректный бинарный VRM/VRMA (glTF 2.0).");
  }
  const size = view.getUint32(12, true);
  if (size > bytes.byteLength - 20) throw new Error("Повреждён заголовок модели.");
  const data = JSON.parse(new TextDecoder().decode(new Uint8Array(bytes, 20, size)));
  if (extension && !data.extensions?.[extension] && !(extension === "VRMC_vrm" && data.extensions?.VRM)) {
    throw new Error("Файл не содержит нужных данных VRM/VRMA.");
  }
  for (const item of [...(data.buffers ?? []), ...(data.images ?? [])]) {
    if (item.uri && !/^data:/i.test(item.uri)) throw new Error("Модель с внешними ресурсами: экспортируйте единый файл VRM.");
  }
}
