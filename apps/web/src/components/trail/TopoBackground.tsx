const PAGE_RINGS = [
  [70, 38, -14], [130, 74, -12], [200, 116, -10], [280, 166, -8], [370, 224, -6], [470, 290, -5], [580, 360, -4],
] as const;

export function TopoBackground({ variant, draw = false }: { variant: "page" | "scene"; draw?: boolean }) {
  const [cx, cy] = variant === "scene" ? [300, 300] : [760, 420];
  return (
    <svg
      aria-hidden="true"
      className="topo-background"
      data-draw={draw ? "true" : undefined}
      data-variant={variant}
      preserveAspectRatio="xMidYMid slice"
      viewBox="0 0 1000 560"
    >
      <g fill="none" stroke="currentColor" strokeWidth="1">
        {PAGE_RINGS.map(([rx, ry, rotate], index) => (
          <ellipse
            cx={cx + index * 5}
            cy={cy + index * 5}
            key={rx}
            pathLength={1}
            rx={rx}
            ry={ry}
            transform={`rotate(${rotate} ${cx + index * 5} ${cy + index * 5})`}
          />
        ))}
        <path pathLength={1} d="M-10 90 C 90 60, 170 115, 260 86 S 420 40, 520 66" />
        <path pathLength={1} d="M-10 114 C 95 84, 175 142, 270 112 S 430 68, 540 94" />
      </g>
      {variant === "scene" ? (
        <g className="topo-elevations" fill="currentColor">
          <text x="262" y="226">1,240</text>
          <text x="120" y="160">1,180</text>
          <text x="470" y="110">1,120</text>
        </g>
      ) : null}
    </svg>
  );
}
