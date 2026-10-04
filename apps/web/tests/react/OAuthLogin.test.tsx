import { afterEach, expect, test, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { OAuthLoginButtons } from "../../src/components/OAuthLoginButtons.tsx";

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

test("使用 GitHub 登录先发起安全请求再跳转到 provider", async () => {
  const user = userEvent.setup();
  const authorizationUrl = "https://github.com/login/oauth/authorize?client_id=test&state=test";
  const fetchMock = vi.fn(async (_input: RequestInfo | URL) => new Response(JSON.stringify({ authorizationUrl }), {
    status: 200, headers: { "Content-Type": "application/json" },
  }));
  vi.stubGlobal("fetch", fetchMock);
  const navigate = vi.fn();
  render(<OAuthLoginButtons navigate={navigate} />);
  await user.click(screen.getByRole("button", { name: "使用 GitHub 登录" }));
  expect(navigate).toHaveBeenCalledWith(authorizationUrl);
  const request = fetchMock.mock.calls[0]?.[0] as Request;
  expect(request.method).toBe("POST");
  expect(await request.json()).toEqual({ intent: "login", returnTo: "/projects" });
});

test("provider 未配置时保留页面并解释下一步", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
    code: "provider_not_configured", message: "此登录方式尚未启用，请联系管理员", traceId: "test",
  }), { status: 503, headers: { "Content-Type": "application/json" } })));
  const navigate = vi.fn();
  render(<OAuthLoginButtons navigate={navigate} />);
  await userEvent.click(screen.getByRole("button", { name: "使用飞书登录" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("尚未启用");
  expect(navigate).not.toHaveBeenCalled();
});

test("拒绝 API 返回的开放重定向", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
    authorizationUrl: "https://evil.example/?state=test",
  }), { status: 200, headers: { "Content-Type": "application/json" } })));
  const navigate = vi.fn();
  render(<OAuthLoginButtons navigate={navigate} />);
  await userEvent.click(screen.getByRole("button", { name: "使用 GitHub 登录" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("授权地址无效");
  expect(navigate).not.toHaveBeenCalled();
});
