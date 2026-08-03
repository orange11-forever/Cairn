import { z } from "zod";

import { NonEmptyStringSchema, ResourceIdSchema } from "./primitives.ts";

export const DOCUMENT_STATUSES = ["completed", "processing", "failed"] as const;
export const KnownStatusSchema = z.enum(DOCUMENT_STATUSES);
export type KnownStatus = z.infer<typeof KnownStatusSchema>;

export const DocumentDtoSchema = z.object({
  id: ResourceIdSchema,
  title: NonEmptyStringSchema,
  status: KnownStatusSchema,
});
export type DocumentDto = z.infer<typeof DocumentDtoSchema>;

export const DocumentsResponseSchema = z.array(DocumentDtoSchema);
export type DocumentsResponse = z.infer<typeof DocumentsResponseSchema>;
