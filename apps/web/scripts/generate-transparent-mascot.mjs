import { readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const inputPath = resolve(webRoot, "public/assets/brand/mascot/cairn-mascot.png");
const outputPath = resolve(
  webRoot,
  "public/assets/brand/mascot/cairn-mascot-transparent.png",
);

const input = await readFile(inputPath);
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  const dataUrl = await page.evaluate(async (sourceBase64) => {
    const source = `data:image/png;base64,${sourceBase64}`;
    const image = new Image();
    image.src = source;
    await image.decode();

    if (image.naturalWidth !== 1024 || image.naturalHeight !== 1536) {
      throw new Error(
        `Expected a 1024x1536 source, got ${image.naturalWidth}x${image.naturalHeight}`,
      );
    }

    const canvas = document.createElement("canvas");
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) throw new Error("Canvas 2D context is unavailable");

    context.drawImage(image, 0, 0);
    const frame = context.getImageData(0, 0, canvas.width, canvas.height);
    const { data, width, height } = frame;
    const pixelCount = width * height;
    const indexOf = (x, y) => y * width + x;
    const rgbaOffset = (index) => index * 4;
    const pixelAt = (index) => {
      const offset = rgbaOffset(index);
      return [data[offset], data[offset + 1], data[offset + 2]];
    };
    const median = (values) => {
      values.sort((a, b) => a - b);
      return values[Math.floor(values.length / 2)];
    };

    const borderSamples = [[], [], []];
    const borderDepth = 12;
    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        if (
          x >= borderDepth &&
          x < width - borderDepth &&
          y >= borderDepth &&
          y < height - borderDepth
        ) {
          continue;
        }
        const pixel = pixelAt(indexOf(x, y));
        borderSamples[0].push(pixel[0]);
        borderSamples[1].push(pixel[1]);
        borderSamples[2].push(pixel[2]);
      }
    }
    const background = borderSamples.map(median);
    const colorDistance = (pixel) => Math.hypot(
      pixel[0] - background[0],
      pixel[1] - background[1],
      pixel[2] - background[2],
    );
    const isBackgroundCandidate = (pixel) => {
      const maximum = Math.max(...pixel);
      const minimum = Math.min(...pixel);
      return maximum - minimum <= 45 && maximum >= 115 && colorDistance(pixel) <= 80;
    };

    const exterior = new Uint8Array(pixelCount);
    const queue = new Uint32Array(pixelCount);
    let queueHead = 0;
    let queueTail = 0;
    const enqueue = (x, y) => {
      const index = indexOf(x, y);
      if (exterior[index] || !isBackgroundCandidate(pixelAt(index))) return;
      exterior[index] = 1;
      queue[queueTail] = index;
      queueTail += 1;
    };

    for (let x = 0; x < width; x += 1) {
      enqueue(x, 0);
      enqueue(x, height - 1);
    }
    for (let y = 1; y < height - 1; y += 1) {
      enqueue(0, y);
      enqueue(width - 1, y);
    }

    while (queueHead < queueTail) {
      const index = queue[queueHead];
      queueHead += 1;
      const x = index % width;
      const y = Math.floor(index / width);
      if (x > 0) enqueue(x - 1, y);
      if (x + 1 < width) enqueue(x + 1, y);
      if (y > 0) enqueue(x, y - 1);
      if (y + 1 < height) enqueue(x, y + 1);
    }

    const touchesExterior = (x, y) => {
      for (let offsetY = -1; offsetY <= 1; offsetY += 1) {
        for (let offsetX = -1; offsetX <= 1; offsetX += 1) {
          if (offsetX === 0 && offsetY === 0) continue;
          const neighborX = x + offsetX;
          const neighborY = y + offsetY;
          if (
            neighborX >= 0 &&
            neighborX < width &&
            neighborY >= 0 &&
            neighborY < height &&
            exterior[indexOf(neighborX, neighborY)]
          ) {
            return true;
          }
        }
      }
      return false;
    };

    let transparentPixels = 0;
    let opaquePixels = 0;
    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        const index = indexOf(x, y);
        const offset = rgbaOffset(index);
        if (exterior[index]) {
          data[offset + 3] = 0;
          transparentPixels += 1;
          continue;
        }

        if (touchesExterior(x, y)) {
          const distance = colorDistance(pixelAt(index));
          const alpha = Math.max(0, Math.min(1, (distance - 18) / 92));
          if (alpha < 1) {
            data[offset + 3] = Math.round(alpha * 255);
            for (let channel = 0; channel < 3; channel += 1) {
              const recovered =
                (data[offset + channel] - background[channel] * (1 - alpha)) /
                Math.max(alpha, 0.01);
              data[offset + channel] = Math.max(0, Math.min(255, Math.round(recovered)));
            }
          }
        }

        if (data[offset + 3] >= 250) opaquePixels += 1;
      }
    }

    const transparentRatio = transparentPixels / pixelCount;
    const opaqueRatio = opaquePixels / pixelCount;
    if (transparentRatio < 0.45 || transparentRatio > 0.85) {
      throw new Error(`Unexpected transparent coverage: ${transparentRatio.toFixed(3)}`);
    }
    if (opaqueRatio < 0.12 || opaqueRatio > 0.55) {
      throw new Error(`Unexpected opaque coverage: ${opaqueRatio.toFixed(3)}`);
    }
    for (const [x, y] of [
      [0, 0],
      [width - 1, 0],
      [0, height - 1],
      [width - 1, height - 1],
    ]) {
      if (data[rgbaOffset(indexOf(x, y)) + 3] !== 0) {
        throw new Error(`Corner ${x},${y} is not transparent`);
      }
    }

    context.putImageData(frame, 0, 0);
    return canvas.toDataURL("image/png");
  }, input.toString("base64"));
  await writeFile(outputPath, Buffer.from(dataUrl.split(",")[1], "base64"));
} finally {
  await browser.close();
}
