import type { IdentityContext } from "../api/auth.ts";
import type { ApiError } from "../api/errors.ts";
import { LogOut, UserRound } from "lucide-react";

export function AccountMenu({
  identity,
  onLogout,
  logoutError,
  appearance,
}: {
  identity: IdentityContext;
  onLogout: () => Promise<void>;
  logoutError: ApiError | null;
  appearance?: React.ReactNode;
}) {
  return (
    <details className="account-menu">
      <summary>
        <UserRound aria-hidden="true" size={18} strokeWidth={1.8} />
        <span className="current-user account-label-full">{identity.user.displayName ?? identity.user.email}</span>
        <span className="account-label-short">账户</span>
      </summary>
      <div className="account-menu-panel">
        <p className="account-email">{identity.user.email}</p>
        <p className="account-organization">{identity.organization.name}</p>
        {logoutError !== null && <p role="alert">{logoutError.message}</p>}
        {appearance}
        <button type="button" className="logout-btn" onClick={() => void onLogout()}>
          <LogOut aria-hidden="true" size={16} strokeWidth={1.8} />
          退出
        </button>
      </div>
    </details>
  );
}
