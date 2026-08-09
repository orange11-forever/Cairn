import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";

const REPOSITORY_ROOT = join(import.meta.dirname, "../../../..");

const EXPECTED_ISC_LICENSE = `ISC License

Copyright (c) 2026 orange11-forever

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
`;

async function readRepositoryFile(relativePath) {
  return readFile(join(REPOSITORY_ROOT, relativePath), "utf8");
}

test("repository publishes the approved ISC license verbatim", async () => {
  assert.equal(await readRepositoryFile("LICENSE"), EXPECTED_ISC_LICENSE);
});

test("all package metadata declares ISC", async () => {
  const nodeManifestPaths = [
    "package.json",
    "apps/web/package.json",
    "packages/contracts/package.json",
    "packages/sdk/package.json",
  ];

  for (const path of nodeManifestPaths) {
    const manifest = JSON.parse(await readRepositoryFile(path));
    assert.equal(manifest.license, "ISC", `${path} must declare ISC`);
  }

  for (const path of ["pyproject.toml", "apps/api/pyproject.toml"]) {
    const manifest = await readRepositoryFile(path);
    assert.match(manifest, /^license = "ISC"$/m, `${path} must declare ISC`);
  }
});

test("root README links the repository license", async () => {
  const readme = await readRepositoryFile("README.md");
  assert.match(readme, /\[ISC License\]\(LICENSE\)/);
});
