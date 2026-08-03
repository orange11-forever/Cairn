import type { UserDto } from "@cairn/contracts";
import { LogOut, UserRound } from "lucide-react";

export function AccountMenu({
  user,
  onLogout,
  appearance,
}: {
  user: UserDto;
  onLogout: () => Promise<void>;
  appearance?: React.ReactNode;
}) {
  return (
    <details className="account-menu">
      <summary>
        <UserRound aria-hidden="true" size={18} strokeWidth={1.8} />
        <span className="current-user account-label-full">{user.displayName ?? user.email}</span>
        <span className="account-label-short">账户</span>
      </summary>
      <div className="account-menu-panel">
        <p className="account-email">{user.email}</p>
        {appearance}
        <button type="button" className="logout-btn" onClick={() => void onLogout()}>
          <LogOut aria-hidden="true" size={16} strokeWidth={1.8} />
          退出
        </button>
      </div>
    </details>
  );
}
