export function CairnStack({ size = "md" }: { size?: "sm" | "md" }) {
  return (
    <span aria-hidden="true" className="cairn-stack" data-size={size}>
      <span className="stone" />
      <span className="stone" />
      <span className="stone" />
    </span>
  );
}

export function CairnLoader({ label, size = "md" }: { label: string; size?: "sm" | "md" }) {
  return (
    <span className="cairn-loader" role="status">
      <CairnStack size={size} />
      <span className="cairn-loader-label">{label}</span>
    </span>
  );
}
