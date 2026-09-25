import type { components, operations, paths } from "../src/generated/schema";

type Queue = operations["queue_source_sync_api_v1_projects__project_id__knowledge_sources__source_id__syncs_post"];
type Poll = operations["get_source_sync_api_v1_projects__project_id__knowledge_sources__source_id__syncs__sync_id__get"];
type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false;
type Assert<T extends true> = T;
export type SyncContract = [
  Assert<Equal<keyof Queue["responses"], 202 | 401 | 403 | 404 | 405 | 422 | 500 | 503>>,
  Assert<Equal<keyof Poll["responses"], 200 | 401 | 404 | 405 | 422 | 500 | 503>>,
  Assert<Equal<Queue["responses"][202]["content"]["application/json"], components["schemas"]["KnowledgeSourceSyncResponse"]>>,
  Assert<Equal<Poll["responses"][200]["content"]["application/json"], components["schemas"]["KnowledgeSourceSyncResponse"]>>,
  Assert<Equal<Queue["parameters"]["header"], { "X-CSRF-Token": string }>>,
  Assert<Equal<Queue["requestBody"]["content"]["application/json"], components["schemas"]["KnowledgeSourceSyncCreateRequest"]>>,
  Assert<Equal<paths["/api/v1/projects/{project_id}/knowledge/sources/{source_id}/syncs"]["post"], Queue>>,
  Assert<Equal<paths["/api/v1/projects/{project_id}/knowledge/sources/{source_id}/syncs/{sync_id}"]["get"], Poll>>,
];
