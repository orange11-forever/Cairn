import { QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";

import { ApiError } from "../../src/api/errors.ts";
import { createAppQueryClient, shouldRetry } from "../../src/app/queryClient.ts";
import { SessionProvider, useSession } from "../../src/session/SessionContext.tsx";

const IDENTITY = {
  user: { id: "00000000-0000-4000-8000-000000001001", email: "demo@cairn.dev", displayName: "演示用户" },
  organization: { id: "00000000-0000-4000-8000-000000002001", slug: "cairn-demo", name: "Cairn Demo" },
  membership: { id: "00000000-0000-4000-8000-000000003001", role: "owner" },
  csrfToken: "csrf-test-token",
};
const USER = IDENTITY.user;

const DOC = {
  id: "00000000-0000-4000-8000-000000000001",
  title: "产品需求文档",
  status: "completed" as const,
};

afterEach(() => vi.restoreAllMocks());

test("query retry policy retries one transient ApiError and never retries contracts", () => {
  expect(shouldRetry(0, new ApiError("http", "暂时失败", { status: 503 }))).toBe(true);
  expect(shouldRetry(1, new ApiError("http", "暂时失败", { status: 503 }))).toBe(false);
  expect(shouldRetry(0, new ApiError("http", "请求无效", { status: 400 }))).toBe(false);
  expect(shouldRetry(0, new ApiError("contract", "格式不正确"))).toBe(false);
  expect(shouldRetry(0, new Error("network"))).toBe(false);
});

test("logout aborts the session, clears queries, and replaces the URL", async () => {
  const queryClient = createAppQueryClient();
  queryClient.setQueryData(["documents", USER.id, "success"], { documents: [DOC], dropped: 0 });
  const observedSignal = { current: null as AbortSignal | null };
  const events: string[] = [];
  const originalCancelQueries = queryClient.cancelQueries.bind(queryClient);
  const cancelQueries = vi.spyOn(queryClient, "cancelQueries").mockImplementation(async (...args) => {
    events.push("queries:cancel");
    return originalCancelQueries(...args);
  });
  const originalClear = queryClient.clear.bind(queryClient);
  const clear = vi.spyOn(queryClient, "clear").mockImplementation(() => {
    events.push("queries:clear");
    originalClear();
  });

  function Harness() {
    const { session, logout } = useSession();
    const location = useLocation();
    const query = useQueryClient();
    if (session !== null && observedSignal.current === null) {
      observedSignal.current = session.signal;
      session.signal.addEventListener("abort", () => events.push("session:abort"), { once: true });
    }
    return (
      <>
        <button onClick={() => void logout()}>logout</button>
        <output>{location.pathname}</output>
        <output>{query.getQueryData(["documents", USER.id, "success"]) === undefined ? "empty" : "filled"}</output>
      </>
    );
  }

  const user = userEvent.setup();
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/documents"]}>
        <SessionProvider restoredIdentity={IDENTITY} sessionApi={{ restore: async () => IDENTITY, logout: async () => undefined }}>
          <Harness />
        </SessionProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );

  await user.click(screen.getByRole("button", { name: "logout" }));
  await waitFor(() => expect(screen.getByText("/login")).toBeInTheDocument());

  expect(observedSignal.current?.aborted).toBe(true);
  expect(events.slice(0, 3)).toEqual(["queries:cancel", "session:abort", "queries:clear"]);
  expect(queryClient.getQueryData(["documents", USER.id, "success"])).toBeUndefined();
  cancelQueries.mockRestore();
  clear.mockRestore();
});

test("restore outages expose a retry state instead of becoming anonymous", async () => {
  const queryClient = createAppQueryClient();
  let attempts = 0;

  function Harness() {
    const { status, session, restoreError, retryRestore } = useSession();
    return (
      <>
        <output>{status}</output>
        <output>{session?.user.email ?? "no-session"}</output>
        <output>{restoreError?.message ?? "no-error"}</output>
        <button onClick={retryRestore}>retry</button>
      </>
    );
  }

  const user = userEvent.setup();
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <SessionProvider
          sessionApi={{
            restore: async () => {
              attempts += 1;
              if (attempts === 1) {
                throw new ApiError("http", "服务暂时不可用", {
                  status: 503,
                  code: "database_unavailable",
                });
              }
              return IDENTITY;
            },
            logout: async () => undefined,
          }}
        >
          <Harness />
        </SessionProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );

  expect(await screen.findByText("restore-error")).toBeInTheDocument();
  expect(screen.getByText("no-session")).toBeInTheDocument();
  expect(screen.getByText("服务暂时不可用")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "retry" }));

  expect(await screen.findByText("authenticated")).toBeInTheDocument();
  expect(screen.getByText("demo@cairn.dev")).toBeInTheDocument();
  expect(attempts).toBe(2);
});
