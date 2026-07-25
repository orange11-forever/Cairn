// apps/web 的静态服务器。
// 为什么需要它：ES Modules 受同源策略约束，file:// 的 origin 是 null，
// <script type="module"> 会被 CORS 直接挡掉。前端必须从 http:// 提供。
//
// 运行：pnpm web   （另开一个终端 pnpm mock 起后端）

import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join, extname, normalize } from "node:path";

const ROOT = fileURLToPath(new URL("../apps/web/", import.meta.url));
const PORT = Number(process.env.PORT ?? 5500);

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
};

const server = createServer(async (req, res) => {
  const pathname = decodeURIComponent(new URL(req.url, `http://localhost:${PORT}`).pathname);

  // 目录穿越防护：normalize 之后仍以 .. 开头说明请求想跳出 ROOT。
  // 本地开发服务器也照做，因为这套习惯要带到 Day 19 的上传接口去。
  const relative = normalize(pathname === "/" ? "index.html" : pathname.slice(1));
  if (relative.startsWith("..")) {
    res.writeHead(403).end("forbidden");
    return;
  }

  try {
    const body = await readFile(join(ROOT, relative));
    res.writeHead(200, { "Content-Type": MIME[extname(relative)] ?? "application/octet-stream" });
    res.end(body);
  } catch {
    res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    res.end("not found");
  }
});

server.listen(PORT, () => {
  console.log(`前端已启动：http://localhost:${PORT}`);
  console.log(`别忘了另开终端跑：pnpm mock`);
});
