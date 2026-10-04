export function BrandMark({ compact = false }: { compact?: boolean }) {
  return <span className={`cairn-brand-mark${compact ? " cairn-brand-mark-compact" : ""}`}
    role="img" aria-label="Cairn">
    <svg aria-hidden="true" viewBox="0 0 36 36" xmlns="http://www.w3.org/2000/svg">
      <path d="M2.2 28.7 9.4 15c.5-1 1.3-1.3 2-.3l2.7 3.7c-1.5 1.1-2.7 2.8-3.6 4.5l-3.8 7.6H3.2c-1.2 0-1.6-.8-1-1.8Z" />
      <path d="m14.1 17.4 4.1-8.6c.6-1.3 1.3-2.1 2.5-2.1 1.3 0 2 .9 2.6 2.1l3.1 7-5.1 4-3-1.9c-1.3-.9-2.7-1.1-4.2-.5Z" />
      <path d="m10.1 30.5 4.8-8.7c.7-1.3 1.5-2 2.6-1.4l3.2 2c.4.2.7.2 1.1-.1l5.6-4.5 6.2 10.8c.6 1.1.2 1.9-1.1 1.9H10.1Z" />
    </svg>
    {compact ? null : <span aria-hidden="true">Cairn</span>}
  </span>;
}
