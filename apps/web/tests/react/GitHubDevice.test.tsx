import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { GitHubDeviceAuthorization } from "../../src/components/GitHubDeviceAuthorization.tsx";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json" },
});
const started = { attemptId: "a".repeat(43), userCode: "ABCD-EFGH", verificationUri: "https://github.com/login/device", expiresIn: 300, interval: 1 };
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); });

test("device authorization shows a code, opens only the fixed native page, and completes after polling", async () => {
  const messages: string[] = [];
  vi.stubGlobal("chrome", { webview: { postMessage: (message: string) => messages.push(message) } });
  const completed = vi.fn();
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    if (request.url.endsWith("/poll")) return json({ status: "login_ready", interval: 5, account: { id: 1, login: "octo" } });
    return json(started);
  }));
  render(<GitHubDeviceAuthorization intent="login" label="使用 GitHub 登录" onComplete={completed} />);
  await userEvent.click(screen.getByRole("button", { name: "使用 GitHub 登录" }));
  expect(await screen.findByText("ABCD-EFGH")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "打开 GitHub 授权页面" }));
  expect(messages).toEqual(["cairn:github:authorize"]);
  await waitFor(() => expect(completed).toHaveBeenCalledWith(expect.objectContaining({ status: "login_ready" })), { timeout: 2500 });
});

test("cancel erases the device attempt and prevents late navigation", async () => {
  const completed = vi.fn();
  const deleted: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    if (request.method === "DELETE") { deleted.push(request); return new Response(null, { status: 204 }); }
    return json({ ...started, interval: 20 });
  }));
  const view = render(<GitHubDeviceAuthorization intent="repositories" label="授权仓库" csrfToken="csrf" onComplete={completed} />);
  await userEvent.click(screen.getByRole("button", { name: "授权仓库" }));
  await userEvent.click(await screen.findByRole("button", { name: "取消授权" }));
  await waitFor(() => expect(screen.queryByText("ABCD-EFGH")).not.toBeInTheDocument());
  expect(deleted[0]?.headers.get("X-CSRF-Token")).toBe("csrf");
  expect(completed).not.toHaveBeenCalled();
  view.unmount();
});

test("unconfigured application explains the problem without creating a false connected state", async () => {
  const completed = vi.fn();
  vi.stubGlobal("fetch", vi.fn(async () => json({ code: "provider_not_configured", message: "此安装包尚未配置 Cairn GitHub 授权应用", traceId: "test" }, 503)));
  render(<GitHubDeviceAuthorization intent="login" label="使用 GitHub 登录" onComplete={completed} />);
  await userEvent.click(screen.getByRole("button", { name: "使用 GitHub 登录" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("尚未配置");
  expect(completed).not.toHaveBeenCalled();
});

test("unmount cancels an in-flight start and ignores its late result", async () => {
  let resolve!: (response: Response) => void;
  let signal: AbortSignal | null = null;
  const completed = vi.fn();
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    signal = (input as Request).signal;
    return new Promise<Response>(done => { resolve = done; });
  }));
  const view = render(<GitHubDeviceAuthorization intent="login" label="使用 GitHub 登录" onComplete={completed} />);
  await userEvent.click(screen.getByRole("button", { name: "使用 GitHub 登录" }));
  view.unmount();
  expect(signal!.aborted).toBe(true);
  await act(async () => resolve(json(started)));
  expect(completed).not.toHaveBeenCalled();
});
