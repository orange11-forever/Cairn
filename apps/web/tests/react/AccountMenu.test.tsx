import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test } from "vitest";
import { AccountMenu } from "../../src/components/AccountMenu.tsx";
import type { IdentityContext } from "../../src/api/auth.ts";

test("passwordless user without a name or email retains an account label", () => {
  const identity: IdentityContext = {
    user: { id: "00000000-0000-4000-8000-000000001001", email: null, displayName: null },
    organization: { id: "00000000-0000-4000-8000-000000002001", name: "个人空间", slug: "personal-test" },
    membership: { id: "00000000-0000-4000-8000-000000003001", role: "owner" }, csrfToken: "csrf-test",
  };
  render(<MemoryRouter><AccountMenu identity={identity} onLogout={async () => undefined} logoutError={null} /></MemoryRouter>);
  expect(screen.getByText("Cairn 用户")).toBeInTheDocument();
  expect(screen.getByText("未提供邮箱")).toBeInTheDocument();
});
