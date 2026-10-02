import { createCairnClient, matchesComponentSchema, type components } from "@cairn/sdk";
import { apiOrigins } from "./config.ts";
import { ApiError } from "./errors.ts";
import { parseApiErrorResponse } from "./parseApiErrorResponse.ts";

export type OAuthProvider = "github" | "feishu";
export type LinkedIdentities = components["schemas"]["LinkedIdentitiesResponse"];
export type LinkedIdentity = components["schemas"]["LinkedIdentityResponse"];
export type ProviderStatus = components["schemas"]["OAuthProviderResponse"];
const client = () => createCairnClient({ baseUrl: apiOrigins.identity });

async function request<T>(signal: AbortSignal, run: (signal: AbortSignal) => Promise<T>): Promise<T> {
  const deadline = AbortSignal.timeout(10_000);
  const combined = AbortSignal.any([signal, deadline]);
  try { return await run(combined); } catch (error) {
    if (combined.aborted) throw new ApiError(signal.aborted ? "aborted" : "timeout", "请求已取消或超时，请重试");
    if (error instanceof ApiError) throw error;
    throw new ApiError("network", "无法连接服务器，请重试", { cause: error });
  }
}

function failure(error: unknown, response: Response): ApiError {
  const detail = parseApiErrorResponse(error, { message: "登录方式操作失败，请重试", code: "http_error", traceId: null });
  return new ApiError("http", detail.message, { code: detail.code, status: response.status, traceId: detail.traceId });
}

export function startOAuth({ provider, intent, csrfToken }: {
  provider: OAuthProvider; intent: "login" | "link"; csrfToken?: string;
}, signal: AbortSignal): Promise<string> {
  return request(signal, async (requestSignal) => {
    const { data, error, response } = await client().POST("/api/v1/auth/oauth/{provider}/start", {
      params: { path: { provider } },
      body: { intent, returnTo: intent === "link" ? "/account/identities" : "/projects" },
      headers: csrfToken === undefined ? {} : { "X-CSRF-Token": csrfToken }, signal: requestSignal,
    });
    if (!response.ok) throw failure(error, response);
    if (!matchesComponentSchema("OAuthStartResponse", data)) throw new ApiError("contract", "授权响应无效，请重试");
    const url = new URL(data.authorizationUrl);
    const expected = provider === "github" ? "https://github.com/login/oauth/authorize" :
      "https://accounts.feishu.cn/open-apis/authen/v1/authorize";
    if (url.origin + url.pathname !== expected || url.username || url.password || url.hash || !url.searchParams.get("state")) {
      throw new ApiError("contract", "授权地址无效，请联系管理员");
    }
    return data.authorizationUrl;
  });
}

export function fetchOAuthProviders(signal: AbortSignal): Promise<ProviderStatus[]> {
  return request(signal, async (requestSignal) => {
    const { data, error, response } = await client().GET("/api/v1/auth/oauth/providers", { signal: requestSignal });
    if (!response.ok) throw failure(error, response);
    if (!Array.isArray(data) || data.length !== 2 || new Set(data.map(item => item.provider)).size !== 2 ||
        !data.every(item => matchesComponentSchema("OAuthProviderResponse", item))) {
      throw new ApiError("contract", "登录方式响应无效，请重试");
    }
    return data;
  });
}

export function fetchLinkedIdentities(signal: AbortSignal): Promise<LinkedIdentities> {
  return request(signal, async (requestSignal) => {
    const { data, error, response } = await client().GET("/api/v1/auth/identities", { signal: requestSignal });
    if (!response.ok) throw failure(error, response);
    if (!matchesComponentSchema("LinkedIdentitiesResponse", data)) throw new ApiError("contract", "绑定信息响应无效，请重试");
    return data;
  });
}

export function unlinkIdentity({ id, csrfToken }: { id: string; csrfToken: string }, signal: AbortSignal): Promise<void> {
  return request(signal, async (requestSignal) => {
    const { error, response } = await client().DELETE("/api/v1/auth/identities/{identity_id}", {
      params: { path: { identity_id: id } }, headers: { "X-CSRF-Token": csrfToken }, signal: requestSignal,
    });
    if (!response.ok) throw failure(error, response);
  });
}
