import { matchesComponentSchema } from "@cairn/sdk";

export interface ParsedApiErrorResponse {
  message: string;
  code: string | null;
  traceId: string | null;
}

export function parseApiErrorResponse(
  body: unknown,
  fallback: ParsedApiErrorResponse,
): ParsedApiErrorResponse {
  if (!matchesComponentSchema("ErrorBody", body)) return fallback;

  const message = body.message.trim();
  return {
    message: message ? message : fallback.message,
    code: body.code.trim() || fallback.code,
    traceId: body.traceId.trim() || fallback.traceId,
  };
}
