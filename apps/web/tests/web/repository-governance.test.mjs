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

function frontMatter(markdown) {
  const match = /^---\n([\s\S]*?)\n---\n/.exec(markdown);
  assert.ok(match, "review policy must start with YAML front matter");
  return load(match[1]);
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
    "阶段 2.5A：RBAC/ACL（已交付）",
    "Stage 3A Task 1–11：知识摄取基础（已交付）",
    "Stage 3A Task 12：项目范围混合搜索 API（已交付）",
    "Stage 3A Task 13：真实 Web 知识工作区基础（已交付）",
  ]) {
    assert.ok(architecture.includes(statement), `missing architecture invariant: ${statement}`);
  }
  assert.doesNotMatch(architecture, /完整 RBAC\/ACL[^。\n]*尚未实现/);
});

test("tracked Markdown does not link private documentation", async () => {
  const { stdout } = await runGit(["ls-files", "-z", "--", "*.md"]);
  const markdownPaths = stdout.split("\0").filter(Boolean);

  for (const path of markdownPaths) {
    const markdown = await readRepositoryFile(path);
    assert.ok(
      !/docs\/(?:specs|superpowers)\//.test(markdown),
      `${path} must not link private documentation`,
    );
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
  const privatePathFamilies = [
    {
      privatePath: ".codex/",
      representativePath: ".codex/repository-governance-private.md",
    },
    {
      privatePath: "AGENTS.md",
      representativePath: "AGENTS.md",
    },
    {
      privatePath: ".superpowers/",
      representativePath: ".superpowers/repository-governance-private.md",
    },
    {
      privatePath: "docs/specs/",
      representativePath: "docs/specs/repository-governance-private.md",
    },
    {
      privatePath: "docs/archive/",
      representativePath: "docs/archive/repository-governance-private.md",
    },
    {
      privatePath: "docs/superpowers/",
      representativePath: "docs/superpowers/repository-governance-private.md",
    },
    {
      privatePath: ".remember/",
      representativePath: ".remember/repository-governance-private.md",
    },
  ];
  const { stdout: trackedOutput } = await runGit(["ls-files", "-z"]);
  const trackedPaths = trackedOutput.split("\0").filter(Boolean);

  for (const { privatePath, representativePath } of privatePathFamilies) {
    const { stdout } = await runGit(
      ["check-ignore", "--verbose", "--no-index", "--", representativePath],
    ).catch((error) => {
      assert.fail(`${representativePath} must resolve to an ignore rule: ${error.message}`);
    });
    assert.ok(
      stdout.endsWith(`\t${representativePath}\n`),
      `${representativePath} must resolve to an ignore rule`,
    );

    const trackedPrivatePaths = trackedPaths.filter((path) =>
      privatePath.endsWith("/") ? path.startsWith(privatePath) : path === privatePath,
    );
    assert.deepEqual(
      trackedPrivatePaths,
      [],
      `${privatePath} must not contain tracked files: ${trackedPrivatePaths.join(", ")}`,
    );
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

test("public review policy enforces boundary and negative-path review", async () => {
  const reviewDocument = await readRepositoryFile("docs/review.md").catch(() => null);
  assert.notEqual(reviewDocument, null, "docs/review.md must exist");
  const policy = frontMatter(reviewDocument).review;

  assert.deepEqual(policy.sequence, ["specification", "quality"]);
  assert.deepEqual(policy.scope, ["diff", "affected-boundary"]);
  assert.deepEqual(policy.negativePaths, [
    "validation",
    "authentication-authorization",
    "infrastructure",
    "unexpected-exception",
  ]);
  assert.deepEqual(policy.contractDimensions, [
    "status",
    "body-schema",
    "request-trace-id",
    "security-protocol-headers",
    "openapi-sdk",
  ]);
  assert.equal(policy.requiredGate, "pnpm verify");
  assert.equal(policy.requiredApprovals, 0);
});
