import { createCairnClient, matchesComponentSchema, type components } from "@cairn/sdk";
import { apiOrigins } from "./config.ts";
import { knowledgeContractError, knowledgeRequestError, knowledgeResponseError } from "./knowledgeRequest.ts";

export type ProjectPlanPreviewResponse = components["schemas"]["ProjectPlanPreviewResponse"];
export type ProposedTask = components["schemas"]["ProposedTask"];
export type ProjectPlanApplication = components["schemas"]["ProjectPlanApplicationResponse"];
export type ProjectPlanApplicationPage = components["schemas"]["ProjectPlanApplicationPage"];
export type ProjectPlanApplyRequest = components["schemas"]["ProjectPlanApplyRequest"];

function parseJson(value: unknown): unknown {
  if (typeof value !== "string") return value;
  try { return JSON.parse(value) as unknown; } catch { return undefined; }
}

function validPlan(response: ProjectPlanPreviewResponse, projectId: string): boolean {
  const { plan, snapshot, citations } = response;
  if (response.projectId.toLowerCase() !== projectId.toLowerCase() || snapshot.project.id.toLowerCase() !== projectId.toLowerCase()) return false;
  if ([...snapshot.tasks, ...snapshot.stages, ...snapshot.milestones].some(item => item.projectId.toLowerCase() !== projectId.toLowerCase())) return false;
  const evidence = new Set(["S1", ...citations.map(item => item.id)]);
  if (evidence.size !== citations.length + 1) return false;
  if ([plan, ...plan.stages, ...plan.milestones, ...plan.tasks].some(item => new Set(item.citationIds).size !== item.citationIds.length || item.citationIds.some(id => !evidence.has(id)))) return false;
  if (plan.status === "insufficient_evidence") return plan.stages.length + plan.milestones.length + plan.tasks.length === 0;
  if (!plan.stages.length || !plan.milestones.length || !plan.tasks.length || !plan.citationIds.length) return false;
  const stages = new Set(plan.stages.map(item => item.id));
  const milestones = new Map(plan.milestones.map(item => [item.id, item]));
  const tasks = new Set(plan.tasks.map(item => item.id));
  if (stages.size !== plan.stages.length || milestones.size !== plan.milestones.length || tasks.size !== plan.tasks.length) return false;
  if (plan.milestones.some(item => !stages.has(item.stageId))) return false;
  if (plan.tasks.some(item => !stages.has(item.stageId) || (item.milestoneId !== null && milestones.get(item.milestoneId)?.stageId !== item.stageId) || item.dependsOn.includes(item.id) || new Set(item.dependsOn).size !== item.dependsOn.length || item.dependsOn.some(id => !tasks.has(id)))) return false;
  const resolved = new Set<string>();
  while (resolved.size < tasks.size) {
    const ready = plan.tasks.filter(task => !resolved.has(task.id) && task.dependsOn.every(id => resolved.has(id)));
    if (!ready.length) return false;
    ready.forEach(task => resolved.add(task.id));
  }
  return true;
}

function validApplication(value: ProjectPlanApplication, projectId: string): boolean {
  if (value.projectId !== projectId || value.plan.status !== "planned") return false;
  const groups = [[value.plan.stages, value.stageIds], [value.plan.milestones, value.milestoneIds], [value.plan.tasks, value.taskIds]] as const;
  const ids: string[] = [];
  for (const [items, mapping] of groups) {
    if (Object.keys(mapping).length !== items.length || items.some(item => !mapping[item.id])) return false;
    ids.push(...Object.values(mapping));
  }
  return new Set(ids).size === ids.length;
}

export async function applyProjectPlan({projectId, csrfToken, payload, signal}: {
  projectId: string; csrfToken: string; payload: ProjectPlanApplyRequest; signal: AbortSignal;
}): Promise<ProjectPlanApplication> {
  const context="POST /api/v1/projects/{project_id}/plans";
  try {
    const {data,error,response}=await createCairnClient({baseUrl:apiOrigins.identity}).POST("/api/v1/projects/{project_id}/plans",{
      params:{path:{project_id:projectId},header:{"X-CSRF-Token":csrfToken}},body:payload,parseAs:"text",signal,
    });
    if(response.status!==200 && response.status!==201) throw knowledgeResponseError(parseJson(error),response,context);
    const parsed=parseJson(data);
    if(!matchesComponentSchema("ProjectPlanApplicationResponse",parsed) || !validApplication(parsed,projectId) || parsed.operationId!==payload.operationId) throw knowledgeContractError(context);
    return parsed;
  } catch(error) {throw knowledgeRequestError(error,context,signal);}
}

export async function fetchAppliedProjectPlan({projectId,operationId,signal}:{projectId:string;operationId:string;signal:AbortSignal}):Promise<ProjectPlanApplication> {
  const context="GET /api/v1/projects/{project_id}/plans/{operation_id}";
  try {
    const {data,error,response}=await createCairnClient({baseUrl:apiOrigins.identity}).GET("/api/v1/projects/{project_id}/plans/{operation_id}",{
      params:{path:{project_id:projectId,operation_id:operationId}},parseAs:"text",signal,
    });
    if(response.status!==200) throw knowledgeResponseError(parseJson(error),response,context);
    const parsed=parseJson(data);
    if(!matchesComponentSchema("ProjectPlanApplicationResponse",parsed) || !validApplication(parsed,projectId) || parsed.operationId!==operationId) throw knowledgeContractError(context);
    return parsed;
  } catch(error) {throw knowledgeRequestError(error,context,signal);}
}

export async function fetchAppliedProjectPlans({projectId,cursor,signal}:{projectId:string;cursor?:string|null;signal:AbortSignal}):Promise<ProjectPlanApplicationPage> {
  const context="GET /api/v1/projects/{project_id}/plans";
  try {
    const {data,error,response}=await createCairnClient({baseUrl:apiOrigins.identity}).GET("/api/v1/projects/{project_id}/plans",{
      params:{path:{project_id:projectId},query:{cursor:cursor??undefined,limit:10}},parseAs:"text",signal,
    });
    if(response.status!==200) throw knowledgeResponseError(parseJson(error),response,context);
    const parsed=parseJson(data);
    if(!matchesComponentSchema("ProjectPlanApplicationPage",parsed) || parsed.items.some(item=>!validApplication(item,projectId))) throw knowledgeContractError(context);
    return parsed;
  } catch(error) {throw knowledgeRequestError(error,context,signal);}
}

export async function previewProjectPlan({projectId, csrfToken, signal}: {
  projectId: string; csrfToken: string; signal: AbortSignal;
}): Promise<ProjectPlanPreviewResponse> {
  const context = "POST /api/v1/projects/{project_id}/plan-preview";
  try {
    const {data,error,response} = await createCairnClient({baseUrl:apiOrigins.identity}).POST(
      "/api/v1/projects/{project_id}/plan-preview",
      {params:{path:{project_id:projectId},header:{"X-CSRF-Token":csrfToken}},parseAs:"text",signal},
    );
    if(response.status !== 200) throw knowledgeResponseError(parseJson(error),response,context);
    const parsed = parseJson(data);
    if(!matchesComponentSchema("ProjectPlanPreviewResponse",parsed) || !validPlan(parsed,projectId)) throw knowledgeContractError(context);
    return parsed;
  } catch(error) { throw knowledgeRequestError(error,context,signal); }
}
