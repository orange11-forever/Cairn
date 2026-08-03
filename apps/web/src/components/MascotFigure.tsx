import { useState } from "react";

export type MascotState = "idle" | "thinking" | "success" | "attention";

export interface MascotFigureProps {
  variant?: "avatar" | "half" | "full";
  state?: MascotState;
  label?: string;
  className?: string;
}

const MASCOT_SRC = "/assets/brand/mascot/cairn-mascot.png";
const FALLBACK_SRC = "/assets/brand/cairn-logo.png";

const STATE_LABEL: Record<MascotState, string> = {
  idle: "准备中",
  thinking: "思考中",
  success: "已完成",
  attention: "需要处理",
};

export function MascotFigure({
  variant = "avatar",
  state = "idle",
  label = "Cairn 看板娘",
  className,
}: MascotFigureProps) {
  const [src, setSrc] = useState(MASCOT_SRC);
  const [fallbackFailed, setFallbackFailed] = useState(false);

  const handleImageError = () => {
    if (src === MASCOT_SRC) {
      setSrc(FALLBACK_SRC);
      return;
    }

    setFallbackFailed(true);
  };

  return (
    <span
      className={["mascot-figure", className].filter(Boolean).join(" ")}
      data-state={state}
      data-variant={variant}
    >
      {fallbackFailed ? (
        <span aria-label={label} className="mascot-image-fallback" role="img" />
      ) : (
        <img
          alt={label}
          data-state={state}
          data-variant={variant}
          onError={handleImageError}
          src={src}
        />
      )}
      <span className="mascot-state" role="status">
        {STATE_LABEL[state]}
      </span>
    </span>
  );
}
