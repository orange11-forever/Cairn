import type { components } from "../src/index.ts";

const requestWithoutDefaultedLimit = {
  query: "knowledge base",
} satisfies components["schemas"]["KnowledgeSearchRequest"];

void requestWithoutDefaultedLimit;
