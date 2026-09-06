import { ApiError } from "./errors.ts";
import { parseApiErrorResponse } from "./parseApiErrorResponse.ts";

function retryAfterSeconds(response: Response): number | null {
  const value = response.headers.get("Retry-After");
  if (value === null || !/^\d+$/.test(value)) return null;
  const seconds = Number(value);
  return Number.isSafeInteger(seconds) && seconds >= 1 ? seconds : null;
}

export function knowledgeResponseError(
  error: unknown,
  response: Response,
  context: string,
): ApiError {
  const detail = parseApiErrorResponse(error, {
    message: `服务器返回 ${response.status}`,
    code: "http_error",
    traceId: response.headers.get("X-Request-ID"),
  });
  return new ApiError("http", detail.message, {
    status: response.status,
    code: detail.code,
    traceId: detail.traceId,
    retryAfterSeconds: retryAfterSeconds(response),
    context,
  });
}

export function knowledgeContractError(context: string): ApiError {
  console.error(`[contract] ${context} 响应不符合生成的 OpenAPI 契约`);
  return new ApiError("contract", "服务器返回的数据格式不正确，请联系管理员", {
    context,
  });
}

export function knowledgeRequestError(
  error: unknown,
  context: string,
  signal: AbortSignal,
): ApiError {
  if (error instanceof ApiError) return error;
  if (signal.aborted) {
    return new ApiError("aborted", "请求已被取消", { context, cause: error });
  }
  return new ApiError("network", "无法连接服务器，请检查网络", {
    context,
    cause: error,
  });
}
