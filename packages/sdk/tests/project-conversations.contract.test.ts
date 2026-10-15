import type { components, paths } from "../src/generated/schema.js";

type CreateResponses =
  paths["/api/v1/projects/{project_id}/knowledge/conversations"]["post"]["responses"];
type CreatedConversation = CreateResponses[201]["content"]["application/json"];
type ReplayedConversation = CreateResponses[200]["content"]["application/json"];

const fixture: components["schemas"]["KnowledgeConversationResponse"] = {
  id: "00000000-0000-4000-8000-000000000001",
  title: "新对话",
  revision: 1,
  createdAt: "2026-10-12T12:00:00Z",
  updatedAt: "2026-10-12T12:00:00Z",
  turns: [],
};

// Both HTTP success statuses must expose the same generated response body to callers.
export const createdConversation: CreatedConversation = fixture;
export const replayedConversation: ReplayedConversation = fixture;
