import { DOCUMENT_STATUSES, ResourceIdSchema, type KnownStatus } from "@cairn/contracts";
import { z } from "zod";

export { DOCUMENT_STATUSES };
export type { KnownStatus };

/** Frontend-only status. Unknown transport values remain visible instead of hiding documents. */
export const DocumentStatusSchema = z.enum([...DOCUMENT_STATUSES, "unknown"]);
export type DocumentStatus = z.infer<typeof DocumentStatusSchema>;

const LenientTitleSchema = z.unknown().transform((value) => {
  if (typeof value === "string" && value.trim() !== "") return value.trim();
  return "未命名文档";
});

const LenientStatusSchema = DocumentStatusSchema.catch("unknown");

export const DocumentSchema = z.object({
  id: ResourceIdSchema,
  title: LenientTitleSchema,
  status: LenientStatusSchema,
});
export type Document = z.infer<typeof DocumentSchema>;
