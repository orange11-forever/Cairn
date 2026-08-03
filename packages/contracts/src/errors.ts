import { z } from "zod";

export const ApiErrorResponseSchema = z.looseObject({
  message: z.string().optional(),
  code: z.string().optional(),
  traceId: z.string().optional(),
});
export type ApiErrorResponse = z.infer<typeof ApiErrorResponseSchema>;
