import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { chmod, mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import test from "node:test";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";

const execFileAsync = promisify(execFile);
const REPOSITORY_ROOT = join(dirname(fileURLToPath(import.meta.url)), "../../../..");
const BUILD_SCRIPT = join(REPOSITORY_ROOT, "deploy/docker/minio/build.sh");

test("MinIO build creates its output and uses upstream release metadata", async (context) => {
  const directory = await mkdtemp(join(tmpdir(), "cairn-minio-build-"));
  context.after(() => rm(directory, { force: true, recursive: true }));
  const source = join(directory, "source");
  const bin = join(directory, "bin");
  const output = join(directory, "missing", "out", "minio");
  const log = join(directory, "go-args.log");
  await mkdir(join(source, "buildscripts"), { recursive: true });
  await mkdir(bin);

  const fakeGo = join(bin, "go");
  await writeFile(
    fakeGo,
    [
      "#!/bin/sh",
      "set -eu",
      'if [ "$1" = "run" ]; then',
      '  test "${MINIO_RELEASE:-}" = "RELEASE"',
      "  printf '%s\\n' '-s -w -X github.com/minio/minio/cmd.ReleaseTag=RELEASE.2025-10-15T17-29-55Z'",
      "  exit 0",
      "fi",
      'printf \'<%s>\\n\' "$@" > "$FAKE_GO_LOG"',
      'while [ "$#" -gt 0 ]; do',
      '  if [ "$1" = "-o" ]; then',
      "    shift",
      '    test -d "$(dirname "$1")"',
      '    printf \'%s\\n\' \'#!/bin/sh\' \'echo minio version RELEASE.2025-10-15T17-29-55Z\' > "$1"',
      '    chmod +x "$1"',
      "    exit 0",
      "  fi",
      "  shift",
      "done",
      "exit 42",
    ].join("\n"),
    "utf8",
  );
  await chmod(fakeGo, 0o755);

  await execFileAsync("sh", [BUILD_SCRIPT], {
    env: {
      ...process.env,
      FAKE_GO_LOG: log,
      MINIO_OUTPUT_PATH: output,
      MINIO_SOURCE_DIR: source,
      PATH: `${bin}:${process.env.PATH ?? ""}`,
    },
  });

  const invocation = await readFile(log, "utf8");
  assert.match(invocation, /<-tags>\n<kqueue>/);
  assert.match(invocation, /<-trimpath>/);
  assert.match(invocation, /<-ldflags>\n<-s -w -X .*ReleaseTag=RELEASE\.2025-10-15T17-29-55Z>/);
  assert.match(invocation, new RegExp(`<-o>\\n<${output.replaceAll("/", "\\/")}>`));
  assert.match(await readFile(output, "utf8"), /RELEASE\.2025-10-15T17-29-55Z/);
});
