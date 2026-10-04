import { afterEach, expect, test, vi } from "vitest";
import { prepareLoginContext } from "../../src/api/auth.ts";

afterEach(() => vi.unstubAllGlobals());

test("initially cookieless tabs serialize bootstrap until the previous response arrives", async () => {
  let queue = Promise.resolve();
  vi.stubGlobal("navigator", { locks: { request: (_name: string, _options: unknown, run: () => Promise<void>) => {
    const next = queue.then(run); queue = next.catch(() => undefined); return next;
  } } });
  let finish!: (response: Response) => void;
  const delayed = new Promise<Response>((resolve) => { finish = resolve; });
  const fetch = vi.fn().mockImplementationOnce(() => delayed).mockResolvedValue(new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetch);
  const first = prepareLoginContext(new AbortController().signal);
  const second = prepareLoginContext(new AbortController().signal);
  await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  finish(new Response(null, { status: 204 }));
  await Promise.all([first, second]);
  expect(fetch).toHaveBeenCalledTimes(2);
  const request = fetch.mock.calls[0]?.[0] as Request;
  expect(request.credentials).toBe("include");
  expect(new URL(request.url).pathname).toBe("/api/v1/auth/login-context");
});

test("unsupported browser cannot bypass the initialization gate", async () => {
  vi.stubGlobal("navigator", {});
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  await expect(prepareLoginContext(new AbortController().signal)).rejects.toMatchObject({ kind: "contract" });
  expect(fetch).not.toHaveBeenCalled();
});
