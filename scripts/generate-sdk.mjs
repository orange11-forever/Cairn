import { spawnSync } from "node:child_process";
import { mkdtemp, mkdir, readFile, rm, copyFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { spawnInvocation } from "./spawn-command.mjs";

const REPOSITORY_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const UV = process.platform === "win32" ? "uv.exe" : "uv";
const PNPM = process.platform === "win32" ? "pnpm.cmd" : "pnpm";
const OPENAPI_PATH = join(REPOSITORY_ROOT, "packages/sdk/openapi.json");
const SCHEMA_PATH = join(REPOSITORY_ROOT, "packages/sdk/src/generated/schema.d.ts");
const RUNTIME_SCHEMAS_PATH = join(
  REPOSITORY_ROOT,
  "packages/sdk/src/generated/runtime-schemas.ts",
);
const COMPONENT_SCHEMA_PREFIX = "#/components/schemas/";

function run(command, args, env = process.env) {
  const invocation = spawnInvocation(command, args, { env });
  const result = spawnSync(invocation.command, invocation.args, {
    cwd: REPOSITORY_ROOT,
    env,
    shell: false,
    stdio: "inherit",
  });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    throw new Error(`${command} exited with status ${result.status ?? "unknown"}`);
  }
}

async function sameBytes(left, right) {
  try {
    const [leftBytes, rightBytes] = await Promise.all([readFile(left), readFile(right)]);
    return leftBytes.equals(rightBytes);
  } catch (error) {
    if (error?.code === "ENOENT") return false;
    throw error;
  }
}

async function generateRuntimeSchemas(openapiPath, outputPath) {
  const document = JSON.parse(await readFile(openapiPath, "utf8"));
  const schemas = document?.components?.schemas;
  if (schemas === null || typeof schemas !== "object" || Array.isArray(schemas)) {
    throw new Error("OpenAPI document does not contain components.schemas");
  }
  const source = [
    "// Generated from FastAPI OpenAPI by scripts/generate-sdk.mjs. Do not edit.",
    `export const componentSchemas = ${JSON.stringify(schemas, null, 2)} as const;`,
    "",
  ].join("\n");
  await writeFile(outputPath, source, "utf8");
}

function collectComponentSchemas(schema, schemas, collected) {
  if (schema === null || typeof schema !== "object") return;
  if (Array.isArray(schema)) {
    for (const item of schema) collectComponentSchemas(item, schemas, collected);
    return;
  }
  if (typeof schema.$ref === "string" && schema.$ref.startsWith(COMPONENT_SCHEMA_PREFIX)) {
    const name = schema.$ref.slice(COMPONENT_SCHEMA_PREFIX.length);
    if (collected.has(name)) return;
    collected.add(name);
    collectComponentSchemas(schemas[name], schemas, collected);
    return;
  }
  for (const value of Object.values(schema)) {
    collectComponentSchemas(value, schemas, collected);
  }
}

function stripOptionalDefaults(schema) {
  if (schema === null || typeof schema !== "object" || Array.isArray(schema)) return;
  const required = new Set(Array.isArray(schema.required) ? schema.required : []);
  if (schema.properties !== null && typeof schema.properties === "object") {
    for (const [name, property] of Object.entries(schema.properties)) {
      if (
        !required.has(name) &&
        property !== null &&
        typeof property === "object" &&
        !Array.isArray(property)
      ) {
        delete property.default;
      }
      stripOptionalDefaults(property);
    }
  }
  for (const keyword of ["items", "anyOf", "oneOf", "allOf"]) {
    stripOptionalDefaults(schema[keyword]);
  }
}

async function generateTypeInput(openapiPath, outputPath) {
  const document = JSON.parse(await readFile(openapiPath, "utf8"));
  const typeDocument = structuredClone(document);
  const schemas = typeDocument?.components?.schemas;
  if (schemas === null || typeof schemas !== "object" || Array.isArray(schemas)) {
    throw new Error("OpenAPI document does not contain components.schemas");
  }
  const requestComponents = new Set();
  const responseComponents = new Set();
  for (const pathItem of Object.values(typeDocument.paths ?? {})) {
    if (pathItem === null || typeof pathItem !== "object") continue;
    for (const operation of Object.values(pathItem)) {
      if (operation === null || typeof operation !== "object") continue;
      for (const media of Object.values(operation.requestBody?.content ?? {})) {
        collectComponentSchemas(media?.schema, schemas, requestComponents);
      }
      for (const response of Object.values(operation.responses ?? {})) {
        for (const media of Object.values(response?.content ?? {})) {
          collectComponentSchemas(media?.schema, schemas, responseComponents);
        }
      }
    }
  }
  for (const name of requestComponents) {
    if (!responseComponents.has(name)) stripOptionalDefaults(schemas[name]);
  }
  await writeFile(outputPath, `${JSON.stringify(typeDocument, null, 2)}\n`, "utf8");
}

const checkOnly = process.argv.slice(2).includes("--check");
const temporaryRoot = await mkdtemp(join(tmpdir(), "cairn-sdk-"));
const temporaryOpenapi = join(temporaryRoot, "openapi.json");
const temporaryTypeInput = join(temporaryRoot, "type-input-openapi.json");
const temporarySchema = join(temporaryRoot, "schema.d.ts");
const temporaryRuntimeSchemas = join(temporaryRoot, "runtime-schemas.ts");

try {
  run(
    UV,
    ["run", "--offline", "--package", "cairn-api", "python", "scripts/export-openapi.py", temporaryOpenapi],
    { ...process.env, UV_CACHE_DIR: join(temporaryRoot, "uv-cache") },
  );
  await generateTypeInput(temporaryOpenapi, temporaryTypeInput);
  run(PNPM, [
    "--filter",
    "@cairn/sdk",
    "exec",
    "openapi-typescript",
    temporaryTypeInput,
    "--output",
    temporarySchema,
  ]);
  await generateRuntimeSchemas(temporaryOpenapi, temporaryRuntimeSchemas);

  if (checkOnly) {
    const stale = [];
    if (!(await sameBytes(temporaryOpenapi, OPENAPI_PATH))) stale.push("packages/sdk/openapi.json");
    if (!(await sameBytes(temporarySchema, SCHEMA_PATH))) {
      stale.push("packages/sdk/src/generated/schema.d.ts");
    }
    if (!(await sameBytes(temporaryRuntimeSchemas, RUNTIME_SCHEMAS_PATH))) {
      stale.push("packages/sdk/src/generated/runtime-schemas.ts");
    }
    if (stale.length > 0) {
      console.error(`Stale generated SDK artifacts: ${stale.join(", ")}`);
      process.exitCode = 1;
    }
  } else {
    await mkdir(dirname(SCHEMA_PATH), { recursive: true });
    await copyFile(temporaryOpenapi, OPENAPI_PATH);
    await copyFile(temporarySchema, SCHEMA_PATH);
    await copyFile(temporaryRuntimeSchemas, RUNTIME_SCHEMAS_PATH);
  }
} finally {
  await rm(temporaryRoot, { recursive: true, force: true });
}
