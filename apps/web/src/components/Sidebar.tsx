// 顶部品牌栏 + 主导航。纯展示：导航项进来，语义化的 header 出去。
//
// 名字叫 Sidebar 是跟着 Day 8 大纲的措辞（"拆分侧栏"）。实际它在视觉上是顶栏——
// .product-header 用的是横向布局。名字和现实不符是将来的困惑源，
// 但改名要动 CSS 类名和大纲对照，今天不值得；Day 11 迁 Next.js 重排布局时一起处理。

interface NavItem {
  href: string;
  label: string;
}

interface SidebarProps {
  brand: string;
  items: NavItem[];
  /** 当前页面的 href。用来渲染 aria-current，读屏用户靠它知道自己在哪。 */
  activeHref: string;
  /** Day 9：当前登录用户。显示身份 + 提供退出入口。 */
  user: { email: string; displayName?: string };
  onLogout: () => void;
}

export function Sidebar({ brand, items, activeHref, user, onLogout }: SidebarProps) {
  return (
    <header className="product-header">
      <a href="/">{brand}</a>
      <nav aria-label="主导航">
        <ul>
          {items.map((item) => (
            <li key={item.href}>
              {/*
                aria-current 只在当前页那一项出现。
                写成 `item.href === activeHref ? "page" : undefined` 而不是 `: false`——
                React 对 undefined 的处理是「不渲染这个属性」，
                而 aria-current="false" 是一个真实存在的属性值，读屏软件会读到它。
                这两者在 DOM 里不是一回事。
              */}
              <a href={item.href} aria-current={item.href === activeHref ? "page" : undefined}>
                {item.label}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      {/*
        Day 9：当前用户 + 退出。
        显示身份不只是装饰——用户需要能确认"我现在是谁"。
        企业环境里一个人常有多个账号（自己的 + 测试账号），
        看不到当前身份就会在错误的账号下上传文档。
      */}
      <div className="product-header-user">
        {/*
          displayName 缺失时退回 email（schemas/users.ts 里说了这是展示决策，
          不是校验决策——所以判断落在这里，不在 schema 里）。
        */}
        <span className="current-user">{user.displayName ?? user.email}</span>
        <button type="button" className="logout-btn" onClick={onLogout}>
          退出
        </button>
      </div>
    </header>
  );
}
