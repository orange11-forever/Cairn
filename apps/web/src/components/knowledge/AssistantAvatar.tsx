import { MascotFigure } from "../MascotFigure.tsx";

export function AssistantAvatar({ name, avatarDataUrl }: { name: string; avatarDataUrl?: string | null }) {
  return avatarDataUrl ? <img className="assistant-avatar" src={avatarDataUrl} alt={`${name}的头像`} width={44} height={44} /> : <MascotFigure variant="avatar" label={name} />;
}

export async function readAssistantAvatar(file: File): Promise<string> {
  if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) throw new Error("请选择 PNG、JPEG 或 WebP 图片。");
  if (file.size > 4 * 1024 * 1024) throw new Error("头像图片不能超过 4 MB。");
  let image: ImageBitmap;
  try { image = await createImageBitmap(file); }
  catch { throw new Error("图片无法读取，请选择有效的 PNG、JPEG 或 WebP 图片。"); }
  try {
    const canvas = document.createElement("canvas"); canvas.width = canvas.height = 128;
    const context = canvas.getContext("2d");
    if (context === null) throw new Error("当前窗口无法处理头像，请重新打开页面。");
    const size = Math.min(image.width, image.height);
    context.drawImage(image, (image.width - size) / 2, (image.height - size) / 2, size, size, 0, 0, 128, 128);
    const result = canvas.toDataURL("image/png");
    if (!result.startsWith("data:image/png;base64,") || result.length > 90000) throw new Error("头像处理失败，请选择其他图片。");
    return result;
  } finally { image.close(); }
}
