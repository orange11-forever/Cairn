import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const avatarUrl = new URL(
  "../../public/assets/brand/mascot/cairn-mascot-avatar.png",
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
