import { createCairnClient, matchesComponentSchema, type components } from "@cairn/sdk";
import { apiOrigins } from "./config.ts";
import { knowledgeContractError, knowledgeRequestError, knowledgeResponseError } from "./knowledgeRequest.ts";
import type { Project } from "./projects.ts";

export type ScheduleScenario=components["schemas"]["ProjectScheduleResponse"];
export type CapacityRequest=components["schemas"]["ProjectCapacityUpdateRequest"];
function parseJson(value:unknown):unknown {if(typeof value!=="string")return value;try{return JSON.parse(value) as unknown;}catch{return undefined;}}
export async function fetchScheduleScenario({projectId,startDate,signal}:{projectId:string;startDate:string;signal:AbortSignal}):Promise<ScheduleScenario> {
  const context="GET /api/v1/projects/{project_id}/schedule-scenario";
  try {
    const {data,error,response}=await createCairnClient({baseUrl:apiOrigins.identity}).GET("/api/v1/projects/{project_id}/schedule-scenario",{params:{path:{project_id:projectId},query:{startDate}},parseAs:"text",signal});
    if(response.status!==200)throw knowledgeResponseError(parseJson(error),response,context);
    const parsed=parseJson(data);
    if(!matchesComponentSchema("ProjectScheduleResponse",parsed) || parsed.project.id!==projectId || parsed.startDate!==startDate || (parsed.gaps.length>0 && (parsed.completionDate!==null || parsed.schedule.length>0 || parsed.criticalChain!==null)))throw knowledgeContractError(context);
    return parsed;
  }catch(error){throw knowledgeRequestError(error,context,signal);}
}
export async function updateProjectCapacity({projectId,csrfToken,payload,signal}:{projectId:string;csrfToken:string;payload:CapacityRequest;signal:AbortSignal}):Promise<Project> {
  const context="PATCH /api/v1/projects/{project_id}/capacity";
  try {
    const {data,error,response}=await createCairnClient({baseUrl:apiOrigins.identity}).PATCH("/api/v1/projects/{project_id}/capacity",{params:{path:{project_id:projectId},header:{"X-CSRF-Token":csrfToken}},body:payload,parseAs:"text",signal});
    if(response.status!==200)throw knowledgeResponseError(parseJson(error),response,context);
    const parsed=parseJson(data);
    if(!matchesComponentSchema("ProjectResponse",parsed) || parsed.id!==projectId || parsed.revision!==payload.expectedProjectRevision+1)throw knowledgeContractError(context);
    return parsed;
  }catch(error){throw knowledgeRequestError(error,context,signal);}
}
