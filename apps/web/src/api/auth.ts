import {
  createCairnClient,
  matchesComponentSchema,
  type components,
} from "@cairn/sdk";

import { apiOrigins } from "./config.ts";
import { ApiError } from "./errors.ts";
import { parseApiErrorResponse } from "./parseApiErrorResponse.ts";

export type IdentityContext = components["schemas"]["IdentityContextResponse"];
export type LoginInput = components["schemas"]["LoginRequest"];
const IDENTITY_TIMEOUT_MS = 3_000;

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

function parseIdentityContext(data: unknown, context: string): IdentityContext {
  if (matchesComponentSchema("IdentityContextResponse", data)) return data;
  console.error(`[contract] ${context} 响应不符合 OpenAPI IdentityContextResponse`);
  throw new ApiError("contract", "服务器返回的数据格式不正确，请联系管理员", { context });
}

async function identityRequest<T>(
  context: string,
  parentSignal: AbortSignal,
  run: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
  const deadline = new AbortController();
  const timer = setTimeout(() => deadline.abort(), IDENTITY_TIMEOUT_MS);
  const signal = AbortSignal.any([parentSignal, deadline.signal]);

  try {
    return await run(signal);
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (signal.aborted) {
      if (deadline.signal.aborted && !parentSignal.aborted) {
        throw new ApiError("timeout", "请求超时，请重试", { context, cause: error });
      }
      throw new ApiError("aborted", "请求已被取消", { context, cause: error });
    }
    throw new ApiError("network", "无法连接服务器，请检查网络", {
      context,
      cause: error,
    });
  } finally {
    clearTimeout(timer);
  }
}

export async function login(input: LoginInput, signal: AbortSignal): Promise<IdentityContext> {
  return browserLoginLock(signal, () => identityRequest("POST /api/v1/login", signal, async (requestSignal) => {
    const { data, error, response } = await identityClient().POST("/api/v1/login", {
      body: { email: input.email.trim(), password: input.password },
      signal: requestSignal,
    });
    if (data !== undefined) {
      return parseIdentityContext(data, "POST /api/v1/login");
    }
    throw responseError(error, response, "POST /api/v1/login");
  }));
}

export async function restoreSession(signal: AbortSignal): Promise<IdentityContext> {
  return identityRequest("GET /api/v1/session", signal, async (requestSignal) => {
    const { data, error, response } = await identityClient().GET("/api/v1/session", {
      signal: requestSignal,
    });
    if (data !== undefined) {
      return parseIdentityContext(data, "GET /api/v1/session");
    }
    const failure = responseError(error, response, "GET /api/v1/session");
    throw failure;
  });
}

export async function logoutSession(csrfToken: string, signal: AbortSignal): Promise<void> {
  return browserLoginLock(signal, () => identityRequest("POST /api/v1/logout", signal, async (requestSignal) => {
    const { error, response } = await identityClient().POST("/api/v1/logout", {
      headers: { "X-CSRF-Token": csrfToken },
      signal: requestSignal,
    });
    if (response.ok) return;
    throw responseError(error, response, "POST /api/v1/logout");
  }));
}


function browserLoginLock<T>(signal: AbortSignal, run: () => Promise<T>): Promise<T> {
  return navigator.locks ? navigator.locks.request("cairn-login-context", { signal }, run).then(value => value) : run();
}

export async function prepareLoginContext(signal: AbortSignal): Promise<void> {
  // One browser cookie context must be established before any tab can sign in.
  // Web Locks serialize initially cookieless tabs, including delayed responses.
  if (!navigator.locks) throw new ApiError("contract", "请使用支持安全登录的最新浏览器，并通过 HTTPS 或 localhost 访问", { context: "login context" });
  return navigator.locks.request("cairn-login-context", { signal }, async () =>
    identityRequest("POST /api/v1/auth/login-context", signal, async (requestSignal) => {
      const { error, response } = await identityClient().POST("/api/v1/auth/login-context", { signal: requestSignal });
      if (!response.ok) throw responseError(error, response, "POST /api/v1/auth/login-context");
    }));
}


export async function finalizeOAuthLogin(signal: AbortSignal): Promise<IdentityContext> {
  return browserLoginLock(signal, () => identityRequest("POST /api/v1/auth/oauth/finalize", signal, async (requestSignal) => {
    const { data, error, response } = await identityClient().POST("/api/v1/auth/oauth/finalize", { signal: requestSignal });
    if (data !== undefined) return parseIdentityContext(data, "POST /api/v1/auth/oauth/finalize");
    throw responseError(error, response, "POST /api/v1/auth/oauth/finalize");
  }));
}
