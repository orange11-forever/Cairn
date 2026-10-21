import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { RegistrationForm } from "../../src/components/RegistrationForm.tsx";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const created = { message: "账号已创建，请使用邮箱和密码登录。邮箱仅作为登录标识。" };
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); window.history.replaceState(null, "", "/"); });

test("registration checks availability and sends exact password without creating a session", async () => {
  const fetch = vi.fn(async (request: Request) => request.method === "GET" ? json({ enabled: true }) : json(created, 201));
  vi.stubGlobal("fetch", fetch);
  const setItem = vi.spyOn(Storage.prototype, "setItem");
  render(<MemoryRouter><RegistrationForm /></MemoryRouter>);
  await screen.findByRole("button", { name: "创建账号" });
  await userEvent.type(screen.getByLabelText("邮箱"), "new@example.com");
  await userEvent.type(screen.getByLabelText("密码"), "  original-password-2026  ");
  await userEvent.click(screen.getByRole("button", { name: "创建账号" }));
  await screen.findByRole("heading", { name: "注册成功" });
  expect(screen.queryByLabelText("密码")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "前往登录" })).toHaveAttribute("href", "/login");
  expect(screen.queryByRole("button", { name: /发送.*邮件/ })).not.toBeInTheDocument();
  expect(setItem).not.toHaveBeenCalled();
  const request = fetch.mock.calls[1]?.[0];
  expect(new URL(request!.url).pathname).toBe("/api/v1/auth/register");
  expect(await request!.json()).toMatchObject({ email: "new@example.com", password: "  original-password-2026  " });
  expect(fetch).toHaveBeenCalledTimes(2);
});

test("disabled registration gives useful login navigation without showing the registration form", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json({ enabled: false })));
  render(<MemoryRouter><RegistrationForm /></MemoryRouter>);
  await screen.findByText("暂时无法注册，请稍后再试。");
  expect(screen.queryByRole("button", { name: "创建账号" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "返回登录" })).toHaveAttribute("href", "/login");
});

test("duplicate email displays the server error without announcing success", async () => {
  vi.stubGlobal("fetch", vi.fn(async (request: Request) => request.method === "GET" ? json({ enabled: true }) : json({ code: "registration_conflict", message: "无法使用此邮箱创建新账号", traceId: "trace" }, 409)));
  render(<MemoryRouter><RegistrationForm /></MemoryRouter>);
  await screen.findByRole("button", { name: "创建账号" });
  await userEvent.type(screen.getByLabelText("邮箱"), "new@example.com");
  await userEvent.type(screen.getByLabelText("密码"), "original-password-2026");
  await userEvent.click(screen.getByRole("button", { name: "创建账号" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("无法使用此邮箱创建新账号");
  expect(screen.queryByRole("heading", { name: "注册成功" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "创建账号" })).toBeEnabled();
});

test("navigation aborts registration and ignores a late response", async () => {
  let resolve!: (response: Response) => void;
  let signal: AbortSignal | undefined;
  vi.stubGlobal("fetch", vi.fn((request: Request) => {
    if (request.method === "GET") return Promise.resolve(json({ enabled: true }));
    signal = request.signal;
    return new Promise<Response>(done => { resolve = done; });
  }));
  const mounted = render(<MemoryRouter><RegistrationForm /></MemoryRouter>);
  await screen.findByRole("button", { name: "创建账号" });
  await userEvent.type(screen.getByLabelText("邮箱"), "new@example.com");
  await userEvent.type(screen.getByLabelText("密码"), "original-password-2026");
  await userEvent.click(screen.getByRole("button", { name: "创建账号" }));
  await waitFor(() => expect(signal).toBeDefined());
  mounted.unmount();
  expect(signal!.aborted).toBe(true);
  await act(async () => resolve(json(created, 201)));
  expect(screen.queryByRole("heading", { name: "注册成功" })).not.toBeInTheDocument();
});
