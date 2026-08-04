import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const sourcePath = process.argv[2];
if (sourcePath === undefined) {
  throw new Error("Usage: node scripts/generate-mascot-avatar.mjs <source.png>");
}

const outputPath = fileURLToPath(
  new URL("../public/assets/brand/mascot/cairn-mascot-avatar.png", import.meta.url),
);
const source = `data:image/png;base64,${(await readFile(sourcePath)).toString("base64")}`;
const browser = await chromium.launch({ headless: true });

try {
  const page = await browser.newPage();
  const dataUrl = await page.evaluate(async (imageSource) => {
    const image = new Image();
    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = reject;
      image.src = imageSource;
    });

    const canvas = document.createElement("canvas");
    canvas.width = 256;
    canvas.height = 256;
    const context = canvas.getContext("2d");
    if (context === null) throw new Error("2D canvas is unavailable");

    context.imageSmoothingEnabled = true;
    context.imageSmoothingQuality = "high";
    context.beginPath();
    context.arc(128, 128, 128, 0, Math.PI * 2);
    context.clip();
    context.drawImage(image, 310, 110, 660, 660, 0, 0, 256, 256);
    return canvas.toDataURL("image/png");
  }, source);

  await writeFile(outputPath, Buffer.from(dataUrl.split(",")[1], "base64"));
} finally {
  await browser.close();
}
