import { QueryClient } from "@tanstack/react-query";
import { expect, test } from "vitest";

import { knowledgeKeys } from "../../src/queries/knowledge.ts";

test("knowledge resource caches stay isolated across organizations", () => {
  const queryClient = new QueryClient();
  const projectId = "00000000-0000-4000-8000-000000004001";
  const organizationA = "00000000-0000-4000-8000-000000002001";
  const organizationB = "00000000-0000-4000-8000-000000002002";

  queryClient.setQueryData(
    knowledgeKeys.resources(organizationA, projectId),
    { pages: [{ items: [{ title: "组织 A 私有资料" }] }] },
  );

  expect(queryClient.getQueryData(
    knowledgeKeys.resources(organizationB, projectId),
  )).toBeUndefined();
});

test("knowledge search keys isolate tenant and search inputs", () => {
  const maybeSearchKey = Reflect.get(knowledgeKeys, "search");
  expect(maybeSearchKey).toBeTypeOf("function");
  const searchKey = maybeSearchKey as (
    organizationId: string,
    projectId: string,
    query: string,
    limit: number,
  ) => readonly unknown[];
  const projectId = "00000000-0000-4000-8000-000000004001";

  expect(searchKey("org-a", projectId, "租约", 8)).not.toEqual(
    searchKey("org-b", projectId, "租约", 8),
  );
  expect(searchKey("org-a", projectId, "租约", 8)).not.toEqual(
    searchKey("org-a", projectId, "索引", 8),
  );
  expect(searchKey("org-a", projectId, "租约", 8)).not.toEqual(
    searchKey("org-a", projectId, "租约", 20),
  );
});
