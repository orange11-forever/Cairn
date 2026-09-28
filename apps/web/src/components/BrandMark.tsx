export function BrandMark({ compact = false }: { compact?: boolean }) {
  return <span className={`cairn-brand-mark${compact ? " cairn-brand-mark-compact" : ""}`}
    role="img" aria-label="Cairn">
    <svg aria-hidden="true" viewBox="0 0 36 36" xmlns="http://www.w3.org/2000/svg">
      <path className="cairn-stone-top"
        d="M6.2 11.4c-.5-1.4.2-2.7 1.5-3.4L20.7 2c1.6-.8 3.4-.6 4.8.5l6.2 5c1.5 1.2 1.4 3.2.3 4.6l-2.2 2.5c-.8.9-1.8 1.2-3 1L8 13.1c-.9-.1-1.5-.6-1.8-1.7Z" />
      <path className="cairn-stone-middle"
        d="M5.9 15.7c.6-.8 1.5-1.2 2.5-1.1l17.5 2.1c-4.1 1.1-6.5 3.8-6.7 7.7-.1 2.2.7 4 2 5.4L5.3 27.5c-2.1-.3-3.1-2.1-2.3-4.1l2.9-7.7Z" />
      <path className="cairn-stone-bottom"
        d="M5.8 28.8c.4-.6 1.1-.9 1.9-.8l20 2.8c1.2.2 2.3.8 3.1 1.8l2 2.4c.5.6.1 1.1-.7 1.1H13.4c-2.2 0-4.3-1-5.8-2.6l-2.5-2.8c-.6-.7-.4-1.3.7-1.9Z" />
    </svg>
    {compact ? null : <span aria-hidden="true">Cairn</span>}
  </span>;
}
