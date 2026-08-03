import type { UserDto } from "@cairn/contracts";

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
        <span className="current-user account-label-full">{user.displayName ?? user.email}</span>
        <span className="account-label-short">账户</span>
      </summary>
      <div className="account-menu-panel">
        <p className="account-email">{user.email}</p>
        {appearance}
        <button type="button" className="logout-btn" onClick={() => void onLogout()}>
          退出
        </button>
      </div>
    </details>
  );
}
