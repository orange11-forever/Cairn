import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const avatarUrl = new URL(
  "../../public/assets/brand/mascot/cairn-mascot-avatar.png",
  import.meta.url,
);
const transparentFullUrl = new URL(
  "../../public/assets/brand/mascot/cairn-mascot-transparent.png",
  import.meta.url,
);
const PNG_SIGNATURE = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);

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
});
