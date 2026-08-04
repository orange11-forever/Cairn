import { createCairnClient, type components } from "@cairn/sdk";

import { apiOrigins } from "./config.ts";
import { ApiError } from "./errors.ts";
import { parseApiErrorResponse } from "./parseApiErrorResponse.ts";

export type IdentityContext = components["schemas"]["IdentityContextResponse"];
export type LoginInput = components["schemas"]["LoginRequest"];

function identityClient() {
  return createCairnClient({ baseUrl: apiOrigins.identity });
}

function responseError(error: unknown, response: Response, context: string): ApiError {
  const detail = parseApiErrorResponse(error, {
    message: `服务器返回 ${response.status}`,
    code: "http_error",
    traceId: response.headers.get("X-Request-ID"),
  });
  return new ApiError("http", detail.message, {
    status: response.status,
    code: detail.code,
    traceId: detail.traceId,
    context,
  });
}

export async function login(input: LoginInput, signal: AbortSignal): Promise<IdentityContext> {
  try {
    const { data, error, response } = await identityClient().POST("/api/v1/login", {
      body: { email: input.email.trim(), password: input.password },
      signal,
    });
    if (data !== undefined) return data;
    throw responseError(error, response, "POST /api/v1/login");
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof Error && error.name === "AbortError") {
      throw new ApiError("aborted", "请求已被取消", { context: "POST /api/v1/login" });
    }
    throw new ApiError("network", "无法连接服务器，请检查网络", {
      context: "POST /api/v1/login",
      cause: error,
    });
  }
}

export async function restoreSession(signal: AbortSignal): Promise<IdentityContext> {
  try {
    const { data, error, response } = await identityClient().GET("/api/v1/session", { signal });
    if (data !== undefined) return data;
    throw responseError(error, response, "GET /api/v1/session");
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError("network", "无法连接服务器，请检查网络", {
      context: "GET /api/v1/session",
      cause: error,
    });
  }
}

export async function logoutSession(csrfToken: string, signal: AbortSignal): Promise<void> {
  try {
    const { error, response } = await identityClient().POST("/api/v1/logout", {
      headers: { "X-CSRF-Token": csrfToken },
      signal,
    });
    if (response.ok) return;
    throw responseError(error, response, "POST /api/v1/logout");
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError("network", "无法连接服务器，请检查网络", {
      context: "POST /api/v1/logout",
      cause: error,
    });
  }
}
