import type { components } from "../src/index.ts";

type RequiredKeys<Value> = {
  [Key in keyof Value]-?: Record<string, never> extends Pick<Value, Key> ? never : Key;
}[keyof Value];

type AssertRequired<Value, Key extends keyof Value> = Key extends RequiredKeys<Value>
  ? true
  : never;

const requestWithoutDefaultedLimit = {
  query: "knowledge base",
} satisfies components["schemas"]["KnowledgeSearchRequest"];

void requestWithoutDefaultedLimit;

export const responseDefaultsRemainRequired: [
  AssertRequired<components["schemas"]["ApiVersionResponse"], "service">,
  AssertRequired<components["schemas"]["HealthResponse"], "status">,
  AssertRequired<components["schemas"]["ReadyResponse"], "status">,
  AssertRequired<components["schemas"]["UploadInstruction"], "method">,
] = [true, true, true, true];
