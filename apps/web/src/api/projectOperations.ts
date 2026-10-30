import { createCairnClient, matchesComponentSchema, type components } from "@cairn/sdk";
import { apiOrigins } from "./config.ts";
import { knowledgeContractError, knowledgeRequestError, knowledgeResponseError } from "./knowledgeRequest.ts";

export type OperationPreview = components["schemas"]["ProjectOperationPreviewResponse"];
export type OperationRequest = components["schemas"]["ProjectOperationApplyRequest"];
export type ProjectOperation = components["schemas"]["ProjectOperationResponse"];
export type OperationPage = components["schemas"]["ProjectOperationPage"];
export type ProjectAction = ProjectOperation["action"];

function parseJson(value: unknown): unknown {
  if (typeof value !== "string") return value;
  try { return JSON.parse(value) as unknown; } catch { return undefined; }
}

export async function previewProjectOperation({projectId, csrfToken, intent, signal}: {
  projectId: string; csrfToken: string; intent: string; signal: AbortSignal;
}): Promise<OperationPreview> {
  const context="POST /api/v1/projects/{project_id}/operation-preview";
  try {
    const {data,error,response}=await createCairnClient({baseUrl:apiOrigins.identity}).POST("/api/v1/projects/{project_id}/operation-preview",{
      params:{path:{project_id:projectId},header:{"X-CSRF-Token":csrfToken}},body:{intent},parseAs:"text",signal,
    });
    if(response.status!==200) throw knowledgeResponseError(parseJson(error),response,context);
    const parsed=parseJson(data);
    if(!matchesComponentSchema("ProjectOperationPreviewResponse",parsed) || parsed.projectId!==projectId || parsed.snapshot.project.id!==projectId || parsed.intent!==intent) throw knowledgeContractError(context);
    return parsed;
  } catch(error) {throw knowledgeRequestError(error,context,signal);}
}

export async function applyProjectOperation({projectId,csrfToken,payload,signal}:{projectId:string;csrfToken:string;payload:OperationRequest;signal:AbortSignal}):Promise<ProjectOperation> {
  const context="POST /api/v1/projects/{project_id}/operations";
  try {
    const {data,error,response}=await createCairnClient({baseUrl:apiOrigins.identity}).POST("/api/v1/projects/{project_id}/operations",{
      params:{path:{project_id:projectId},header:{"X-CSRF-Token":csrfToken}},body:payload,parseAs:"text",signal,
    });
    if(response.status!==200 && response.status!==201) throw knowledgeResponseError(parseJson(error),response,context);
    const parsed=parseJson(data);
    if(!matchesComponentSchema("ProjectOperationResponse",parsed) || parsed.projectId!==projectId || parsed.operationId!==payload.operationId) throw knowledgeContractError(context);
    return parsed;
  } catch(error) {throw knowledgeRequestError(error,context,signal);}
}

export async function fetchProjectOperation({projectId,operationId,signal}:{projectId:string;operationId:string;signal:AbortSignal}):Promise<ProjectOperation> {
  const context="GET /api/v1/projects/{project_id}/operations/{operation_id}";
  try {
    const {data,error,response}=await createCairnClient({baseUrl:apiOrigins.identity}).GET("/api/v1/projects/{project_id}/operations/{operation_id}",{
      params:{path:{project_id:projectId,operation_id:operationId}},parseAs:"text",signal,
    });
    if(response.status!==200) throw knowledgeResponseError(parseJson(error),response,context);
    const parsed=parseJson(data);
    if(!matchesComponentSchema("ProjectOperationResponse",parsed) || parsed.projectId!==projectId || parsed.operationId!==operationId) throw knowledgeContractError(context);
    return parsed;
  } catch(error) {throw knowledgeRequestError(error,context,signal);}
}

export async function fetchProjectOperations({projectId,cursor,signal}:{projectId:string;cursor?:string|null;signal:AbortSignal}):Promise<OperationPage> {
  const context="GET /api/v1/projects/{project_id}/operations";
  try {
    const {data,error,response}=await createCairnClient({baseUrl:apiOrigins.identity}).GET("/api/v1/projects/{project_id}/operations",{
      params:{path:{project_id:projectId},query:{cursor:cursor??undefined,limit:10}},parseAs:"text",signal,
    });
    if(response.status!==200) throw knowledgeResponseError(parseJson(error),response,context);
    const parsed=parseJson(data);
    if(!matchesComponentSchema("ProjectOperationPage",parsed) || parsed.items.some(item=>item.projectId!==projectId)) throw knowledgeContractError(context);
    return parsed;
  } catch(error) {throw knowledgeRequestError(error,context,signal);}
}
