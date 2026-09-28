import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const publicMark = new URL("../../public/assets/brand/cairn-mark-v3.svg", import.meta.url);
const publicWordmark = new URL("../../public/assets/brand/cairn-wordmark-v3.svg", import.meta.url);
const rootMark = new URL("../../../../assets/brand/cairn-mark-v3.svg", import.meta.url);
const rootWordmark = new URL("../../../../assets/brand/cairn-wordmark-v3.svg", import.meta.url);

function paths(svg) {
  return [...svg.matchAll(/<path\b[^>]*\bd="([^"]+)"/g)].map((match) => match[1]);
}

test("downloadable Cairn mark and wordmark share the same concept mountain silhouette", async () => {
  const [mark, wordmark, readmeMark, readmeWordmark] = await Promise.all([
    publicMark, publicWordmark, rootMark, rootWordmark,
  ].map((url) => readFile(url, "utf8")));
  assert.equal(mark, readmeMark);
  assert.equal(wordmark, readmeWordmark);
  assert.equal(paths(mark).length, 3);
  assert.deepEqual(paths(wordmark), paths(mark));
  assert.match(wordmark, />Cairn<\/text>/);
  assert.doesNotMatch(mark + wordmark, /<(?:image|script)\b|(?:href|src)="https?:\/\//i);
});

test("the browser favicon references the new reusable vector mark", async () => {
  const html = await readFile(new URL("../../index.html", import.meta.url), "utf8");
  assert.match(html, /<link rel="icon" type="image\/svg\+xml" href="\/assets\/brand\/cairn-mark-v3\.svg">/);
});
