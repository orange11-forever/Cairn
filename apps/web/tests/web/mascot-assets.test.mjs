import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { inflateSync } from "node:zlib";

const avatarUrl = new URL(
  "../../public/assets/brand/mascot/cairn-mascot-avatar.png",
  import.meta.url,
);
const transparentFullUrl = new URL(
  "../../public/assets/brand/mascot/cairn-mascot-transparent.png",
  import.meta.url,
);
const PNG_SIGNATURE = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);

function paethPredictor(left, above, upperLeft) {
  const estimate = left + above - upperLeft;
  const leftDistance = Math.abs(estimate - left);
  const aboveDistance = Math.abs(estimate - above);
  const upperLeftDistance = Math.abs(estimate - upperLeft);
  if (leftDistance <= aboveDistance && leftDistance <= upperLeftDistance) return left;
  return aboveDistance <= upperLeftDistance ? above : upperLeft;
}

function decodeRgbaPng(png) {
  assert.deepEqual(png.subarray(0, 8), PNG_SIGNATURE);
  let width;
  let height;
  const compressed = [];

  for (let offset = 8; offset < png.length;) {
    const length = png.readUInt32BE(offset);
    const type = png.toString("ascii", offset + 4, offset + 8);
    const dataStart = offset + 8;
    const dataEnd = dataStart + length;
    assert.ok(dataEnd + 4 <= png.length, `truncated ${type} chunk`);

    if (type === "IHDR") {
      width = png.readUInt32BE(dataStart);
      height = png.readUInt32BE(dataStart + 4);
      assert.equal(png[dataStart + 8], 8, "decoder requires 8-bit channels");
      assert.equal(png[dataStart + 9], 6, "decoder requires RGBA channels");
      assert.equal(png[dataStart + 12], 0, "decoder requires a non-interlaced PNG");
    } else if (type === "IDAT") {
      compressed.push(png.subarray(dataStart, dataEnd));
    }

    offset = dataEnd + 4;
    if (type === "IEND") break;
  }

  assert.ok(Number.isInteger(width) && Number.isInteger(height), "missing PNG dimensions");
  assert.ok(compressed.length > 0, "missing PNG image data");
  const bytesPerPixel = 4;
  const stride = width * bytesPerPixel;
  const scanlines = inflateSync(Buffer.concat(compressed));
  assert.equal(scanlines.length, height * (stride + 1), "unexpected PNG scanline size");
  const pixels = Buffer.alloc(width * height * bytesPerPixel);
  let sourceOffset = 0;

  for (let y = 0; y < height; y += 1) {
    const filter = scanlines[sourceOffset];
    sourceOffset += 1;
    assert.ok(filter <= 4, `unsupported PNG filter ${filter}`);
    const rowOffset = y * stride;
    const previousRowOffset = rowOffset - stride;

    for (let x = 0; x < stride; x += 1) {
      const raw = scanlines[sourceOffset];
      sourceOffset += 1;
      const left = x >= bytesPerPixel ? pixels[rowOffset + x - bytesPerPixel] : 0;
      const above = y > 0 ? pixels[previousRowOffset + x] : 0;
      const upperLeft = y > 0 && x >= bytesPerPixel
        ? pixels[previousRowOffset + x - bytesPerPixel]
        : 0;
      const reconstructed = filter === 0
        ? raw
        : filter === 1
          ? raw + left
          : filter === 2
            ? raw + above
            : filter === 3
              ? raw + Math.floor((left + above) / 2)
              : raw + paethPredictor(left, above, upperLeft);
      pixels[rowOffset + x] = reconstructed & 0xff;
    }
  }

  return { width, height, pixels };
}

function assertTransparentMascotAlpha({ width, height, pixels }) {
  const alphaAt = (x, y) => pixels[(y * width + x) * 4 + 3];
  assert.deepEqual(
    [alphaAt(0, 0), alphaAt(width - 1, 0), alphaAt(0, height - 1), alphaAt(width - 1, height - 1)],
    [0, 0, 0, 0],
    "full mascot must keep transparent corners",
  );

  let transparent = 0;
  let opaque = 0;
  for (let offset = 3; offset < pixels.length; offset += 4) {
    if (pixels[offset] === 0) transparent += 1;
    if (pixels[offset] === 255) opaque += 1;
  }
  const pixelCount = width * height;
  const transparentRatio = transparent / pixelCount;
  const opaqueRatio = opaque / pixelCount;
  assert.ok(
    transparentRatio >= 0.35 && transparentRatio <= 0.85,
    `unexpected transparent coverage ${transparentRatio.toFixed(4)}`,
  );
  assert.ok(
    opaqueRatio >= 0.12 && opaqueRatio <= 0.65,
    `unexpected opaque coverage ${opaqueRatio.toFixed(4)}`,
  );
  return { transparentRatio, opaqueRatio };
}

test("mascot avatar is a compact 256px RGBA PNG", async () => {
  const png = await readFile(avatarUrl);

  assert.deepEqual(png.subarray(0, 8), PNG_SIGNATURE);
  assert.equal(png.toString("ascii", 12, 16), "IHDR");
  assert.equal(png.readUInt32BE(16), 256);
  assert.equal(png.readUInt32BE(20), 256);
  assert.equal(png[24], 8, "avatar must use 8-bit channels");
  assert.equal(png[25], 6, "avatar must contain RGBA channels");
  assert.ok(png.byteLength < 300_000, "avatar must stay below 300 KB");
});

test("full mascot is a 1024x1536 RGBA PNG", async () => {
  const png = await readFile(transparentFullUrl);

  assert.deepEqual(png.subarray(0, 8), PNG_SIGNATURE);
  assert.equal(png.toString("ascii", 12, 16), "IHDR");
  assert.equal(png.readUInt32BE(16), 1024);
  assert.equal(png.readUInt32BE(20), 1536);
  assert.equal(png[24], 8, "full mascot must use 8-bit channels");
  assert.equal(png[25], 6, "full mascot must contain RGBA channels");
  assert.ok(png.byteLength < 2_500_000, "full mascot must stay below 2.5 MB");
  assertTransparentMascotAlpha(decodeRgbaPng(png));
});

test("full mascot alpha contract rejects an opaque pixel mutation", async () => {
  const decoded = decodeRgbaPng(await readFile(transparentFullUrl));
  const opaquePixels = Buffer.from(decoded.pixels);
  for (let offset = 3; offset < opaquePixels.length; offset += 4) opaquePixels[offset] = 255;

  assert.throws(
    () => assertTransparentMascotAlpha({ ...decoded, pixels: opaquePixels }),
    /transparent corners/,
  );

  for (const [x, y] of [
    [0, 0],
    [decoded.width - 1, 0],
    [0, decoded.height - 1],
    [decoded.width - 1, decoded.height - 1],
  ]) {
    opaquePixels[(y * decoded.width + x) * 4 + 3] = 0;
  }
  assert.throws(
    () => assertTransparentMascotAlpha({ ...decoded, pixels: opaquePixels }),
    /transparent coverage/,
  );
});
