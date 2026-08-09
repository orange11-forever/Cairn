import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";
import { promisify } from "node:util";
import { load } from "js-yaml";

const REPOSITORY_ROOT = join(import.meta.dirname, "../../../..");
const execFileAsync = promisify(execFile);

async function runGit(args) {
  return execFileAsync("git", args, {
    cwd: REPOSITORY_ROOT,
    encoding: "utf8",
  });
}

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

test("public architecture documentation is reachable and status-explicit", async () => {
  const [architecture, rootReadme, apiReadme] = await Promise.all([
    readRepositoryFile("docs/architecture.md"),
    readRepositoryFile("README.md"),
    readRepositoryFile("apps/api/README.md"),
  ]);

  assert.match(rootReadme, /\[公开架构说明\]\(docs\/architecture\.md\)/);
  assert.match(apiReadme, /\[公开架构说明\]\(\.\.\/\.\.\/docs\/architecture\.md\)/);
  assert.doesNotMatch(apiReadme, /docs\/specs\//);

  for (const heading of [
    "## 当前已交付",
    "## 目标架构",
    "## 安全与数据不变量",
    "## 阶段路线",
  ]) {
    assert.ok(architecture.includes(heading), `missing architecture heading: ${heading}`);
  }

  for (const statement of [
    "PostgreSQL 是业务事实来源",
    "Redis 不是真实数据来源",
    "业务写入、审计记录与 Outbox 事件在同一事务提交",
    "阶段 2.5A：RBAC/ACL",
    "阶段 3：知识摄取与检索",
  ]) {
    assert.ok(architecture.includes(statement), `missing architecture invariant: ${statement}`);
  }
});

test("repository text and binary policies are cross-platform stable", async () => {
  const attributes = await readRepositoryFile(".gitattributes");
  assert.equal(
    attributes,
    `* text=auto eol=lf

*.png binary
*.jpg binary
*.jpeg binary
*.gif binary
*.ico binary
*.webp binary
*.woff binary
*.woff2 binary
`,
  );

  const mascotPath = "apps/web/public/assets/brand/mascot/cairn-mascot.png";
  const { stdout } = await runGit(["ls-files", "-s", "--", mascotPath]);
  assert.match(stdout, /^100644 [0-9a-f]+ 0\tapps\/web\/public\/assets\/brand\/mascot\/cairn-mascot\.png\n$/);
});

test("personal agent files and detailed plans remain private", async () => {
  for (const path of [
    ".codex/config.toml",
    "AGENTS.md",
    "docs/superpowers/specs/private.md",
  ]) {
    const { stdout } = await runGit([
      "check-ignore",
      "--verbose",
      "--no-index",
      "--",
      path,
    ]);
    assert.match(stdout, new RegExp(`${path.replaceAll(".", "\\.")}\\n$`));
  }
});

test("repository governance names the exact required CI check", async () => {
  const workflow = load(await readRepositoryFile(".github/workflows/ci.yml"));
  assert.equal(`${workflow.name} / ${workflow.jobs.verify.name}`, "CI / Full verification");

  const ciDocs = await readRepositoryFile("docs/ci.md");
  for (const policy of [
    "`CI / Full verification`",
    "零审批 Pull Request",
    "禁止直接推送 `main`",
    "禁止强制推送和删除 `main`",
    "不得配置持久 bypass",
    "squash merge",
  ]) {
    assert.ok(ciDocs.includes(policy), `missing CI governance policy: ${policy}`);
  }
});
