import { ApiErrorResponseSchema } from "@cairn/contracts";

export interface ParsedApiErrorResponse {
  message: string;
  code: string | null;
  traceId: string | null;
}

export function parseApiErrorResponse(
  body: unknown,
  fallback: ParsedApiErrorResponse,
): ParsedApiErrorResponse {
  const parsed = ApiErrorResponseSchema.safeParse(body);
  if (!parsed.success) return fallback;

  const message = parsed.data.message?.trim();
  return {
    message: message ? message : fallback.message,
    code: parsed.data.code?.trim() || fallback.code,
    traceId: parsed.data.traceId?.trim() || fallback.traceId,
  };
}
