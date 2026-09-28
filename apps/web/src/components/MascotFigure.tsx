import { useState } from "react";

export type MascotState = "idle" | "thinking" | "success" | "attention";

export interface MascotFigureProps {
  variant?: "avatar" | "half" | "full";
  state?: MascotState;
  label?: string;
  className?: string;
  idleCaption?: string;
}

const MASCOT_CHIBI_SRC = "/assets/brand/mascot/cairn-mascot-chibi.png";
const MASCOT_FULL_SRC = "/assets/brand/mascot/cenning-full-v2-20260928.png";
const FALLBACK_SRC = "/assets/brand/cairn-mark-v2.svg";

type ImageStage = "primary" | "logo" | "accessible";

const STATE_LABEL: Record<MascotState, string> = {
  idle: "准备中",
  thinking: "思考中",
  success: "已完成",
  attention: "需要处理",
};

export function MascotFigure({
  variant = "avatar",
  state = "idle",
  label = "岑宁，Cairn 知识向导",
  className,
  idleCaption,
}: MascotFigureProps) {
  const [imageStage, setImageStage] = useState<ImageStage>("primary");
  const primarySrc = variant === "full" ? MASCOT_FULL_SRC : MASCOT_CHIBI_SRC;
  const src = imageStage === "primary" ? primarySrc : FALLBACK_SRC;

  const handleImageError = () => {
    setImageStage((current) => (current === "primary" ? "logo" : "accessible"));
  };

  return (
    <span
      className={["mascot-figure", className].filter(Boolean).join(" ")}
      data-state={state}
      data-variant={variant}
    >
      {imageStage === "accessible" ? (
        <span aria-label={label} className="mascot-image-fallback" role="img" />
      ) : (
        <picture className="mascot-art">
          {variant === "full" && imageStage === "primary" ? (
            <source media="(max-width: 599px)" srcSet={MASCOT_CHIBI_SRC} />
          ) : null}
          <img
            alt={label}
            data-state={state}
            data-variant={variant}
            onError={handleImageError}
            src={src}
          />
        </picture>
      )}
      <span className="mascot-state" role="status">
        {state === "idle" && idleCaption !== undefined ? idleCaption : STATE_LABEL[state]}
      </span>
    </span>
  );
}
