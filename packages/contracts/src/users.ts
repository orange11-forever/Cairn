import { z } from "zod";

import { NonEmptyStringSchema, ResourceIdSchema } from "./primitives.ts";

export const USER_ROLES = ["owner", "admin", "member", "viewer"] as const;
export const UserRoleSchema = z.enum(USER_ROLES);
export type UserRole = z.infer<typeof UserRoleSchema>;

export const UserDtoSchema = z.object({
  id: ResourceIdSchema,
  email: z.email(),
  displayName: NonEmptyStringSchema.optional(),
  role: UserRoleSchema,
});
export type UserDto = z.infer<typeof UserDtoSchema>;
