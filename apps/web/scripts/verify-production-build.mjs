import { readdir, readFile } from "node:fs/promises";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const WEB_ROOT = fileURLToPath(new URL("..", import.meta.url));
const DIST_ROOT = join(WEB_ROOT, "dist");

async function listFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const target = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...await listFiles(target));
    else files.push(target);
  }
  return files;
}

const forbidden = [
  "模拟场景",
  "data-dev-only",
  "cairn-demo-2026",
  "CAIRN_CSRF_SECRET",
  "local-development-secret-change-before-deploying-32-bytes",
];
const offenders = [];
for (const file of await listFiles(DIST_ROOT)) {
  const content = await readFile(file, "utf8");
  if (forbidden.some((value) => content.includes(value))) {
    offenders.push(relative(DIST_ROOT, file));
  }
}

if (offenders.length > 0) {
  throw new Error(`Production build contains development controls: ${offenders.join(", ")}`);
}
