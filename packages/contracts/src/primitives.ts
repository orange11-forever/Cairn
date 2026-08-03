import { z } from "zod";

export const ResourceIdSchema = z.uuid();
export type ResourceId = z.infer<typeof ResourceIdSchema>;

export const NonEmptyStringSchema = z.string().transform((value) => value.trim()).refine(
  (value) => value !== "",
  { message: "不能是空字符串" },
);

export const IsoDateTimeSchema = z.iso.datetime();
export type IsoDateTime = z.infer<typeof IsoDateTimeSchema>;
