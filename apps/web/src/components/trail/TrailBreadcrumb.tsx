import { Link, useLocation } from "react-router-dom";

export function TrailBreadcrumb({ items }: { items: { label: string; to?: string }[] }) {
  const { pathname } = useLocation();
  return (
    <nav aria-label="当前位置" className="trail-breadcrumb">
      {/* key 随路径变化，让小路在每次换页时重新画一遍。 */}
      <ol key={pathname}>
        {items.map((item, index) => {
          const last = index === items.length - 1;
          return (
            <li key={`${index}:${item.label}`}>
              {index > 0 ? <span aria-hidden="true" className="trail-path" /> : null}
              {!last && item.to !== undefined
                ? <Link to={item.to}>{item.label}</Link>
                : <span aria-current={last ? "page" : undefined}>{item.label}</span>}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
