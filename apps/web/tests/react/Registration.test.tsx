import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { RegistrationForm } from "../../src/components/RegistrationForm.tsx";
import { EmailVerification } from "../../src/components/EmailVerification.tsx";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const accepted = { message: "请查收邮件", registrationReceipt: "private-receipt", resendAfterSeconds: 60 };
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); window.history.replaceState(null, "", "/"); });

test("registration checks availability and sends exact password without creating a session", async () => {
  const fetch = vi.fn(async (request: Request) => request.method === "GET" ? json({ enabled: true }) : json(accepted, 202));
  vi.stubGlobal("fetch", fetch);
  const setItem = vi.spyOn(Storage.prototype, "setItem");
  render(<MemoryRouter><RegistrationForm /></MemoryRouter>);
  await screen.findByRole("button", { name: "发送验证邮件" });
  await userEvent.type(screen.getByLabelText("邮箱"), "new@example.com");
  await userEvent.type(screen.getByLabelText("密码"), "  original-password-2026  ");
  await userEvent.click(screen.getByRole("button", { name: "发送验证邮件" }));
  await screen.findByRole("heading", { name: "查收验证邮件" });
  expect(screen.getByRole("button", { name: /重新发送/ })).toBeDisabled();
  expect(screen.getByLabelText("注册时的密码")).toHaveValue("");
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
  expect(screen.queryByRole("button", { name: "发送验证邮件" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "返回登录" })).toHaveAttribute("href", "/login");
});

test("email scanners and mounting verification never POST; fragment is scrubbed", async () => {
  window.history.replaceState(null, "", "/register/verify#token=private-email-proof");
  const fetch = vi.fn(async (_request: Request) => json({ message: "邮箱验证成功" }));
  vi.stubGlobal("fetch", fetch);
  render(<MemoryRouter><EmailVerification /></MemoryRouter>);
  expect(window.location.hash).toBe("");
  expect(fetch).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "验证邮箱并创建账号" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("请填写注册时的密码");
  expect(fetch).not.toHaveBeenCalled();
  await userEvent.type(screen.getByLabelText("注册时的密码"), "original-password-2026");
  await userEvent.click(screen.getByRole("button", { name: "验证邮箱并创建账号" }));
  await screen.findByRole("heading", { name: "邮箱已验证" });
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(await fetch.mock.calls[0]![0].json()).toEqual({ token: "private-email-proof", password: "original-password-2026" });
  expect(screen.getByRole("link", { name: "前往登录" })).toHaveAttribute("href", "/login");
});

test("invalid proof displays safe retry and missing fragment never sends a request", async () => {
  const fetch = vi.fn(async () => json({ code: "registration_invalid", message: "验证链接或密码无效", traceId: "trace" }, 400));
  vi.stubGlobal("fetch", fetch);
  window.history.replaceState(null, "", "/register/verify#token=private-proof");
  const mounted = render(<MemoryRouter><EmailVerification /></MemoryRouter>);
  await userEvent.type(screen.getByLabelText("注册时的密码"), "wrong-password");
  await userEvent.click(screen.getByRole("button", { name: "验证邮箱并创建账号" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("验证链接或密码无效");
  expect(screen.getByRole("button", { name: "验证邮箱并创建账号" })).toBeEnabled();
  mounted.unmount();
  render(<MemoryRouter><EmailVerification /></MemoryRouter>);
  expect(screen.getByText("请重新打开邮件中的验证链接，或重新注册。")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "验证邮箱并创建账号" })).not.toBeInTheDocument();
  expect(fetch).toHaveBeenCalledTimes(1);
});

test("navigation aborts a pending proof and ignores a response arriving after unmount", async () => {
  window.history.replaceState(null, "", "/register/verify#token=private-proof");
  let resolve!: (response: Response) => void;
  let signal: AbortSignal | undefined;
  vi.stubGlobal("fetch", vi.fn((request: Request) => { signal = request.signal; return new Promise<Response>(done => { resolve = done; }); }));
  const mounted = render(<MemoryRouter><EmailVerification /></MemoryRouter>);
  await userEvent.type(screen.getByLabelText("注册时的密码"), "original-password-2026");
  await userEvent.click(screen.getByRole("button", { name: "验证邮箱并创建账号" }));
  await waitFor(() => expect(signal).toBeDefined());
  mounted.unmount();
  expect(signal!.aborted).toBe(true);
  await act(async () => resolve(json({ message: "邮箱验证成功" })));
  expect(screen.queryByRole("heading", { name: "邮箱已验证" })).not.toBeInTheDocument();
});

test("resend keeps the original in-memory receipt after a generic accepted reply", async () => {
  const posts: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (request: Request) => {
    if (request.method === "GET") return json({ enabled: true });
    posts.push(request);
    return json({ ...accepted, registrationReceipt: posts.length === 1 ? "original-receipt" : "decoy-receipt", resendAfterSeconds: 0 }, 202);
  }));
  render(<MemoryRouter><RegistrationForm /></MemoryRouter>);
  await screen.findByRole("button", { name: "发送验证邮件" });
  await userEvent.type(screen.getByLabelText("邮箱"), "new@example.com");
  await userEvent.type(screen.getByLabelText("密码"), "original-password-2026");
  await userEvent.click(screen.getByRole("button", { name: "发送验证邮件" }));
  await screen.findByRole("heading", { name: "查收验证邮件" });
  for (const password of ["wrong-password-2026", "original-password-2026"]) {
    await userEvent.type(screen.getByLabelText("注册时的密码"), password);
    await userEvent.click(screen.getByRole("button", { name: "重新发送验证邮件" }));
    await waitFor(() => expect(screen.getByLabelText("注册时的密码")).toHaveValue(""));
  }
  expect((await posts[2]!.json()).registrationReceipt).toBe("original-receipt");
});

test("verification refuses to announce completion for a valid message at accepted status", async () => {
  window.history.replaceState(null, "", "/register/verify#token=synthetic-proof");
  vi.stubGlobal("fetch", vi.fn(async () => json({ message: "verified" }, 202)));
  render(<MemoryRouter><EmailVerification /></MemoryRouter>);
  await userEvent.type(screen.getByLabelText("注册时的密码"), "synthetic-password");
  await userEvent.click(screen.getByRole("button", { name: "验证邮箱并创建账号" }));
  await waitFor(() => expect(screen.queryByRole("alert") !== null).toBe(true));
  expect(screen.queryByRole("heading", { name: "邮箱已验证" }) === null).toBe(true);
});
