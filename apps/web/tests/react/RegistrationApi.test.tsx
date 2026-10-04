import { afterEach, expect, test, vi } from "vitest";
import { register, registrationAvailability, resendRegistration, verifyRegistration } from "../../src/api/registration.ts";

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
const input = { email: "new@example.com", password: "original-password-2026" };

test("registration responses require all fields and verification cannot consume session identity", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ registrationReceipt: "receipt", resendAfterSeconds: 60 }, { status: 202 })));
  await expect(register(input, new AbortController().signal)).rejects.toMatchObject({ kind: "contract" });
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ user: {}, organization: {}, membership: {}, csrfToken: "secret" })));
  await expect(verifyRegistration({ token: "proof", password: input.password }, new AbortController().signal)).rejects.toMatchObject({ kind: "contract" });
});

test("resend propagates trace IDs and Retry-After for cooldown recovery", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ code: "registration_rate_limited", message: "稍后重试", traceId: "private-trace" }, { status: 429, headers: { "Retry-After": "42", "X-Request-ID": "private-trace" } })));
  await expect(resendRegistration({ ...input, registrationReceipt: "receipt" }, new AbortController().signal)).rejects.toMatchObject({ kind: "http", status: 429, code: "registration_rate_limited", traceId: "private-trace", retryAfterSeconds: 42 });
});

test("SMTP send requests have a bounded fifteen-second deadline and release the timer", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("fetch", vi.fn((request: Request) => new Promise<Response>((_resolve, reject) => request.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true }))));
  const result = register(input, new AbortController().signal);
  const assertion = expect(result).rejects.toMatchObject({ kind: "timeout" });
  await vi.advanceTimersByTimeAsync(15_000);
  await assertion;
  expect(vi.getTimerCount()).toBe(0);
});

test("parent cancellation remains cancellation rather than network/timeout", async () => {
  const parent = new AbortController();
  vi.stubGlobal("fetch", vi.fn((request: Request) => new Promise<Response>((_resolve, reject) => request.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true }))));
  const result = verifyRegistration({ token: "proof", password: input.password }, parent.signal);
  const assertion = expect(result).rejects.toMatchObject({ kind: "aborted" });
  await Promise.resolve(); parent.abort();
  await assertion;
});

const accepted = { message: "accepted", registrationReceipt: "receipt", resendAfterSeconds: 60 };
test.each([
  ["availability", 202], ["availability", 201],
  ["register", 200], ["register", 201],
  ["resend", 200], ["resend", 201],
  ["verify", 202], ["verify", 201],
] as const)("%s rejects an otherwise valid body at wrong-success status %i", async (operation, status) => {
  const body = operation === "availability" ? { enabled: true } : operation === "verify" ? { message: "verified" } : accepted;
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(body, { status })));
  const signal = new AbortController().signal;
  const result = operation === "availability" ? registrationAvailability(signal)
    : operation === "register" ? register(input, signal)
    : operation === "resend" ? resendRegistration({ ...input, registrationReceipt: "receipt" }, signal)
    : verifyRegistration({ token: "proof", password: input.password }, signal);
  await expect(result).rejects.toMatchObject({ kind: "contract" });
});
