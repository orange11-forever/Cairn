import { z } from "zod";

import { NonEmptyStringSchema, ResourceIdSchema } from "./primitives.ts";

export const UploadFileDtoSchema = z.object({
  name: NonEmptyStringSchema,
  size: z.number().int().nonnegative(),
});
export type UploadFileDto = z.infer<typeof UploadFileDtoSchema>;

export const UploadRequestSchema = z.object({ files: z.array(UploadFileDtoSchema).min(1) });
export type UploadRequest = z.infer<typeof UploadRequestSchema>;

export const UploadJobDtoSchema = z.object({
  id: ResourceIdSchema,
  documentTitle: NonEmptyStringSchema,
  status: z.literal("pending"),
});
export type UploadJobDto = z.infer<typeof UploadJobDtoSchema>;

export const UploadResponseSchema = z.object({
  accepted: z.number().int().nonnegative(),
  jobs: z.array(UploadJobDtoSchema),
});
export type UploadResponse = z.infer<typeof UploadResponseSchema>;
