const messages: Record<string, string> = {
  linked: "登录方式已绑定，今后可以用此账号登录 Cairn。",
  identity_not_linked: "此第三方登录方式当前不可用。请重新发起或使用其他登录方式。",
  identity_conflict: "此第三方账号已被绑定，请选择其他账号。",
  provider_already_linked: "已绑定该平台账号。若要更换，请先解绑。",
  provider_failed: "第三方授权失败，请重新发起。",
  cancelled: "已取消授权，可以重新尝试。",
  session_changed: "登录状态已改变，本次授权未生效。请重新发起。",
  organization_selection_required: "此账号有多个组织，请使用邮箱密码登录。",
  reauthentication_required: "请重新登录后管理登录方式。",
};

export function OAuthNotice({ outcome }: { outcome: string | null | undefined }) {
  const message = outcome ? messages[outcome] : undefined;
  if (message === undefined) return null;
  return <p className={outcome === "linked" ? "oauth-notice" : "form-error"}
    role={outcome === "linked" ? "status" : "alert"}>{message}</p>;
}
