import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { join } from "node:path";

const REPOSITORY_ROOT = join(import.meta.dirname, "../../../..");
const WORKFLOW_PATH = join(REPOSITORY_ROOT, ".github/workflows/ci.yml");

async function readWorkflow() {
  return readFile(WORKFLOW_PATH, "utf8");
}

test("CI targets main with least privilege and PR-only cancellation", async () => {
  const workflow = await readWorkflow();

  assert.match(workflow, /^name: CI$/m);
  assert.match(
    workflow,
    /^on:\n  pull_request:\n    branches:\n      - main\n  push:\n    branches:\n      - main$/m,
  );
  assert.doesNotMatch(workflow, /pull_request_target/);
  assert.match(workflow, /^permissions:\n  contents: read$/m);
  assert.match(
    workflow,
    /group: \$\{\{ github\.workflow \}\}-\$\{\{ github\.event\.pull_request\.number \|\| github\.run_id \}\}/,
  );
  assert.match(
    workflow,
    /cancel-in-progress: \$\{\{ github\.event_name == 'pull_request' \}\}/,
  );
  assert.match(workflow, /runs-on: ubuntu-24\.04/);
  assert.match(workflow, /timeout-minutes: 30/);
  assert.doesNotMatch(workflow, /continue-on-error/);
});

test("CI pins its toolchain and delegates to the complete repository gate", async () => {
  const workflow = await readWorkflow();

  for (const action of [
    "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7",
    "pnpm/action-setup@0977fd99725f1db4007ccb2928dbb4e90d06cc86 # v6",
    "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020 # v7",
    "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7",
    "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9 # v9.0.0",
  ]) {
    assert.ok(workflow.includes(action), `missing pinned action: ${action}`);
  }

  for (const command of [
    "pnpm install --frozen-lockfile",
    "uv sync --all-packages --all-groups --frozen",
    "pnpm --filter cairn-web exec playwright install --with-deps chromium",
  ]) {
    assert.ok(workflow.includes(`run: ${command}`), `missing install command: ${command}`);
  }

  assert.match(workflow, /persist-credentials: false/);
  assert.match(workflow, /node-version: "22"/);
  assert.match(workflow, /python-version: "3\.12"/);
  assert.match(workflow, /enable-cache: true/);
  assert.equal(workflow.match(/run: pnpm verify$/gm)?.length, 1);
});
