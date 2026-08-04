import createClient, { type Client } from "openapi-fetch";

import type { paths } from "./generated/schema.d.ts";

export type CairnClient = Client<paths>;

export function createCairnClient({
  baseUrl,
  fetch: fetchImpl = globalThis.fetch,
}: {
  baseUrl: string;
  fetch?: typeof globalThis.fetch;
}): CairnClient {
  return createClient<paths>({
    baseUrl,
    fetch: fetchImpl,
    credentials: "include",
  });
}
