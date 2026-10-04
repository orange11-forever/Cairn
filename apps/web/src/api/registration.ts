import { createCairnClient, matchesComponentSchema, type components } from "@cairn/sdk";
import { apiOrigins } from "./config.ts";
import { ApiError } from "./errors.ts";
import { parseApiErrorResponse } from "./parseApiErrorResponse.ts";

export type RegistrationInput = components["schemas"]["RegistrationRequest"];
export type ResendInput = components["schemas"]["RegistrationResendRequest"];
export type VerificationInput = components["schemas"]["RegistrationVerifyRequest"];
type Accepted = components["schemas"]["RegistrationAccepted"];
type Verified = components["schemas"]["RegistrationVerified"];
type Availability = components["schemas"]["RegistrationAvailability"];

async function request<T>(parent: AbortSignal, expectedStatus: 200 | 202, run: (signal: AbortSignal) => Promise<{ data?: unknown; error?: unknown; response: Response }>, validate: (data: unknown) => data is T): Promise<T> {
  const deadline = new AbortController();
  const timer = setTimeout(() => deadline.abort(), 15_000);
  const signal = AbortSignal.any([parent, deadline.signal]);
  try {
    const { data, error, response } = await run(signal);
    if (!response.ok) {
      const detail = parseApiErrorResponse(error, { message: "暂时无法完成操作，请重试", code: "http_error", traceId: response.headers.get("X-Request-ID") });
      const retry = Number(response.headers.get("Retry-After"));
      throw new ApiError("http", detail.message, { status: response.status, code: detail.code, traceId: detail.traceId, retryAfterSeconds: Number.isFinite(retry) && retry > 0 ? retry : null });
    }
    if (response.status !== expectedStatus) throw new ApiError("contract", "服务器返回的操作状态不正确，请联系管理员");
    if (!validate(data)) throw new ApiError("contract", "服务器返回的数据格式不正确，请联系管理员");
    return data;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (signal.aborted) throw new ApiError(parent.aborted ? "aborted" : "timeout", parent.aborted ? "请求已被取消" : "请求超时，请重试");
    throw new ApiError("network", "无法连接服务器，请检查网络", { cause: error });
  } finally { clearTimeout(timer); }
}
const client = () => createCairnClient({ baseUrl: apiOrigins.identity });
export function registrationAvailability(signal: AbortSignal): Promise<Availability> {
  return request(signal, 200, signal => client().GET("/api/v1/auth/registration", { signal }), (data): data is Availability => matchesComponentSchema("RegistrationAvailability", data));
}
export function register(input: RegistrationInput, signal: AbortSignal): Promise<Accepted> {
  return request(signal, 202, signal => client().POST("/api/v1/auth/register", { body: { ...input, email: input.email.trim() }, signal }), (data): data is Accepted => matchesComponentSchema("RegistrationAccepted", data));
}
export function resendRegistration(input: ResendInput, signal: AbortSignal): Promise<Accepted> {
  return request(signal, 202, signal => client().POST("/api/v1/auth/register/resend", { body: input, signal }), (data): data is Accepted => matchesComponentSchema("RegistrationAccepted", data));
}
export function verifyRegistration(input: VerificationInput, signal: AbortSignal): Promise<Verified> {
  return request(signal, 200, signal => client().POST("/api/v1/auth/register/verify", { body: input, signal }), (data): data is Verified => matchesComponentSchema("RegistrationVerified", data));
}
