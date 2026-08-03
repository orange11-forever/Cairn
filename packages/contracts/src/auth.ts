import { z } from "zod";

import { UserDtoSchema } from "./users.ts";

export const LoginRequestSchema = z.object({ email: z.email(), password: z.string().min(1) });
export type LoginRequest = z.infer<typeof LoginRequestSchema>;

export const LoginResponseSchema = z.object({ user: UserDtoSchema });
export type LoginResponse = z.infer<typeof LoginResponseSchema>;
