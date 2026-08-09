import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";

import { load } from "js-yaml";

const REPOSITORY_ROOT = join(import.meta.dirname, "../../../..");
const WORKFLOW_PATH = join(REPOSITORY_ROOT, ".github/workflows/ci.yml");

const EXPECTED_ACTIONS = [
  "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
  "pnpm/action-setup@0977fd99725f1db4007ccb2928dbb4e90d06cc86",
  "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020",
  "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
  "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9",
];

const EXPECTED_STEPS = [
  {
    name: "Checkout repository",
    uses: EXPECTED_ACTIONS[0],
    with: { "persist-credentials": false },
  },
  {
    name: "Install pnpm",
    uses: EXPECTED_ACTIONS[1],
    with: { version: "10.34.5", run_install: false },
  },
  {
    name: "Set up Node.js",
    uses: EXPECTED_ACTIONS[2],
    with: {
      "node-version": "22",
      cache: "pnpm",
      "cache-dependency-path": "pnpm-lock.yaml",
    },
  },
  {
    name: "Set up Python",
    uses: EXPECTED_ACTIONS[3],
    with: { "python-version": "3.12" },
  },
  {
    name: "Set up uv",
    uses: EXPECTED_ACTIONS[4],
    with: { "enable-cache": true, "cache-dependency-glob": "uv.lock" },
  },
  { name: "Install Node.js dependencies", run: "pnpm install --frozen-lockfile" },
  {
    name: "Install Python dependencies",
    run: "uv sync --all-packages --all-groups --frozen",
  },
  {
    name: "Install Chromium",
    run: "pnpm --filter cairn-web exec playwright install --with-deps chromium",
  },
  { name: "Run full verification", run: "pnpm verify" },
];

async function readWorkflow() {
  return readFile(WORKFLOW_PATH, "utf8");
}

function assertRecord(value, label) {
  assert.ok(
    value !== null && typeof value === "object" && !Array.isArray(value),
    `${label} must be a mapping`,
  );
}

function assertExactKeys(value, expectedKeys, label) {
  assertRecord(value, label);
  assert.deepEqual(
    Object.keys(value).sort(),
    [...expectedKeys].sort(),
    `${label} keys must be exact`,
  );
}

function hasKey(value, key) {
  if (Array.isArray(value)) return value.some((item) => hasKey(item, key));
  if (value === null || typeof value !== "object") return false;
  return Object.entries(value).some(
    ([entryKey, entryValue]) => entryKey === key || hasKey(entryValue, key),
  );
}

function validateWorkflow(source) {
  const workflow = load(source);
  assertExactKeys(
    workflow,
    ["name", "on", "permissions", "concurrency", "jobs"],
    "workflow",
  );
  assert.equal(workflow.name, "CI");
  assert.deepEqual(workflow.on, {
    pull_request: { branches: ["main"] },
    push: { branches: ["main"] },
  });
  assert.deepEqual(workflow.permissions, { contents: "read" });
  assert.deepEqual(workflow.concurrency, {
    group: "${{ github.workflow }}-${{ github.event.pull_request.number || github.run_id }}",
    "cancel-in-progress": "${{ github.event_name == 'pull_request' }}",
  });

  assertExactKeys(workflow.jobs, ["verify"], "job");
  const verify = workflow.jobs.verify;
  assertExactKeys(
    verify,
    ["name", "runs-on", "timeout-minutes", "env", "steps"],
    "verify job",
  );
  assert.equal(verify.name, "Full verification");
  assert.equal(verify["runs-on"], "ubuntu-24.04");
  assert.equal(verify["timeout-minutes"], 30);
  assert.deepEqual(verify.env, { CI: "true" });
  assert.deepEqual(verify.steps, EXPECTED_STEPS, "verify steps must be exact");

  const actions = verify.steps
    .filter((step) => "uses" in step)
    .map((step) => step.uses);
  assert.deepEqual(actions, EXPECTED_ACTIONS);
  for (const action of actions) {
    assert.match(
      action,
      /^[^@]+@[0-9a-f]{40}$/,
      `action must use a full commit SHA: ${action}`,
    );
  }

  assert.equal(verify.steps.filter((step) => step.run === "pnpm verify").length, 1);
  assert.equal(hasKey(workflow, "continue-on-error"), false);
}

function replaceOnce(source, target, replacement) {
  assert.ok(source.includes(target), `mutation target not found: ${target}`);
  return source.replace(target, replacement);
}

test("CI workflow has the exact secure verification structure", async () => {
  validateWorkflow(await readWorkflow());
});

test("CI workflow rejects malformed YAML", async () => {
  const workflow = await readWorkflow();
  assert.throws(() => validateWorkflow(`${workflow}\nmalformed: [\n`), {
    name: "YAMLException",
  });
});

test("CI workflow rejects job-level permission overrides", async () => {
  const workflow = await readWorkflow();
  const mutated = replaceOnce(
    workflow,
    "    timeout-minutes: 30\n",
    "    timeout-minutes: 30\n    permissions:\n      contents: write\n",
  );
  assert.throws(() => validateWorkflow(mutated), /verify job keys must be exact/);
});

test("CI workflow rejects extra unpinned actions", async () => {
  const workflow = await readWorkflow();
  const mutated = replaceOnce(
    workflow,
    "      - name: Run full verification\n        run: pnpm verify\n",
    "      - name: Run full verification\n        run: pnpm verify\n\n      - name: Upload artifact\n        uses: actions/upload-artifact@main\n",
  );
  assert.throws(() => validateWorkflow(mutated), /verify steps must be exact/);
});

test("CI workflow rejects extra jobs", async () => {
  const workflow = await readWorkflow();
  const mutated = replaceOnce(
    workflow,
    "      - name: Run full verification\n        run: pnpm verify\n",
    "      - name: Run full verification\n        run: pnpm verify\n\n  publish:\n    runs-on: ubuntu-24.04\n    steps:\n      - run: echo publish\n",
  );
  assert.throws(() => validateWorkflow(mutated), /job keys must be exact/);
});
