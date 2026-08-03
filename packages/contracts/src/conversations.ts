import { z } from "zod";

import { IsoDateTimeSchema, NonEmptyStringSchema, ResourceIdSchema } from "./primitives.ts";

export const AskRequestSchema = z.object({ question: NonEmptyStringSchema });
export type AskRequest = z.infer<typeof AskRequestSchema>;

export const CitationDtoSchema = z.object({
  documentId: ResourceIdSchema,
  documentTitle: NonEmptyStringSchema,
  snippet: NonEmptyStringSchema,
  anchor: NonEmptyStringSchema.optional(),
  score: z.number().min(0).max(1).optional(),
});
export type CitationDto = z.infer<typeof CitationDtoSchema>;

export const GroundedAnswerDtoSchema = z.object({
  kind: z.literal("grounded_answer"),
  id: ResourceIdSchema,
  content: NonEmptyStringSchema,
  createdAt: IsoDateTimeSchema,
  citations: z.array(CitationDtoSchema).min(1),
});

export const NotFoundAnswerDtoSchema = z.object({
  kind: z.literal("not_found"),
  id: ResourceIdSchema,
  createdAt: IsoDateTimeSchema,
});

export const AskResponseSchema = z.discriminatedUnion("kind", [
  GroundedAnswerDtoSchema,
  NotFoundAnswerDtoSchema,
]);
export type GroundedAnswerDto = z.infer<typeof GroundedAnswerDtoSchema>;
export type NotFoundAnswerDto = z.infer<typeof NotFoundAnswerDtoSchema>;
export type AskResponseDto = z.infer<typeof AskResponseSchema>;
